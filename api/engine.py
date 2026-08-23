"""Scoring engine behind the API. Loads once, scores once, serves many.

WHY THE WORK IS SPLIT THIS WAY. Running the detectors takes minutes over a
year of ten stations, and an HTTP handler that does that is not a service. But
the expensive part -- residuals, features, conformal p-values -- does not depend
on any request parameter. The alert BUDGET does, and it only moves a threshold;
the date window and station only slice. So the pipeline runs once at startup and
every request is a threshold plus a slice, which is milliseconds.

That split is also what makes the numbers honest. A request cannot change how a
score was computed, only which scores it sees, so two users asking different
questions are looking at the same detector.

Re-scoring with different DETECTOR settings is a separate, explicit operation
(`rescore`) because it costs minutes and invalidates everything cached.
"""
from __future__ import annotations
import json, time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from detect import baseline as B
from detect import features as FT
from detect.learned import LearnedDetector, conformalize, ensemble
from evaluation.metrics import _runs, merge_runs, threshold_for_budget
from signature import classify as SIG
from health import state as H

VARIABLES = ("temp", "rh", "pres")
REF_END = "2023-10-01"
RAILS = {"temp": (-40.0, 60.0), "rh": (0.0, 100.0), "pres": (500.0, 1100.0)}
STATE = {"Assam_Flood_Basins": "Assam", "Maharashtra_Diversity": "Maharashtra"}

DEFAULT_DATA = "data/skyguard_injected.csv"
DEFAULT_GRAPH = "data/neighbours_realistic.json"


