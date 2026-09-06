"""Serve the learned reference and its TreeSHAP account of itself.

WHAT THIS ADDS THAT THE PANEL COULD NOT SAY

The panel's exact Shapley values answer *which agent decided*. Nothing in the
system could answer *why the expected reading was that number* -- the median of
six neighbours has no features to attribute to, so "because four other stations
said so" was the end of the explanation.

This endpoint answers it. The reference is a gradient-boosted model over robust
neighbourhood statistics and the clock, and TreeSHAP decomposes each prediction
into per-feature contributions that sum to it exactly. Two attributions at two
layers: Shapley for the verdict, TreeSHAP for the number the verdict was
computed from.

WHY IT SERVES ALONGSIDE THE MEDIAN RATHER THAN REPLACING IT

The detector in the shipped pipeline still differences against the neighbour
median. Swapping that term is a change to every measured number in the
project, and it is not made by an endpoint. So this returns BOTH references and
both residuals for the same reading, which is the comparison a reader needs in
order to believe the swap is worth making -- and which keeps the claim honest
while it is still a comparison rather than the decision path.

DEGRADES, DOES NOT BREAK

The model files and the simulated network are both optional at runtime. Where
either is missing the endpoint says so and the board simply does not draw the
section; nothing else changes.
"""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "reference"
CHANNELS = ("temp", "rh", "pres")

_lock = threading.Lock()
_state: dict = {"ready": None, "why": None}


def _load():
    """Everything needed for one prediction, loaded once and kept.

    The npz is ~10 MB and the three boosters ~2.3 MB each; loading them per
    request would put a second of latency on a panel that is otherwise
    instant.
    """
    with _lock:
        if _state["ready"] is not None:
            return _state
        try:
            import lightgbm as lgb
            import numpy as np

            from learn.reference_model import (CLEAN, FAULTED, PER_DAY,
                                               TRAIN_DAYS, climatology_for,
                                               load, neighbours)

            # THE MODEL IS TRAINED ON CLEAN DATA AND SERVED ON THE FAULTED
            # RECORD, AND MIXING THOSE UP IS A LIE ON THE SCREEN.
            #
            # The board's cases were raised on the faulted network -- that is
            # what the detector graded. Explaining the clean series for the same
            # station and step answers a question nobody asked and does it in
            # the flattering direction: the fault is simply absent from the
            # numbers, so the model looks like it predicted a reading it never
            # saw. Measured on BENGALURU pressure, the two series differ by up
            # to 14.6 hPa.
            #
            # So: geometry and the training split come from the clean file --
            # the faulted export carries no elevation -- and every VALUE served
            # is the faulted one. Training stays on clean, which is the point of
            # a reference: it is what a healthy region looks like.
            d = load(CLEAN)
            nb_idx, nb_dist = neighbours(d)
            split = TRAIN_DAYS * PER_DAY

            served = load(CLEAN)
            try:
                import numpy as _np
                zf = _np.load(FAULTED, allow_pickle=True)
                for _ch in CHANNELS:
                    served.vals[_ch] = _np.asarray(zf[_ch], dtype=_np.float64)
                _state["source"] = "faulted"
            except Exception:
                # No faulted export: serve the clean record and say so, rather
                # than silently answering about different data than the board.
                _state["source"] = "clean"
            d = served

            # ONE ROW PER REQUEST, NOT THE WHOLE MATRIX.
            #
            # build_matrix materialises every station at every step: 990,720
            # rows x 13 features x 8 bytes is ~103 MB per channel, over 300 MB
            # across three, before NumPy's temporaries -- a plausible way to be
            # killed by the OOM reaper on the first request to a panel. A
            # request needs one row, so only the climatologies are precomputed
            # (24 x 344 each) and the features are built per call.
            #
            # That leaves two implementations of one feature set, which is why
            # tests/test_reference_row.py asserts they agree exactly.
            boosters, clims = {}, {}
            for ch in CHANNELS:
                f = MODEL_DIR / f"{ch}.txt"
                if not f.exists():
                    raise FileNotFoundError(f"no model for {ch}")
                boosters[ch] = lgb.Booster(model_file=str(f))
                clims[ch] = climatology_for(d, ch, split)

            _state.update(ready=True, why=None, d=d, boosters=boosters,
                          clims=clims, nb_idx=nb_idx, nb_dist=nb_dist,
                          split=split, np=np,
                          names_by_index={str(n): i
                                          for i, n in enumerate(d.names)})
        except Exception as e:                       # noqa: BLE001
            _state.update(ready=False, why=f"{type(e).__name__}: {e}")
        return _state


