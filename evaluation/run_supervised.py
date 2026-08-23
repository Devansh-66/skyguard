"""Does supervision help, and is it real? Two questions, two tables.

    python -m evaluation.run_supervised

Table 1  supervised vs unsupervised vs ensemble, at a fixed alert budget.
Table 2  LEAVE-ONE-FAULT-TYPE-OUT. Train with a whole class removed, test on
         it. This is the table that decides whether the model learned shape or
         memorised the injector, and it is printed whether or not it flatters
         the model.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from detect import features as FT
from detect.learned import LearnedDetector, conformalize, ensemble
from detect.supervised import SupervisedDetector
from evaluation.metrics import evaluate, mark_weather_activity
from inject.faults import FAULT_TYPES

VARIABLES = ("temp", "rh", "pres")
REF_END = "2023-10-01"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_injected.csv")
    ap.add_argument("--events", default="data/injected_events.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    ap.add_argument("--budget", type=float, default=1 / 7)
    ap.add_argument("--runs", type=int, default=4)
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    df = df[df.run_id < args.runs].reset_index(drop=True)
    events = pd.read_csv(args.events)
    graph = json.loads(Path(args.graph).read_text())

    coefs = {v: B.fit_baseline(df[df.run_id == 0], v, ref_end=REF_END)
             for v in VARIABLES}

    print("building features on the full frame ...")
    F_all = FT.build(df, coefs, graph, causal=True)

    train_m = (df.split == "train").to_numpy()
    test_m = (df.split == "test").to_numpy()
    ref_m = (df.timestamp < pd.Timestamp(REF_END, tz="UTC")).to_numpy()

    F_train, F_test = F_all[train_m], F_all[test_m]
    train, test = df[train_m].reset_index(drop=True), df[test_m].reset_index(drop=True)
    F_test = F_test.reset_index(drop=True)
    F_ref = F_all[ref_m]
    ref = df[ref_m].reset_index(drop=True)

    rows, lofo_rows, imps = [], [], {}

    for var in VARIABLES:
        y_train = df.loc[train_m, f"is_fault_{var}"].to_numpy().astype(int)
        y_test = df.loc[test_m, f"is_fault_{var}"].to_numpy().astype(int)
        types_train = df.loc[train_m, f"fault_type_{var}"]

        sup = SupervisedDetector(variable=var).fit(F_train, y_train)
        p_sup = sup.score(F_test)
        imps[var] = sup.importances(F_test, y_test)

        det = LearnedDetector(variable=var).fit(F_ref)
        miss = ~np.isfinite(test[var].to_numpy(dtype=float))
        p_learn = conformalize(det.distance(F_ref), det.distance(F_test))
        p_nz = conformalize(B.neighbour_z(ref, var, coefs[var], graph),
                            B.neighbour_z(test, var, coefs[var], graph))
        p_per = conformalize(B.persistence(ref, var), B.persistence(test, var))
        # The supervised channel is conformalised like every other one, so it
        # is combined on the same p-value scale rather than by a chosen weight.
        p_sup_conf = conformalize(-sup.score(F_ref), -p_sup)

        cands = {
            "unsupervised_ens": ensemble([p_learn, p_nz, p_per], certain=miss),
            "supervised": np.where(miss, 1e6, np.nan_to_num(p_sup)),
            "ens_plus_supervised": ensemble([p_learn, p_nz, p_per, p_sup_conf],
                                            certain=miss),
        }
        t = mark_weather_activity(test, var)
        for name, s in cands.items():
            r = evaluate(t.assign(_s=s), events, var, "_s", args.budget)
            fa = r["false_alarms_per_station_day"]
            rows.append({"variable": var, "detector": name,
                         "PR-AUC": round(r["pr_auc"], 4),
                         "event_recall": round(r["event_recall"], 3),
                         "FA quiet": round(fa["quiet"], 3)})

        # ---- the falsification test -------------------------------------
        for ft in FAULT_TYPES:
            held = SupervisedDetector(variable=var).fit(
                F_train, y_train, exclude_types=types_train, drop=(ft,))
            s_held = np.where(miss, 1e6, np.nan_to_num(held.score(F_test)))
            r_held = evaluate(t.assign(_s=s_held), events, var, "_s", args.budget)
            seen = r["event_recall_by_type"].get(ft, float("nan"))
            unseen = r_held["event_recall_by_type"].get(ft, float("nan"))
            lofo_rows.append({"variable": var, "fault_type": ft,
                              "recall_trained_on_it": round(seen, 3)
                              if seen == seen else None,
                              "recall_never_seen": round(unseen, 3)
                              if unseen == unseen else None})

    print(f"\nalert budget {args.budget:.4f}/station/day (1/week)\n")
    print(pd.DataFrame(rows).to_string(index=False))

    print("\npermutation importance on held-out rows (average precision lost):")
    print(pd.DataFrame(imps).fillna(0).round(4).to_string())

    lofo = pd.DataFrame(lofo_rows)
    print("\nLEAVE-ONE-FAULT-TYPE-OUT -- did it learn shape or memorise the injector?")
    piv = lofo.pivot_table(index="fault_type", columns="variable",
                           values=["recall_trained_on_it", "recall_never_seen"])
    print(piv.round(2).to_string())

    a = lofo.recall_trained_on_it.astype(float)
    b = lofo.recall_never_seen.astype(float)
    ok = a.notna() & b.notna()
    print(f"\nmean recall when the class was in training : {a[ok].mean():.3f}")
    print(f"mean recall when the class was NEVER seen  : {b[ok].mean():.3f}")
    drop = a[ok].mean() - b[ok].mean()
    print(f"generalisation gap                         : {drop:+.3f}")
    print("\nA large positive gap means the model recognises the injector's\n"
          "signature rather than the fault's. Read the per-class rows before\n"
          "quoting the headline -- the gap is rarely uniform.")


if __name__ == "__main__":
    main()
