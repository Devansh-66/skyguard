"""Supervised naming vs the hand-written templates, on identical windows.

    python -m evaluation.run_signature_ml

Both classifiers see exactly the same detected windows and the same eight
descriptors, so the comparison isolates the classifier and nothing else. And
both are put through leave-one-fault-type-out, because a namer that has never
seen a drift should say `unknown` rather than confidently say `step_offset`.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from detect import features as FT
from detect.learned import LearnedDetector, conformalize, ensemble
from evaluation.metrics import _runs, merge_runs, threshold_for_budget
from signature import classify as SIG
from signature.supervised import SignatureModel, DESCRIPTORS

VARIABLES = ("temp", "rh", "pres")
REF_END = "2023-10-01"
RAILS = {"temp": (-40.0, 60.0), "rh": (0.0, 100.0), "pres": (500.0, 1100.0)}


def windows_for(df, F, split_df, coefs, graph, scores, budget, nat):
    """Detect, describe, and label every window in one split."""
    rows = []
    for var in VARIABLES:
        sc = scores[var]
        clean = sc[~split_df[f"is_fault_{var}"].to_numpy().astype(bool)]
        thr = threshold_for_budget(clean, len(clean) / 24.0, budget)
        flag = np.nan_to_num(sc, nan=0.0) >= thr
        dres = FT.neighbour_residual(split_df, var, coefs[var], graph)
        sigma = {s: B.robust_sigma(dres.loc[g.index].to_numpy(), var)
                 for s, g in split_df.groupby("station_name", sort=False)}
        for (run, st), g in split_df.groupby(["run_id", "station_name"], sort=False):
            pos = split_df.index.get_indexer(g.index)
            for a, b in merge_runs(_runs(flag[pos])):
                if b - a < 2:
                    continue
                idx = g.index[a:b]
                w = SIG.describe(split_df.loc[idx], None, var, dres.loc[idx],
                                 sigma[st], RAILS[var], 0.0,
                                 nat[var].get(st, 0.0))
                t = split_df.loc[idx, f"fault_type_{var}"]
                t = t[t != ""].mode()
                rows.append({**w.descriptors, "variable": var, "station": st,
                             "truth": t.iloc[0] if len(t) else "(false alarm)",
                             "template": SIG.classify(w)["label"]})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_injected.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    ap.add_argument("--budget", type=float, default=1 / 7)
    ap.add_argument("--runs", type=int, default=4)
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    df = df[df.run_id < args.runs].reset_index(drop=True)
    graph = json.loads(Path(args.graph).read_text())
    coefs = {v: B.fit_baseline(df[df.run_id == 0], v, ref_end=REF_END)
             for v in VARIABLES}

    print("building features ...")
    F_all = FT.build(df, coefs, graph, causal=True)
    ref_m = (df.timestamp < pd.Timestamp(REF_END, tz="UTC")).to_numpy()
    F_ref, ref = F_all[ref_m], df[ref_m].reset_index(drop=True)

    nat = {}
    for v in VARIABLES:
        nat[v] = {}
        for s, g in ref.groupby("station_name", sort=False):
            x = g[v].to_numpy(dtype=float)
            x = x[np.isfinite(x)]
            nat[v][s] = float(np.mean(x[1:] == x[:-1])) if len(x) > 1 else 0.0

    sets = {}
    for name in ("train", "test"):
        m = (df.split == name).to_numpy()
        sub = df[m].reset_index(drop=True)
        Fs = F_all[m].reset_index(drop=True)
        dets = {v: LearnedDetector(variable=v).fit(F_ref) for v in VARIABLES}
        scores = {}
        for v in VARIABLES:
            scores[v] = ensemble([
                conformalize(dets[v].distance(F_ref), dets[v].distance(Fs)),
                conformalize(B.neighbour_z(ref, v, coefs[v], graph),
                             B.neighbour_z(sub, v, coefs[v], graph)),
                conformalize(B.persistence(ref, v), B.persistence(sub, v)),
            ], certain=~np.isfinite(sub[v].to_numpy(dtype=float)))
        sets[name] = windows_for(df, Fs, sub, coefs, graph, scores,
                                 args.budget, nat)
        print(f"{name}: {len(sets[name])} windows, "
              f"{(sets[name].truth != '(false alarm)').sum()} real")

    tr, te = sets["train"], sets["test"]
    real_te = te[te.truth != "(false alarm)"]

    model = SignatureModel().fit(tr[list(DESCRIPTORS)], tr.truth)
    pred = model.predict(te[list(DESCRIPTORS)])
    te = te.assign(ml=pred.label.to_numpy(), ml_p=pred.probability.to_numpy())
    real_te = te[te.truth != "(false alarm)"]

    def acc(col):
        named = real_te[real_te[col] != "unknown"]
        return (float((named.truth == named[col]).mean()) if len(named) else float("nan"),
                len(named), len(real_te))

    for col, label in (("template", "templates (hand-written)"),
                       ("ml", "supervised")):
        a, n, tot = acc(col)
        print(f"\n{label:<26} naming accuracy {a:.3f}  "
              f"({n}/{tot} named, {(1-n/tot)*100:.0f}% unknown)")

    print("\nsupervised confusion on real faults:")
    print(pd.crosstab(real_te.truth, real_te.ml).to_string())

    fa = te[te.truth == "(false alarm)"]
    print(f"\nfalse alarms labelled by supervised: "
          f"{fa.ml.value_counts(normalize=True).head(4).round(3).to_dict()}")
    print(f"false alarms labelled by templates : "
          f"{fa.template.value_counts(normalize=True).head(4).round(3).to_dict()}")

    # ---- leave one fault type out -------------------------------------
    print("\nLEAVE-ONE-FAULT-TYPE-OUT (naming)")
    out = []
    for ft in sorted(set(tr.truth) - {"(false alarm)"}):
        sub_te = real_te[real_te.truth == ft]
        if sub_te.empty:
            continue
        held = SignatureModel().fit(tr[list(DESCRIPTORS)], tr.truth, drop=(ft,))
        p = held.predict(sub_te[list(DESCRIPTORS)])
        # It cannot get the class right -- it has never heard of it. The right
        # behaviour is to ABSTAIN, so that is what is measured.
        out.append({"fault_type": ft, "n": len(sub_te),
                    "abstained": round(float((p.label == "unknown").mean()), 2),
                    "confidently_wrong": round(
                        float(((p.label != "unknown") &
                               (p.probability >= 0.7)).mean()), 2)})
    print(pd.DataFrame(out).to_string(index=False))
    print("\n`abstained` is the good column. `confidently_wrong` is the model\n"
          "asserting a cause it has no basis for -- the failure that\n"
          "exists to prevent.")


if __name__ == "__main__":
    main()
