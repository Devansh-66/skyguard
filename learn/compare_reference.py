"""Which model should be the reference? Measure, do not assume.

LightGBM was the first thing reached for, which is a reason to check it and
not a reason to keep it. Every candidate here gets the SAME features (the
robust neighbourhood statistics from reference_model.py), the SAME time split
(train on the first 20 days, score on the last 10) and is judged on the SAME
two things:

  1. sigma of the held-out residual -- lower is a better reference, and
     time-to-detect a drift scales with it directly;
  2. leak -- how far the reference moves for a HEALTHY station when one of its
     neighbours breaks after the training window. This is the test that
     disqualified the per-neighbour feature set (4.44 K against the median's
     0.16 K), and any model that scores a lovely sigma by leaning on one input
     fails it.

A model that wins on 1 and loses on 2 is not the better model. The median is
in the table as the floor every candidate has to clear.

    python -m learn.compare_reference             # temp, the hard channel
    python -m learn.compare_reference --all       # all three
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from learn.reference_model import (CLEAN, PER_DAY, TRAIN_DAYS, build_matrix,
                                   load, neighbours, robust_sigma)

OUT = Path("models/reference/comparison.json")


def candidates(seed: int = 0) -> dict:
    """Every model that is a plausible reference, at sensible defaults.

    Nothing is tuned. A comparison where one entrant was tuned and the others
    were not is a comparison of tuning effort, and the point here is the
    model family. Row counts are ~660k train, so anything quadratic is out.
    """
    from sklearn.ensemble import (ExtraTreesRegressor,
                                  HistGradientBoostingRegressor,
                                  RandomForestRegressor)
    from sklearn.linear_model import Ridge
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    import lightgbm as lgb
    import xgboost as xgb
    from catboost import CatBoostRegressor

    return {
        # The straight line. If a tree model cannot beat this, the features
        # are doing the work and the model is decoration.
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),

        "lightgbm": lgb.LGBMRegressor(
            n_estimators=400, learning_rate=0.05, num_leaves=63,
            min_child_samples=50, subsample=0.8, subsample_freq=1,
            colsample_bytree=0.9, random_state=seed, verbose=-1),

        "xgboost": xgb.XGBRegressor(
            n_estimators=400, learning_rate=0.05, max_depth=7,
            min_child_weight=50, subsample=0.8, colsample_bytree=0.9,
            random_state=seed, tree_method="hist", n_jobs=-1),

        "catboost": CatBoostRegressor(
            iterations=400, learning_rate=0.05, depth=7,
            random_seed=seed, verbose=0, thread_count=-1),

        "hist_gbr": HistGradientBoostingRegressor(
            max_iter=400, learning_rate=0.05, max_leaf_nodes=63,
            min_samples_leaf=50, random_state=seed),

        "extra_trees": ExtraTreesRegressor(
            n_estimators=200, min_samples_leaf=20, max_features=0.8,
            n_jobs=-1, random_state=seed),

        "random_forest": RandomForestRegressor(
            n_estimators=150, min_samples_leaf=20, max_features=0.8,
            n_jobs=-1, random_state=seed),

        # A small MLP, because "why not a neural network" will be asked.
        "mlp": make_pipeline(StandardScaler(), MLPRegressor(
            hidden_layer_sizes=(64, 32), max_iter=40, batch_size=2048,
            early_stopping=True, random_state=seed)),
    }


def _fit_predict(model, Xtr, ytr, Xte):
    """Train and predict, with NaN handled the way each library needs.

    Boosting libraries take NaN natively. sklearn's forests and Ridge do not,
    so NaN is imputed to the column median -- the same value a 'missing'
    neighbour would contribute in the served row builder.
    """
    name = type(model).__name__
    native_nan = name in ("LGBMRegressor", "XGBRegressor", "CatBoostRegressor",
                          "HistGradientBoostingRegressor")
    if not native_nan:
        med = np.nanmedian(Xtr, axis=0)
        Xtr = np.where(np.isnan(Xtr), med, Xtr)
        Xte = np.where(np.isnan(Xte), med, Xte)
    t0 = time.time()
    model.fit(Xtr, ytr)
    fit_s = time.time() - t0
    t0 = time.time()
    pred = model.predict(Xte)
    pred_s = time.time() - t0
    return pred, fit_s, pred_s, med if not native_nan else None


def leak(model, med, d, ch, nb_idx, nb_dist, split, X0, st, step, base_pred,
         victim: int) -> dict:
    """How far the reference moves for healthy stations when one neighbour
    breaks after the training window. Mean and p95 over the affected rows."""
    affected = np.where((nb_idx == victim).any(axis=1))[0]
    rows = np.isin(st, affected) & (step >= split)
    out = {}
    for label, fn in (("offset_10K", lambda a: a + 10.0),
                      ("stuck", lambda a: np.full_like(a, a[0]))):
        d2 = load(CLEAN)
        col = d2.vals[ch][:, victim].copy()
        d2.vals[ch][split:, victim] = fn(col[split:])
        Xc, _, _, _, _, _ = build_matrix(d2, ch, nb_idx, nb_dist, split)
        Xr = Xc[rows]
        if med is not None:
            Xr = np.where(np.isnan(Xr), med, Xr)
        dl = np.abs(model.predict(Xr) - base_pred[rows])
        out[label] = {"mean": round(float(np.nanmean(dl)), 4),
                      "p95": round(float(np.nanpercentile(dl, 95)), 4)}
    return out


def run(channels, seed=0) -> dict:
    d = load(CLEAN)
    nb_idx, nb_dist = neighbours(d)
    split = TRAIN_DAYS * PER_DAY
    victim = int(np.argmax(np.bincount(nb_idx.reshape(-1), minlength=d.n_st)))
    report = {"train_days": TRAIN_DAYS, "victim": str(d.names[victim]),
              "channels": {}}

    for ch in channels:
        X, y, step, st, names, _ = build_matrix(d, ch, nb_idx, nb_dist, split)
        ok = np.isfinite(y)
        tr, te = (step < split) & ok, (step >= split) & ok
        med_col = names.index("nb_median")

        rows = {}
        # the floor: the neighbour median, exactly as the pipeline uses it
        r_med = y[te] - X[te][:, med_col]
        rows["neighbour_median"] = {
            "sigma": round(robust_sigma(r_med), 4), "fit_s": 0.0, "pred_s": 0.0}
        # its leak, so the candidates have something to be compared against
        affected = np.where((nb_idx == victim).any(axis=1))[0]
        aff = np.isin(st, affected) & (step >= split)
        lk = {}
        for label, fn in (("offset_10K", lambda a: a + 10.0),
                          ("stuck", lambda a: np.full_like(a, a[0]))):
            d2 = load(CLEAN)
            col = d2.vals[ch][:, victim].copy()
            d2.vals[ch][split:, victim] = fn(col[split:])
            Xc, _, _, _, _, _ = build_matrix(d2, ch, nb_idx, nb_dist, split)
            dm = np.abs(Xc[aff][:, med_col] - X[aff][:, med_col])
            lk[label] = {"mean": round(float(np.nanmean(dm)), 4),
                         "p95": round(float(np.nanpercentile(dm, 95)), 4)}
        rows["neighbour_median"]["leak"] = lk

        for name, model in candidates(seed).items():
            print(f"  {ch}: {name} ...", end="", flush=True)
            pred, fit_s, pred_s, med = _fit_predict(model, X[tr], y[tr], X[te])
            sig = robust_sigma(y[te] - pred)
            # predictions for every test-window row, for the leak test
            Xall = X.copy()
            if med is not None:
                Xall = np.where(np.isnan(Xall), med, Xall)
            base_pred = np.full(X.shape[0], np.nan)
            base_pred[step >= split] = model.predict(Xall[step >= split])
            lk = leak(model, med, d, ch, nb_idx, nb_dist, split, X, st, step,
                      base_pred, victim)
            rows[name] = {"sigma": round(sig, 4), "fit_s": round(fit_s, 1),
                          "pred_s": round(pred_s, 2), "leak": lk}
            print(f" sigma {sig:.4f}  leak(offset10K p95) {lk['offset_10K']['p95']:.3f}"
                  f"  fit {fit_s:.0f}s")
        report["channels"][ch] = rows

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    chs = ("temp", "rh", "pres") if args.all else ("temp",)
    rep = run(chs)
    for ch, rows in rep["channels"].items():
        print(f"\n{ch}: broke {rep['victim']} after the training window")
        print(f"  {'model':<18} {'sigma':>7} {'ratio':>6}  {'leak mean':>9} {'leak p95':>8}  {'fit':>6}")
        base = rows["neighbour_median"]["sigma"]
        for name, r in sorted(rows.items(), key=lambda kv: kv[1]["sigma"]):
            lk = r["leak"]["offset_10K"]
            print(f"  {name:<18} {r['sigma']:>7.4f} {r['sigma']/base:>6.3f}  "
                  f"{lk['mean']:>9.3f} {lk['p95']:>8.3f}  {r['fit_s']:>5.0f}s")
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()
