"""Serving the learned model, and being honest about what it is worth.

WHICH MODEL, AND WHY THERE ARE TWO

    fault_clf.joblib             14 features   AP 0.525   1.58x base
    fault_clf_deployable.joblib  11 features   AP 0.406   1.22x base

The difference is three HOUSEKEEPING features -- logger voltage and logger
temperature -- which an ARM mast reports and an IMD automatic weather station
under PS26073 does not. The fourteen-feature model is not merely worse on
Indian data, it is inapplicable: three of its inputs do not exist there.

So this serves the eleven-feature model by default. The other is kept for the
comparison, because "what the method could do with full instrument telemetry"
is a real number and so is the 23% it costs to give it up.

WHAT THIS ENDPOINT IS NOT

It is not an alarm. Out of fold, precision never reaches 80% at any useful
recall -- the recall there is 0.000. At 1.22x a base rate the model reorders a
queue a person already reads, and every response says so in the same breath as
the number. A score presented without that is a score that will be mistaken for
a verdict.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

_ROOT = Path(__file__).resolve().parent.parent
_MODELS = {
    "deployable": _ROOT / "models" / "fault_clf_deployable.joblib",
    "full": _ROOT / "models" / "fault_clf.joblib",
}
DEFAULT = os.environ.get("SKYGUARD_MODEL", "deployable")

CAVEAT = ("Ranking aid, not an alarm. Out of fold this model reaches 1.22x the "
          "base rate and never reaches 80% precision at usable recall. Use it "
          "to order a queue a person reads, never to dispatch on its own.")


@lru_cache(maxsize=4)
def _load(name: str):
    path = _MODELS.get(name)
    if path is None:
        raise HTTPException(404, f"unknown model {name!r}; "
                                 f"have {', '.join(sorted(_MODELS))}")
    if not path.exists():
        raise HTTPException(503, f"{path.name} has not been trained. Run: "
                                 f"python -m learn.deployable")
    import joblib
    return joblib.load(path)


@lru_cache(maxsize=4)
def _explainer(name: str):
    """TreeSHAP, built once. Exact for tree ensembles, so the contributions
    below are the model's actual decomposition and not a surrogate's guess."""
    import shap
    return shap.TreeExplainer(_load(name)["model"])


class Reading(BaseModel):
    """The feature vector for one (station, sensor, hour).

    Missing keys are NaN rather than zero, which is not a detail: this model is
    a HistGradientBoosting and treats NaN as "unknown" natively, while a zero is
    a confident claim that the feature is exactly average.
    """
    features: dict[str, float] = Field(..., description="feature name to value")
    model: str = Field(DEFAULT, description="deployable (T/P/RH only) or full")
    explain: bool = Field(True, description="include per-feature contributions")


@router.get("/api/model")
def describe() -> dict:
    """What is loaded, what it scores, and what it is not for."""
    import json
    out = []
    for name, path in sorted(_MODELS.items()):
        rep = path.with_suffix(".json")
        entry: dict = {"name": name, "available": path.exists()}
        if rep.exists():
            r = json.loads(rep.read_text(encoding="utf-8"))
            entry.update(features=r.get("features"),
                         average_precision=r.get("pooled_average_precision"),
                         base_rate=r.get("pooled_base_rate"),
                         lift=r.get("lift"), caveats=r.get("caveats"))
        elif path.exists():
            entry["features"] = _load(name)["features"]
        out.append(entry)
    return {"default": DEFAULT, "models": out, "caveat": CAVEAT,
            "why_two": "The 14-feature model uses logger voltage and logger "
                       "temperature. An AWS under PS26073 reports only "
                       "temperature, pressure and humidity, so those three "
                       "features cannot exist on Indian data at all."}


@router.post("/api/model/score")
def score(r: Reading) -> dict:
    bundle = _load(r.model)
    names: list[str] = bundle["features"]
    x = np.array([[float(r.features.get(f, np.nan)) for f in names]], dtype=float)

    missing = [f for f in names if f not in r.features]
    p = float(bundle["model"].predict_proba(x)[0, 1])

    out: dict = {
        "probability": p,
        "threshold": float(bundle["threshold"]),
        "above_threshold": p >= float(bundle["threshold"]),
        "model": r.model,
        "features_used": names,
        # Say which inputs were absent rather than letting a NaN pass as a
        # reading. A vector with half its features missing scores fine and
        # means nothing.
        "features_missing": missing,
        "caveat": CAVEAT,
    }
    if r.explain:
        try:
            sv = _explainer(r.model).shap_values(x)
            vals = np.asarray(sv[1] if isinstance(sv, list) else sv).reshape(-1)
            order = np.argsort(-np.abs(vals))
            out["contributions"] = [
                {"feature": names[i], "value": (None if np.isnan(x[0, i])
                                                else float(x[0, i])),
                 "shap": float(vals[i])}
                for i in order[:8]
            ]
        except Exception as e:                       # explanation is optional
            out["contributions_error"] = f"{type(e).__name__}: {e}"
    return out