@router.get("/api/reference/status")
def status() -> dict:
    """Whether the learned reference can answer at all, and on what."""
    s = _load()
    if not s["ready"]:
        return {"available": False, "reason": s["why"],
                "note": "The board omits the model section; nothing else "
                        "changes. Train with: python -m learn.reference_model"}
    import json
    rep = MODEL_DIR / "report.json"
    return {
        "available": True,
        # Which record the served readings come from. The board grades the
        # faulted one; anything else here would be explaining another dataset.
        "served_from": s.get("source"),
        "channels": list(CHANNELS),
        "stations": int(s["d"].n_st),
        "steps": int(s["d"].n_steps),
        "trained_on_steps": int(s["split"]),
        "report": json.loads(rep.read_text(encoding="utf-8")) if rep.exists() else None,
    }


@router.get("/api/reference/explain")
def explain(station: str = Query(..., description="station NAME as on the map"),
            channel: str = Query("temp"),
            step: int = Query(..., ge=0),
            top: int = Query(6, ge=1, le=13)) -> dict:
    """What the model expected here, and which features made it that number."""
    s = _load()
    if not s["ready"]:
        raise HTTPException(503, s["why"] or "reference model unavailable")
    if channel not in CHANNELS:
        raise HTTPException(400, f"channel must be one of {CHANNELS}")

    np = s["np"]
    idx = s["names_by_index"].get(station)
    if idx is None:
        raise HTTPException(404, f"no station named {station!r}")

    from learn.reference_model import FEATURE_NAMES, row_features

    d = s["d"]
    step = int(min(max(step, 0), d.n_steps - 1))
    X = row_features(d, channel, s["nb_idx"], s["nb_dist"],
                     s["clims"][channel], idx, step)
    names = FEATURE_NAMES
    booster = s["boosters"][channel]

    # LightGBM computes SHAP itself; the last column is the base value and the
    # rest sum with it to the prediction exactly.
    contrib = booster.predict(X, pred_contrib=True)[0]
    base, vals = float(contrib[-1]), contrib[:-1]
    pred = float(base + vals.sum())

    med = float(X[0, names.index("nb_median")])
    # The observed anomaly, against the same training-window climatology the
    # features were built from.
    hod = (step * 15 // 60) % 24
    obs = float(d.vals[channel][step, idx] - s["clims"][channel][hod, idx])
    obs = None if not np.isfinite(obs) else obs

    # RESIDUALS ALONE ARE THE WRONG COMPARISON, AND THEY FLATTER THE WRONG SIDE.
    #
    # A better reference leaves a SMALLER residual on a healthy station and a
    # smaller one on a faulty station too -- it tracks the weather more
    # tightly, not the fault. Read as raw numbers that looks like less signal.
    # What decides detection is the residual measured in the spread of
    # residuals, so both are also reported in sigma, each against its own.
    import json as _json
    rep = MODEL_DIR / "report.json"
    sig_m = sig_l = None
    if rep.exists():
        try:
            chs = _json.loads(rep.read_text(encoding="utf-8"))["channels"][channel]
            sig_m = chs["sigma_neighbour_median"]
            sig_l = chs["sigma_learned"]
        except Exception:
            pass

    def _z(resid, sigma):
        if resid is None or not sigma:
            return None
        return round(abs(resid) / sigma, 2)

    order = np.argsort(-np.abs(vals))[:top]
    return {
        "station": station,
        "channel": channel,
        "step": step,
        "observed_anomaly": None if obs is None else round(obs, 4),
        # The two references, side by side on the same reading.
        "learned": {"prediction": round(pred, 4),
                    "residual": None if obs is None else round(obs - pred, 4),
                    "sigma": sig_l,
                    "z": None if obs is None else _z(obs - pred, sig_l)},
        "neighbour_median": {"prediction": round(med, 4),
                             "residual": None if obs is None else round(obs - med, 4),
                             "sigma": sig_m,
                             "z": None if obs is None else _z(obs - med, sig_m)},
        "base_value": round(base, 4),
        "contributions": [
            {"feature": names[j], "value": round(float(X[0, j]), 4),
             "contribution": round(float(vals[j]), 4)}
            for j in order
        ],
        "note": "Contributions sum to the prediction exactly; TreeSHAP is "
                "exact for a tree ensemble rather than sampled.",
    }
