"""Scoring harness. Nothing goes in detect/ or signature/ until this can score it.

Takes a per-point anomaly SCORE (higher = more anomalous, any scale) plus the
ground truth the injector wrote, and returns the metric set CLAUDE.md mandates:

    PR-AUC                  not ROC-AUC; at ~3 % prevalence ROC flatters junk
    POD vs amplitude        the headline number is min detectable amp at 90 % POD
    event / point recall    both; the gap tells you if you catch onsets or bulk
    FA per station-day      split quiet vs active weather -- a detector that
                            only false-alarms during storms has not solved the
                            fault-vs-weather problem, it has hidden it
    time to detection       distribution per fault type, not a mean
    fixed alert budget      the only fair way to compare two methods

A note on what counts as a hit. Event recall uses ANY-OVERLAP: the event is
detected if at least one point inside it is flagged. That is the operationally
meaningful definition -- an engineer is dispatched once, not once per hour.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VARIABLES = ("temp", "rh", "pres")


# ---------------------------------------------------------------- primitives

def pr_auc(y_true: np.ndarray, score: np.ndarray) -> float:
    """Average precision. Computed directly so evaluation/ needs no sklearn."""
    y = np.asarray(y_true).astype(bool)
    s = np.asarray(score, dtype=float)
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    if y.sum() == 0:
        return float("nan")

    order = np.argsort(-s)
    y = y[order]
    tp = np.cumsum(y)
    fp = np.cumsum(~y)
    precision = tp / (tp + fp)
    recall = tp / y.sum()
    # step integral, the standard average-precision definition
    return float(np.sum(np.diff(np.concatenate([[0.0], recall])) * precision))


def threshold_for_budget(score: np.ndarray, station_days: float,
                         alerts_per_station_day: float) -> float:
    """The threshold that spends exactly the given alert budget.

    Comparing two detectors at their own best thresholds compares nothing. Fix
    the budget an operator will actually tolerate, then ask what each catches.
    """
    s = np.asarray(score, dtype=float)
    s = s[np.isfinite(s)]
    n_alerts = max(1, int(round(alerts_per_station_day * station_days)))
    if n_alerts >= len(s):
        return float(np.min(s))
    return float(np.partition(s, -n_alerts)[-n_alerts])


# ------------------------------------------------------------- event scoring

def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs as [start, end) index pairs."""
    m = np.asarray(mask).astype(bool)
    if not m.any():
        return []
    d = np.diff(np.concatenate([[0], m.view(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def event_scores(df: pd.DataFrame, var: str, flag_col: str) -> pd.DataFrame:
    """Per-event hit/miss and time-to-detection, in hours from event onset."""
    rows = []
    eid_col, ft_col = f"event_id_{var}", f"fault_type_{var}"
    grp = df[df[eid_col] >= 0].groupby(["run_id", eid_col], sort=False)
    for (run, eid), g in grp:
        g = g.sort_values("timestamp")
        flag = g[flag_col].to_numpy().astype(bool)
        hit = bool(flag.any())
        ttd = float(np.flatnonzero(flag)[0]) if hit else float("nan")
        rows.append({"run_id": run, "event_id": eid, "variable": var,
                     "fault_type": g[ft_col].iloc[0], "duration_h": len(g),
                     "hit": hit, "ttd_h": ttd})
    return pd.DataFrame(rows)


# --------------------------------------------------------- false alarm rates

def false_alarm_rates(df: pd.DataFrame, var: str, flag_col: str,
                      activity_col: str = "weather_active") -> dict:
    """Alerts per station-day on CLEAN points, split by weather activity.

    The split is the whole point. A detector can post a respectable overall
    false-alarm rate while emitting all of it during frontal passages -- which
    is precisely the failure PS26073 asks us to avoid.
    """
    clean = df[~df[f"is_fault_{var}"].astype(bool)]
    out = {}
    for label, sub in (("all", clean),
                       ("quiet", clean[~clean[activity_col]]),
                       ("active", clean[clean[activity_col]])):
        if len(sub) == 0:
            out[label] = float("nan")
            continue
        station_days = len(sub) / 24.0
        # count ALERTS, not flagged points: a 40-hour flag is one dispatch
        alerts = sum(len(_runs(g[flag_col].to_numpy()))
                     for _, g in sub.groupby(["run_id", "station_name"], sort=False))
        out[label] = float(alerts / station_days)
    return out


def mark_weather_activity(df: pd.DataFrame, var: str = "temp",
                          quantile: float = 0.75) -> pd.DataFrame:
    """Flag hours of genuinely active weather, using CLEAN points only.

    Activity is the rolling spread of the variable across the network -- when
    real weather is moving through, every station moves. Derived from clean
    points so an injected fault cannot make its own hour look 'active' and
    thereby excuse the false alarm it caused.
    """
    out = df.copy()
    clean = out[var].where(~out[f"is_fault_{var}"].astype(bool))
    spread = (clean.groupby([out.run_id, out.timestamp]).transform("std"))
    roll = spread.groupby(out.station_name).transform(
        lambda s: s.rolling(6, min_periods=1).mean())
    out["weather_active"] = roll > roll.quantile(quantile)
    return out


# ------------------------------------------------------------ POD vs amplitude

def pod_curve(events: pd.DataFrame, scored: pd.DataFrame, var: str,
              n_bins: int = 8) -> pd.DataFrame:
    """Probability of detection as a function of injected amplitude.

    This is the headline plot. Report the amplitude at which POD reaches 90 %
    -- 'we detect a 0.35 K step' is a claim an evaluator can check, whereas
    'we achieve 94 % accuracy' is not.
    """
    ev = events[(events.variable == var) & events.amplitude.notna()].copy()
    if ev.empty:
        return pd.DataFrame()
    m = scored.merge(ev[["run_id", "event_id", "amplitude", "fault_type"]],
                     on=["run_id", "event_id"], how="inner",
                     suffixes=("", "_ev"))
    if m.empty:
        return pd.DataFrame()
    edges = np.exp(np.linspace(np.log(m.amplitude.min()),
                               np.log(m.amplitude.max() * 1.001), n_bins + 1))
    m["bin"] = pd.cut(m.amplitude, edges, include_lowest=True)
    g = m.groupby("bin", observed=True).agg(
        n=("hit", "size"), pod=("hit", "mean"),
        amp_median=("amplitude", "median")).reset_index(drop=True)
    return g


def amplitude_at_pod(curve: pd.DataFrame, target: float = 0.90) -> float:
    """Smallest binned amplitude from which POD stays >= target upward."""
    if curve.empty:
        return float("nan")
    ok = curve.pod >= target
    # walk down from the top; the claim must hold for every larger bin too
    best = float("nan")
    for i in range(len(curve) - 1, -1, -1):
        if ok.iloc[i]:
            best = float(curve.amp_median.iloc[i])
        else:
            break
    return best


# ------------------------------------------------------------------ top level

def evaluate(df: pd.DataFrame, events: pd.DataFrame, var: str,
             score_col: str, alerts_per_station_day: float = 1 / 7) -> dict:
    """Full metric set for one variable at one alert budget."""
    if "weather_active" not in df.columns:
        df = mark_weather_activity(df, var)

    y = df[f"is_fault_{var}"].to_numpy().astype(bool)
    s = df[score_col].to_numpy(dtype=float)

    clean_days = (~y).sum() / 24.0
    thr = threshold_for_budget(s[~y], clean_days, alerts_per_station_day)
    flag_col = f"_flag_{var}"
    df = df.assign(**{flag_col: np.nan_to_num(s, nan=-np.inf) >= thr})

    sc = event_scores(df, var, flag_col)
    curve = pod_curve(events, sc, var)

    ttd = sc[sc.hit].groupby("fault_type").ttd_h.describe(
        percentiles=[0.5, 0.9])[["count", "50%", "90%"]] if not sc.empty else None

    return {
        "variable": var,
        "alert_budget_per_station_day": alerts_per_station_day,
        "threshold": thr,
        "pr_auc": pr_auc(y, s),
        "point_recall": float(np.nan_to_num(s, nan=-np.inf)[y].__ge__(thr).mean())
                        if y.any() else float("nan"),
        "event_recall": float(sc.hit.mean()) if not sc.empty else float("nan"),
        "event_recall_by_type": (sc.groupby("fault_type").hit.mean().round(3).to_dict()
                                 if not sc.empty else {}),
        "false_alarms_per_station_day": false_alarm_rates(df, var, flag_col),
        "pod_curve": curve.to_dict("records"),
        "amplitude_at_90pct_pod": amplitude_at_pod(curve),
        "ttd_hours_by_type": (ttd.round(1).to_dict("index") if ttd is not None else {}),
        "n_events": int(len(sc)),
        "prevalence": float(y.mean()),
    }
