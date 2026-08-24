"""Fault injection with ground truth.

PS26073 is evaluated on anomaly-injected data, so this module is the single most
load-bearing thing in the repo: every accuracy number the team ever quotes is a
statement about this injector as much as about the detector. Two consequences.

1. Amplitudes are sampled across a WIDE range, log-uniform, never at one
   convenient size. A detector tuned against 5 K spikes will report 99 % recall
   and miss every real 0.4 K drift. What we need is the POD-vs-amplitude curve,
   and you only get that if small faults are in the mix.

2. Injection is reproducible from a seed and every event is logged with its
   amplitude, so a miss can always be traced to "0.3 K step, below the floor"
   rather than an unexplained hole in the recall.

The faults model FAILURE MODES OF THE INSTRUMENT, not weather. Genuine
meteorological events are already in the ERA5 signal and must NOT be labelled as
anomalies -- if the detector fires on a real squall line it is a false alarm, and
that distinction is the whole point of the problem statement.

    python -m inject.faults --data data/skyguard_realistic.csv --out data/
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

VARIABLES = ("temp", "rh", "pres")

# The taxonomy is fixed across the repo. `unknown` is an OUTPUT label only --
# the detector may emit it; the injector never produces it.
FAULT_TYPES = ("spike", "frozen", "dropout", "saturation",
               "step_offset", "calibration_drift", "noise_burst")

# Injected separately, because it is the only fault here that is DERIVED rather
# than invented, and the only one that moves two channels at once.
CROSS_CHANNEL_TYPES = ("shield_failure",)

# Sensor rails, for saturation. These are the limits of the PROBE, not of the
# climate -- a stuck-high RH probe reads 100, not 140.
RAILS = {"temp": (-40.0, 60.0), "rh": (0.0, 100.0), "pres": (500.0, 1100.0)}

# Logger resolution -- injected values are quantised the same way real ones are,
# otherwise a fault is trivially detectable by having too many decimal places.
RESOLUTION = {"temp": 0.1, "rh": 0.1, "pres": 0.1}

# Amplitude ranges, log-uniform, in the units of each variable. The LOW end is
# deliberately below what anyone expects to detect: that is what makes the
# POD curve informative rather than a flat line at 1.0.
AMPLITUDE = {
    "spike":             {"temp": (0.5, 15.0), "rh": (3.0, 60.0), "pres": (0.5, 20.0)},
    "step_offset":       {"temp": (0.2, 5.0),  "rh": (1.0, 20.0), "pres": (0.2, 8.0)},
    "noise_burst":       {"temp": (0.2, 4.0),  "rh": (1.0, 15.0), "pres": (0.2, 5.0)},
    # drift amplitude is a RATE, per day
    "calibration_drift": {"temp": (0.005, 0.15), "rh": (0.02, 0.6), "pres": (0.005, 0.2)},
}

# Event durations in hours, log-uniform. Frozen/dropout/saturation/drift are
# persistent; spikes are near-instantaneous. The ceilings are capped so that
# point-level prevalence lands in the low single digits -- the imbalance IS the
# problem, and an injector that faults a quarter of the record quietly turns
# PS26073 into an easy task and every metric into a flattering lie.
DURATION = {
    "spike":             (1, 3),
    "frozen":            (6, 240),
    "dropout":           (2, 120),
    "saturation":        (6, 168),
    "step_offset":       (24, 720),
    "calibration_drift": (240, 1440),
    "noise_burst":       (6, 120),
}

# Relative frequency. Drift and frozen dominate real AWS failure logs; dropout
# is common but easy. Weighted so the hard classes are not starved of examples.
WEIGHTS = {"spike": 0.20, "frozen": 0.18, "dropout": 0.12, "saturation": 0.08,
           "step_offset": 0.15, "calibration_drift": 0.17, "noise_burst": 0.10}


@dataclass
class Event:
    station: str
    variable: str
    fault_type: str
    start: str
    end: str
    duration_h: int
    amplitude: float          # units of the variable, or units/day for drift
    sign: int


def _loguniform(lo: float, hi: float, rng: np.random.Generator) -> float:
    return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))


def _quantise(v: np.ndarray, var: str) -> np.ndarray:
    r = RESOLUTION[var]
    return np.round(v / r) * r


def _apply(values: np.ndarray, ft: str, var: str, amp: float, sign: int,
           rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Return (faulted segment, mask of samples actually modified).

    The mask exists because a spike displaces only a few samples inside its
    window, and labelling the untouched ones as faulted is simply wrong. It
    depressed every spike metric in the repo: for a three-hour spike two of the
    three labelled points were clean data, so point-level precision and recall
    were being scored against samples no fault had ever touched.
    """
    v = values.astype(float).copy()
    n = len(v)
    lo, hi = RAILS[var]
    touched = np.ones(n, dtype=bool)

    if ft == "spike":
        # a few isolated points, not the whole window
        k = max(1, n // 2)
        idx = rng.choice(n, size=k, replace=False)
        v[idx] += sign * amp
        touched = np.zeros(n, dtype=bool)
        touched[idx] = True

    elif ft == "frozen":
        # the probe stops responding: last good value repeats exactly
        v[:] = v[0]

    elif ft == "dropout":
        # NaN means "no observation". It is NOT zero and must never be imputed.
        v[:] = np.nan

    elif ft == "saturation":
        # pinned at a rail, with the tiny jitter a stuck ADC still shows
        rail = hi if sign > 0 else lo
        v[:] = rail
        v += rng.normal(0.0, RESOLUTION[var] / 2, n)

    elif ft == "step_offset":
        v += sign * amp

    elif ft == "calibration_drift":
        # amp is per DAY; hourly data
        v += sign * amp * np.arange(n) / 24.0

    elif ft == "noise_burst":
        v += rng.normal(0.0, amp, n)

    else:
        raise ValueError(f"unknown fault type {ft}")

    if ft != "dropout":
        v = np.clip(v, lo, hi)
        v = _quantise(v, var)
    return v, touched


def inject_shield_failure(out: pd.DataFrame, events: list, eid: int,
                          rate_per_station_year: float = 0.15,
                          seed: int = 4242) -> tuple[pd.DataFrame, list, int]:
    """Radiation-shield degradation: the one fault shape derived from physics.

    Every other fault in this file is a shape someone chose. This one falls out
    of thermodynamics, which is why it is worth having: it is the only injected
    fault whose signature we did not get to pick.

    A radiation shield keeps sunlight off the probes. When it degrades -- dirty,
    cracked, or aspiration lost -- the air inside is heated above ambient during
    daylight. Both probes then measure that heated air:

        T reads high, by an amount that follows the solar cycle
        RH reads low, because warmer air of the SAME vapour content is further
          from saturation

    and the consequence is the discriminator: heating air at constant vapour
    content leaves the DEW POINT UNCHANGED. Verified numerically -- a 1.0, 2.5
    or 4.0 K shield bias all leave Td at 20.102 C, to three decimals.

    A genuine warm dry airmass, by contrast, carries less vapour: the same
    warming moves Td from 20.1 to 17.5 or 15.5. So:

        T up, RH down, Td unchanged   -> the shield, or the siting
        T up, RH down, Td down        -> real weather

    That is a test on three parameters we already have, and it separates a
    sensor problem from an atmospheric one without any labelled training data.
    """
    from physics.relations import vapour_pressure, saturation_vapour_pressure

    rng = np.random.default_rng(seed)
    idx_all = out.index.to_numpy()

    for si, (station, g) in enumerate(out.groupby("station_name", sort=True)):
        idx = g.index.to_numpy()
        n = len(idx)
        n_ev = rng.poisson(rate_per_station_year * n / (365.25 * 24))
        occupied = np.zeros(n, dtype=bool)

        for _ in range(n_ev):
            # Shields degrade over weeks, not hours.
            dur = int(round(_loguniform(336, min(2160, n // 4), rng)))
            # Must not land on a window that already carries a fault. The
            # per-variable pass has already run, and overlapping it would both
            # overwrite its label and break the physics this fault exists to
            # demonstrate -- a drift underneath the shield heating moves the dew
            # point, which is precisely the thing that is supposed to stay put.
            for _try in range(60):
                a = int(rng.integers(0, max(n - dur, 1)))
                lo, hi = max(0, a - 72), min(n, a + dur + 72)
                if occupied[lo:hi].any():
                    continue
                seg = idx[a:a + dur]
                if bool(out.loc[seg, "is_fault_temp"].any()) or                    bool(out.loc[seg, "is_fault_rh"].any()):
                    continue
                break
            else:
                continue
            occupied[a:a + dur] = True

            rows = idx[a:a + dur]
            peak = _loguniform(0.4, 4.0, rng)          # peak daytime bias, K

            sh = out.loc[rows, "solar_hour"].to_numpy(dtype=float)
            # Solar heating: a half sine from sunrise to sunset, zero at night.
            # A shield that has failed does nothing in the dark, which is itself
            # part of the signature.
            w = np.clip(np.sin(np.pi * (sh - 6.0) / 12.0), 0.0, None)
            # ramp in over the first third -- degradation is gradual
            ramp = np.clip(np.arange(dur) / max(dur / 3.0, 1.0), 0.0, 1.0)
            dT = peak * w * ramp

            t = out.loc[rows, "temp"].to_numpy(dtype=float)
            rh = out.loc[rows, "rh"].to_numpy(dtype=float)
            ok = np.isfinite(t) & np.isfinite(rh)
            e = np.array([vapour_pressure(a_, b_) if o else np.nan
                          for a_, b_, o in zip(t, rh, ok)])
            t_new = t + dT
            es_new = np.array([saturation_vapour_pressure(v) if o else np.nan
                               for v, o in zip(t_new, ok)])
            rh_new = np.clip(100.0 * e / es_new, 0.0, 100.0)

            out.loc[rows, "temp"] = np.round(t_new / RESOLUTION["temp"]) * RESOLUTION["temp"]
            out.loc[rows, "rh"] = np.round(rh_new / RESOLUTION["rh"]) * RESOLUTION["rh"]

            for var in ("temp", "rh"):
                out.loc[rows, f"is_fault_{var}"] = True
                out.loc[rows, f"fault_type_{var}"] = "shield_failure"
                out.loc[rows, f"event_id_{var}"] = eid

            ts = out.loc[rows, "timestamp"]
            for var in ("temp", "rh"):
                events.append(Event(station, var, "shield_failure",
                                    str(ts.iloc[0]), str(ts.iloc[-1]), dur,
                                    round(peak, 4), 1))
            eid += 1

    return out, events, eid


def inject(df: pd.DataFrame, events_per_station_year: float = 1.5,
           seed: int = 7, min_gap_h: int = 72) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inject faults into a prepared frame. Returns (faulted_df, events_df).

    The returned frame gains three ground-truth columns PER VARIABLE:
        is_fault_<var>    bool, point-level label
        fault_type_<var>  str, '' where clean
        event_id_<var>    int, -1 where clean -- lets you score event-level

    Ground truth lives in the frame rather than a side file on purpose: it is
    impossible to accidentally misalign a label with its timestamp.
    """
    out = df.copy().sort_values(["station_name", "timestamp"]).reset_index(drop=True)
    for var in VARIABLES:
        out[f"is_fault_{var}"] = False
        out[f"fault_type_{var}"] = ""
        out[f"event_id_{var}"] = -1

    types = list(WEIGHTS)
    probs = np.array([WEIGHTS[t] for t in types], dtype=float)
    probs /= probs.sum()

    events: list[Event] = []
    eid = 0

    for si, (station, g) in enumerate(out.groupby("station_name", sort=True)):
        idx = g.index.to_numpy()
        n = len(idx)
        years = n / (365.25 * 24)

        for vi, var in enumerate(VARIABLES):
            rng = np.random.default_rng(seed + si * 1013 + vi * 97)
            n_events = rng.poisson(events_per_station_year * years)
            occupied = np.zeros(n, dtype=bool)

            for _ in range(n_events):
                ft = types[rng.choice(len(types), p=probs)]
                dlo, dhi = DURATION[ft]
                dur = int(round(_loguniform(dlo, min(dhi, n // 4), rng)))
                dur = max(1, min(dur, n // 4))

                # find a free window, guarded by min_gap_h on both sides
                for _try in range(40):
                    s = int(rng.integers(0, n - dur))
                    a = max(0, s - min_gap_h)
                    b = min(n, s + dur + min_gap_h)
                    if not occupied[a:b].any():
                        break
                else:
                    continue  # crowded; skip rather than overlap
                occupied[s:s + dur] = True

                sign = int(rng.choice([-1, 1]))
                amp = (_loguniform(*AMPLITUDE[ft][var], rng)
                       if ft in AMPLITUDE else float("nan"))

                rows = idx[s:s + dur]
                new, touched = _apply(out.loc[rows, var].to_numpy(),
                                      ft, var, amp, sign, rng)
                out.loc[rows, var] = new
                # Label only what was actually changed.
                lab = rows[touched]
                out.loc[lab, f"is_fault_{var}"] = True
                out.loc[lab, f"fault_type_{var}"] = ft
                out.loc[lab, f"event_id_{var}"] = eid

                ts = out.loc[lab, "timestamp"]
                events.append(Event(station, var, ft, str(ts.iloc[0]), str(ts.iloc[-1]),
                                    int(touched.sum()),
                                    round(amp, 4) if amp == amp else float("nan"),
                                    sign))
                eid += 1

    if "solar_hour" in out.columns:
        out, events, eid = inject_shield_failure(out, events, eid,
                                                 seed=seed + 4242)

    ev = pd.DataFrame([asdict(e) for e in events])
    if not ev.empty:
        ev.insert(0, "event_id", range(len(ev)))
    return out, ev


def split(df: pd.DataFrame, holdout_stations: tuple[str, ...],
          holdout_from: str) -> pd.DataFrame:
    """Label rows train/test by WHOLE STATION and WHOLE TIME PERIOD.

    Never a random point split. Residuals are autocorrelated over days, so a
    random split leaks the answer across the boundary and inflates every metric.
    """
    out = df.copy()
    cut = pd.Timestamp(holdout_from, tz="UTC")
    out["split"] = np.where(
        out.station_name.isin(holdout_stations) | (out.timestamp >= cut),
        "test", "train")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_realistic.csv")
    ap.add_argument("--out", default="data")
    ap.add_argument("--rate", type=float, default=1.5,
                    help="events per station per variable per year")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--replicates", type=int, default=10,
                    help="independent realisations; raises event count without "
                         "raising point-level prevalence")
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])

    # Replicates, not a higher rate. Prevalence must stay in the low single
    # digits to keep the class imbalance honest, but 50 events cannot support a
    # per-fault-type POD curve. Independent realisations of the same year give
    # the event count without touching the imbalance -- each run is scored on
    # its own and the curves are pooled across runs.
    frames, evs = [], []
    for r in range(args.replicates):
        f, e = inject(df, events_per_station_year=args.rate,
                      seed=args.seed + r * 100_003)
        f.insert(0, "run_id", r)
        e.insert(0, "run_id", r)
        frames.append(f)
        evs.append(e)
    faulted = pd.concat(frames, ignore_index=True)
    ev = pd.concat(evs, ignore_index=True)
    ev["event_uid"] = ev.run_id.astype(str) + ":" + ev.event_id.astype(str)
    faulted = split(faulted, holdout_stations=("Silchar", "Pune"),
                    holdout_from="2023-10-01")

    from pathlib import Path
    outdir = Path(args.out)
    faulted.to_csv(outdir / "skyguard_injected.csv", index=False)
    ev.to_csv(outdir / "injected_events.csv", index=False)

    pt = {v: float(faulted[f"is_fault_{v}"].mean()) for v in VARIABLES}
    print(f"replicates: {args.replicates}")
    print(ev.groupby(["fault_type", "variable"]).size().unstack(fill_value=0).to_string())
    print(f"\n{len(ev)} events over {faulted.station_name.nunique()} stations")
    print("point-level prevalence: " +
          "  ".join(f"{v} {p*100:.2f}%" for v, p in pt.items()))
    print("split: " + faulted.split.value_counts().to_string().replace("\n", "  "))
    print(f"\nwrote {outdir/'skyguard_injected.csv'}")
    print(f"wrote {outdir/'injected_events.csv'}")


if __name__ == "__main__":
    main()
