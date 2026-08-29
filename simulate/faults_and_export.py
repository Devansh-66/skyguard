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
        zz = {}
        for ch in CHANNELS:
            base = resids[ch][:clean_steps]
            med = np.nanmedian(base, axis=0)
            mad = 1.4826 * np.nanmedian(np.abs(base - med), axis=0)
            # Shrink each station's own estimate halfway toward the network
            # median. The residual spread is mostly a property of the geometry
            # and the weather, which every station shares; a per-station
            # estimate from one window is noisy, and the stations it
            # underestimates are exactly the ones that then cry wolf.
            pooled = np.nanmedian(mad)
            sigma = np.maximum(0.5 * mad + 0.5 * pooled, 1e-6)
            zz[ch] = (resids[ch] - med) / sigma
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
    # BANDS CHOSEN FROM A MEASURED TRADE-OFF, not from the round numbers used
    # elsewhere. Sweeping the threshold on this network gave:
    #
    #     2 sigma  82% recall  38.6% of healthy stations also flagged
    #     3 sigma  54% recall  11.1%
    #     4 sigma  32% recall   2.8%
    #     5 sigma  25% recall   0.0%
    #
    # There is no good point on that curve, and pretending otherwise by picking
    # 2 sigma would paint a third of the country amber. 4 and 6 keep the map
    # honest at the cost of recall, and the number to quote is the trade, not
    # one end of it.
    grade_i = np.where(np.isnan(data["temp"]) & np.isnan(data["rh"]), 3,
                       np.where(worst >= 6, 2, np.where(worst >= 4, 1, 0)))
    grade_i = np.where(np.isfinite(worst), grade_i, 3)   # 3 = no data

    # hourly for the map
    hourly = grade_i[::4]
    n_h = hourly.shape[0]
    chars = np.array(list("012-"))
    rows = ["".join(chars[hourly[:, s]]) for s in range(n_st)]

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
        "t0": str(t0), "step_hours": 1, "n_steps": int(n_h),
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
