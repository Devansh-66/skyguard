"""Is the semidiurnal pressure tide a usable per-station reference clock?

    python -m evaluation.run_tide

WHY THIS MIGHT MATTER

Every detector we have needs neighbours. IMD's operational spatial regression
test (Ranalkar et al., MAUSAM 66(1), 2015) needs them too, over a 2x2 degree
box. So the Himalayan, Thar, island and northeast stations -- the ones hardest
to visit and least affordable to lose -- are exactly the ones no buddy method
can reach.

The atmospheric solar semidiurnal tide S2 is a candidate way in. It is a large,
near-deterministic 12-hour oscillation in surface pressure, strongest in the
tropics, and it is driven by solar heating of ozone and water vapour rather than
by local weather. If its phase is stable enough at one station, that station
carries its own clock, and a drifting logger shows up as a phase shift with no
neighbour involved. Logger clock drift is otherwise nearly undetectable: the
series stays internally perfect, so every temporal check passes.

WHAT WOULD KILL THE IDEA, AND IS TESTED HERE

  1. S2 amplitude too small against our pressure noise -> no usable phase.
  2. S2 phase not stable window to window -> the "clock" wanders more than the
     drift we want to catch, and the method is worthless.
  3. Phase precision too poor to resolve an operationally interesting clock
     offset in an operationally interesting time.

Any of those and we drop it rather than dress it up.

A CAVEAT THAT MUST TRAVEL WITH THE RESULT. This runs on ERA5-derived hourly
data, not on real barometer records. ERA5 represents the tide, but hourly
sampling gives only 12 samples per S2 cycle, and a reanalysis is smoother than
a real instrument. Treat any number here as an upper bound on how well this
works, and as a go/no-go signal only.
"""
from __future__ import annotations
import argparse

import numpy as np
import pandas as pd

# Solar tidal components. S1 and S3 are fitted alongside S2 so that power
# belonging to them is not swept into the S2 estimate -- S1 in particular is
# large and would bias the phase badly if ignored.
PERIODS_H = (24.0, 12.0, 8.0)


def _design(hours: np.ndarray) -> np.ndarray:
    cols = [np.ones_like(hours)]
    for p in PERIODS_H:
        w = 2.0 * np.pi * hours / p
        cols += [np.sin(w), np.cos(w)]
    return np.column_stack(cols)


def fit_tide(hours: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Return (S2 amplitude in hPa, S2 phase in radians)."""
    ok = np.isfinite(p)
    if ok.sum() < 48:
        return float("nan"), float("nan")
    X = _design(hours[ok])
    beta, *_ = np.linalg.lstsq(X, p[ok], rcond=None)
    a, b = beta[3], beta[4]          # S2 sin, cos
    return float(np.hypot(a, b)), float(np.arctan2(b, a))


def wrap(x: np.ndarray) -> np.ndarray:
    """Wrap angles to (-pi, pi] so a phase near the branch cut does not blow up."""
    return (x + np.pi) % (2.0 * np.pi) - np.pi


def phase_to_minutes(phase_rad: float) -> float:
    """A phase shift of a 12-hour wave, expressed as clock error in minutes."""
    return phase_rad * 12.0 * 60.0 / (2.0 * np.pi)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_realistic.csv")
    ap.add_argument("--window-days", type=int, default=30)
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    print(f"{len(df):,} rows, {df.station_name.nunique()} stations\n")

    print("=== 1. Is S2 big enough, and is its phase stable? ===")
    print(f"Per station, fitted in independent {args.window_days}-day windows.")
    print("phase SD is converted to the clock error it corresponds to.\n")

    rows = []
    per_station_windows = {}
    for st, g in df.groupby("station_name", sort=True):
        g = g.sort_values("timestamp")
        t = g.timestamp
        hours = (t - t.iloc[0]).dt.total_seconds().to_numpy() / 3600.0
        p = g.pres.to_numpy(dtype=float)

        amps, phases = [], []
        step = args.window_days * 24
        for s in range(0, len(g) - step + 1, step):
            A, ph = fit_tide(hours[s:s + step], p[s:s + step])
            if np.isfinite(A):
                amps.append(A)
                phases.append(ph)
        if len(amps) < 4:
            continue
        amps = np.asarray(amps)
        phases = np.asarray(phases)
        # Circular SD, via the mean resultant length. A plain SD would be wrong
        # for angles near the wrap point.
        R = np.hypot(np.mean(np.sin(phases)), np.mean(np.cos(phases)))
        circ_sd = float(np.sqrt(-2.0 * np.log(max(R, 1e-12))))
        per_station_windows[st] = (hours, p)
        rows.append({
            "station": st,
            "n_win": len(amps),
            "S2 amp hPa": round(float(np.mean(amps)), 3),
            "amp SD": round(float(np.std(amps)), 3),
            "phase SD rad": round(circ_sd, 4),
            "= clock SD min": round(abs(phase_to_minutes(circ_sd)), 1),
        })

    t1 = pd.DataFrame(rows)
    print(t1.to_string(index=False))
    med_amp = float(t1["S2 amp hPa"].median())
    med_clk = float(t1["= clock SD min"].median())
    print(f"\nmedian S2 amplitude {med_amp:.3f} hPa, "
          f"median phase scatter equals {med_clk:.1f} min of clock error")

    print("\n=== 2. Can a known clock offset be recovered? ===")
    print("The series is shifted by a known amount and the tide refitted. If the")
    print("recovered shift does not track the injected one, the method is dead.\n")

    out = []
    for shift_min in (0, 10, 20, 30, 60, 120):
        errs = []
        for st, (hours, p) in per_station_windows.items():
            step = args.window_days * 24
            for s in range(0, len(hours) - step + 1, step):
                h, pp = hours[s:s + step], p[s:s + step]
                _, ph0 = fit_tide(h, pp)
                # A logger clock running fast by `shift_min` labels each sample
                # with a timestamp that is too late; the fitted phase moves by
                # the same amount. Shifting the time axis reproduces exactly
                # that, without touching the pressure values.
                _, ph1 = fit_tide(h + shift_min / 60.0, pp)
                errs.append(phase_to_minutes(wrap(np.array([ph1 - ph0]))[0]))
        errs = np.asarray(errs)
        out.append({"injected min": shift_min,
                    "recovered median min": round(float(np.median(errs)), 1),
                    "recovered IQR min": round(float(np.subtract(
                        *np.percentile(errs, [75, 25]))), 1)})
    print(pd.DataFrame(out).to_string(index=False))

    print("\n=== 3. Verdict ===")
    detectable = 3.0 * med_clk
    print(f"Smallest clock error separable from natural phase scatter at 3 sigma,")
    print(f"using one {args.window_days}-day window: about {detectable:.0f} minutes.")
    if med_amp < 0.3:
        print("KILL: S2 amplitude is too small here to carry a usable phase.")
    elif detectable > 120:
        print("KILL: phase scatter swamps any clock error worth catching.")
    else:
        print("VIABLE on this data -- worth testing on real barometer records,")
        print("which is the only test that settles it.")
    print("\nERA5 hourly data gives 12 samples per S2 cycle and is smoother than")
    print("a real barometer. Treat these as an upper bound, not a result.")


if __name__ == "__main__":
    main()
