"""End-to-end: features -> learned layer -> signature classifier, all scored.

    python -m evaluation.run_full

Prints three things:
  1. the learned detector against the baselines, at a fixed alert budget
  2. the confusion matrix of the signature classifier on detected events
  3. worked example alerts, as an operator would read them
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from detect import features as FT
from detect.learned import (LearnedDetector, conformalize, ensemble,
                            ensemble_budgeted)
from evaluation.metrics import evaluate, mark_weather_activity, _runs, merge_runs
from signature import classify as SIG

VARIABLES = ("temp", "rh", "pres")
REF_END = "2023-10-01"
RAILS = {"temp": (-40.0, 60.0), "rh": (0.0, 100.0), "pres": (500.0, 1100.0)}


def coherence_series(df: pd.DataFrame, var: str, coefs: dict,
                     graph: dict) -> tuple[pd.Series, pd.Series]:
    """Return (neighbour-difference residual, coherence).

    coherence = 1 - |neighbour-difference| / |own residual|, clipped to [0, 1].

    Near 1 when the station moved and its neighbours moved with it -- real
    weather. Near 0 when the station moved alone -- a fault. It is a ratio of
    two quantities we already compute, so it costs nothing, and it is the single
    descriptor that separates the two things PS26073 asks us to distinguish.
    """
    r = B.residual(df, var, coefs)
    d = FT.neighbour_residual(df, var, coefs, graph)
    own = r.abs().rolling(1).max()
    coh = 1.0 - (d.abs() / own.clip(lower=1e-6))
    return d, coh.clip(0.0, 1.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_injected.csv")
    ap.add_argument("--events", default="data/injected_events.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    ap.add_argument("--budget", type=float, default=1 / 7)
    ap.add_argument("--centred", dest="causal", action="store_false",
                    default=True,
                    help="reproduce the lookahead variant, for comparison only")
    ap.add_argument("--no-td", dest="use_td", action="store_false", default=True,
                    help="A/B arm: withhold the td_ratio and diurnal_gain "
                         "descriptors and the shield_failure template, i.e. the "
                         "classifier as it stood before they were added. Naming "
                         "must be compared on NON-shield faults only, since this "
                         "arm cannot name shield at all.")
    ap.add_argument("--runs", type=int, default=4,
                    help="replicates to score; all 10 is slow and adds little")
    args = ap.parse_args()

    if not args.use_td:
        # Control arm: remove the template that depends on the new descriptors,
        # so the comparison isolates their effect on the pre-existing classes.
        SIG.TEMPLATES.pop("shield_failure", None)

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    df = df[df.run_id < args.runs].reset_index(drop=True)
    events = pd.read_csv(args.events)
    graph = json.loads(Path(args.graph).read_text())

    # Dew point is carried as a derived column with its own baseline, purely so
    # a neighbour-difference residual can be formed for it. That residual is
    # what separates a heated probe from a genuinely warmer airmass: heating at
    # constant vapour content moves T and leaves Td alone.
    from physics.relations import dew_point
    df["td"] = [dew_point(t, r) for t, r in zip(df.temp, df.rh)]
    coefs = {v: B.fit_baseline(df[df.run_id == 0], v, ref_end=REF_END)
             for v in VARIABLES + ("td",)}

    # EVERY channel is computed on the FULL frame and only then subset.
    #
    # Building them on the test subset instead is a bug that cost us a lot. The
    # split marks a row test if its station is held out OR its timestamp is past
    # the cut, so a holdout station is test for the whole year while its
    # NEIGHBOURS before the cut are labelled train. Subsetting first deletes
    # those neighbours, the neighbour-difference residual goes NaN for 75 % of
    # the holdout stations' rows, and since the flag is nan_to_num(..., 0.0)
    # every fault on a holdout station before the cut was silently scored as a
    # miss. 37.6 % of all test rows had a NaN primary channel.
    #
    # Computing on the full frame does not leak: the features are causal, so a
    # value at time t uses only data at or before t, and a neighbour's reading
    # is something a deployed system would genuinely have.
    ref_mask = (df.timestamp < pd.Timestamp(REF_END, tz="UTC")).to_numpy()
    test_mask = (df.split == "test").to_numpy()
    ref = df[ref_mask].reset_index(drop=True)
    test = df[test_mask].reset_index(drop=True)

    print("building features ...")
    F_all = FT.build(df, coefs, graph, causal=args.causal)
    F_ref = F_all[ref_mask].reset_index(drop=True)
    F_test = F_all[test_mask].reset_index(drop=True)

    def split_channel(fn, *a, **k):
        """Run a detector channel on the whole frame, return (ref, test) parts."""
        v = np.asarray(fn(df, *a, **k), dtype=float)
        return v[ref_mask], v[test_mask]

    # Fitted on the frozen reference window with NO labels -- the same data a
    # deployed system would have on day one.
    # ONE DETECTOR PER VARIABLE. A single station-level vector scored against a
    # per-sensor label is a category error: it dilutes the one faulted channel
    # with two healthy ones and loses to a plain z-score.
    dets = {v: LearnedDetector(variable=v).fit(F_ref) for v in VARIABLES}
    learned_score = {v: dets[v].score(F_test) for v in VARIABLES}

    # Ensemble: each detector conformalised against the same reference window,
    # then combined by minimum p. They are blind to different things, so a
    # minimum rather than a blend -- see detect/learned.ensemble.
    ens, ens_nl = {}, {}
    for v in VARIABLES:
        miss = ~np.isfinite(test[v].to_numpy(dtype=float))
        p_learn = conformalize(dets[v].distance(F_ref), dets[v].distance(F_test))
        p_nz = conformalize(*split_channel(B.neighbour_z, v, coefs[v], graph,
                                           args.causal))
        p_per = conformalize(*split_channel(B.persistence, v))
        # Two blind-spot channels. `spike` and `noise_burst` are invisible to a
        # long-window level detector and to a run-length detector, so they get
        # detectors of their own rather than a threshold tweak.
        p_ham = conformalize(*split_channel(B.local_outlier, v, coefs[v], graph))
        p_dis = conformalize(*split_channel(B.dispersion, v, coefs[v], graph))
        ens[v] = ensemble([p_learn, p_nz, p_per], certain=miss)
        # Per-channel budget. The two blind-spot channels get a share each
        # instead of competing with drift-dominated channels for one threshold.
        ens_nl[v] = ensemble_budgeted(
            [p_learn, p_nz, p_per, p_ham, p_dis], args.budget,
            weights=[3, 3, 2, 1, 1], certain=miss)
    print(f"learned: {dets['temp'].version}  "
          f"{dets['temp'].fitted_on['n_fit']} fit / "
          f"{dets['temp'].fitted_on['n_calib']} calib rows per variable")

    # ------------------------------------------------ 1. detection comparison
    rows = []
    per_type = {}
    for var in VARIABLES:
        t = mark_weather_activity(test, var)
        cands = {
            "neighbour_z": split_channel(B.neighbour_z, var, coefs[var], graph,
                                         args.causal)[1],
            "combined": split_channel(B.combined, var, coefs[var], graph,
                                      args.causal)[1],
            "learned": learned_score[var],
            "ensemble": ens[var],
            "ens_budgeted": ens_nl[var],
        }
        for name, s in cands.items():
            r = evaluate(t.assign(_s=s), events, var, "_s", args.budget)
            fa = r["false_alarms_per_station_day"]
            rows.append({"variable": var, "detector": name,
                         "PR-AUC": round(r["pr_auc"], 4),
                         "event_recall": round(r["event_recall"], 3),
                         "FA quiet": round(fa["quiet"], 3),
                         "FA active": round(fa["active"], 3)})
            per_type[(var, name)] = r["event_recall_by_type"]
    print(f"\nalert budget {args.budget:.4f}/station/day (1/week)\n")
    print(pd.DataFrame(rows).to_string(index=False))

    # Per fault type. The headline hides exactly the classes we are trying to
    # fix -- spike and noise_burst are rare, so they barely move the average.
    pt = pd.DataFrame(per_type).round(2)
    pt.columns = pd.MultiIndex.from_tuples(pt.columns)
    print("\nevent recall by fault type:")
    print(pt.fillna(0).to_string())

    # ------------------------------------------------ 2. signature classifier
    #
    # The threshold comes from the ALERT BUDGET, not from a convenient quantile.
    # A 97th-percentile cut posts 260 alerts per station-year, which no operator
    # would read; scoring the classifier on that flood measures nothing.
    from evaluation.metrics import threshold_for_budget

    pred_rows, examples = [], []
    for var in VARIABLES:
        sc = ens[var]
        clean = sc[~test[f"is_fault_{var}"].to_numpy().astype(bool)]
        thr = threshold_for_budget(clean, len(clean) / 24.0, args.budget)
        flag = np.nan_to_num(sc, nan=0.0) >= thr

        d_res_all, coh_all = coherence_series(df, var, coefs[var], graph)
        d_res = d_res_all[test_mask].reset_index(drop=True)
        coh = coh_all[test_mask].reset_index(drop=True)
        d_td = (FT.neighbour_residual(df, "td", coefs["td"], graph)[test_mask]
                .reset_index(drop=True))
        sigma = {s: B.robust_sigma(d_res.loc[g.index].to_numpy(), var)
                 for s, g in test.groupby("station_name", sort=False)}
        sig_td = {s: B.robust_sigma(d_td.loc[g.index].to_numpy(), "temp")
                  for s, g in test.groupby("station_name", sort=False)}
        # How often does this station's probe repeat a reading when healthy?
        # Measured on the frozen reference window, per station, because it is
        # set by the local climate and the logger resolution together.
        nat = {}
        for s_, g in ref[ref.run_id == 0].groupby("station_name", sort=False):
            v = g[var].to_numpy(dtype=float)
            v = v[np.isfinite(v)]
            nat[s_] = float(np.mean(v[1:] == v[:-1])) if len(v) > 1 else 0.0
        for (run, st), g in test.groupby(["run_id", "station_name"], sort=False):
            pos = test.index.get_indexer(g.index)
            # MEASURED, and left at the 12 h default deliberately.
            #
            # A radiation-shield fault is switched off by sunset, so at a 12 h
            # gap its daily bursts stay separate ~4 h windows and the signature
            # stage calls a 400-hour siting fault a spike. Widening to 30 h
            # bridges the night and does let shield_failure fire -- but it also
            # merges genuine 1-hour spikes into the quiet hours around them, so
            # the merged window looks mostly clean and reads as weather. Naming
            # fell 0.611 -> 0.489 and false alarms called `genuine_weather` rose
            # to 0.49. One global gap cannot serve a 1-hour spike and a fault
            # the sun switches on and off; that needs per-hypothesis merging,
            # which is not built. The gap stays at 12 and shield_failure stays
            # unnameable, which is the honest state.
            for a, b in merge_runs(_runs(flag[pos])):
                if b - a < 2:
                    continue
                idx = g.index[a:b]
                # How much of the departure survives in the dew point?
                lvl = abs(float(np.nanmedian(d_res.loc[idx]))) / max(sigma[st], 1e-9)
                lvl_td = abs(float(np.nanmedian(d_td.loc[idx]))) / max(sig_td[st], 1e-9)
                tdr = (lvl_td / lvl) if lvl > 0.5 else None
                if not args.use_td:
                    tdr = None
                w = SIG.describe(test.loc[idx], F_test.loc[idx], var,
                                 d_res.loc[idx], sigma[st], RAILS[var],
                                 float(coh.loc[idx].median()),
                                 nat.get(st, 0.0), tdr,
                                 d_td.loc[idx], sig_td[st])
                res = SIG.classify(w)
                # A window with no injected fault is a FALSE ALARM, not
                # weather. Labelling it `genuine_weather` would credit the
                # classifier for correctly naming the detector's own mistakes.
                truth = test.loc[idx, f"fault_type_{var}"]
                truth = truth[truth != ""].mode()
                truth = truth.iloc[0] if len(truth) else "(false alarm)"
                pred_rows.append({"variable": var, "true": truth,
                                  "pred": res["label"],
                                  "confidence": res["confidence"]})
                if len(examples) < 40:
                    examples.append((truth, res, SIG.explain(res, st, var)))

    pr = pd.DataFrame(pred_rows)
    if pr.empty:
        print("\nno windows to classify")
        return

    n_fa = int((pr["true"] == "(false alarm)").sum())
    print(f"\nsignature classifier ({SIG.VERSION}) on {len(pr)} detected "
          f"windows, {n_fa} of them the detector's own false alarms")
    real = pr[pr["true"] != "(false alarm)"]
    print(pd.crosstab(real["true"], real["pred"]).to_string())

    named = real[real.pred != "unknown"]
    acc = float((named["true"] == named["pred"]).mean()) if len(named) else float("nan")
    print(f"\nnaming accuracy on real faults : {acc:.3f}  "
          f"({len(named)}/{len(real)} named, "
          f"{(real.pred == 'unknown').mean()*100:.0f} % honest unknown)")

    # What the classifier says about the detector's own false alarms matters as
    # much as the confusion matrix: labelling them `genuine_weather` or
    # `unknown` filters them for free, labelling them `frozen` sends a van to a
    # healthy station.
    fa = pr[pr["true"] == "(false alarm)"]
    if len(fa):
        print("false alarms are labelled : "
              f"{fa.pred.value_counts(normalize=True).head(4).round(3).to_dict()}")

    # ---------------------------------------------------- 3. worked examples
    print("\nexample alerts as an operator sees them:")
    seen = set()
    for truth, res, text in examples:
        if res["label"] in seen:
            continue
        seen.add(res["label"])
        mark = "ok " if res["label"] == truth else "MISS"
        print(f"  [{mark}] truth={truth:<18} conf={res['confidence']:.2f}  {text}")


if __name__ == "__main__":
    main()
