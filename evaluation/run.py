"""Run every baseline detector through the harness and print the comparison.

    python -m evaluation.run

Baselines are fitted on the TRAIN split only -- whole stations and whole time
periods held out, never a random point split.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from evaluation.metrics import evaluate, mark_weather_activity

VARIABLES = ("temp", "rh", "pres")

# Frozen climatology reference window ends here. Everything at or after this
# timestamp is scored; nothing after it ever updates the baseline.
REF_END = "2023-10-01"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_injected.csv")
    ap.add_argument("--events", default="data/injected_events.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    ap.add_argument("--budget", type=float, default=1 / 7,
                    help="alerts per station per day")
    ap.add_argument("--out", default="evaluation/results.json")
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"]).reset_index(drop=True)
    events = pd.read_csv(args.events)
    graph = json.loads(Path(args.graph).read_text())

    # The climatology is fitted on a FROZEN reference window, on every station
    # including the held-out ones, using no labels and a Huber loss. That is
    # what deployment can actually do: real history is unlabelled, and a station
    # held out from detector evaluation still has its own past.
    ref = df[df.run_id == 0]

    results = {}
    for var in VARIABLES:
        coefs = B.fit_baseline(ref, var, ref_end=REF_END)

        test = df[df.split == "test"].reset_index(drop=True)
        test = mark_weather_activity(test, var)

        scores = {
            "self_z": B.self_z(test, var, coefs),
            "neighbour_z": B.neighbour_z(test, var, coefs, graph),
            "combined": B.combined(test, var, coefs, graph),
        }
        for name, s in scores.items():
            t = test.assign(_s=s)
            results[f"{var}/{name}"] = evaluate(t, events, var, "_s", args.budget)

    rows = []
    for k, r in results.items():
        var, det = k.split("/")
        fa = r["false_alarms_per_station_day"]
        rows.append({
            "variable": var, "detector": det,
            "PR-AUC": round(r["pr_auc"], 4),
            "event_recall": round(r["event_recall"], 3),
            "point_recall": round(r["point_recall"], 3),
            "FA/st-day": round(fa["all"], 3),
            "FA quiet": round(fa["quiet"], 3),
            "FA active": round(fa["active"], 3),
            "amp@90%POD": round(r["amplitude_at_90pct_pod"], 3),
        })
    table = pd.DataFrame(rows)
    print(f"alert budget: {args.budget:.4f} alerts/station/day "
          f"({args.budget*7:.2f}/week)\n")
    print(table.to_string(index=False))

    print("\nevent recall by fault type (combined detector):")
    br = pd.DataFrame({v: results[f"{v}/combined"]["event_recall_by_type"]
                       for v in VARIABLES})
    print(br.to_string())

    Path(args.out).write_text(json.dumps(results, indent=2, default=str))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
