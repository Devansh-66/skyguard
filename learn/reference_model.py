"""A learned reference: predict what a station SHOULD have read.

WHY THE MODEL GOES HERE AND NOT IN THE SCORER

Every anomaly score in this project is a subtraction: the station's reading
minus what it ought to be. Today "what it ought to be" is the median anomaly of
its neighbours -- robust, free, and deliberately crude. It weights a station
40 km away across a mountain the same as one 200 km away on the same plain, it
knows nothing about the hour, and its error is the noise floor every downstream
threshold sits on.

That noise floor is what decides how long a drift takes to find. Detection needs
the accumulated drift to pass 6 sigma of the residual, so halving sigma halves
the time to detection for every drift rate at once. A cleverer scorer does not
do that; a better reference does.

So the model's only job is the reference. The detector downstream is unchanged,
which is also what makes the comparison honest: same bands, same episode rule,
same everything, one term swapped.

WHAT IS AND IS NOT ALLOWED IN THE FEATURES

The station's own reading, at any lag, is forbidden. A model given its own past
learns to predict the drift along with the weather and reports healthy while
the instrument fails -- the same self-masking that makes a node refitting its
own baseline useless, measured in evaluation/run_edge_approx.py. Neighbours,
the clock and geometry only.

AND NO INDIVIDUAL NEIGHBOUR EITHER. MEASURED.

The first version of this model took one column per neighbour, which let it
lean on the nearest. Corrupting that neighbour with a +10 K offset moved the
reference by 4.44 K, against 0.16 K for the median it was replacing -- so every
healthy station beside a broken one would have alarmed. The median's breakdown
point is not a crude stand-in for a model; it is a property the pipeline
depends on.

The features are therefore statistics of the neighbourhood that are themselves
robust -- the median, a trimmed mean, the spread, how many reported -- plus the
things a median genuinely cannot know: hour, season, geometry. The model can
learn that a station runs half a degree warm at dawn relative to its region. It
cannot learn to follow one station off a cliff.

WHAT IS MEASURED

Residual spread on held-out days against the neighbour median on the same days,
per channel, on stations with no injected fault. Reported by
`python -m learn.reference_model`.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CLEAN = Path("data/sim/network_15min.npz")
FAULTED = Path("data/sim/network_faulted.npz")
OUT = Path("models/reference")

# How many neighbours enter the feature vector. Six is what the rest of the
# system uses for a live node, and going wider costs a feature per station
# while adding stations that are further away than the weather is coherent.
K = 6
RADIUS_KM = 250.0

# Where the record is cut. Training on the first twenty days and scoring on the
# last ten is the only split that answers the question a deployment asks: the
# model will always be older than the data it judges.
TRAIN_DAYS = 20
STEP_MIN = 15
PER_DAY = 24 * 60 // STEP_MIN


def _dist_km(lat1, lon1, lat2, lon2):
    dx = (lon2 - lon1) * math.cos(math.radians(lat1)) * 111.0
    dy = (lat2 - lat1) * 111.0
    return np.hypot(dx, dy)


@dataclass
class Data:
    vals: dict[str, np.ndarray]      # channel -> (steps, stations)
    lat: np.ndarray
    lon: np.ndarray
    elev: np.ndarray
    names: np.ndarray
    n_steps: int
    n_st: int


def load(path: Path = CLEAN) -> Data:
    z = np.load(path, allow_pickle=True)
    vals = {c: np.asarray(z[c], dtype=np.float64) for c in ("temp", "rh", "pres")}
    n_steps, n_st = vals["temp"].shape
    elev = (np.asarray(z["elev"], dtype=np.float64) if "elev" in z.files
            else np.zeros(n_st))
    return Data(vals=vals, lat=np.asarray(z["lat"], dtype=np.float64),
                lon=np.asarray(z["lon"], dtype=np.float64), elev=elev,
                names=np.asarray(z["names"]), n_steps=n_steps, n_st=n_st)


def neighbours(d: Data, k: int = K) -> tuple[np.ndarray, np.ndarray]:
    """The k nearest stations to each station, and how far away they are.

    Excludes the station itself, which is the one bug in this function that
    would not announce itself: the model would score perfectly and the
    detector would go blind.
    """
    idx = np.zeros((d.n_st, k), dtype=np.int32)
    dist = np.zeros((d.n_st, k), dtype=np.float64)
    for s in range(d.n_st):
        km = _dist_km(d.lat[s], d.lon[s], d.lat, d.lon)
        km[s] = np.inf                      # never itself
        km[km > RADIUS_KM] = np.inf
        order = np.argsort(km)[:k]
        idx[s] = order
        dist[s] = np.where(np.isinf(km[order]), np.nan, km[order])
    return idx, dist


def climatology(x: np.ndarray, hod: np.ndarray, upto: int) -> np.ndarray:
    """Per-station mean by hour of day, fitted on the first `upto` steps only.

    Fitted on the training window and applied to everything, because a
    climatology fitted on the window it is then evaluated on is the in-sample
    estimate that inflated sigma by 1.61x the last time this project made that
    mistake.
    """
    n_st = x.shape[1]
    clim = np.zeros((24, n_st))
    for h in range(24):
        m = (hod[:upto] == h)
        clim[h] = np.nanmean(x[:upto][m], axis=0) if m.any() else 0.0
    return clim


def build_matrix(d: Data, ch: str, nb_idx: np.ndarray, nb_dist: np.ndarray,
                 split: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Features and target for one channel, as flat (rows, features).

    One row per station per timestep. The target is the station's own anomaly;
    the features are its neighbours' anomalies, how far away they are, and the
    clock. Nothing about the station's own history appears anywhere.
    """
    x = d.vals[ch]
    steps = np.arange(d.n_steps)
    hod = (steps * STEP_MIN // 60) % 24
    doy = steps * STEP_MIN / 1440.0

    clim = climatology(x, hod, split)
    anom = x - clim[hod]                                  # (steps, stations)

    nb_anom = anom[:, nb_idx]                             # (steps, st, k)
    # A neighbour beyond the radius contributes nothing rather than a zero,
    # which would read as "agrees exactly with its own climatology".
    far = np.isnan(nb_dist)
    nb_anom[:, far] = np.nan

    n_steps, n_st = anom.shape
    k = nb_idx.shape[1]

    hour_sin = np.sin(2 * np.pi * hod / 24)[:, None]
    hour_cos = np.cos(2 * np.pi * hod / 24)[:, None]
    doy_sin = np.sin(2 * np.pi * doy / 365.25)[:, None]
    doy_cos = np.cos(2 * np.pi * doy / 365.25)[:, None]

    # ---- robust neighbourhood statistics, never a named neighbour
    with np.errstate(invalid="ignore"):
        nb_med = np.nanmedian(nb_anom, axis=2)
        nb_mad = np.nanmedian(np.abs(nb_anom - nb_med[:, :, None]), axis=2)
        nb_n = np.sum(np.isfinite(nb_anom), axis=2).astype(float)
        # A trimmed mean: drop the extreme neighbour at each end, then average.
        # Sorting puts NaN last, so the count decides where the middle is.
        srt = np.sort(nb_anom, axis=2)
        trim = np.full_like(nb_med, np.nan)
        for c in range(3, k + 1):
            m = nb_n == c
            if m.any():
                trim[m] = np.nanmean(srt[:, :, 1:c - 1][m], axis=1)
        # Two nearest only, as a second view with a different radius. Still a
        # median, so still robust to one of them.
        nb_med_near = np.nanmedian(nb_anom[:, :, :3], axis=2)

    cols = []
    names = []
    cols.append(nb_med);      names.append("nb_median")
    cols.append(trim);        names.append("nb_trimmed_mean")
    cols.append(nb_mad);      names.append("nb_spread")
    cols.append(nb_n);        names.append("nb_count")
    cols.append(nb_med_near); names.append("nb_median_near3")
    cols.append(np.broadcast_to(np.nanmean(nb_dist, axis=1), (n_steps, n_st)))
    names.append("nb_mean_km")
    cols.append(np.broadcast_to(nb_dist[:, 0], (n_steps, n_st)))
    names.append("nearest_km")
    cols.append(np.broadcast_to(hour_sin, (n_steps, n_st))); names.append("hour_sin")
    cols.append(np.broadcast_to(hour_cos, (n_steps, n_st))); names.append("hour_cos")
    cols.append(np.broadcast_to(doy_sin, (n_steps, n_st))); names.append("season_sin")
    cols.append(np.broadcast_to(doy_cos, (n_steps, n_st))); names.append("season_cos")
    cols.append(np.broadcast_to(d.elev[None, :], (n_steps, n_st)))
    names.append("elev_m")
    # Height ABOVE the neighbourhood, which is the part a shared weather field
    # cannot account for -- absolute elevation alone says nothing without it.
    nb_elev = np.nanmean(np.where(np.isnan(nb_dist), np.nan, d.elev[nb_idx]), axis=1)
    cols.append(np.broadcast_to((d.elev - nb_elev)[None, :], (n_steps, n_st)))
    names.append("elev_above_nb")

    X = np.stack([c.reshape(-1) for c in cols], axis=1)
    y = anom.reshape(-1)
    step_of_row = np.repeat(steps, n_st)
    station_of_row = np.tile(np.arange(n_st), n_steps)
    return X, y, step_of_row, station_of_row, names, anom


def row_features(d: Data, ch: str, nb_idx: np.ndarray, nb_dist: np.ndarray,
                 clim: np.ndarray, station: int, step: int) -> np.ndarray:
    """The same feature vector as build_matrix, for ONE station at ONE step.

    Serving does not need the other 990,719 rows, and materialising them costs
    over 300 MB across three channels. This must stay in step with
    build_matrix; tests/test_reference_row.py asserts that it does, because two
    implementations of one feature set is a bug that hides until the model is
    quietly being served the wrong numbers.
    """
    x = d.vals[ch]
    hod = (step * STEP_MIN // 60) % 24
    doy = step * STEP_MIN / 1440.0
    k = nb_idx.shape[1]

    nb = np.array([x[step, j] - clim[hod, j] for j in nb_idx[station]],
                  dtype=np.float64)
    nb[np.isnan(nb_dist[station])] = np.nan

    with np.errstate(invalid="ignore"):
        nb_med = np.nanmedian(nb) if np.isfinite(nb).any() else np.nan
        nb_mad = (np.nanmedian(np.abs(nb - nb_med))
                  if np.isfinite(nb).any() else np.nan)
        n = float(np.sum(np.isfinite(nb)))
        srt = np.sort(nb)
        trim = (np.nanmean(srt[1:int(n) - 1])
                if 3 <= n <= k and int(n) - 1 > 1 else np.nan)
        near3 = np.nanmedian(nb[:3]) if np.isfinite(nb[:3]).any() else np.nan
        mean_km = np.nanmean(nb_dist[station])
        nb_elev = np.nanmean(np.where(np.isnan(nb_dist[station]), np.nan,
                                      d.elev[nb_idx[station]]))

    return np.array([
        nb_med, trim, nb_mad, n, near3, mean_km, nb_dist[station][0],
        math.sin(2 * math.pi * hod / 24), math.cos(2 * math.pi * hod / 24),
        math.sin(2 * math.pi * doy / 365.25), math.cos(2 * math.pi * doy / 365.25),
        d.elev[station], d.elev[station] - nb_elev,
    ], dtype=np.float64)[None, :]


FEATURE_NAMES = ["nb_median", "nb_trimmed_mean", "nb_spread", "nb_count",
                 "nb_median_near3", "nb_mean_km", "nearest_km",
                 "hour_sin", "hour_cos", "season_sin", "season_cos",
                 "elev_m", "elev_above_nb"]


def climatology_for(d: Data, ch: str, split: int) -> np.ndarray:
    """The training-window climatology a served row needs."""
    steps = np.arange(d.n_steps)
    hod = (steps * STEP_MIN // 60) % 24
    return climatology(d.vals[ch], hod, split)


def robust_sigma(r: np.ndarray) -> float:
    r = r[np.isfinite(r)]
    if r.size == 0:
        return float("nan")
    med = np.median(r)
    mad = np.median(np.abs(r - med))
    return float(1.4826 * mad)


def run(channels=("temp", "rh", "pres"), quiet=False) -> dict:
    import lightgbm as lgb

    d = load()
    nb_idx, nb_dist = neighbours(d)
    split = TRAIN_DAYS * PER_DAY
    report: dict = {"split_step": split, "train_days": TRAIN_DAYS,
                    "k": K, "channels": {}}

    OUT.mkdir(parents=True, exist_ok=True)

    for ch in channels:
        X, y, step, st, feat_names, anom = build_matrix(d, ch, nb_idx, nb_dist, split)
        tr = step < split
        te = ~tr
        ok = np.isfinite(y)

        model = lgb.LGBMRegressor(
            n_estimators=400, learning_rate=0.05, num_leaves=63,
            min_child_samples=50, subsample=0.8, subsample_freq=1,
            colsample_bytree=0.9, random_state=0, verbose=-1,
        )
        model.fit(X[tr & ok], y[tr & ok], feature_name=feat_names)

        pred = model.predict(X[te & ok])
        resid_model = y[te & ok] - pred

        # THE BASELINE, ON EXACTLY THE SAME ROWS.
        # The median of the same k neighbours -- what the pipeline uses today,
        # and now one of the model's own features, so the comparison is
        # "does the model improve on this" rather than "does it beat something
        # it never saw".
        med = X[:, feat_names.index("nb_median")]
        resid_med = y[te & ok] - med[te & ok]

        s_model = robust_sigma(resid_model)
        s_med = robust_sigma(resid_med)
        report["channels"][ch] = {
            "sigma_neighbour_median": round(s_med, 4),
            "sigma_learned": round(s_model, 4),
            "ratio": round(s_model / s_med, 4) if s_med else None,
            "mae_neighbour_median": round(float(np.nanmean(np.abs(resid_med))), 4),
            "mae_learned": round(float(np.nanmean(np.abs(resid_model))), 4),
            "rows_train": int((tr & ok).sum()),
            "rows_test": int((te & ok).sum()),
        }
        model.booster_.save_model(str(OUT / f"{ch}.txt"))

        if not quiet:
            print(f"{ch:5s}  neighbour median sigma {s_med:7.4f}"
                  f"   learned {s_model:7.4f}"
                  f"   ratio {s_model / s_med:5.3f}")

    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def explain(ch: str, X: "np.ndarray", feat_names: list[str],
            top: int = 6) -> list[dict]:
    """Per-feature contributions to each prediction, via TreeSHAP.

    Exact for a tree ensemble and linear in the tree size, which is the whole
    reason the model is a tree: the same question over an arbitrary model needs
    sampling, and an explanation that is itself an estimate is a poor answer to
    "why did you expect 24.1 degrees here".

    Contributions are in the target's units and sum to the prediction minus the
    model's base value, so a reader can check the arithmetic rather than take
    the ordering on trust -- the same efficiency property the panel's exact
    Shapley values have.
    """
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(OUT / f"{ch}.txt"))
    # LightGBM computes SHAP itself; the `shap` package is not needed to get
    # the values, only to draw them.
    contrib = booster.predict(X, pred_contrib=True)   # (rows, features + 1)
    base = contrib[:, -1]
    out = []
    for i in range(contrib.shape[0]):
        vals = contrib[i, :-1]
        order = np.argsort(-np.abs(vals))[:top]
        out.append({
            "base": float(base[i]),
            "prediction": float(base[i] + vals.sum()),
            "top": [{"feature": feat_names[j],
                     "value": float(X[i, j]),
                     "contribution": float(vals[j])} for j in order],
        })
    return out


def robustness(ch: str = "temp", victim: int | None = None) -> dict:
    """How much of ONE neighbour's fault leaks into a healthy station's answer.

    THIS EXPERIMENT DECIDED THE FEATURE SET, so it lives in the repository
    rather than in a notebook. The first version of this model took one column
    per neighbour and scored a much better sigma -- temp 0.269 against the
    median's 0.392. It was not deployable: corrupting the nearest neighbour
    moved the reference by 4.44 K, against 0.16 K for the median, so every
    healthy station beside a broken one would have alarmed.

    Two things this measurement had to get right before it said anything:

      * The fault must start AFTER the training window. Applied to the whole
        record it is invisible -- the per-station climatology absorbs a constant
        offset into that station's own normal, and the anomaly never moves
        (measured: 1.8e-15). That is also why a station that has always read
        high cannot be caught by differencing at all.
      * The summary must be the tail, not the median. A median of six is
        unmoved by one of them in three rows out of four, so the median shift
        is 0.000 for both references and the table reads as "nothing happens".
    """
    import lightgbm as lgb

    d = load()
    nb_idx, nb_dist = neighbours(d)
    split = TRAIN_DAYS * PER_DAY
    booster = lgb.Booster(model_file=str(OUT / f"{ch}.txt"))

    X0, y0, step, st, names, _ = build_matrix(d, ch, nb_idx, nb_dist, split)
    med_col = names.index("nb_median")
    sel = (step >= split) & np.isfinite(y0)

    if victim is None:
        victim = int(np.argmax(np.bincount(nb_idx.reshape(-1),
                                           minlength=d.n_st)))
    affected = np.where((nb_idx == victim).any(axis=1))[0]
    rows = np.isin(st, affected) & sel

    base_pred = booster.predict(X0[rows])
    base_med = X0[rows][:, med_col]

    faults = {
        "offset_3K": lambda a: a + 3.0,
        "offset_10K": lambda a: a + 10.0,
        "stuck": lambda a: np.full_like(a, a[0]),
        "spike_25K": lambda a: a + 25.0,
        "missing": lambda a: np.full_like(a, np.nan),
    }
    out = {"channel": ch, "victim": str(d.names[victim]),
           "neighbour_of": int(len(affected)), "rows": int(rows.sum()),
           "sigma_neighbour_median": round(robust_sigma(y0[sel] - X0[sel][:, med_col]), 4),
           "sigma_learned": round(robust_sigma(y0[sel] - booster.predict(X0[sel])), 4),
           "leak": {}}

    for label, fn in faults.items():
        d2 = load()
        col = d2.vals[ch][:, victim].copy()
        d2.vals[ch][split:, victim] = fn(col[split:])
        Xc, _, _, _, _, _ = build_matrix(d2, ch, nb_idx, nb_dist, split)
        dm = np.abs(Xc[rows][:, med_col] - base_med)
        dl = np.abs(booster.predict(Xc[rows]) - base_pred)
        out["leak"][label] = {
            "median_mean": round(float(np.nanmean(dm)), 4),
            "median_p95": round(float(np.nanpercentile(dm, 95)), 4),
            "learned_mean": round(float(np.nanmean(dl)), 4),
            "learned_p95": round(float(np.nanpercentile(dl, 95)), 4),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--channels", nargs="*",
                    default=["temp", "rh", "pres"])
    ap.add_argument("--robustness", action="store_true",
                    help="measure how much of one neighbour's fault leaks "
                         "into a healthy station's reference")
    args = ap.parse_args()

    if args.robustness:
        for ch in args.channels:
            r = robustness(ch)
            print(f"\n{ch}: breaking {r['victim']}, a neighbour of "
                  f"{r['neighbour_of']} stations")
            print(f"  sigma  median {r['sigma_neighbour_median']:.4f}"
                  f"   learned {r['sigma_learned']:.4f}")
            print(f"  {'fault':<12} {'median mean':>12} {'p95':>8}"
                  f" {'learned mean':>13} {'p95':>8}")
            for k, v in r["leak"].items():
                print(f"  {k:<12} {v['median_mean']:>12.3f}"
                      f" {v['median_p95']:>8.3f} {v['learned_mean']:>13.3f}"
                      f" {v['learned_p95']:>8.3f}")
        return

    rep = run(tuple(args.channels))
    print()
    print("A ratio below 1.00 means the learned reference is quieter than the")
    print("neighbour median, and drift detection time scales with it directly.")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
