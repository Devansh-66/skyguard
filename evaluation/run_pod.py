"""POD versus amplitude, and the minimum detectable amplitude per fault type.

    python -m evaluation.run_pod

WHY THIS IS THE RIGHT HEADLINE FOR SPIKES

Spike recall came out at 0.24 / 0.00 / 0.17 for temperature, humidity and
pressure -- and IDENTICAL for five different detectors, including two written
specifically to catch spikes. When a plain z-score, a Mahalanobis distance, a
Hampel filter and two ensembles all agree to the second decimal, the number is
not describing any of them. It is describing the injected amplitudes against the
noise floor.

So "spike recall 0.24" is a statement about the injector's amplitude
distribution, not about the detector, and quoting it as an accuracy figure is
close to meaningless. `we detect a 3 K spike, and a 1 K spike is below the noise
floor at this alert budget` is a claim an evaluator can check and an operator can
use.

The alert budget is swept as well, because it is the one dial that genuinely
moves these classes: a short fault competes for the same budget as a ninety-day
drift, and buying more budget is what buys more spikes.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from detect import features as FT
from detect.learned import LearnedDetector, conformalize, ensemble
from evaluation.metrics import (evaluate, mark_weather_activity, event_scores,
                                pod_curve, threshold_for_budget)

VARIABLES = ("temp", "rh", "pres")
REF_END = "2023-10-01"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_injected.csv")
    ap.add_argument("--events", default="data/injected_events.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    ap.add_argument("--runs", type=int, default=10)
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    df = df[df.run_id < args.runs].reset_index(drop=True)
    events = pd.read_csv(args.events)
    graph = json.loads(Path(args.graph).read_text())
    coefs = {v: B.fit_baseline(df[df.run_id == 0], v, ref_end=REF_END)
             for v in VARIABLES}

    ref = df[df.timestamp < pd.Timestamp(REF_END, tz="UTC")].reset_index(drop=True)
    test = df[df.split == "test"].reset_index(drop=True)
    print("building features ...")
    F_ref, F_test = (FT.build(ref, coefs, graph), FT.build(test, coefs, graph))

    budgets = [1/7, 1/2, 1.0, 3.0]
    rows, curves = [], []

    for var in VARIABLES:
        det = LearnedDetector(variable=var).fit(F_ref)
        miss = ~np.isfinite(test[var].to_numpy(dtype=float))
        sc = ensemble([
            conformalize(det.distance(F_ref), det.distance(F_test)),
            conformalize(B.neighbour_z(ref, var, coefs[var], graph),
                         B.neighbour_z(test, var, coefs[var], graph)),
            conformalize(B.persistence(ref, var), B.persistence(test, var)),
        ], certain=miss)
        t = mark_weather_activity(test, var).assign(_s=sc)

        # the noise floor the amplitudes are competing against
        d = FT.neighbour_residual(test, var, coefs[var], graph)
        sigma = float(np.nanmedian([B.robust_sigma(d.loc[g.index].to_numpy(), var)
                                    for _, g in test.groupby("station_name")]))

        for b in budgets:
            y = test[f"is_fault_{var}"].to_numpy().astype(bool)
            thr = threshold_for_budget(sc[~y], (~y).sum()/24.0, b)
            flag = f"_f_{var}"
            tt = t.assign(**{flag: np.nan_to_num(sc, nan=-np.inf) >= thr})
            es = event_scores(tt, var, flag)
            for ft in ("spike", "noise_burst", "step_offset", "calibration_drift"):
                sub = es[es.fault_type == ft]
                if sub.empty:
                    continue
                cur = pod_curve(events, sub, var, n_bins=5)
                # smallest amplitude bin whose POD is at least the target
                def amp_at(p):
                    ok = cur[cur.pod >= p]
                    return float(ok.amp_median.min()) if len(ok) else float("nan")
                rows.append({"variable": var, "fault": ft,
                             "alerts/st/week": round(b*7, 1),
                             "n": len(sub), "recall": round(float(sub.hit.mean()), 2),
                             "amp@50%POD": round(amp_at(0.5), 2),
                             "amp@90%POD": round(amp_at(0.9), 2),
                             "sigma": round(sigma, 2)})
                if abs(b - 1/7) < 1e-9 and ft == "spike" and not cur.empty:
                    for _, r in cur.iterrows():
                        curves.append({"variable": var,
                                       "amplitude": round(float(r.amp_median), 2),
                                       "amp/sigma": round(float(r.amp_median)/sigma, 2),
                                       "n": int(r.n), "POD": round(float(r.pod), 2)})

    out = pd.DataFrame(rows)
    print("\nminimum detectable amplitude, by fault type and alert budget")
    print("(units: K for temp, % for rh, hPa for pres; sigma is the "
          "neighbour-difference noise floor)\n")
    for ft in out.fault.unique():
        print(f"--- {ft}")
        print(out[out.fault == ft].drop(columns="fault").to_string(index=False))
        print()

    if curves:
        print("POD vs amplitude for SPIKE at 1 alert/station/week:")
        print(pd.DataFrame(curves).to_string(index=False))
        print("\nRead the amp/sigma column. Where it is below about 3, POD "
              "collapses --\nthat is the detection threshold doing its job, not "
              "a detector failing.")


if __name__ == "__main__":
    main()
