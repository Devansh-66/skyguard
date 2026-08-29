"""SHAP explanations for the fault classifier, global and per-alert.

    python -m learn.explain

WHY THIS IS NOT DECORATION

The problem statement asks for "confidence scores and explainable AI-based
reasoning" and names SHAP/LIME under suggested technologies. But the reason to
want it here is narrower than the marking scheme: this product tells someone to
drive to a mast. "The model says 0.83" is not a reason to send a van. "This is
flagged because the logger temperature moved with the reading, and the drift has
been growing for eleven days" is.

WHY SHAP AND NOT LIME

The model is a gradient-boosted tree ensemble, and TreeSHAP computes exact
Shapley values for tree ensembles in polynomial time -- no sampling, no
surrogate model, no randomness between runs. LIME would fit a local linear
surrogate around each point and give a different answer on each call for the
same input, which is a poor property for something an operator may be asked to
justify later. For a tree model the exact method exists, so use it.

WHAT SHAP VALUES MEAN, STATED PLAINLY BECAUSE IT IS EASY TO OVERCLAIM

A SHAP value is that feature's contribution to THIS prediction relative to the
dataset's average prediction, in log-odds. It is an attribution, not a cause: it
says the model leaned on this feature here, not that the sensor failed because
of it. The distinction matters when the reasoning is shown to an engineer who
will act on it, so the wording in the output keeps it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MODEL = Path("models/fault_clf.joblib")
DATA = Path("models/arm_dataset.npz")
OUT = Path("models/shap_summary.json")

# What each feature is, in words an operator can use. The point of an
# explanation is lost if it explains in variable names.
PLAIN = {
    "z": "how far the reading sits from its own recent normal",
    "abs_z": "size of that departure, ignoring direction",
    "z_d1": "how fast the departure moved in the last hour",
    "z_d6": "how fast the departure moved over six hours",
    "z_max_24": "worst departure in the last day",
    "z_mean_24": "average departure over the last day",
    "bias_sigma": "estimated offset of the sensor, in its own noise units",
    "drift_sigma_day": "how fast that offset is growing per day",
    "trust": "share of recent consistency checks this sensor passed",
    "flat_frac_24": "how much of the last day the value did not change at all",
    "gap_frac_24": "how much of the last day the sensor failed to report",
    "rail_near": "how close the reading is to the instrument's physical limit",
    "hk_volt_z": "how far the logger supply voltage has moved",
    "hk_ltemp_z": "how far the logger board temperature has moved",
    "hk_max_abs_z": "the larger of the two housekeeping departures",
}


def sentence(name: str, value: float, shap: float) -> str:
    """One clause of the reason a row was flagged."""
    word = PLAIN.get(name, name)
    direction = "raises" if shap > 0 else "lowers"
    v = "missing" if not np.isfinite(value) else f"{value:.2f}"
    return f"{word} ({v}) {direction} the score by {abs(shap):.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=4)
    args = ap.parse_args()

    import joblib
    import shap
    from learn.features import FEATURES

    if not MODEL.exists() or not DATA.exists():
        raise SystemExit("run `python -m learn.train` first")
    bundle = joblib.load(MODEL)
    model, feats = bundle["model"], bundle["features"]
    if list(feats) != list(FEATURES):
        raise SystemExit("saved feature order differs from learn.features; retrain")

    d = np.load(DATA, allow_pickle=True)
    X, y, groups = d["X"], d["y"], d["groups"]

    # TreeSHAP is exact but not free: a background sample keeps it to seconds
    # rather than minutes, and the ranking is stable well before the full set.
    rng = np.random.default_rng(0)
    sub = rng.choice(len(y), size=min(4000, len(y)), replace=False)
    expl = shap.TreeExplainer(model)
    sv = expl.shap_values(X[sub])
    # Newer SHAP returns (n, features, classes) for binary classifiers; older
    # returns a list of two arrays. Both mean the same thing and both appear in
    # the wild, so handle each rather than pinning a version.
    if isinstance(sv, list):
        sv = sv[1]
    elif sv.ndim == 3:
        sv = sv[:, :, 1]

    mean_abs = np.abs(sv).mean(axis=0)
    order = np.argsort(-mean_abs)

    print(f"rows explained: {len(sub):,}   features: {len(FEATURES)}")
    print("\nGLOBAL: mean |SHAP|, the model's reliance on each feature")
    for i in order:
        bar = "#" * int(round(mean_abs[i] / max(mean_abs.max(), 1e-9) * 34))
        print(f"  {FEATURES[i]:17s} {mean_abs[i]:7.4f}  {bar}")

    # A signed view too: does a feature push toward "faulty" or away from it?
    # Mean |SHAP| alone cannot tell a strong detector from a strong exonerator.
    print("\nDIRECTION: correlation between the feature and its own SHAP value")
    print("  positive means larger values push the score toward FAULT")
    for i in order[:8]:
        col, s = X[sub, i], sv[:, i]
        m = np.isfinite(col)
        r = (np.corrcoef(col[m], s[m])[0, 1] if m.sum() > 30 else np.nan)
        print(f"  {FEATURES[i]:17s} {r:+.3f}")

    # Worked examples: the highest-scoring rows, explained the way the product
    # would have to explain them to the person being sent out.
    # ONE ROW PER STATION. Consecutive hours inside the same fault window score
    # almost identically and explain identically, so taking the top N by score
    # returned the same station four times with the same three clauses. An
    # explanation that repeats itself demonstrates nothing.
    p = model.predict_proba(X[sub])[:, 1]
    seen, top = set(), []
    for t in np.argsort(-p):
        st = str(groups[sub][t])
        if st in seen:
            continue
        seen.add(st)
        top.append(t)
        if len(top) >= args.examples:
            break
    print(f"\nWORKED EXAMPLES: the {args.examples} highest-scoring rows")
    examples = []
    for t in top:
        row, contrib = X[sub][t], sv[t]
        k = np.argsort(-np.abs(contrib))[:3]
        reasons = [sentence(FEATURES[j], row[j], contrib[j]) for j in k]
        print(f"\n  score {p[t]:.3f}   station {groups[sub][t]}   "
              f"actually faulty: {'yes' if y[sub][t] else 'no'}")
        for r in reasons:
            print(f"    - {r}")
        examples.append({"score": float(p[t]), "station": str(groups[sub][t]),
                         "labelled_faulty": bool(y[sub][t]), "reasons": reasons})

    OUT.write_text(json.dumps({
        "method": "TreeSHAP (exact for tree ensembles)",
        "rows_explained": int(len(sub)),
        "global_mean_abs_shap": [
            {"feature": FEATURES[i], "mean_abs_shap": float(mean_abs[i])}
            for i in order],
        "examples": examples,
        "caveat": ("A SHAP value is that feature's contribution to THIS "
                   "prediction relative to the dataset average, in log-odds. It "
                   "is an attribution, not a cause: it says the model leaned on "
                   "this feature here, not that the sensor failed because of "
                   "it."),
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
