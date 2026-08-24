"""Does our headline number describe a timescale, or a sample count?

    python -m evaluation.run_cadence

Our data is hourly ERA5. Real AWS report every 15 minutes, or every minute on
the GPRS network (IMD Vision 2047, section 1.1.1). If our results are really
about hourly sampling rather than about physical timescales, none of them
transfer, and we would not know until someone asked.

Every window in the code is expressed in SAMPLES. At 15-minute data the same
"720-sample" window is 7.5 days rather than 30, and the same "24-sample" window
is 6 hours rather than a full diurnal cycle. That is the trap this script exists
to expose.

WHAT IS AND IS NOT TESTED HONESTLY. Downsampling to 3-hourly uses real data --
every value is one we already had. Upsampling to 15 minutes CANNOT be honest
about sub-hourly variability, because ERA5 does not contain any: interpolating
would invent a suspiciously smooth signal and flatter every detector. So the
15-minute arm interpolates the mean and adds sub-hourly noise from the same
assumption used in scripts/realism.py, and it is labelled synthetic throughout.
It answers "do the windows scale", not "how good are we on real 15-minute data".
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from detect.baseline import harmonic_baseline, _huber_irls, robust_sigma

VARIABLES = ("temp", "rh", "pres")
DRIFT_K_PER_DAY = 0.02


def resample(df: pd.DataFrame, step_hours: float, seed: int = 5) -> pd.DataFrame:
    """Change cadence. Downsampling is real; upsampling is explicitly synthetic."""
    out = []
    rng = np.random.default_rng(seed)
    for st, g in df.groupby("station_name", sort=True):
        g = g.sort_values("timestamp").reset_index(drop=True)
        if step_hours >= 1.0:
            k = int(round(step_hours))
            out.append(g.iloc[::k].copy())        # instantaneous samples, real
        else:
            per = int(round(1.0 / step_hours))
            t = pd.date_range(g.timestamp.iloc[0], g.timestamp.iloc[-1],
                              freq=f"{int(step_hours*60)}min")
            num = [c for c in ("temp", "rh", "pres", "solar_hour", "doy")
                   if c in g.columns]
            gi = g.set_index("timestamp")[num]
            union = gi.index.union(t)
            h = (gi.reindex(union).interpolate("time")
                   .reindex(t).rename_axis("timestamp").reset_index())
            h["station_name"] = st
            # Sub-hourly variability ERA5 does not contain. Same AR(1) form as
            # scripts/realism.py, scaled so the HOURLY mean is unchanged --
            # otherwise finer sampling would silently add energy the atmosphere
            # does not have.
            for v, sd in (("temp", 0.15), ("rh", 0.9), ("pres", 0.05)):
                if v not in h:
                    continue
                phi = np.exp(-1.0 / (per * 1.5))
                e = rng.normal(0, np.sqrt(1 - phi * phi), len(h))
                x = np.empty(len(h)); x[0] = rng.normal()
                for i in range(1, len(h)):
                    x[i] = phi * x[i - 1] + e[i]
                x -= pd.Series(x).rolling(per, min_periods=1).mean().to_numpy()
                h[v] = h[v] + sd * x
            # solar_hour must be recomputed rather than interpolated -- it
            # wraps at 24 and linear interpolation across the wrap produces a
            # station that briefly runs backwards through the day.
            lon = float(g["longitude"].iloc[0]) if "longitude" in g else 0.0
            hh = h.timestamp.dt.hour + h.timestamp.dt.minute / 60.0
            h["solar_hour"] = (hh + lon / 15.0) % 24.0
            h["doy"] = h.timestamp.dt.dayofyear
            h["longitude"] = lon
            out.append(h)
    return pd.concat(out, ignore_index=True)


def daily_neighbour_sigma(df: pd.DataFrame, graph: dict, var: str = "temp") -> dict:
    """Sigma of the DAILY-MEAN neighbour difference, per station.

    This is the statistic the drift detector actually runs on, and it is the
    reason cadence should not matter much: a daily mean of 96 samples is less
    noisy than a daily mean of 24, so finer sampling should help slightly rather
    than hurt. Worth checking rather than asserting.
    """
    res = {}
    for st, g in df.groupby("station_name", sort=True):
        g = g.sort_values("timestamp")
        y = g[var].to_numpy(dtype=float)
        ok = np.isfinite(y)
        if ok.sum() < 200:
            continue
        X = harmonic_baseline(g, var)
        r = y - X @ _huber_irls(X[ok], y[ok])
        res[st] = pd.Series(r, index=g.timestamp.values)
    daily = pd.DataFrame(res).resample("D").mean()
    out = {}
    for st in daily.columns:
        nb = [n for n in graph.get(st, {}).get("neighbours", []) if n in daily.columns]
        if not nb:
            continue
        d = daily[st] - daily[nb].median(axis=1)
        out[st] = float(d.std())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_realistic.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    args = ap.parse_args()

    base = pd.read_csv(args.data, parse_dates=["timestamp"])
    base = base[base.timestamp < pd.Timestamp("2023-10-01", tz="UTC")]
    graph = json.loads(Path(args.graph).read_text())

    cadences = [("15 min (synthetic)", 0.25), ("1 h (real)", 1.0),
                ("3 h (real)", 3.0), ("6 h (real)", 6.0)]

    print("=== 1. Does the drift statistic survive a cadence change? ===")
    print("Sigma of the daily-mean neighbour difference, and the drift slope it")
    print(f"can resolve at 3 sigma. Detector works on DAILY means, so cadence")
    print("should matter little -- more samples per day, less noise in the mean.\n")
    rows = []
    for name, step in cadences:
        d = resample(base, step)
        sig = daily_neighbour_sigma(d, graph)
        if not sig:
            continue
        med = float(np.median(list(sig.values())))
        rows.append({"cadence": name,
                     "samples/day": round(24 / step),
                     "rows/station": int(len(d) / d.station_name.nunique()),
                     "daily sigma K": round(med, 4),
                     "latency d @0.02K/day": round(3 * med / DRIFT_K_PER_DAY),
                     "min slope @60d, K/day": round(3 * med / 60, 4)})
    t1 = pd.DataFrame(rows)
    print(t1.to_string(index=False))

    print("\n=== 2. The trap: windows are in SAMPLES, not hours ===")
    print("What a fixed sample count means in real time at each cadence.\n")
    w = []
    for name, step in cadences:
        w.append({"cadence": name,
                  "720 samples =": f"{720*step/24:.1f} days",
                  "24 samples =": f"{24*step:.0f} h",
                  "12 samples =": f"{12*step:.0f} h"})
    print(pd.DataFrame(w).to_string(index=False))
    print("\nAt 15-minute data an unscaled 720-sample scale window covers 7.5 days")
    print("instead of 30, and an unscaled 24-sample Hampel window covers 6 hours")
    print("instead of a full diurnal cycle -- so it would no longer contain the")
    print("cycle it is meant to normalise against. Any deployment at a different")
    print("cadence must rescale every window by TIME, not carry the sample counts")
    print("across.")


if __name__ == "__main__":
    main()
