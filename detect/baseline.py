"""Baseline detectors. Deliberately simple -- these are the bar to beat.

If a learned model cannot beat `neighbour_z` on the harness at a fixed alert
budget, the learned model does not go in the submission. Reporting a neural
result without this comparison is how teams lose the accuracy marks.

All three are CAUSAL by default -- trailing window, never a future sample -- so
the latency they cost is zero. That matters for the Real-Time score, and it is
the difference between code that can serve a live request and code that cannot.
Pass causal=False to reproduce the centred variant for comparison; it is faster
and its numbers are not honest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# MAD floor. On 0.1-resolution data the MAD hits exactly zero on calm nights and
# the z-score goes to infinity, flagging the quietest hours of the year. The
# floor is a fraction of the logger resolution: on quantised data the MAD
# hits exactly zero on a calm night and the z-score goes infinite.
MAD_FLOOR_C = 0.75
# Reported resolution of each channel, used to floor the robust sigma so a
# quantised-but-healthy sensor cannot produce a divide-by-almost-zero z-score.
# `td` is not reported by any instrument -- it is derived from T and RH -- but
# it is differenced like a channel, so it needs an entry. Its effective
# quantisation follows temperature's, since dTd/dT is order 1 in humid air.
RESOLUTION = {"temp": 0.1, "rh": 0.1, "pres": 0.1, "td": 0.1}


def causal_scale(x, var: str, window: int = 720,
                 min_periods: int = 24):
    """Trailing-window median and robust sigma. STRICTLY CAUSAL.

    The centred version -- a median and MAD over the whole series -- is what the
    first draft used, and it is a lookahead leak: a reading in October was
    normalised using statistics that included December. It inflates every
    metric, and worse, it cannot serve a live request at all, because when the
    current hour is the last hour there is no rest of the year to normalise
    against.

    `.shift(1)` excludes the current sample from its own scale estimate.
    Without it a large excursion inflates the very sigma it is measured against
    and partially hides itself.

    The first `min_periods` samples return NaN: a detector with no history has
    nothing to say, and saying so beats guessing. That warm-up is real, and it
    is what a newly commissioned station experiences.
    """
    s = pd.Series(np.asarray(x, dtype=float)).shift(1)
    med = s.rolling(window, min_periods=min_periods).median()
    mad = (s - med).abs().rolling(window, min_periods=min_periods).median()
    sigma = np.maximum(1.4826 * mad.to_numpy(), MAD_FLOOR_C * RESOLUTION[var])
    return med.to_numpy(), sigma


def robust_sigma(x: np.ndarray, var: str) -> float:
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    return max(1.4826 * mad, MAD_FLOOR_C * RESOLUTION[var])


def harmonic_baseline(g: pd.DataFrame, var: str) -> np.ndarray:
    """Design matrix: 2 diurnal + 2 annual harmonics, ~9 parameters.

    Indexed by LOCAL SOLAR hour, not IST -- India spans two hours of solar time
    and an IST bin smears the diurnal cycle across that span.
    """
    sh, doy = g.solar_hour.to_numpy(), g.doy.to_numpy()
    cols = [np.ones(len(g))]
    for k in (1, 2):
        cols += [np.sin(2 * np.pi * k * sh / 24), np.cos(2 * np.pi * k * sh / 24),
                 np.sin(2 * np.pi * k * doy / 365.25),
                 np.cos(2 * np.pi * k * doy / 365.25)]
    return np.column_stack(cols)


def _huber_irls(X: np.ndarray, y: np.ndarray, c: float = 1.345,
                iters: int = 12) -> np.ndarray:
    """Huber regression by IRLS. Robust because the reference period contains
    UNLABELLED faults -- an OLS climatology fits the very drift it is meant to
    expose."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    for _ in range(iters):
        r = y - X @ beta
        s = 1.4826 * np.median(np.abs(r - np.median(r)))
        s = max(s, 1e-6)
        u = np.abs(r) / s
        w = np.where(u <= c, 1.0, c / np.maximum(u, 1e-9))
        sw = np.sqrt(w)
        beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    return beta


