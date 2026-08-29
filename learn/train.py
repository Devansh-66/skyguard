"""Train a fault classifier on ARM, and report what it is actually worth.

    python -m learn.train

WHAT IS BEING LEARNED

One row is (station, sensor, hour). The label is whether an ARM analyst named
that sensor's variable in a fault report covering that hour -- a human who went
out and looked, not a threshold. The features are in learn/features.py and are
all unitless, which is the only reason a model fitted in Oklahoma has any claim
on a station in Odisha.

THE SPLIT IS BY STATION, AND THIS IS THE WHOLE EXPERIMENT

With nine stations and a handful of long fault windows, a random split is
worthless: rows from the same fault land in train and test, and the model scores
beautifully by memorising the fault it has already seen. Grouping by station
asks the question that matters -- does this transfer to an instrument it has
never seen -- and that is the same question as "does this transfer to India",
one step smaller.

WHAT THE NUMBERS DO NOT MEAN

ARM reports what somebody noticed. An hour we call faulty that no report covers
may be a false alarm or may be a real fault nobody wrote up, so precision here
is a LOWER BOUND and recall is the number to trust. And the reference is each
station's own trailing window, which a fault longer than the window partly
absorbs -- so long faults are systematically harder than these figures suggest
rather than easier.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

warnings.filterwarnings("ignore")

from learn.features import FEATURES, assert_causal, row_features, to_vector

CACHE = Path("models/arm_dataset.npz")
MODEL = Path("models/fault_clf.joblib")
REPORT = Path("models/fault_clf_report.json")

# Which channels get a row. Housekeeping is a FEATURE, never a label: an analyst
# names logger_volt to explain a fault, and predicting the explanation from
# itself would be circular.
LABELLED = ("temp", "pres", "rh")

VAR_OF = {"temp": "temp_mean", "pres": "atmos_pressure", "rh": "rh_mean"}


def build_dataset() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Every held ARM window, turned into rows. Cached: it reads netCDF."""
    from api.ai import _dqr, _prepared

    dq = _dqr()
    X: list[list[float]] = []
    y: list[int] = []
    groups: list[str] = []
    meta: list[str] = []
    checked = 0

    pairs: list[tuple[str, str]] = []
    for _, r in dq.iterrows():
        ds = str(r["datastream"])
        st = ds.split(".")[0]
        pairs.append((st, str(r["dqr"])))

    seen: set[tuple[str, str]] = set()
    for st, dqr in pairs:
        if (st, dqr) in seen:
            continue
        seen.add((st, dqr))
        t0 = time.time()
        try:
            df, z, beliefs, r = _prepared(st, dqr)
        except Exception as e:
            print(f"  skip {st} {dqr}: {type(e).__name__}")
            continue

        named = str(r["variables"])
        n_rows = 0
        for k in LABELLED:
            if k not in df or k not in z:
                continue
            # The label is per SENSOR: a report naming rh_mean says nothing
            # about the thermometer, and labelling every channel of the station
            # faulty would teach the model that faults are station-wide.
            is_named = VAR_OF[k] in named
            for i in range(len(df)):
                f = row_features(df, z, beliefs, k, i)
                X.append(to_vector(f))
                y.append(1 if (is_named and bool(df.faulty[i])) else 0)
                groups.append(st)
                meta.append(f"{st}|{dqr}|{k}|{i}")
                n_rows += 1

            # Causality is checked on real rows, not asserted in a comment.
            if checked < 12 and len(df) > 30:
                assert_causal(df, z, beliefs, k, len(df) // 2)
                checked += 1

        print(f"  {st:12s} {dqr:12s} {n_rows:6d} rows  "
              f"({time.time() - t0:.1f}s)  named: {named[:44]}")

    Xa = np.asarray(X, dtype=float)
    ya = np.asarray(y, dtype=int)
    ga = np.asarray(groups, dtype=object)
    print(f"\n  causality verified on {checked} sampled rows")
    return Xa, ya, ga, meta


def load_dataset(rebuild: bool):
    if CACHE.exists() and not rebuild:
        d = np.load(CACHE, allow_pickle=True)
        print(f"dataset from {CACHE}")
        return d["X"], d["y"], d["groups"], list(d["meta"])
    print("building dataset from ARM netCDF (cached afterwards)")
    X, y, g, meta = build_dataset()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, X=X, y=y, groups=g, meta=np.asarray(meta, dtype=object))
    return X, y, g, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score, precision_recall_curve
    from sklearn.model_selection import LeaveOneGroupOut

    X, y, groups, _meta = load_dataset(args.rebuild)
    stations = sorted(set(groups.tolist()))
    base = float(y.mean())
    print(f"\nrows {len(y):,}   positives {int(y.sum()):,} ({base:.1%})   "
          f"stations {len(stations)}   features {len(FEATURES)}")
    print("station rows and base rate:")
    for st in stations:
        m = groups == st
        print(f"  {st:12s} {m.sum():6d} rows   {y[m].mean():6.1%} faulty")

    def new_model():
        return HistGradientBoostingClassifier(
            max_depth=4, max_iter=250, learning_rate=0.06,
            min_samples_leaf=60, l2_regularization=1.0,
            # The corpus is windows built around reports, so positives are not
            # rare -- but they are unevenly spread across stations, and a
            # station held out can shift the balance a long way.
            class_weight="balanced", random_state=0)

    # LEAVE ONE STATION OUT. Nine folds, each asking: trained on eight
    # instruments it has seen, what does it do on a ninth it has not?
    logo = LeaveOneGroupOut()
    rows = []
    oof = np.full(len(y), np.nan)
    for tr, te in logo.split(X, y, groups):
        st = groups[te][0]
        if y[te].sum() == 0 or y[tr].sum() == 0:
            print(f"  {st:12s} skipped: no positives on one side of the split")
            continue
        m = new_model().fit(X[tr], y[tr])
        p = m.predict_proba(X[te])[:, 1]
        oof[te] = p
        ap_ = average_precision_score(y[te], p)
        rows.append((st, int(y[te].sum()), len(te), ap_, float(y[te].mean())))

    print("\nleave-one-station-out, average precision against that station's base rate:")
    for st, pos, n, ap_, br in rows:
        lift = ap_ / br if br > 0 else float("nan")
        print(f"  {st:12s} n={n:6d}  positives={pos:5d}  AP={ap_:.3f}  "
              f"base={br:.3f}  lift={lift:.2f}x")

    ok = ~np.isnan(oof)
    overall_ap = average_precision_score(y[ok], oof[ok])
    overall_base = float(y[ok].mean())
    print(f"\npooled out-of-fold AP {overall_ap:.3f} against a base rate of "
          f"{overall_base:.3f}  ({overall_ap / overall_base:.2f}x)")

    # An operating point chosen for PRECISION, because the product dispatches a
    # technician: an alarm that is wrong half the time trains people to ignore
    # it, and a missed slow drift costs a data point rather than a van.
    prec, rec, thr = precision_recall_curve(y[ok], oof[ok])
    target = 0.80
    idx = np.where(prec[:-1] >= target)[0]
    if len(idx):
        j = idx[int(np.argmax(rec[:-1][idx]))]
        chosen = float(thr[j])
        print(f"at precision >= {target:.0%}: recall {rec[j]:.3f}, "
              f"threshold {chosen:.3f}")
    else:
        chosen = 0.5
        print(f"precision never reaches {target:.0%} out of fold; "
              f"threshold left at 0.5")

    # WOULD ONE NUMBER HAVE DONE?
    #
    # The question any reviewer should ask of a model on sixteen features: does
    # it beat just thresholding the most obvious one. Scoring each feature on
    # its own, pooled, against the same labels answers it before anyone has to
    # ask. If a single channel came close, the model would not be earning its
    # place and the honest thing would be to ship the threshold.
    print("\nwould one number have done? single-feature AP, pooled:")
    singles = []
    for name in ("bias_sigma", "abs_z", "z_max_24", "trust", "drift_sigma_day",
                 "hk_max_abs_z", "flat_frac_24", "gap_frac_24"):
        j = FEATURES.index(name)
        v = X[:, j]
        # Low trust is bad; for everything else large magnitude is bad.
        sc = -v if name == "trust" else np.abs(v)
        finite = np.isfinite(sc)
        if finite.sum() < 100:
            continue
        sc = np.where(finite, sc, np.nanmin(sc[finite]))
        a = average_precision_score(y, sc)
        singles.append({"feature": name, "average_precision": float(a),
                        "lift": float(a / base)})
        print(f"  {name:18s} AP={a:.3f}  lift={a / base:.2f}x")
    best = max(singles, key=lambda d: d["average_precision"]) if singles else None
    if best:
        print(f"  best single feature {best['feature']} at {best['lift']:.2f}x, "
              f"against the model's {overall_ap / overall_base:.2f}x out of fold")

    final = new_model().fit(X, y)
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    try:
        import joblib
        joblib.dump({"model": final, "features": list(FEATURES),
                     "threshold": chosen}, MODEL)
        print(f"\nwrote {MODEL}")
    except Exception as e:
        print(f"\ncould not save the model: {type(e).__name__}: {e}")

    imp = None
    try:
        from sklearn.inspection import permutation_importance
        sub = np.random.RandomState(0).choice(len(y), size=min(6000, len(y)),
                                              replace=False)
        pi = permutation_importance(final, X[sub], y[sub], n_repeats=3,
                                    random_state=0, scoring="average_precision")
        imp = sorted(zip(FEATURES, pi.importances_mean), key=lambda t: -t[1])
        print("\nwhat the model actually leans on:")
        for name, v in imp[:8]:
            print(f"  {name:18s} {v:+.4f}")
    except Exception as e:
        print(f"\npermutation importance unavailable: {type(e).__name__}")

    REPORT.write_text(json.dumps({
        "rows": int(len(y)), "positives": int(y.sum()), "base_rate": base,
        "stations": stations,
        "per_station": [{"station": s, "n": n, "positives": p,
                         "average_precision": a, "base_rate": b}
                        for s, p, n, a, b in rows],
        "pooled_average_precision": overall_ap,
        "pooled_base_rate": overall_base,
        "threshold": chosen,
        "single_feature_baselines": singles,
        "features": list(FEATURES),
        "importance": [{"feature": f, "value": float(v)} for f, v in (imp or [])],
        "caveats": [
            "Split is leave-one-station-out. A random split would score far "
            "higher and mean nothing: rows from the same fault would sit in "
            "both halves.",
            "Precision is a LOWER BOUND. ARM reports what somebody noticed, so "
            "an hour flagged outside a report may be a real fault nobody wrote "
            "up. Recall is the number to trust.",
            "The reference is each station's own trailing window, which a fault "
            "longer than that window partly absorbs. Long faults are harder "
            "than these figures suggest, not easier.",
            "This is a RANKING aid, not an alarm. At 80% precision the "
            "out-of-fold recall is under 1%, so it must not be wired to "
            "anything that dispatches a technician on its own. What it earns "
            "is a better ordering of the queue a person already reads.",
        ],
    }, indent=1), encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
