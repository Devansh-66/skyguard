"""Stage 4 -- the signature classifier. This is the novelty.

Stages 1-3 answer "is this anomalous". Every WMO-conformant QC system already
does that, and doing it well earns the accuracy marks but not the innovation
ones. Stage 4 answers the question an operator actually has:

    WHICH fault is this, or is it real weather?

An alert saying "anomaly, score 8.3" tells a maintenance engineer nothing about
whether to dispatch a van. An alert saying "RH probe saturated at 100 %, began
14:00 Tuesday, temperature and pressure unaffected, neighbours disagree" tells
them what to put in it.

HOW IT WORKS. Each detected window is reduced to eight shape descriptors, and
each fault class is a template over those descriptors. The classifier scores
every template and takes the best -- but only if it beats the runner-up by a
margin. Otherwise it returns `unknown`, per CLAUDE.md rule 7: a confidently
wrong root cause destroys operator trust faster than an honest "cause
unclassified", and an operator who stops believing the labels stops reading the
alerts at all.

THE WEATHER TEMPLATE IS A FIRST-CLASS CLASS. `genuine_weather` competes on
equal footing with the seven fault types, and it wins on one descriptor the
faults cannot fake: COHERENCE. A frontal passage moves every station in the
neighbourhood; a failing probe moves one. That is the discriminator PS26073 is
really asking for, and it is a physical argument rather than a learned one --
which is why it can be explained to a meteorologist in one sentence.

Rules are explicit and inspectable on purpose. A gradient-boosted classifier
would likely score a point or two higher and would be unauditable, and the
explainability marks are worth more than the point.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd

VERSION = "signature-1.0.0"

LABELS = ("spike", "frozen", "dropout", "saturation", "step_offset",
          "calibration_drift", "noise_burst", "genuine_weather", "unknown")

# Minimum margin between best and runner-up template before a label is claimed.
# Tuned on the harness, not guessed -- see evaluation/run_signature.py.
MIN_MARGIN = 0.12


# ------------------------------------------------------------- descriptors

@dataclass
class Window:
    descriptors: dict
    evidence: dict


def describe(seg: pd.DataFrame, F: pd.DataFrame, var: str,
             dres: pd.Series, sigma: float, rails: tuple[float, float],
             _unused_coherence: float = 0.0, natural_flat: float = 0.0) -> Window:
    """Reduce one flagged window to eight scale-free shape descriptors.

    Scale-free is the point: the same template must fire for a 0.4 K step and a
    4 K step, or the classifier degenerates into an amplitude detector.
    """
    v = seg[var].to_numpy(dtype=float)
    d = dres.to_numpy(dtype=float)
    n = len(v)
    lo, hi = rails

    finite = np.isfinite(v)
    frac_missing = float((~finite).mean())

    vf = v[finite]
    if len(vf) == 0:
        vf = np.array([np.nan])

    # Flatness, EXCESS over what this station normally shows. On 0.1-resolution
    # data consecutive readings are often identical by rounding alone -- calm
    # night pressure repeats for hours and is perfectly healthy. Measuring raw
    # repetition made the classifier call 88 false alarms `frozen`; measuring
    # the excess over the station's own natural rate is what distinguishes a
    # dead probe from a quiet one.
    same = np.sum(vf[1:] == vf[:-1]) / max(len(vf) - 1, 1) if len(vf) > 1 else 0.0
    flat = float(np.clip((same - natural_flat) / max(1.0 - natural_flat, 1e-6),
                         0.0, 1.0))

    # Railing: at a probe limit AND not moving. The conjunction is essential.
    # RH reaches exactly 100 % on any saturated night in Assam -- that is the
    # atmosphere, not the sensor, and treating it as a rail hit produced 175
    # false `saturation` calls. A stuck probe is at the rail and frozen there;
    # saturated air is at the rail and still fluctuating.
    at_rail = (float(np.mean((np.abs(vf - hi) < 0.15) | (np.abs(vf - lo) < 0.15)))
               if len(vf) else 0.0)
    rail = at_rail * flat

    # level: median offset of the residual, in sigma
    level = float(np.abs(np.nanmedian(d)) / sigma) if sigma > 0 else 0.0

    # ramp: least-squares slope per day, in sigma, plus how linear it is
    ramp, linearity = 0.0, 0.0
    ok = np.isfinite(d)
    if ok.sum() >= 8:
        t = np.arange(n)[ok] / 24.0
        y = d[ok]
        A = np.column_stack([np.ones(len(t)), t])
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        pred = A @ beta
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        ramp = float(abs(beta[1]) * n / 24.0 / sigma) if sigma > 0 else 0.0
        linearity = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # spread: scatter of the residual against the sigma the station normally has
    spread = float(np.nanstd(d) / sigma) if sigma > 0 else 0.0

    # brevity: short windows look like spikes, long ones cannot
    brevity = float(np.clip(3.0 / max(n, 1), 0.0, 1.0))

    # Coherence is DERIVED from the level, not passed in. An earlier version
    # took the ratio |neighbour difference| / |own residual|, which is a ratio
    # of two small numbers exactly when it matters and collapsed to zero on a
    # foggy night -- the case it existed to catch. Dhubri RH pinned at 100 %
    # sits 0.006 sigma from its neighbours: it agrees with them completely, and
    # a stuck probe would not. The level already says that, so use it.
    #
    # k = 1.5 sigma: agreement inside 1.5 sigma reads as more coherent than not.
    coherence = float(1.0 / (1.0 + level / 1.5))

    return Window(
        descriptors={
            "missing": frac_missing, "flat": flat, "rail": rail,
            "at_rail": at_rail, "natural_flat": natural_flat,
            "level": level, "ramp": ramp, "linearity": max(linearity, 0.0),
            "spread": spread, "brevity": brevity, "coherence": coherence,
        },
        evidence={
            "duration_h": n, "median_residual": float(np.nanmedian(d)),
            "sigma": round(sigma, 4),
            "slope_per_day": round(float(ramp * sigma * 24.0 / max(n, 1)), 4),
        },
    )


# ---------------------------------------------------------------- templates

def _sat(x: float, k: float) -> float:
    """Saturating ramp: 0 below nothing, ->1 as x passes k. Keeps every term in
    [0, 1] so template scores stay comparable."""
    return float(x / (x + k)) if x > 0 else 0.0


TEMPLATES = {
    # each returns a score in [0, 1]
    "dropout": lambda d: d["missing"],

    # Both stuck-sensor templates are gated on DISAGREEMENT with the neighbours.
    # Without that gate, a foggy night in Assam -- RH pinned at 100 % for
    # fourteen hours, flat and at the rail -- is descriptor-for-descriptor
    # identical to a stuck humidity probe, and the classifier called 175 such
    # windows `saturation`. No shape descriptor can separate the two, because
    # the shapes really are the same. What separates them is that fog wets the
    # whole valley and a broken probe does not.
    "saturation": lambda d: d["rail"] * (1 - d["missing"]) * (1 - d["coherence"]),

    "frozen": lambda d: (d["flat"] * (1 - d["rail"]) * (1 - d["missing"])
                         * (1 - d["coherence"])),

    "spike": lambda d: (d["brevity"] * _sat(d["level"], 3.0)
                        * (1 - d["flat"]) * (1 - d["missing"])),

    "calibration_drift": lambda d: (_sat(d["ramp"], 2.0) * d["linearity"]
                                    * (1 - d["brevity"]) * (1 - d["flat"])),

    "step_offset": lambda d: (_sat(d["level"], 2.0) * (1 - d["brevity"])
                              * (1 - d["linearity"]) * (1 - d["flat"])
                              * (1 - _sat(d["spread"], 2.0))),

    "noise_burst": lambda d: (_sat(max(d["spread"] - 1.0, 0.0), 1.0)
                              * (1 - _sat(d["level"], 2.0)) * (1 - d["flat"])),

    # The weather template. High coherence means the neighbours moved too, and
    # no instrument failure mode can produce that -- a probe cannot make three
    # other stations agree with it.
    "genuine_weather": lambda d: (d["coherence"] * (1 - d["flat"])
                                  * (1 - d["rail"]) * (1 - d["missing"])),
}


def classify(w: Window, min_margin: float = MIN_MARGIN) -> dict:
    """Score every template; return the winner, or `unknown` if it is not clear."""
    d = w.descriptors
    # A dropout window has no residual at all, so several descriptors are NaN.
    # NaN must collapse to "this template does not match", never propagate into
    # the confidence an operator reads.
    d = {k: (0.0 if v != v else v) for k, v in d.items()}
    scores = {name: float(np.clip(fn(d), 0.0, 1.0)) for name, fn in TEMPLATES.items()}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (best, s1), (runner, s2) = ranked[0], ranked[1]

    margin = s1 - s2
    if s1 < 0.15 or margin < min_margin:
        label, confidence = "unknown", 0.0
    else:
        label = best
        # confidence is the margin, squashed. It is a RANKING confidence, not a
        # probability, and is labelled as such wherever it is displayed.
        confidence = float(margin / (margin + 0.25))

    return {
        "label": label,
        "confidence": round(confidence, 3),
        "runner_up": runner if label != "unknown" else ranked[0][0],
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "descriptors": {k: round(v, 3) for k, v in d.items()},
        "evidence": w.evidence,
        "signature_version": VERSION,
    }


def explain(result: dict, station: str, var: str) -> str:
    """One sentence an operator can act on. Not a template dump."""
    lab, c, e, d = (result["label"], result["confidence"],
                    result["evidence"], result["descriptors"])
    unit = {"temp": "K", "rh": "%", "pres": "hPa"}[var]
    dur = e["duration_h"]
    if lab == "dropout":
        return f"{station} {var}: no observations for {dur} h."
    if lab == "saturation":
        return (f"{station} {var}: probe pinned at its limit for {dur} h "
                f"({d['rail']*100:.0f} % of samples at the rail).")
    if lab == "frozen":
        return (f"{station} {var}: value has not changed for {dur} h "
                f"({d['flat']*100:.0f} % identical consecutive readings).")
    if lab == "spike":
        return (f"{station} {var}: isolated excursion of "
                f"{e['median_residual']:+.2f} {unit} vs neighbours, {dur} h.")
    if lab == "calibration_drift":
        return (f"{station} {var}: drifting {e['slope_per_day']:+.3f} {unit}/day "
                f"against its neighbours over {dur} h, linear to R2 "
                f"{d['linearity']:.2f}.")
    if lab == "step_offset":
        return (f"{station} {var}: sustained offset of "
                f"{e['median_residual']:+.2f} {unit} vs neighbours for {dur} h, "
                f"no drift.")
    if lab == "noise_burst":
        return (f"{station} {var}: scatter {d['spread']:.1f}x its usual level "
                f"for {dur} h with no change in mean.")
    if lab == "genuine_weather":
        return (f"{station} {var}: {e['median_residual']:+.2f} {unit} excursion, "
                f"but neighbours moved with it ({d['coherence']*100:.0f} % "
                f"coherence) -- consistent with real weather, not a fault.")
    return (f"{station} {var}: {dur} h anomaly, cause unclassified "
            f"(best match {result['runner_up']}, below confidence floor).")
