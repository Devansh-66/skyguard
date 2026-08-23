"""Per-fault-type budgets against one flat budget, at the SAME total spend.

    python -m evaluation.run_allocated

The comparison is only meaningful at equal cost. Both arms emit the same number
of alerts per station-day; the difference is how those alerts are distributed
across fault classes.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from detect import features as FT
from detect.allocate import (allocate, quota_report, DEFAULT_ALLOCATION,
                             CANDIDATE_MULTIPLE)
from detect.learned import LearnedDetector, conformalize, ensemble
from evaluation.metrics import _runs, merge_runs, threshold_for_budget
from signature import classify as SIG

VARIABLES = ("temp", "rh", "pres")
REF_END = "2023-10-01"
RAILS = {"temp": (-40.0, 60.0), "rh": (0.0, 100.0), "pres": (500.0, 1100.0)}


def candidates(test, F_test, ref, F_ref, coefs, graph, budget, mult):
    """Windows detected at a loose threshold, described and named."""
    rows = []
    for var in VARIABLES:
        det = LearnedDetector(variable=var).fit(F_ref)
        miss = ~np.isfinite(test[var].to_numpy(dtype=float))
        sc = ensemble([
            conformalize(det.distance(F_ref), det.distance(F_test)),
            conformalize(B.neighbour_z(ref, var, coefs[var], graph),
                         B.neighbour_z(test, var, coefs[var], graph)),
            conformalize(B.persistence(ref, var), B.persistence(test, var)),
        ], certain=miss)

        y = test[f"is_fault_{var}"].to_numpy().astype(bool)
        thr_loose = threshold_for_budget(sc[~y], (~y).sum()/24.0, budget*mult)
        thr_flat = threshold_for_budget(sc[~y], (~y).sum()/24.0, budget)

        dres = FT.neighbour_residual(test, var, coefs[var], graph)
        sigma = {s: B.robust_sigma(dres.loc[g.index].to_numpy(), var)
                 for s, g in test.groupby("station_name", sort=False)}
        nat = {}
        for s, g in ref.groupby("station_name", sort=False):
            x = g[var].to_numpy(dtype=float); x = x[np.isfinite(x)]
            nat[s] = float(np.mean(x[1:] == x[:-1])) if len(x) > 1 else 0.0

        flag = np.nan_to_num(sc, nan=0.0) >= thr_loose
        for (run, st), g in test.groupby(["run_id", "station_name"], sort=False):
            pos = test.index.get_indexer(g.index)
            for a, b in merge_runs(_runs(flag[pos])):
                if b - a < 2:
                    continue
                idx = g.index[a:b]
                w = SIG.describe(test.loc[idx], None, var, dres.loc[idx],
                                 sigma[st], RAILS[var], 0.0, nat.get(st, 0.0))
                res = SIG.classify(w)
                peak = float(np.nanmax(sc[pos][a:b]))
                truth = test.loc[idx, f"fault_type_{var}"]
                truth = truth[truth != ""].mode()
                rows.append({
                    "run_id": run, "variable": var, "station": st,
                    "event_id": int(test.loc[idx, f"event_id_{var}"].max()),
                    "label": res["label"], "score": peak,
                    "in_flat": peak >= thr_flat,
                    "truth": truth.iloc[0] if len(truth) else "(false alarm)",
                })
    return pd.DataFrame(rows)


def recall_by_type(sel: pd.DataFrame, truth_events: pd.DataFrame) -> pd.Series:
    hit = set(zip(sel.run_id, sel.variable, sel.event_id))
    truth_events = truth_events.copy()
    truth_events["hit"] = [
        (r, v, e) in hit for r, v, e in
        zip(truth_events.run_id, truth_events.variable, truth_events.event_id)]
    return truth_events.groupby("fault_type").hit.mean().round(3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_injected.csv")
    ap.add_argument("--events", default="data/injected_events.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    ap.add_argument("--budget", type=float, default=1/7)
    ap.add_argument("--runs", type=int, default=6)
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    df = df[df.run_id < args.runs].reset_index(drop=True)
    events = pd.read_csv(args.events)
    events = events[events.run_id < args.runs]
    graph = json.loads(Path(args.graph).read_text())
    coefs = {v: B.fit_baseline(df[df.run_id == 0], v, ref_end=REF_END)
             for v in VARIABLES}

    ref = df[df.timestamp < pd.Timestamp(REF_END, tz="UTC")].reset_index(drop=True)
    test = df[df.split == "test"].reset_index(drop=True)
    print("building features ...")
    F_ref, F_test = FT.build(ref, coefs, graph), FT.build(test, coefs, graph)

    cand = candidates(test, F_test, ref, F_ref, coefs, graph,
                      args.budget, CANDIDATE_MULTIPLE)
    station_days = len(test) / 24.0 / test.station_name.nunique()
    station_days *= test.station_name.nunique()      # total station-days

    # only events that exist in the test split can be recalled
    te = events.merge(
        test[["run_id"]].drop_duplicates(), on="run_id", how="inner")
    te = te[te.station.isin(set(test.station_name))]

    flat = cand[cand.in_flat]
    alloc = allocate(cand, args.budget, station_days)

    print(f"\ncandidates {len(cand)} at {CANDIDATE_MULTIPLE:.0f}x budget")
    print(f"flat budget      : {len(flat)} alerts")
    print(f"per-type budget  : {len(alloc)} alerts")

    print("\nquota report:")
    print(quota_report(cand, alloc, args.budget, station_days).to_string(index=False))

    a, b = recall_by_type(flat, te), recall_by_type(alloc, te)
    comp = pd.DataFrame({"flat_budget": a, "per_type_budget": b}).fillna(0.0)
    comp["change"] = (comp.per_type_budget - comp.flat_budget).round(3)
    print("\nevent recall by fault type, at equal total spend:")
    print(comp.to_string())

    for name, sel in (("flat", flat), ("per-type", alloc)):
        fa = (sel.truth == "(false alarm)").mean() if len(sel) else float("nan")
        print(f"{name:9s} false-alarm share of alerts: {fa:.2f}")


if __name__ == "__main__":
    main()
