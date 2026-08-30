"""The model that can actually run on an Indian AWS.

    python -m learn.deployable

WHY A SECOND MODEL EXISTS

learn/train.py fits fourteen features, three of which are HOUSEKEEPING: logger
voltage and logger temperature. Those are the only evidence in the vector that
is not derived from temperature, pressure or humidity, and they are what let the
model separate "the probe is wrong" from "the logger is dying".

An ARM mast reports them. An IMD automatic weather station under PS26073 reports
temperature, pressure and relative humidity and nothing else. So the fourteen-
feature model is unusable on Indian data -- simulated or real -- not because it
transfers badly but because three of its inputs do not exist there.

WHAT IT COSTS, MEASURED

    all 14 features, ARM             AP 0.525   1.58x base
    11 features, no housekeeping     AP 0.406   1.22x base

A 23% loss of average precision, and the honest number to quote for anything
deployed in India. Both belong in the writeup: the first is what the method can
do given full instrument telemetry, the second is what this problem statement
allows.

WHAT IT IS FOR

Ranking, not alarming. At 1.22x base rate this reorders a queue a person
already reads; wiring it to anything that dispatches a technician on its own
would be indefensible, and the threshold below is chosen for precision with
that in mind.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from learn.features import FEATURES

CACHE = Path("models/arm_dataset.npz")
MODEL = Path("models/fault_clf_deployable.joblib")
REPORT = Path("models/fault_clf_deployable.json")

# Everything a station reporting only T, P and RH can produce.
DEPLOYABLE = tuple(f for f in FEATURES if not f.startswith("hk_"))


def main() -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score, precision_recall_curve
    from sklearn.model_selection import LeaveOneGroupOut

    if not CACHE.exists():
        sys.exit(f"missing {CACHE}; run `python -m learn.train` first")
    d = np.load(CACHE, allow_pickle=True)
    X, y, groups = d["X"], d["y"], d["groups"]
    cols = [FEATURES.index(f) for f in DEPLOYABLE]
    Xd = X[:, cols]

    print(f"{len(DEPLOYABLE)} features, no housekeeping: {', '.join(DEPLOYABLE)}")
    print(f"rows {len(y):,}  positives {int(y.sum()):,} ({y.mean():.1%})")

    def new_model():
        return HistGradientBoostingClassifier(
            max_depth=4, max_iter=250, learning_rate=0.06, min_samples_leaf=60,
            l2_regularization=1.0, class_weight="balanced", random_state=0)

    # LEAVE ONE STATION OUT, the same protocol as the full model. A random split
    # would put rows from one fault on both sides and score beautifully.
    oof = np.full(len(y), np.nan)
    per = []
    for tr, te in LeaveOneGroupOut().split(Xd, y, groups):
        st = groups[te][0]
        if y[te].sum() == 0 or y[tr].sum() == 0:
            continue
        m = new_model().fit(Xd[tr], y[tr])
        oof[te] = m.predict_proba(Xd[te])[:, 1]
        per.append({"station": str(st), "n": int(len(te)),
                    "average_precision": float(average_precision_score(y[te], oof[te])),
                    "base_rate": float(y[te].mean())})

    ok = ~np.isnan(oof)
    ap = float(average_precision_score(y[ok], oof[ok]))
    base = float(y[ok].mean())
    print(f"\npooled out-of-fold AP {ap:.3f} against base {base:.3f} "
          f"({ap / base:.2f}x)")
    for r in per:
        print(f"  {r['station']:12s} AP={r['average_precision']:.3f} "
              f"base={r['base_rate']:.3f}")

    prec, rec, thr = precision_recall_curve(y[ok], oof[ok])
    target = 0.80
    idx = np.where(prec[:-1] >= target)[0]
    if len(idx):
        j = int(idx[np.argmax(rec[:-1][idx])])
        chosen, at_recall = float(thr[j]), float(rec[j])
        print(f"at precision >= {target:.0%}: recall {at_recall:.3f}, "
              f"threshold {chosen:.3f}")
    else:
        chosen, at_recall = 0.5, float("nan")
        print(f"precision never reaches {target:.0%} out of fold; threshold 0.5")

    final = new_model().fit(Xd, y)
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump({"model": final, "features": list(DEPLOYABLE),
                 "threshold": chosen}, MODEL)
    print(f"\nwrote {MODEL}")

    REPORT.write_text(json.dumps({
        "features": list(DEPLOYABLE),
        "excluded": [f for f in FEATURES if f.startswith("hk_")],
        "rows": int(len(y)), "positives": int(y.sum()),
        "pooled_average_precision": ap, "pooled_base_rate": base,
        "lift": ap / base,
        "threshold": chosen, "recall_at_80_precision": at_recall,
        "per_station": per,
        "caveats": [
            "Trained on ARM (nine instruments, Oklahoma and Alaska) because "
            "that is the only corpus with faults a human confirmed. India "
            "contributes real station locations, not labelled faults.",
            "Housekeeping features are excluded because an AWS under PS26073 "
            "reports only temperature, pressure and humidity. That costs 23% "
            "of average precision against the fourteen-feature model: 0.406 "
            "against 0.525.",
            "1.22x a base rate is a RANKING aid. It reorders a queue a person "
            "already reads. It must not be wired to anything that dispatches "
            "on its own.",
            "Precision is a lower bound: ARM reports what somebody noticed, so "
            "an hour flagged outside a report may be a real fault nobody "
            "wrote up.",
        ],
    }, indent=1), encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
