"""Export a slim JSON snapshot for the dashboard.

    python -m dashboard.export

The dashboard is fed by REAL pipeline output, never mock data. A mocked
dashboard demos beautifully and hides every problem the harness just found --
and the problems are what the panel will ask about.

The contract this file writes is also the contract the FastAPI service must
serve, so the frontend can be built against a file today and repointed at an
endpoint later with no change above the fetch.
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
from evaluation.run_full import coherence_series, REF_END, RAILS
from signature import classify as SIG
from health import state as H
from residual.solartime import STATION_LATITUDE

VARIABLES = ("temp", "rh", "pres")
STEP = 3          # export every 3rd hour; the browser cannot use more

# The cluster label is an internal grouping, not a place. Operators think in
# states and IMD organises by them, so the console groups by state and keeps
# the cluster available underneath.
STATE = {"Assam_Flood_Basins": "Assam",
         "Maharashtra_Diversity": "Maharashtra"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/skyguard_injected.csv")
    ap.add_argument("--graph", default="data/neighbours_realistic.json")
    ap.add_argument("--out", default="dashboard/snapshot.json")
    ap.add_argument("--budget", type=float, default=1 / 7)
    args = ap.parse_args()

    df = pd.read_csv(args.data, parse_dates=["timestamp"])
    df = df[df.run_id == 0].reset_index(drop=True)
    graph = json.loads(Path(args.graph).read_text())

    coefs = {v: B.fit_baseline(df, v, ref_end=REF_END) for v in VARIABLES}
    ref = df[df.timestamp < pd.Timestamp(REF_END, tz="UTC")].reset_index(drop=True)
    live = df[df.timestamp >= pd.Timestamp(REF_END, tz="UTC")].reset_index(drop=True)

    F_ref = FT.build(ref, coefs, graph)
    F_live = FT.build(live, coefs, graph)
    dets = {v: LearnedDetector(variable=v).fit(F_ref) for v in VARIABLES}

    stations = sorted(live.station_name.unique())
    out = {
        "generated_from": args.data,
        "window": [str(live.timestamp.min()), str(live.timestamp.max())],
        "alert_budget_per_station_day": args.budget,
        "versions": {"detector": "ensemble/" + dets["temp"].version,
                     "signature": SIG.VERSION, "health": H.VERSION},
        "neighbours": {s: graph[s]["neighbours"] for s in stations if s in graph},
        "stations": [], "alerts": [],
    }

    for var in VARIABLES:
        # The console shows what the best detector we have actually produces:
        # the conformal ensemble, not the learned layer alone.
        sc = ensemble([
            conformalize(dets[var].distance(F_ref), dets[var].distance(F_live)),
            conformalize(B.neighbour_z(ref, var, coefs[var], graph),
                         B.neighbour_z(live, var, coefs[var], graph)),
            conformalize(B.persistence(ref, var), B.persistence(live, var)),
        ], certain=~np.isfinite(live[var].to_numpy(dtype=float)))
        p = 10.0 ** (-sc)
        clean = sc[~live[f"is_fault_{var}"].to_numpy().astype(bool)]
        thr = threshold_for_budget(clean, len(clean) / 24.0, args.budget)
        flag = np.nan_to_num(sc, nan=0.0) >= thr
        d_res, coh = coherence_series(live, var, coefs[var], graph)
        contrib = dets[var].contributions(F_live)

        nat, sigma = {}, {}
        for s_, g in ref.groupby("station_name", sort=False):
            v = g[var].to_numpy(dtype=float)
            v = v[np.isfinite(v)]
            nat[s_] = float(np.mean(v[1:] == v[:-1])) if len(v) > 1 else 0.0
        for s_, g in live.groupby("station_name", sort=False):
            sigma[s_] = B.robust_sigma(d_res.loc[g.index].to_numpy(), var)

        for st, g in live.groupby("station_name", sort=False):
            pos = live.index.get_indexer(g.index)
            for a, b in merge_runs(_runs(flag[pos])):
                if b - a < 2:
                    continue
                idx = g.index[a:b]
                w = SIG.describe(live.loc[idx], F_live.loc[idx], var,
                                 d_res.loc[idx], sigma[st], RAILS[var],
                                 float(coh.loc[idx].median()), nat.get(st, 0.0))
                res = SIG.classify(w)
                peak = idx[int(np.nanargmax(np.nan_to_num(sc[pos][a:b])))]
                c = contrib.loc[peak]
                c = (c / c.abs().sum()).round(3) if c.abs().sum() > 0 else c
                truth = live.loc[idx, f"fault_type_{var}"]
                truth = truth[truth != ""].mode()
                out["alerts"].append({
                    "station": st, "variable": var,
                    "start": str(live.loc[idx[0], "timestamp"]),
                    "end": str(live.loc[idx[-1], "timestamp"]),
                    "duration_h": int(b - a),
                    "label": res["label"], "confidence": res["confidence"],
                    "p_value": float(np.nanmin(p[pos][a:b])),
                    "explanation": SIG.explain(res, st, var),
                    "descriptors": res["descriptors"],
                    "contributions": {k: float(v) for k, v in c.items()},
                    "template_scores": res["scores"],
                    # ground truth travels with the alert so the demo can be
                    # honest about its own misses instead of only showing hits
                    "truth": (truth.iloc[0] if len(truth) else "(false alarm)"),
                })

    # ---- per-station series and health -----------------------------------
    for st, g in live.groupby("station_name", sort=False):
        g = g.sort_values("timestamp")
        sub = g.iloc[::STEP]
        series = {"t": [str(x)[:16] for x in sub.timestamp]}
        for var in VARIABLES:
            d_res, _ = coherence_series(live, var, coefs[var], graph)
            series[var] = [None if not np.isfinite(x) else round(float(x), 2)
                           for x in sub[var]]
            series[f"d_{var}"] = [None if not np.isfinite(x) else round(float(x), 3)
                                  for x in d_res.loc[sub.index]]
        # robust sigma per channel, so the chart can draw a real +/-3 sigma
        # band rather than an arbitrary decorative one
        sig = {}
        for var in VARIABLES:
            dr, _ = coherence_series(live, var, coefs[var], graph)
            sig[var] = round(float(B.robust_sigma(dr.loc[g.index].to_numpy(), var)), 4)
        alerts_here = [a for a in out["alerts"] if a["station"] == st]
        out["stations"].append({
            "name": st,
            "cluster": g.cluster.iloc[0],
            "state": STATE.get(g.cluster.iloc[0], g.cluster.iloc[0]),
            "elevation": float(g.elevation.iloc[0]),
            "longitude": float(g.longitude.iloc[0]),
            "latitude": STATION_LATITUDE.get(st),
            "health": H.roll_up({v: H.assess(alerts_here, v) for v in VARIABLES}),
            "sigma": sig,
            "series": series,
        })

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, separators=(",", ":")))
    n = len(out["alerts"])
    real = sum(1 for a in out["alerts"] if a["truth"] != "(false alarm)")
    print(f"{n} alerts ({real} real, {n-real} false), "
          f"{len(out['stations'])} stations")
    print(f"wrote {args.out}  "
          f"({Path(args.out).stat().st_size/1024:.0f} kB)")


if __name__ == "__main__":
    main()