def fit_baseline(df: pd.DataFrame, var: str, ref_end: str | None = None) -> dict:
    """One coefficient vector per station, from that station's OWN frozen
    reference period.

    Deliberately NOT restricted to the train split. The baseline is climatology,
    not a learned decision rule: it uses no labels, and a station held out from
    detector training still has its own past. Restricting it to train stations
    would leave every newly commissioned station with no baseline -- which is
    exactly the situation on a real network, and the wrong problem to import
    into the harness.

    Fitted with Huber, on a frozen window, and never refitted online.
    """
    ref = df if ref_end is None else df[df.timestamp < pd.Timestamp(ref_end, tz="UTC")]
    coefs = {}
    for s, g in ref.groupby("station_name"):
        g = g.sort_values("timestamp")
        y = g[var].to_numpy(dtype=float)
        ok = np.isfinite(y)
        if ok.sum() < 200:
            continue
        X = harmonic_baseline(g, var)
        coefs[s] = _huber_irls(X[ok], y[ok])
    return coefs


def residual(df: pd.DataFrame, var: str, coefs: dict) -> pd.Series:
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for s, g in df.groupby("station_name"):
        g = g.sort_values("timestamp")
        if s not in coefs:
            continue
        out.loc[g.index] = g[var].to_numpy(dtype=float) - harmonic_baseline(g, var) @ coefs[s]
    return out


# ------------------------------------------------------------------ detectors

def self_z(df: pd.DataFrame, var: str, coefs: dict,
           causal: bool = True) -> np.ndarray:
    """Single-station robust z on the harmonic residual. The naive baseline."""
    r = residual(df, var, coefs)
    out = np.full(len(df), np.nan)
    for (_, s), g in df.groupby(["run_id", "station_name"], sort=False):
        v = r.loc[g.index].to_numpy()
        pos = df.index.get_indexer(g.index)
        if causal:
            med, sig = causal_scale(v, var)
            out[pos] = np.abs(v - med) / sig
        else:
            out[pos] = np.abs(v - np.nanmedian(v)) / robust_sigma(v, var)
    return out


def _neighbour_difference(df: pd.DataFrame, var: str, coefs: dict,
                          graph: dict) -> np.ndarray:
    """Harmonic residual minus the median residual of the chosen neighbours."""
    r = residual(df, var, coefs)
    wide = (pd.DataFrame({"run_id": df.run_id, "t": df.timestamp,
                          "s": df.station_name, "r": r})
            .pivot_table(index=["run_id", "t"], columns="s", values="r"))
    key = pd.MultiIndex.from_arrays([df.run_id, df.timestamp])
    out = np.full(len(df), np.nan)
    for s in wide.columns:
        nb = [n for n in graph.get(s, {}).get("neighbours", []) if n in wide.columns]
        diff = wide[s] - (wide[nb].median(axis=1) if nb else 0.0)
        m = (df.station_name == s).to_numpy()
        if m.any():
            out[m] = diff.reindex(key[m]).to_numpy()
    return out


def neighbour_z(df: pd.DataFrame, var: str, coefs: dict, graph: dict,
                causal: bool = True) -> np.ndarray:
    """Robust z on the NEIGHBOUR-DIFFERENCE residual. The bar to beat.

    Weather is common to the neighbourhood and cancels in the difference; a
    sensor fault is local and survives. This single subtraction is worth more
    than any model choice downstream -- measured 1.4-2.3x noise reduction.
    """
    r = residual(df, var, coefs)
    wide = (pd.DataFrame({"run_id": df.run_id, "t": df.timestamp,
                          "s": df.station_name, "r": r})
            .pivot_table(index=["run_id", "t"], columns="s", values="r"))
    diff = pd.DataFrame(index=wide.index, columns=wide.columns, dtype=float)
    for s in wide.columns:
        nb = [n for n in graph.get(s, {}).get("neighbours", []) if n in wide.columns]
        diff[s] = wide[s] - (wide[nb].median(axis=1) if nb else 0.0)

    key = pd.MultiIndex.from_arrays([df.run_id, df.timestamp])
    out = np.full(len(df), np.nan)
    for s in wide.columns:
        m = (df.station_name == s).to_numpy()
        if not m.any():
            continue
        v = diff[s].reindex(key[m]).to_numpy()
        if causal:
            med, sig = causal_scale(v, var)
            out[m] = np.abs(v - med) / sig
        else:
            out[m] = np.abs(v - np.nanmedian(v)) / robust_sigma(v, var)
    return out


