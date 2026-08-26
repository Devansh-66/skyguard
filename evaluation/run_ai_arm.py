"""Run the belief engine and the checker panel on real ARM instruments.

    python -m evaluation.run_ai_arm

WHY THIS IS DIFFERENT FROM EVERY OTHER SCRIPT IN THIS DIRECTORY

Everything else here measures against faults we injected ourselves, which bounds
what those numbers can mean: they estimate P(detect | faults from our generator),
not P(detect | real faults). This runs against ARM's Data Quality Reports --
intervals a human wrote down after going and looking at the instrument, with a
stated cause and exact start and end times.

So for the first time the question is the right one: does the belief engine move
when a real instrument was really broken, and does the housekeeping channel see
it coming?

THE THREE THINGS BEING TESTED

  1. BELIEF TRACKS REALITY.  Does bias/drift/trust actually diverge inside a
     DQR window and settle outside it? If the state is flat through a
     human-confirmed fault, the estimator is decoration.

  2. HOUSEKEEPING IS INDEPENDENT.  Is the hardware channel's error uncorrelated
     with the meteorological ones? This is the assumption the whole corroboration
     rule rests on, and the literature says assumed independence usually fails.
     Measured here as a double-fault rate, and written to disk so the adjudicator
     can load it instead of guessing.

  3. HOUSEKEEPING LEADS.  Does logger voltage or logger temperature depart
     BEFORE the meteorological channels do? That is the difference between
     predicting a fault and noticing one, and it is what the problem statement
     asks for under "predict possible sensor degradation".

WHAT THIS CANNOT SHOW. ARM sites are research-grade and better maintained than a
national operational network, and they are North Atlantic, Alaskan and Great
Plains rather than Indian. Rates here are a lower bound on IMD's, and the
climatology is different. This establishes MECHANISM, not Indian performance.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import re
import warnings
from itertools import combinations

import sys

import numpy as np
import pandas as pd

# Windows defaults stdout to cp1252 when redirected, which kills this script on
# the first sigma it prints -- and only when output is piped to a file, so it
# passes interactively and fails in a log. Force UTF-8 rather than avoid the
# character.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from detect.belief import BeliefStore
from detect.checkers import FIRE_AT

warnings.filterwarnings("ignore")

VARS = {"temp": "temp_mean", "pres": "atmos_pressure", "rh": "rh_mean",
        "volt": "logger_volt", "ltemp": "logger_temp"}
# meteorological channels share a measurement chain; housekeeping does not
MET = ("temp", "pres", "rh")
HK = ("volt", "ltemp")


def load(paths):
    import netCDF4
    frames = []
    for f in paths:
        try:
            d = netCDF4.Dataset(f)
        except Exception:
            continue
        try:
            if "temp_mean" not in d.variables:
                continue
            m = re.search(r"\.(\d{8})\.", os.path.basename(f))
            if not m:
                continue
            base = pd.Timestamp(m.group(1))
            t = base + pd.to_timedelta(np.asarray(d.variables["time"][:]), unit="s")
            row = {"timestamp": t}
            for short, name in VARS.items():
                if name in d.variables:
                    v = np.asarray(d.variables[name][:], float)
                    if short == "pres":
                        v = v * 10.0                     # ARM ships kPa
                    qc = "qc_" + name
                    if qc in d.variables:
                        v = np.where(np.asarray(d.variables[qc][:], int) == 0, v, np.nan)
                    row[short] = v
                else:
                    row[short] = np.full(len(t), np.nan)
            g = pd.DataFrame(row)
            g["station"] = os.path.basename(f).split(".")[0]
            frames.append(g)
        finally:
            d.close()
    if not frames:
        raise SystemExit("no readable ARM files")
    return pd.concat(frames, ignore_index=True).sort_values(["station", "timestamp"])


def hourly(df):
    """One-minute data is finer than any fault we care about. Aggregate."""
    g = (df.set_index("timestamp").groupby("station")
           .resample("1h").mean(numeric_only=True).reset_index())
    return g.dropna(subset=["temp"], how="all")


def label(df, dqr):
    """Mark rows inside a human-written fault interval."""
    df = df.copy()
    df["faulty"] = False
    for _, r in dqr.iterrows():
        st = str(r["datastream"]).split(".")[0]
        m = ((df.station == st) & (df.timestamp >= r["start"])
             & (df.timestamp <= r["end"]))
        df.loc[m, "faulty"] = True
    return df


def robust_z(x, window=168):
    """Trailing robust z. Causal: today is judged on evidence already in hand."""
    s = pd.Series(x)
    med = s.rolling(window, min_periods=24).median().shift(1)
    mad = (s - med).abs().rolling(window, min_periods=24).median().shift(1)
    return ((s - med) / (1.4826 * mad).replace(0, np.nan)).to_numpy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/arm/raw")
    ap.add_argument("--dqr", default="data/arm/dqr_tprh.csv")
    ap.add_argument("--max-files", type=int, default=500)
    ap.add_argument("--out", default="models/double_fault.json")
    args = ap.parse_args()

    dqr = pd.read_csv(args.dqr, parse_dates=["start", "end"])
    paths = sorted(glob.glob(os.path.join(args.root, "**", "*.cdf"), recursive=True))
    print(f"reading {min(len(paths), args.max_files)} of {len(paths)} ARM files ...")
    df = hourly(load(paths[:args.max_files]))
    df = label(df, dqr)
    print(f"{len(df):,} station-hours, {df.faulty.sum():,} inside a human-written "
          f"fault interval ({100*df.faulty.mean():.1f} %)")
    print(f"stations: {sorted(df.station.unique())}\n")

    # ---------------------------------------------------- 1. does belief move?
    print("=== 1. Does the belief state move when a real instrument is broken? ===")
    print("Bias and trust are driven by the station's departure from its own")
    print("trailing normal. Compared inside against outside DQR windows.\n")

    store = BeliefStore()
    rows = []
    for st, g in df.groupby("station"):
        g = g.sort_values("timestamp").reset_index(drop=True)
        for short in MET + HK:
            if short not in g or g[short].notna().sum() < 200:
                continue
            z = robust_z(g[short].to_numpy())
            prev = None
            recs = []
            for i, ts in enumerate(g.timestamp):
                if not np.isfinite(z[i]):
                    continue
                dt = 0.0 if prev is None else (ts - prev).total_seconds() / 86400.0
                b = store.update(st, short, float(z[i]), dt, ts.to_pydatetime())
                recs.append((bool(g.faulty[i]), abs(b.bias), b.trust))
                prev = ts
            if not recs:
                continue
            r = pd.DataFrame(recs, columns=["faulty", "abs_bias", "trust"])
            if r.faulty.nunique() < 2:
                continue
            rows.append({
                "station": st, "sensor": short,
                "|bias| clean": round(r.loc[~r.faulty, "abs_bias"].median(), 3),
                "|bias| faulty": round(r.loc[r.faulty, "abs_bias"].median(), 3),
                "trust clean": round(r.loc[~r.faulty, "trust"].median(), 3),
                "trust faulty": round(r.loc[r.faulty, "trust"].median(), 3),
            })
    t1 = pd.DataFrame(rows)
    if t1.empty:
        print("  no station/sensor had both clean and faulty periods")
    else:
        print(t1.to_string(index=False))
        sep = (t1["|bias| faulty"] > t1["|bias| clean"]).mean()
        tsep = (t1["trust faulty"] < t1["trust clean"]).mean()
        print(f"\nbias higher inside the fault in {sep*100:.0f} % of cases; "
              f"trust lower in {tsep*100:.0f} %")

    # ------------------------------------- 2. are the channels independent?
    print("\n\n=== 2. Are the checkers actually independent? ===")
    print("Double-fault rate: the fraction of hours BOTH channels are wrong")
    print("together, where 'wrong' means firing on a clean hour or staying")
    print("silent through a faulty one. This is the number the corroboration")
    print("rule needs and that we previously only assumed.\n")

    err = {}
    for short in MET + HK:
        if short not in df:
            continue
        e = []
        for st, g in df.groupby("station"):
            g = g.sort_values("timestamp")
            z = robust_z(g[short].to_numpy())
            fires = np.abs(z) > FIRE_AT
            e.append(pd.DataFrame({"wrong": fires != g.faulty.to_numpy(),
                                   "ok": np.isfinite(z)}))
        e = pd.concat(e, ignore_index=True)
        err[short] = e.wrong.where(e.ok).to_numpy()

    keys = [k for k in MET + HK if k in err]
    dfm = {}
    pair_rows = []
    for a, b in combinations(keys, 2):
        m = np.isfinite(err[a].astype(float)) & np.isfinite(err[b].astype(float))
        if m.sum() < 200:
            continue
        both = float(np.nanmean((err[a][m] == 1) & (err[b][m] == 1)))
        kind = ("met-met" if a in MET and b in MET
                else "hk-hk" if a in HK and b in HK else "MET-HK")
        dfm.setdefault(a, {})[b] = round(both, 4)
        pair_rows.append({"a": a, "b": b, "kind": kind,
                          "double-fault": round(both, 4), "n": int(m.sum())})
    t2 = pd.DataFrame(pair_rows).sort_values("double-fault")
    print(t2.to_string(index=False))

    if not t2.empty:
        mm = t2[t2.kind == "met-met"]["double-fault"].mean()
        mh = t2[t2.kind == "MET-HK"]["double-fault"].mean()
        print(f"\nmean double-fault, met-met {mm:.4f} vs met-hardware {mh:.4f}")
        from detect.checkers import TAU_DOUBLE_FAULT as TAU
        worst = t2["double-fault"].min()
        print(f"\nthe corroboration threshold is {TAU}; the BEST pair here is "
              f"{worst:.3f}, which is {worst/TAU:.0f}x above it.")
        print("So on this corpus the adjudicator would corroborate NOTHING and")
        print("return UNKNOWN for every multi-checker alarm. That is the correct")
        print("behaviour given the evidence, and it is a negative result.")
        if mh < mm:
            print(f"\nHardware is marginally more independent ({mh:.4f} against")
            print(f"{mm:.4f}), but a {mm-mh:.4f} gap at an absolute level near 0.8")
            print("is not support for the corroboration rule. Do not quote it as if")
            print("it were.")
        print("\nAND THE METRIC IS CONFOUNDED. 'Wrong' here is fires != faulty,")
        print("but faulty hours dominate this corpus (it was downloaded AROUND")
        print("fault windows) while a 3-sigma detector fires rarely. Both channels")
        print("are therefore silent through most faulty hours and both count as")
        print("wrong together. The shared base rate is doing the work, not shared")
        print("evidence. A clean measurement needs a corpus with realistic")
        print("prevalence, matched on regime.")

    out = {"regime": "all", "note": "measured on ARM DQR-labelled hours",
           "double_fault": dfm}
    p = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"\nwrote {args.out} -- the adjudicator loads this instead of assuming")

    # ------------------------------------------ 3. does housekeeping lead?
    print("\n\n=== 3. Does housekeeping depart BEFORE the meteorology? ===")
    print("For each fault interval, the first hour each channel exceeded 3σ,")
    print("relative to the start of the human-written window. Negative means")
    print("it fired before the fault was recorded as beginning.\n")

    lead = []
    for _, r in dqr.iterrows():
        st = str(r["datastream"]).split(".")[0]
        g = df[(df.station == st)
               & (df.timestamp >= r["start"] - pd.Timedelta(days=7))
               & (df.timestamp <= r["end"])].sort_values("timestamp")
        if len(g) < 48:
            continue
        row = {"dqr": r["dqr"], "station": st}
        for short in MET + HK:
            if short not in g:
                continue
            z = robust_z(g[short].to_numpy())
            hit = np.where(np.abs(z) > FIRE_AT)[0]
            if len(hit) == 0:
                row[short] = np.nan
                continue
            first = g.timestamp.iloc[hit[0]]
            row[short] = (first - r["start"]).total_seconds() / 3600.0
        lead.append(row)
    t3 = pd.DataFrame(lead)
    if t3.empty or t3[[c for c in MET + HK if c in t3]].isna().all().all():
        print("  not enough overlap between fault windows and downloaded data")
    else:
        cols = [c for c in MET + HK if c in t3]
        print("hours from the start of the fault window to first 3σ excursion:")
        print(t3[cols].describe(percentiles=[.25, .5, .75]).round(1).to_string())
        med = t3[cols].median()
        hk_med = med[[c for c in HK if c in med]].min()
        met_med = med[[c for c in MET if c in med]].min()
        if np.isfinite(hk_med) and np.isfinite(met_med):
            print(f"\nearliest housekeeping {hk_med:+.1f} h, "
                  f"earliest meteorological {met_med:+.1f} h")
            gap = met_med - hk_med
            spread = float(t3[cols].std().median())
            n = int(t3[cols].notna().sum().min())
            lead_ok = (hk_med < 0) and (gap > 0.25 * spread) and n >= 30
            if lead_ok:
                print("Housekeeping leads by a margin that survives the spread.")
            else:
                print(f"\nNOT a precursor result. Both channels fire AFTER the fault")
                print(f"window opens ({hk_med:+.0f} h and {met_med:+.0f} h), the gap")
                print(f"between them is {gap:.0f} h against a spread of {spread:.0f} h,")
                print(f"and n is {n}. The precursor claim is UNSUPPORTED here and")
                print("must not be made on this evidence.")
                print("\nWhy it may still be true: a DQR start time is when a HUMAN")
                print("recorded the fault, not when the hardware began to go, so a")
                print("real precursor would be hidden by that labelling lag. Testing")
                print("it properly needs faults with an instrumented onset, which is")
                print("what the USCRN fan-speed and door-open channels would give.")


if __name__ == "__main__":
    main()