@dataclass
class Engine:
    data_path: str = DEFAULT_DATA
    graph_path: str = DEFAULT_GRAPH
    causal: bool = True

    live: pd.DataFrame = field(default_factory=pd.DataFrame)
    ref: pd.DataFrame = field(default_factory=pd.DataFrame)
    graph: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)     # var -> ndarray, -log10 p
    dres: dict = field(default_factory=dict)       # var -> Series
    sigma: dict = field(default_factory=dict)      # var -> {station: float}
    natural_flat: dict = field(default_factory=dict)
    contrib: dict = field(default_factory=dict)
    detectors: dict = field(default_factory=dict)
    built_at: float = 0.0
    build_seconds: float = 0.0

    # ------------------------------------------------------------------ load
    def build(self) -> "Engine":
        t0 = time.time()
        df = pd.read_csv(self.data_path, parse_dates=["timestamp"])
        if "run_id" in df.columns:
            df = df[df.run_id == 0]
        else:
            df["run_id"] = 0
        df = df.reset_index(drop=True)
        self.graph = json.loads(Path(self.graph_path).read_text())

        cut = pd.Timestamp(REF_END, tz="UTC")
        self.ref = df[df.timestamp < cut].reset_index(drop=True)
        self.live = df[df.timestamp >= cut].reset_index(drop=True)

        coefs = {v: B.fit_baseline(df, v, ref_end=REF_END) for v in VARIABLES}
        self.coefs = coefs
        F_ref = FT.build(self.ref, coefs, self.graph, causal=self.causal)
        F_live = FT.build(self.live, coefs, self.graph, causal=self.causal)

        for v in VARIABLES:
            det = LearnedDetector(variable=v).fit(F_ref)
            self.detectors[v] = det
            miss = ~np.isfinite(self.live[v].to_numpy(dtype=float))
            self.scores[v] = ensemble([
                conformalize(det.distance(F_ref), det.distance(F_live)),
                conformalize(B.neighbour_z(self.ref, v, coefs[v], self.graph, self.causal),
                             B.neighbour_z(self.live, v, coefs[v], self.graph, self.causal)),
                conformalize(B.persistence(self.ref, v), B.persistence(self.live, v)),
            ], certain=miss)
            self.contrib[v] = det.contributions(F_live)
            self.dres[v] = FT.neighbour_residual(self.live, v, coefs[v], self.graph)
            self.sigma[v] = {
                s: float(B.robust_sigma(self.dres[v].loc[g.index].to_numpy(), v))
                for s, g in self.live.groupby("station_name", sort=False)}
            nat = {}
            for s, g in self.ref.groupby("station_name", sort=False):
                x = g[v].to_numpy(dtype=float)
                x = x[np.isfinite(x)]
                nat[s] = float(np.mean(x[1:] == x[:-1])) if len(x) > 1 else 0.0
            self.natural_flat[v] = nat

        self.built_at = time.time()
        self.build_seconds = round(self.built_at - t0, 1)
        return self

    def rescore(self, causal: bool | None = None) -> "Engine":
        """Re-run the whole pipeline. Minutes, not milliseconds -- exposed as
        its own operation so nobody triggers it from a page refresh."""
        if causal is not None:
            self.causal = causal
        self.scores, self.contrib, self.detectors = {}, {}, {}
        return self.build()

    # ----------------------------------------------------------------- clock
    def cutoff(self, until: str | None) -> int:
        """Index of the last observation the virtual clock has reached.

        Everything downstream slices on this, so the replay is not a UI effect:
        at virtual 14 November the server genuinely cannot see 15 November, the
        thresholds are computed from what has arrived, and an alert appears when
        the detector would really have raised it. A replay that filters only the
        chart would show detections before their own onset.
        """
        if not until:
            return len(self.live)
        t = pd.Timestamp(until)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        return int((self.live.timestamp <= t).sum())

    def span(self) -> tuple[str, str]:
        return str(self.live.timestamp.min()), str(self.live.timestamp.max())

    # --------------------------------------------------------------- queries
    def stations(self, state: str | None = None, budget: float = 1 / 7,
                 until: str | None = None) -> list[dict]:
        alerts = self.alerts(budget=budget, until=until)
        out = []
        for name, g in self.live.groupby("station_name", sort=True):
            st = STATE.get(g.cluster.iloc[0], g.cluster.iloc[0])
            if state and st != state:
                continue
            mine = [a for a in alerts if a["station"] == name]
            out.append({
                "name": name, "state": st, "cluster": g.cluster.iloc[0],
                "elevation": float(g.elevation.iloc[0]),
                "longitude": float(g.longitude.iloc[0]),
                "neighbours": self.graph.get(name, {}).get("neighbours", []),
                "sigma": {v: self.sigma[v].get(name) for v in VARIABLES},
                "health": H.roll_up({v: H.assess(mine, v) for v in VARIABLES}),
                "alert_count": len(mine),
            })
        return out

    def series(self, station: str, step: int = 3,
               start: str | None = None, end: str | None = None,
               until: str | None = None, window_hours: int | None = None) -> dict:
        g = self.live[self.live.station_name == station].sort_values("timestamp")
        if until:
            g = g[g.timestamp <= pd.Timestamp(until, tz="UTC")]
        if window_hours:
            # A trailing window, not the whole record. Three months of hourly
            # data squeezed into 600 px is one pixel per six hours, which turns
            # every trace into a band and every fault into a smudge -- and it
            # forces the y-axis to span the season, so a 2 K step offset is
            # invisible next to a 20 K annual swing.
            g = g.tail(window_hours)
        if start:
            g = g[g.timestamp >= pd.Timestamp(start, tz="UTC")]
        if end:
            g = g[g.timestamp <= pd.Timestamp(end, tz="UTC")]
        sub = g.iloc[::max(step, 1)]
        out = {"station": station, "step_hours": step,
               "t": [str(x)[:16] for x in sub.timestamp]}
        for v in VARIABLES:
            out[v] = [None if not np.isfinite(x) else round(float(x), 2)
                      for x in sub[v]]
            out[f"d_{v}"] = [None if not np.isfinite(x) else round(float(x), 3)
                             for x in self.dres[v].loc[sub.index]]
        return out

    def alerts(self, budget: float = 1 / 7, state: str | None = None,
               station: str | None = None, min_confidence: float = 0.0,
               until: str | None = None) -> list[dict]:
        """Re-thresholded per request. The budget is the operator's dial: it
        trades recall against how many vans get sent, and it is the one thing
        the UI should be able to change without a re-score."""
        out = []
        cut = self.cutoff(until)
        seen = np.zeros(len(self.live), dtype=bool)
        seen[:cut] = True

        for var in VARIABLES:
            sc = np.where(seen, self.scores[var], np.nan)
            truth_col = f"is_fault_{var}"
            vis = sc[seen]
            clean = (vis[~self.live.loc[seen, truth_col].to_numpy().astype(bool)]
                     if truth_col in self.live.columns else vis)
            if len(clean) < 24:
                continue
            thr = threshold_for_budget(clean, len(clean) / 24.0, budget)
            flag = np.nan_to_num(sc, nan=0.0) >= thr

            for st, g in self.live.groupby("station_name", sort=False):
                if station and st != station:
                    continue
                pos = self.live.index.get_indexer(g.index)
                for a, b in merge_runs(_runs(flag[pos])):
                    if b - a < 2:
                        continue
                    idx = g.index[a:b]
                    w = SIG.describe(self.live.loc[idx], None, var,
                                     self.dres[var].loc[idx],
                                     self.sigma[var][st], RAILS[var], 0.0,
                                     self.natural_flat[var].get(st, 0.0))
                    res = SIG.classify(w)
                    if res["confidence"] < min_confidence:
                        continue
                    out.append(self._alert(st, var, idx, a, b, pos, sc, res))

        if state:
            byname = {s["name"]: s["state"] for s in self._station_states()}
            out = [a for a in out if byname.get(a["station"]) == state]
        out.sort(key=lambda a: a["start"])
        for i, a in enumerate(out):
            a["id"] = i
        return out

    def _station_states(self) -> list[dict]:
        return [{"name": n, "state": STATE.get(g.cluster.iloc[0], g.cluster.iloc[0])}
                for n, g in self.live.groupby("station_name", sort=True)]

    def _alert(self, st, var, idx, a, b, pos, sc, res) -> dict:
        peak = idx[int(np.nanargmax(np.nan_to_num(sc[pos][a:b])))]
        c = self.contrib[var].loc[peak]
        c = (c / c.abs().sum()).round(3) if c.abs().sum() > 0 else c
        truth = None
        if f"fault_type_{var}" in self.live.columns:
            t = self.live.loc[idx, f"fault_type_{var}"]
            t = t[t != ""].mode()
            truth = t.iloc[0] if len(t) else "(false alarm)"
        return {
            "station": st, "variable": var,
            "start": str(self.live.loc[idx[0], "timestamp"]),
            "end": str(self.live.loc[idx[-1], "timestamp"]),
            "duration_h": int(b - a),
            "label": res["label"], "confidence": res["confidence"],
            "p_value": float(10.0 ** (-np.nanmax(sc[pos][a:b]))),
            "explanation": SIG.explain(res, st, var),
            "descriptors": res["descriptors"],
            "contributions": {k: float(v) for k, v in c.items()},
            "template_scores": res["scores"],
            "truth": truth,
        }

    def shapley(self, station: str, variable: str, timestamp: str) -> dict:
        """Exact 64-coalition Shapley for one point. Costs milliseconds at d=6,
        which is why it runs on demand rather than being precomputed for a
        million rows nobody will open."""
        det = self.detectors[variable]
        F = FT.build(self.live[self.live.station_name == station],
                     self.coefs, self.graph, causal=self.causal)
        row = self.live[(self.live.station_name == station) &
                        (self.live.timestamp == pd.Timestamp(timestamp, tz="UTC"))]
        if row.empty:
            raise KeyError(f"no observation for {station} at {timestamp}")
        x = F.loc[row.index[0], list(det.feature_names)].to_numpy(dtype=float)
        return {"station": station, "variable": variable, "timestamp": timestamp,
                "shapley": det.shapley(np.nan_to_num(x)),
                "detector_version": det.version}

    def meta(self) -> dict:
        return {
            "window": [str(self.live.timestamp.min()), str(self.live.timestamp.max())],
            "reference_ends": REF_END,
            "stations": int(self.live.station_name.nunique()),
            "states": sorted({s["state"] for s in self._station_states()}),
            "causal": self.causal,
            "versions": {
                "detector": "ensemble/" + LearnedDetector.version,
                "signature": SIG.VERSION, "health": H.VERSION,
            },
            "build_seconds": self.build_seconds,
            "source": self.data_path,
            "ground_truth_available": f"fault_type_temp" in self.live.columns,
        }
