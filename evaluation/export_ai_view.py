"""Run the belief engine over one real ARM fault and export what the page shows.

    python -m evaluation.export_ai_view

WHY A REAL FAULT AND NOT MOCK DATA

The page could be filled with invented numbers in an afternoon. It would also be
worth nothing: the whole argument of this project is that claims must be
measured, and a screenshot of fabricated belief states is exactly the thing it
criticises elsewhere. So this runs the actual estimator over an actual ARM
station during an interval a human wrote up as faulty, and exports whatever it
finds -- including when what it finds is unimpressive.

THE CASE, AND WHY THIS ONE

sgpmetE37, DQR D160923.11: 220 hours from 2016-08-24, and the report names
atmos_pressure, rh_mean AND BOTH housekeeping channels, logger_temp and
logger_volt. That is the only kind of window that can exercise the hardware
checker, which is the one evidence source not derived from the three
meteorological numbers and therefore the one that makes corroboration mean
anything.

THE CAVEAT THAT SHIPS ON THE PAGE ITSELF

Until contemporaneous SGP coverage is downloaded, the reference is the station's
own trailing window, which self-masks on any fault longer than that window --
and this fault is 220 hours against a 168-hour window. The export records that
fact so the page can display it rather than quietly present a compromised
number as a result.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from detect.belief import Belief, BIAS_TOLERANCE
from detect.checkers import PANEL, adjudicate, DoubleFaultMatrix

warnings.filterwarnings("ignore")

SENSORS = {"temp": ("temp_mean", "°C", "Temperature"),
           "pres": ("atmos_pressure", "hPa", "Pressure"),
           "rh": ("rh_mean", "%", "Relative humidity"),
           "volt": ("logger_volt", "V", "Logger voltage"),
           "ltemp": ("logger_temp", "°C", "Logger temperature")}
HK = ("volt", "ltemp")


def read_station(root: str, station: str) -> pd.DataFrame:
    import netCDF4
    frames = []
    for f in sorted(glob.glob(os.path.join(root, "**", f"{station}.*.cdf"),
                              recursive=True)):
        try:
            d = netCDF4.Dataset(f)
        except Exception:
            continue
        try:
            m = re.search(r"\.(\d{8})\.", os.path.basename(f))
            if not m or "temp_mean" not in d.variables:
                continue
            t = (pd.Timestamp(m.group(1))
                 + pd.to_timedelta(np.asarray(d.variables["time"][:]), unit="s"))
            row = {"timestamp": t}
            for short, (name, _u, _l) in SENSORS.items():
                if name in d.variables:
                    v = np.asarray(d.variables[name][:], float)
                    if short == "pres":
                        v = v * 10.0                       # ARM ships kPa
                    qc = "qc_" + name
                    if qc in d.variables:
                        v = np.where(np.asarray(d.variables[qc][:], int) == 0,
                                     v, np.nan)
                    row[short] = v
                else:
                    row[short] = np.full(len(t), np.nan)
            frames.append(pd.DataFrame(row))
        finally:
            d.close()
    if not frames:
        raise SystemExit(f"no files for {station} under {root}")
    df = pd.concat(frames, ignore_index=True).sort_values("timestamp")
    return (df.set_index("timestamp").resample("1h").mean(numeric_only=True)
              .reset_index())


def _reference_note(window_h: float, fault_h: float) -> dict:
    """Say honestly how badly the trailing reference is compromised HERE.

    Written from the two numbers rather than hardcoded, because the severity is
    entirely a matter of how the fault length compares to the window -- and a
    fixed sentence quoting the wrong duration is exactly the kind of stale claim
    this project keeps finding and correcting.
    """
    if fault_h >= window_h:
        sev = (f"this fault lasts {fault_h:.0f} hours, LONGER than the "
               f"{window_h:.0f}-hour window, so for most of it the reference "
               f"sits inside the fault, adapts into it, and the station looks "
               f"healthier than it is")
    elif fault_h >= 0.5 * window_h:
        sev = (f"this fault lasts {fault_h:.0f} hours against a "
               f"{window_h:.0f}-hour window, so the reference is partly "
               f"contaminated by the fault and the estimate here is weakened")
    else:
        sev = (f"this fault lasts {fault_h:.0f} hours against a "
               f"{window_h:.0f}-hour window, so the reference is mostly clean "
               f"and the estimate is usable, though not immune")
    return {
        "kind": "trailing", "window_hours": window_h,
        "fault_hours": round(fault_h, 1),
        "compromised": fault_h >= 0.5 * window_h,
        "warning": ("The reference is this station's own trailing window: "
                    + sev + ". A neighbour reference needs contemporaneous "
                    "coverage across the co-located SGP stations; see "
                    "scripts/fetch_sgp_block.ps1."),
    }


def trailing_z(s: pd.Series, window: int = 168) -> np.ndarray:
    med = s.rolling(window, min_periods=24).median().shift(1)
    mad = (s - med).abs().rolling(window, min_periods=24).median().shift(1)
    return ((s - med) / (1.4826 * mad).replace(0, np.nan)).to_numpy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--station", default="sgpmetE37")
    ap.add_argument("--dqr", default="D160923.11")
    ap.add_argument("--root", default="data/arm/raw")
    ap.add_argument("--dqr-csv", default="data/arm/dqr_tprh.csv")
    ap.add_argument("--out", default="dashboard/ai_view.json")
    args = ap.parse_args()

    dq = pd.read_csv(args.dqr_csv, parse_dates=["start", "end"])
    row = dq[dq.dqr == args.dqr]
    if row.empty:
        raise SystemExit(f"DQR {args.dqr} not in {args.dqr_csv}")
    row = row.iloc[0]
    t0, t1 = row["start"], row["end"]

    df = read_station(args.root, args.station)
    df = df[(df.timestamp >= t0 - pd.Timedelta(days=6))
            & (df.timestamp <= t1 + pd.Timedelta(days=4))].reset_index(drop=True)
    if len(df) < 48:
        raise SystemExit("not enough data around this window")
    df["faulty"] = (df.timestamp >= t0) & (df.timestamp <= t1)

    print(f"{args.station}  {args.dqr}")
    print(f"  {row['subject']}")
    print(f"  {t0} -> {t1}  ({(t1-t0).total_seconds()/3600:.0f} h)")
    print(f"  variables named in the report: {row['variables']}")
    print(f"  {len(df)} hourly rows, {int(df.faulty.sum())} inside the window\n")

    series, finals = {}, {}
    for short, (_name, unit, label) in SENSORS.items():
        if short not in df or df[short].notna().sum() < 48:
            continue
        z = trailing_z(df[short])
        b = Belief(station=args.station, sensor=short)
        pts, prev = [], None
        for i, ts in enumerate(df.timestamp):
            if np.isfinite(z[i]):
                dt = 0.0 if prev is None else (ts - prev).total_seconds() / 86400.0
                b = b.update(float(z[i]), dt, ts.to_pydatetime())
                prev = ts
            pts.append({
                "t": ts.isoformat(),
                "v": None if not np.isfinite(df[short][i]) else round(float(df[short][i]), 3),
                "z": None if not np.isfinite(z[i]) else round(float(z[i]), 3),
                "bias": round(b.bias, 3), "trust": round(b.trust, 3),
                "faulty": bool(df.faulty[i]),
            })
        lo, hi = b.bias_ci
        finals[short] = {
            "label": label, "unit": unit,
            "bias": round(b.bias, 3), "bias_lo": round(lo, 3), "bias_hi": round(hi, 3),
            "drift_per_day": round(b.drift, 4),
            "noise": round(b.noise, 3),
            "trust": round(b.trust, 3),
            "evidence": round(b.trust_confidence, 1),
            "checks": b.checks_passed,
            "days_to_spec": b.days_to_spec(BIAS_TOLERANCE),
            "named_in_report": SENSORS[short][0] in str(row["variables"]),
            "housekeeping": short in HK,
        }
        series[short] = pts

    # the checker panel, evaluated at the worst hour inside the window
    inside = df[df.faulty]
    # Choose the worst hour among hours the station ACTUALLY REPORTED. Taking
    # the plain maximum lands on the first all-NaN hour of a dropout, where
    # nothing but the physics check can say anything and the panel demonstrates
    # nothing. Found on a real ARM lightning-strike window.
    zt = trailing_z(df["temp"])
    has_data = df[["temp", "pres", "rh"]].notna().all(axis=1).to_numpy()
    cand = np.where(df.faulty.to_numpy() & has_data, np.abs(zt), np.nan)
    j = int(np.nanargmax(cand)) if np.isfinite(cand).any() else int(inside.index[0])
    ctx = {
        "temp": float(df.temp[j]), "pres": float(df.pres[j]), "rh": float(df.rh[j]),
        "neighbour_diff": None, "neighbour_sigma": None, "n_neighbours": 0,
        "own_resid": float(zt[j]) if np.isfinite(zt[j]) else None, "own_sigma": 1.0,
        "flat_fraction": 0.0, "jump_sigma": float(zt[j]) if np.isfinite(zt[j]) else 0.0,
        "clock_offset_min": None,
        "volt_z": (float(trailing_z(df["volt"])[j]) if "volt" in df else None),
        "logger_temp_z": (float(trailing_z(df["ltemp"])[j]) if "ltemp" in df else None),
    }
    verdicts = [c(ctx) for c in PANEL]
    dec = adjudicate(verdicts, DoubleFaultMatrix("models/double_fault.json"))

    print("checker panel at the worst hour inside the window "
          f"({df.timestamp[j]}):")
    for v in verdicts:
        mark = "FIRED" if v.fired else "  -  "
        print(f"  [{mark}] {v.checker:11s} {v.score:+6.2f}  {v.reason}")
    print(f"\n  adjudication: {dec.verdict.upper()} — {dec.note or dec.corroborated_by}")

    out = {
        "station": args.station,
        "dqr": {"id": args.dqr, "subject": str(row["subject"]),
                "start": t0.isoformat(), "end": t1.isoformat(),
                "hours": round((t1 - t0).total_seconds() / 3600, 1),
                "variables": str(row["variables"]),
                "description": str(row["description"])[:400]},
        "reference": _reference_note(168, (t1 - t0).total_seconds() / 3600.0),
        "sensors": finals,
        "series": series,
        "panel": {
            "at": df.timestamp[j].isoformat(),
            "verdicts": [{"checker": v.checker, "fired": v.fired,
                          "score": round(v.score, 2), "reason": v.reason}
                         for v in verdicts],
            "decision": dec.verdict,
            "note": dec.note,
            "corroborated_by": list(dec.corroborated_by) if dec.corroborated_by else None,
        },
    }
    p = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"\nwrote {args.out}  ({os.path.getsize(p)/1024:.0f} kB)")


if __name__ == "__main__":
    main()
