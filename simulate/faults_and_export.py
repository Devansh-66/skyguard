"""Inject faults into the synthetic network, grade it, and export what a map needs.

    python -m simulate.faults_and_export

TWO JOBS, DELIBERATELY IN ONE PLACE

Injecting the faults and grading them has to be one script, because the grading
must never see the fault list. Splitting them across two files makes it easy for
a later edit to pass the ground truth into the scorer by accident, and a
detector that has been told the answer will look excellent forever.

HOW STATIONS ARE GRADED

By neighbour differencing, which is this project's actual method rather than a
convenience for the demonstration. A station's residual is its reading minus the
MEDIAN of every station within 250 km at the same instant, and that residual is
normalised by its own robust spread over the first quarter of the record, before
any injected fault begins.

That is what makes the demonstration mean something. Weather moves a whole
region together and cancels in the difference; an instrument fault moves one
mast and does not. The generator builds the shared weather explicitly for this
reason -- neighbours correlate at 0.997 and distant stations at 0.78 -- so the
detector is being asked a real question.

WHAT GETS EXPORTED

The console cannot carry 344 stations times 2,880 steps times three channels.
It gets the hourly grade per station per step, one character each, which is what
the map draws; the full series stays on disk for the API and the pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = Path("data/sim/network_15min.npz")
OUT_NPZ = Path("data/sim/network_faulted.npz")
OUT_MAP = Path("dashboard/sim_map.json")

NEAR_KM = 250.0
STEP_MIN = 15
CHANNELS = ("temp", "rh", "pres")

# Fault types, and what each does to a channel. Every one of these is a failure
# an AWS actually has; none is a shape chosen because it is easy to detect.
# THE ROLLING SIGMA. Fifteen days is six correlation times of the weather field
# (tau is 2.5 days), which is what it takes for a robust spread estimate to
# settle. The one-day lag holds the reference behind the point being scored so
# a starting fault is not already inside its own baseline. Six hours between
# recomputes: the spread of a weather residual does not move faster than that.
# THE BANDS, IN ONE PLACE. They were written out twice -- once for the combined
# grade and once for the per-channel grades -- and only one copy was updated
# when they were recalibrated. The map and the alert list were then banding the
# same residual at different thresholds, so a station could be clear on the map
# and alerting in the list. A threshold that appears twice is a threshold that
# will disagree with itself.
WATCH_SIGMA = 6.0
FAULT_SIGMA = 8.0

SIGMA_WIN = 15 * 24 * 60 // 15          # 15 days, in 15-minute steps
SIGMA_LAG = 1 * 24 * 60 // 15           # 1 day
SIGMA_STRIDE = 6 * 60 // 15             # 6 hours
MIN_BASE = 5 * 24 * 60 // 15            # never estimate from under 5 days

FAULT_KINDS = ("drift", "step", "stuck", "dropout", "noise", "shield")


def haversine_matrix(lat, lon):
    la = np.radians(lat)[:, None]
    lo = np.radians(lon)[:, None]
    h = (np.sin((la - la.T) / 2) ** 2
         + np.cos(la) * np.cos(la.T) * np.sin((lo - lo.T) / 2) ** 2)
    return 2 * 6371.0 * np.arcsin(np.clip(np.sqrt(h), 0, 1))


def inject(data: dict, rng, n_faulty: int, solar) -> list[dict]:
    """Corrupt a subset of stations. Returns the truth, which the grader never sees."""
    n_steps, n_st = data["temp"].shape
    victims = rng.choice(n_st, size=n_faulty, replace=False)
    events = []
    for v in victims:
        kind = FAULT_KINDS[rng.integers(len(FAULT_KINDS))]
        ch = CHANNELS[rng.integers(3)]
        # Onset in the middle half of the record, so every fault has a clean
        # run before it to be measured against and a run after it to persist in.
        onset = int(rng.integers(int(n_steps * 0.55), int(n_steps * 0.85)))
        arr = data[ch]
        scale = {"temp": 1.0, "rh": 6.0, "pres": 0.8}[ch]
        ev = {"station": int(v), "channel": ch, "kind": kind, "onset": onset}

        if kind == "drift":
            # Per day, growing linearly. The failure this project exists for:
            # never implausible at any single moment.
            rate = float(rng.uniform(0.6, 2.5)) * scale
            days = (np.arange(n_steps) - onset) * STEP_MIN / 1440.0
            arr[onset:, v] += (rate * days[onset:]).astype(arr.dtype)
            ev["rate_per_day"] = round(rate, 3)
        elif kind == "step":
            amp = float(rng.uniform(2.0, 6.0)) * scale * rng.choice([-1, 1])
            arr[onset:, v] += np.float32(amp)
            ev["amplitude"] = round(amp, 2)
        elif kind == "stuck":
            arr[onset:, v] = arr[onset, v]
            ev["value"] = round(float(arr[onset, v]), 2)
        elif kind == "dropout":
            end = min(n_steps, onset + int(rng.integers(96, 96 * 6)))
            arr[onset:end, v] = np.nan
            ev["until"] = int(end)
        elif kind == "noise":
            mult = float(rng.uniform(6.0, 14.0))
            arr[onset:, v] += rng.normal(0, 0.12 * scale * mult,
                                         n_steps - onset).astype(arr.dtype)
            ev["multiplier"] = round(mult, 1)
        elif kind == "shield":
            # A degraded radiation shield reads high in daylight and barely at
            # night, so the error is a function of the sun rather than a
            # constant. Temperature only -- it is a shield, not a probe.
            ch, arr = "temp", data["temp"]
            ev["channel"] = "temp"
            amp = float(rng.uniform(1.5, 4.0))
            day = np.clip(np.cos(2 * np.pi * (solar[:, v] - 13.0) / 24.0), 0, None)
            ramp = np.clip((np.arange(n_steps) - onset) / (96 * 5.0), 0, 1)
            arr[:, v] += (amp * day * ramp).astype(arr.dtype)
            ev["amplitude"] = round(amp, 2)
        events.append(ev)
    return events


def grade(data: dict, near: np.ndarray, clean_steps: int):
    """Neighbour differencing, then band. Knows nothing about the fault list."""
    n_steps, n_st = data["temp"].shape
    anoms = {}
    for ch in CHANNELS:
        arr = data[ch].astype(np.float32)

        # ANOMALY FIRST, THEN DIFFERENCE.
        #
        # Differencing raw values against neighbours was catastrophic: 49% of
        # healthy stations were flagged. A mast at 4,196 m differenced against
        # neighbours at 200 m carries an enormous offset whose DIURNAL SHAPE
        # also differs -- thin air warms and cools faster -- so the difference
        # swings every day for reasons that have nothing to do with any
        # instrument. Removing each station's own clean-period climatology by
        # hour of day first takes the station's identity out of the residual and
        # leaves weather plus faults, which is what the difference is for.
        hod = ((np.arange(n_steps) * STEP_MIN // 60) % 24)
        clim = np.zeros((24, n_st), dtype=np.float32)
        for h in range(24):
            m = (hod[:clean_steps] == h)
            if m.any():
                clim[h] = np.nanmean(arr[:clean_steps][m], axis=0)
        anom = arr - clim[hod]

        anoms[ch] = anom
    # TWO PASSES, BECAUSE A FAULTY NEIGHBOUR POISONS THE REFERENCE.
    #
    # Measured on the first version: healthy stations had |z| p95 = 2.00 in the
    # training window -- exactly what the MAD predicts -- and 4.33 later, which
    # flagged half of them. The residual was not drifting; the REFERENCE was.
    # A frozen or stepped station sits inside its neighbours' median, and where
    # a station has only four or five neighbours within 250 km, one bad member
    # moves that median enough to condemn the rest.
    #
    # So: grade once, note who looks bad, then re-grade with those excluded from
    # everyone else's neighbour set. No ground truth is consulted -- the second
    # pass uses only the first pass's own output, which is what a deployed
    # system would have. The ARM path does the same thing.
    def _resid(excluded):
        out = {}
        for ch in CHANNELS:
            a = anoms[ch]
            r = np.full_like(a, np.nan)
            for s in range(n_st):
                idx = near[s]
                if excluded is not None and idx.size:
                    idx = idx[~excluded[idx]]
                if idx.size < 3:
                    continue
                r[:, s] = a[:, s] - np.nanmedian(a[:, idx], axis=1)
            out[ch] = r
        return out

    def _z(resids):
        """Standardise the residual against a TRAILING, LAGGED, ROLLING spread.

        WHY NOT ONE ESTIMATE FROM AN EARLY WINDOW, WHICH IS WHAT THIS DID

        Sigma was the MAD of the first half of the record, applied to all of
        it. Measured on a network with no faults injected at all:

            baseline window   |z| p95 = 2.78
            scoring period    |z| p95 = 4.47      inflated 1.61x
            false alarms at 4 sigma: 7.6% of station-hours

        Two things caused that and both are the same mistake. The estimate was
        IN-SAMPLE -- fitted to the window it was then evaluated on, so it fits
        that window's noise and nothing else. And it was FIXED, so a month of
        changing weather was scored against a fortnight of one regime. A
        threshold of 4 was really about 2.5 by the end, which is the entire
        false-alarm rate.

        WHAT IT DOES NOW

        Sigma is recomputed from a window that TRAILS the point being scored,
        so no point is ever standardised against itself. That is also the only
        version a deployed system could run: at 09:00 you have yesterday, not
        next week.

        The window is LAGGED by a day. A slow drift that has already entered
        the reference window inflates sigma and hides itself -- self-masking --
        and holding the reference a day behind buys the detector the beginning
        of a fault before the fault can start defending itself. It does not
        solve self-masking for a fault longer than the window; nothing that
        uses the station's own history can, and that limit is stated wherever
        the recall figure appears.

        Recomputed every SIGMA_STRIDE steps rather than every step, because the
        spread of a weather residual does not move in six hours and 344
        stations times 2,880 steps times three channels of exact rolling MAD
        buys nothing for the cost.
        """
        zz = {}
        for ch in CHANNELS:
            r = resids[ch]
            n_t, n_s = r.shape
            sig = np.full((n_t, n_s), np.nan, dtype=np.float32)
            med = np.full((n_t, n_s), np.nan, dtype=np.float32)

            for start in range(0, n_t, SIGMA_STRIDE):
                # The window ends SIGMA_LAG before this block and reaches back
                # SIGMA_WIN. Early on there is not enough history, so it falls
                # back to the longest trailing stretch available -- which is
                # the honest thing a real deployment does on its first fortnight.
                hi = max(start - SIGMA_LAG, MIN_BASE)
                lo = max(hi - SIGMA_WIN, 0)
                base = r[lo:hi]
                if base.shape[0] < MIN_BASE:
                    base = r[:MIN_BASE]
                m = np.nanmedian(base, axis=0)
                mad = 1.4826 * np.nanmedian(np.abs(base - m), axis=0)
                # Shrink each station's own estimate halfway toward the network
                # median. The residual spread is mostly a property of the
                # geometry and the weather, which every station shares; a
                # per-station estimate from one window is noisy, and the
                # stations it underestimates are exactly the ones that cry wolf.
                pooled = np.nanmedian(mad)
                sd = np.maximum(0.5 * mad + 0.5 * pooled, 1e-6)
                end = min(start + SIGMA_STRIDE, n_t)
                sig[start:end] = sd
                med[start:end] = m

            zz[ch] = (r - med) / sig
        return zz

    z1 = _z(_resid(None))
    worst1 = np.nanmax(np.stack([np.abs(z1[c]) for c in CHANNELS]), axis=0)
    suspect = np.nanmean(worst1 >= 3.0, axis=0) > 0.20
    z = _z(_resid(suspect))
    return z, int(suspect.sum())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faulty", type=int, default=28)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    if not SRC.exists():
        raise SystemExit(f"missing {SRC}; run `python -m simulate.network` first")
    d = np.load(SRC, allow_pickle=True)
    data = {c: d[c].copy() for c in CHANNELS}
    lat, lon = d["lat"], d["lon"]
    n_steps, n_st = data["temp"].shape
    rng = np.random.default_rng(args.seed)

    t0 = np.datetime64(str(d["t0"]))
    t = t0 + np.arange(n_steps) * np.timedelta64(STEP_MIN, "m")
    hours = ((t - t.astype("datetime64[D]")).astype("timedelta64[m]")
             .astype(np.float64) / 60.0)[:, None]
    solar = (hours + lon[None, :] / 15.0) % 24.0

    events = inject(data, rng, args.faulty, solar)

    dm = haversine_matrix(lat, lon)
    near = np.array([np.where((dm[s] <= NEAR_KM) & (np.arange(n_st) != s))[0]
                     for s in range(n_st)], dtype=object)
    # HALF THE RECORD AS BASELINE, and faults only after 55%.
    #
    # Measured on clean data with no faults injected at all: the residual spread
    # over the full record is 1.25x the estimate from a 9-day window at the
    # median and 2.0x at the worst. The weather field has a 2.5-day correlation
    # time, so nine days holds under four independent samples and the MAD
    # underestimates. A 2-sigma threshold was really a 1.0-1.6 sigma one, which
    # is the entire false-alarm rate.
    #
    # Fifteen days is six correlation times, and it is also what a deployment
    # actually has: a mast runs for months before it fails. Giving the detector
    # a baseline shorter than the weather it must average over was an artefact
    # of the demonstration, not a property of the problem.
    clean = int(n_steps * 0.50)
    z, n_excluded = grade(data, near, clean)
    print(f"  second pass excluded {n_excluded} suspect stations from neighbour sets")

    # Worst channel per station per step -> a single grade.
    stack = np.stack([np.abs(z[c]) for c in CHANNELS])
    worst = np.nanmax(np.where(np.isfinite(stack), stack, -np.inf), axis=0)
    worst_ch = np.nanargmax(np.where(np.isfinite(stack), stack, -np.inf), axis=0)
    # BANDS CALIBRATED AGAINST A FAULT-FREE CONTROL RUN, not asserted.
    #
    # The old 4 and 6 were chosen against a sigma estimated in-sample from a
    # fixed early window, and that sigma was 1.61x too small by the end of the
    # month, so "4 sigma" was really about 2.5. The sigma is trailing and
    # lagged now (see _z) and the inflation is down to 1.23x, which moves where
    # the bands belong.
    #
    # Re-measured end to end -- inject 28 faults, grade blind, debounce into
    # alerts with the 3-hour raise and 6-hour clear the interface uses, then
    # ask which STATIONS raise an alert at all:
    #
    #   watch  episodes  stations alerting  faults found  healthy alerting
    #     4.0       352               171         23/28          148/316
    #     5.0       156                84         19/28           65/316
    #     6.0        73                42         16/28           26/316
    #     6.5        55                28         13/28           15/316
    #     7.0        35                17         10/28            7/316
    #
    # 6 and 8 is the chosen point: 57% of the injected faults found at 38%
    # precision, against 86% at 15% before. A queue a technician works down is
    # ruined by precision below about a third -- people stop driving out -- and
    # the missed faults are the slow ones, which cost a data point rather than
    # a van. 7.0 would buy 59% precision for a third of the recall, which is
    # the wrong end of the same trade.
    #
    # Both numbers are worth quoting together and neither alone.
    grade_i = np.where(np.isnan(data["temp"]) & np.isnan(data["rh"]), 3,
                       np.where(worst >= FAULT_SIGMA, 2,
                                np.where(worst >= WATCH_SIGMA, 1, 0)))
    grade_i = np.where(np.isfinite(worst), grade_i, 3)   # 3 = no data

    # Per-channel grades too, so the four map panels work on this network the
    # same way they do on WDQMS. One character per station per hour per channel
    # is about 250 kB each; the combined grade is derived in the browser as the
    # worst of the three rather than shipped a fourth time.
    # AT THE SIMULATION'S OWN RESOLUTION, not resampled to the hour.
    #
    # These were subsampled to hourly, which meant the interface could only ever
    # step an hour at a time and the charts were drawn from three-hourly points
    # -- a resolution baked into the file rather than chosen by whoever is
    # reading it. The record is 15-minute data; shipping it as such is what lets
    # the clock offer 15, 30 or 60 minutes and lets a chart be drawn at any of
    # them. A grade string is one character per step and compresses to almost
    # nothing over the wire, because almost every character is "0".
    chars = np.array(list("012-"))
    n_h = grade_i.shape[0]
    rows = ["".join(chars[grade_i[:, s]]) for s in range(n_st)]

    per_ch = {}
    for ci, ch in enumerate(CHANNELS):
        az = np.abs(z[ch])
        gi = np.where(np.isfinite(az),
                      np.where(az >= FAULT_SIGMA, 2,
                               np.where(az >= WATCH_SIGMA, 1, 0)), 3)
        per_ch[ch] = ["".join(chars[gi[:, s]]) for s in range(n_st)]

    # THE VALUES THEMSELVES, for the field maps.
    #
    # A temperature map is a continuous surface, not a scatter of coloured
    # points -- that is simply how the quantity is represented, and grades alone
    # cannot draw one. So each station's readings go out too, quantised to a
    # byte against a fixed per-channel range -- at the same resolution as the
    # grades, so a shaded verdict lines up exactly with the reading that caused
    # it. They used to be three-hourly against hourly grades, which put the
    # shading up to ninety minutes away from its own cause.
    import base64
    # WHAT RESOLUTION TO SHIP THE READINGS AT.
    #
    # Grades and readings cost completely different amounts. A grade string is
    # one character per step and is almost entirely "0", so all four strings for
    # the whole network gzip to a few kilobytes -- they can go at the full
    # 15-minute resolution for nothing, and that is what lets the clock step at
    # 15, 30 or 60 minutes.
    #
    # Readings are quantised bytes in base64, which is close to incompressible.
    # At 15 minutes they are 3.8 MB on their own. Every halving of resolution
    # halves that, and 30 minutes still puts 48 points across a day, which is
    # more than a 600-pixel chart can show. So the two are shipped at different
    # rates on purpose, and FIELD_EVERY says how many grade steps lie between
    # reading frames.
    FIELD_EVERY = 2                      # grade steps (15 min each) per frame
    # PRESSURE IS REDUCED TO SEA LEVEL FOR THE FIELD MAP, and only for the map.
    #
    # Station pressure spans 611 to 1022 hPa across this network, and almost all
    # of that is elevation: a field drawn from it is a map of the Himalaya with
    # the weather invisible underneath. Every pressure chart a meteorologist
    # reads is MSL for exactly this reason -- it is the reduction that makes
    # synoptic systems appear at all.
    #
    # The DETECTOR keeps using station pressure. Reduction needs temperature,
    # so an MSL value carries the thermometer's errors into the barometer's
    # channel, which is the last thing a per-sensor fault detector should have.
    RANGE = {"temp": (-5.0, 50.0), "rh": (0.0, 100.0), "pres": (990.0, 1026.0)}
    elev = np.asarray(d["elev"], dtype=np.float64)[None, :]
    msl = data["pres"] * (1.0 - (0.0065 * elev)
                          / (data["temp"] + 0.0065 * elev + 273.15)) ** -5.257
    field_src = {"temp": data["temp"], "rh": data["rh"], "pres": msl}
    field_step = FIELD_EVERY
    fields = {}
    for ch in CHANNELS:
        lo, hi = RANGE[ch]
        a = field_src[ch][::field_step]
        q = np.clip(np.round((a - lo) / (hi - lo) * 254.0) + 1.0, 1, 255)
        q = np.where(np.isfinite(a), q, 0).astype(np.uint8)   # 0 = missing
        fields[ch] = q
    n_f = fields["temp"].shape[0]

    truth = {e["station"]: e for e in events}
    stations = []
    for s in range(n_st):
        e = truth.get(s)
        stations.append({
            "id": str(d["ids"][s]), "name": str(d["names"][s]),
            "state": str(d["states"][s]),
            "lat": round(float(lat[s]), 4), "lon": round(float(lon[s]), 4),
            "elev": int(d["elev"][s]),
            "g": rows[s],
            "gt": per_ch["temp"][s], "gh": per_ch["rh"][s], "gp": per_ch["pres"][s],
            "vt": base64.b64encode(fields["temp"][:, s].tobytes()).decode(),
            "vh": base64.b64encode(fields["rh"][:, s].tobytes()).decode(),
            "vp": base64.b64encode(fields["pres"][:, s].tobytes()).decode(),
            # The truth is exported so the interface can SHOW it beside the
            # detection. It is written after grading and never read before.
            "fault": (None if e is None else
                      {"kind": e["kind"], "channel": e["channel"],
                       "onset_hour": e["onset"] // 4}),
        })

    OUT_MAP.parent.mkdir(parents=True, exist_ok=True)
    OUT_MAP.write_text(json.dumps({
        "note": ("SIMULATED READINGS at real IMD station locations. The "
                 "geography is real; the temperature, pressure and humidity are "
                 "generated. Graded by neighbour differencing within 250 km."),
        "t0": str(t0), "step_hours": STEP_MIN / 60.0,
        "step_minutes": STEP_MIN, "n_steps": int(n_h),
        "field_every": FIELD_EVERY, "n_fields": int(n_f),
        "range": {k: list(v) for k, v in RANGE.items()},
        "field_note": {"pres": "reduced to mean sea level; the detector uses "
                               "station pressure"},
        "legend": {"0": "ok", "1": "watch", "2": "fault", "-": "no data"},
        "stations": stations,
    }, separators=(",", ":")), encoding="utf-8")

    np.savez_compressed(OUT_NPZ, **data, z_temp=z["temp"].astype(np.float32),
                        z_rh=z["rh"].astype(np.float32),
                        z_pres=z["pres"].astype(np.float32),
                        grade=grade_i.astype(np.int8), lat=lat, lon=lon,
                        t0=str(t0), step_min=STEP_MIN,
                        ids=d["ids"], names=d["names"], states=d["states"],
                        events=np.array(json.dumps(events), dtype=object))

    print(f"{OUT_MAP}  {OUT_MAP.stat().st_size / 1024:.0f} kB   "
          f"{n_st} stations x {n_h} hourly steps")
    print(f"{OUT_NPZ}  {OUT_NPZ.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"\ninjected {len(events)} faults:")
    kinds = {}
    for e in events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print("  " + "  ".join(f"{k} {v}" for k, v in sorted(kinds.items())))

    # Did the grader find them, without ever being told? Recall over the final
    # quarter, by which time every fault has been running for a while.
    tail = slice(int(n_steps * 0.85), None)
    flagged_tail = (grade_i[tail] >= 1).mean(axis=0)
    faulty_idx = np.array([e["station"] for e in events])
    clean_idx = np.setdiff1d(np.arange(n_st), faulty_idx)
    found = int((flagged_tail[faulty_idx] > 0.5).sum())
    false_pos = int((flagged_tail[clean_idx] > 0.5).sum())
    print(f"\ngraded WITHOUT the fault list:")
    print(f"  {found} of {len(events)} injected faults flagged for most of the "
          f"final stretch  ({found / len(events):.0%})")
    print(f"  {false_pos} of {len(clean_idx)} healthy stations also flagged "
          f"({false_pos / len(clean_idx):.1%})")
    for e in events:
        share = flagged_tail[e["station"]]
        print(f"    {str(d['names'][e['station']]):24s} {e['kind']:8s} "
              f"{e['channel']:5s} flagged {share:5.0%}")


if __name__ == "__main__":
    main()