def persistence(df: pd.DataFrame, var: str) -> np.ndarray:
    """Flatness score -- length of the current identical run, in samples.

    Structurally different from a z-score: it detects frozen and saturated
    sensors, which a point detector like Mahalanobis is blind to by
    construction. Kept separate rather than blended so the signature stage can
    still tell the two apart.
    """
    out = np.zeros(len(df))
    for _, g in df.groupby(["run_id", "station_name"], sort=False):
        v = g[var].to_numpy(dtype=float)
        run = np.zeros(len(v))
        for i in range(1, len(v)):
            run[i] = run[i - 1] + 1 if v[i] == v[i - 1] else 0.0
        out[df.index.get_indexer(g.index)] = run
    return out


def local_outlier(df: pd.DataFrame, var: str, coefs: dict, graph: dict,
                  window: int = 24) -> np.ndarray:
    """Hampel score: deviation from the LOCAL median, in local MAD.

    Targets `spike`, which the long-window z-score is poor at. Both are
    z-scores; the difference is the reference. A 720-hour MAD is a seasonal
    scale, and a one-hour excursion has to beat a whole season's variability to
    clear it. A trailing-24-hour median and MAD ask the operative question
    instead: is this sample unlike the last day at this station?

    Median and MAD rather than mean and sd because the window is short and an
    injected spike is up to half of it -- a mean would chase the outlier it is
    meant to expose. `.shift(1)` keeps the sample out of its own reference.

    Honest about its ceiling: measured on this data the local scale is only
    1.2x tighter than the seasonal one for temperature and 1.5x for pressure,
    so this recovers a modest band of amplitudes, not every missed spike. Spikes
    below roughly 2 sigma stay undetectable at a one-alert-per-week budget, and
    that is a property of the budget rather than of the detector.
    """
    d = _neighbour_difference(df, var, coefs, graph)
    out = np.full(len(df), np.nan)
    for _, g in df.groupby(["run_id", "station_name"], sort=False):
        pos = df.index.get_indexer(g.index)
        x = pd.Series(d[pos]).shift(1)
        med = x.rolling(window, min_periods=8).median()
        mad = (x - med).abs().rolling(window, min_periods=8).median()
        sig = np.maximum(1.4826 * mad.to_numpy(), MAD_FLOOR_C * RESOLUTION[var])
        out[pos] = np.abs(d[pos] - med.to_numpy()) / sig
    return out


def dispersion(df: pd.DataFrame, var: str, coefs: dict, graph: dict,
               window: int = 24) -> np.ndarray:
    """Trailing scatter against the station's own usual scatter.

    Targets `noise_burst`, which every other channel is structurally blind to:
    a noise burst leaves the mean where it was, so a level detector sees
    nothing, and it keeps the sensor moving, so the persistence detector sees
    nothing either.

    Scatter is measured as an interquartile range, not a standard deviation.
    An sd would fire on a single spike, which is a DIFFERENT fault -- keeping
    the two channels responsive to different things is the whole reason for
    having both, and a channel that answers yes to everything adds only false
    alarms to the ensemble.
    """
    d = _neighbour_difference(df, var, coefs, graph)
    out = np.full(len(df), np.nan)
    for _, g in df.groupby(["run_id", "station_name"], sort=False):
        pos = df.index.get_indexer(g.index)
        x = pd.Series(d[pos])
        iqr = (x.rolling(window, min_periods=12).quantile(0.75)
               - x.rolling(window, min_periods=12).quantile(0.25))
        base = iqr.expanding(min_periods=48).median()
        base = np.maximum(np.nan_to_num(base.to_numpy(), nan=0.0),
                          RESOLUTION[var])
        out[pos] = np.nan_to_num(iqr.to_numpy() / base, nan=1.0)
    return out


def combined(df: pd.DataFrame, var: str, coefs: dict, graph: dict,
             causal: bool = True) -> np.ndarray:
    """max(neighbour z, scaled persistence, dropout).

    A max, not a sum: these detect disjoint failure modes and averaging them
    dilutes both. Dropout scores infinite because a missing observation is not
    a borderline call.
    """
    z = neighbour_z(df, var, coefs, graph, causal=causal)
    p = persistence(df, var) / 6.0          # 6 identical samples ~ z of 1
    miss = ~np.isfinite(df[var].to_numpy(dtype=float))
    s = np.fmax(np.nan_to_num(z, nan=0.0), p)
    s[miss] = 1e6
    return s
