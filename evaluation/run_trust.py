"""Does the network believing in itself actually detect better?

    python -m evaluation.run_trust

The trust graph is a good story: a station that goes bad stops being used as a
yardstick for its neighbours, automatically. Stories are cheap. This measures it.

Three arms, identical in every other respect:

    flat        every neighbour weighted equally -- what the system does today
    trust       neighbours weighted by the network's belief in them
    oracle      neighbours weighted by the GROUND TRUTH fault mask

The oracle is the point of the experiment. It is not a method -- it cheats, by
reading the labels -- but it bounds the prize. If the oracle barely beats flat,
then no trust estimator can be worth building here and the honest thing is to
drop the idea rather than ship it because it sounds good. If the oracle is far
ahead and trust captures a decent share of that gap, the mechanism is real.

Scored on the same statistic the drift detector uses: the sigma of the
neighbour-difference series on CLEAN rows. Lower sigma is a tighter reference,
and drift latency scales as sigma / slope, so a reduction here is a proportional
reduction in time-to-detect for every station in the neighbourhood.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from detect.trust import trust_weighted_difference, _wide, _weighted_reference

VARIABLES = ("temp", "rh", "pres")
REF_END = "2023-10-01"


def flat_difference(df, resid, graph):
    """Today's behaviour: an unweighted median of the neighbours."""
    wide = _wide(df, resid)
    key = pd.MultiIndex.from_arrays([df.run_id, df.timestamp])
    out = np.full(len(df), np.nan)
    for s in wide.columns:
        nb = [n for n in graph.get(s, {}).get("neighbours", []) if n in wide.columns]
        diff = wide[s] - (wide[nb].median(axis=1) if nb else 0.0)
        m = (df.station_name == s).to_numpy()
        if m.any():
            out[m] = diff.reindex(key[m]).to_numpy()
    return out


def oracle_difference(df, resid, graph, var):
    """Cheats: weights a neighbour 1.0 when healthy and at the floor when faulted."""
    wide = _wide(df, resid)
    truth = (pd.DataFrame({"run_id": df.run_id, "t": df.timestamp,
                           "s": df.station_name,
                           "f": df[f"is_fault_{var}"].astype(float)})
             .pivot_table(index=["run_id", "t"], columns="s", values="f"))
    w = (1.0 - truth.reindex(wide.index).fillna(0.0)).clip(lower=0.05)

    key = pd.MultiIndex.from_arrays([df.run_id, df.timestamp])
    out = np.full(len(df), np.nan)
    for s in wide.columns:
        nb = [n for n in graph.get(s, {}).get("neighbours", []) if n in wide.columns]
        ref = _weighted_reference(wide, s, nb, w)
        diff = wide[s] - ref.fillna(0.0)
        m = (df.station_name == s).to_numpy()
        if m.any():
            out[m] = diff.reindex(key[m]).to_numpy()
    return out


def clean_sigma(df, d, var):
    """Robust sigma of the difference on rows with NO injected fault anywhere.

    Restricted to clean rows on purpose: including faulted rows would reward an
    arm for making faults larger, when what is being measured is how tight the
    reference is when nothing is wrong.
    """
    ok = ~df[f"is_fault_{var}"].to_numpy().astype(bool) & np.isfinite(d)
    if ok.sum() < 100:
        return float("nan")
    v = d[ok]
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_injected.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    df = df[df.run_id < args.runs].reset_index(drop=True)
    graph = json.loads(Path(args.graph).read_text())

    rows = []
    trust_tables = {}
    for var in VARIABLES:
        coefs = B.fit_baseline(df[df.run_id == 0], var, ref_end=REF_END)
        resid = B.residual(df, var, coefs).to_numpy(dtype=float)

        d_flat = flat_difference(df, resid, graph)
        d_trust, trust = trust_weighted_difference(df, var, resid, graph)
        d_orac = oracle_difference(df, resid, graph, var)
        trust_tables[var] = trust

        s_flat = clean_sigma(df, d_flat, var)
        s_trust = clean_sigma(df, d_trust, var)
        s_orac = clean_sigma(df, d_orac, var)
        gap = s_flat - s_orac
        rows.append({
            "variable": var,
            "sigma flat": round(s_flat, 4),
            "sigma trust": round(s_trust, 4),
            "sigma oracle": round(s_orac, 4),
            "trust gain %": round(100 * (s_flat - s_trust) / s_flat, 2),
            "oracle gain %": round(100 * gap / s_flat, 2),
            "share of prize": (round((s_flat - s_trust) / gap, 2)
                               if abs(gap) > 1e-9 else float("nan")),
        })

    t = pd.DataFrame(rows)
    print("\nsigma of the neighbour difference on CLEAN rows -- lower is a")
    print("tighter reference. Drift latency scales as sigma/slope, so a")
    print("reduction here cuts time-to-detect proportionally.\n")
    print(t.to_string(index=False))

    print("\n=== Did the network demote anyone? ===")
    for var, tr in trust_tables.items():
        lo = tr.min()
        worst = lo.nsmallest(3)
        print(f"\n{var}: lowest trust reached, per station")
        print("  " + ", ".join(f"{s} {v:.2f}" for s, v in worst.items()))
        n_dem = int((tr < 0.5).sum().sum())
        print(f"  station-days below 0.5 trust: {n_dem} of {tr.size}")

    print("\n=== Reading this ===")
    best = t["oracle gain %"].max()
    if best < 2.0:
        print("The ORACLE gain is small, so there is no prize here to win.")
        print("Even perfect knowledge of which neighbour is faulty barely")
        print("tightens the reference -- at this fault prevalence a sick")
        print("neighbour is not what limits the difference series. Trust")
        print("weighting should be dropped as a detection mechanism, whatever")
        print("it does for the narrative.")
    else:
        print("The oracle shows a real prize. 'share of prize' is how much of")
        print("it trust weighting captures without seeing labels.")


if __name__ == "__main__":
    main()
