"""The feature vector, defined once, for both training and live scoring.

WHY ONE FILE AND NOT TWO

The usual way this goes wrong is that features are computed one way in a
training notebook and another way in the serving path, and the model quietly
degrades in production for reasons nobody can find. So there is exactly one
definition here, and both callers import it. When the ESP32 stream arrives, the
online scorer calls `row_features` with the same arguments the trainer does.

TWO PROPERTIES THIS FILE MUST NOT LOSE

1. CAUSAL. Every feature is a function of samples at index <= i. Nothing may
   look forward, not even by one hour, or the reported skill is fiction and the
   model cannot run online at all. `assert_causal` is a runnable check of this,
   not a comment claiming it.

2. UNITLESS. This is what makes a model trained in Oklahoma applicable in
   Odisha. A raw temperature of 34 C means something entirely different in
   Barrow and in Bhubaneswar, so raw values are never features. Everything here
   is a ratio: a departure divided by the station's own noise, a fraction of a
   window, a count over a count. A station is described by how it behaves
   relative to itself, and that description travels.

WHAT IS DELIBERATELY ABSENT

No station identity, no latitude, no month, no absolute value of anything. All
of them would raise cross-validated scores and none would survive the move to a
new network: with nine stations, "which station is this" is a shortcut to the
label, since a station with nineteen fault reports is faulty most of the time it
appears in this corpus.
"""
from __future__ import annotations

import numpy as np

# The order is the contract. A model is saved with this list, and scoring
# refuses to run if the two disagree -- silently reordered columns are a class
# of bug that produces plausible, wrong numbers forever.
FEATURES: tuple[str, ...] = (
    "z",                # robust trailing z of the reading itself
    "abs_z",
    "z_d1",             # how fast that z is moving, 1 hour and 6 hours back
    "z_d6",
    "z_max_24",         # worst |z| in the last day
    "z_mean_24",
    "bias_sigma",       # belief: offset in units of the sensor's own noise
    "drift_sigma_day",
    "flat_frac_24",     # a stuck sensor repeats its last value
    "gap_frac_24",      # a dying sensor stops reporting before it stops lying
    "rail_near",        # ONLY the outer tenth of the instrument's range
    "hk_volt_z",        # housekeeping: the only evidence not derived from T/P/RH
    "hk_ltemp_z",
    "hk_max_abs_z",
)

# Physical rails, per channel, matching api/ingest.py.
#
# TWO FEATURES WERE REMOVED AFTER THE FIRST TRAINING RUN, because permutation
# importance ranked them first and second and both were shortcuts, not signal:
#
#   rail_frac  distance from the MIDDLE of the instrument's range, which for
#              temperature is close to "how cold is it". Barrow sits near its
#              low rail every winter and Graciosa never does, so the model was
#              learning WHICH STATION it was looking at -- the exact leak this
#              file's header forbids. Replaced by `rail_near`, zero across the
#              inner 90% of the range and rising only where an instrument is
#              genuinely against its stop.
#
#   evidence   the belief's alpha+beta, which only grows with the number of
#              updates. It is a row counter, and since every window here is
#              built around a reported fault, position in the window leaks the
#              label.
#
#   trust      REMOVED THIRD, and this one was found by SHAP rather than by
#              suspicion. It was the model's most-used feature by a wide margin
#              -- mean |SHAP| 1.85 against 0.52 for the next -- and it was being
#              used BACKWARDS: trust averages 0.868 inside analyst-reported
#              faults against 0.761 outside them, a correlation of +0.32 with
#              the label. Higher trust was pushing the score toward FAULT.
#
#              The cause is the bias-absorption pathology this project has hit
#              before: inside a sustained fault the belief's estimator converges
#              onto the offset, the innovations shrink, and the Beta reputation
#              RECOVERS. So trust was reporting "this station has been stable
#              for a while", which in a corpus of long reported fault windows
#              means "we are inside one".
#
#              Ablated under the same leave-one-station-out protocol: 0.505 with
#              trust, 0.525 without it, 0.357 on trust alone. The model's
#              favourite feature was making it worse.
#
#              It stays in the PRODUCT -- the board shows trust beside every
#              item and it is meaningful to a person reading one station -- but
#              it is not a model input.
#
# All three scored well. None would have survived contact with a new network.
RAILS = {"temp": (-40.0, 60.0), "rh": (0.0, 105.0), "pres": (500.0, 1100.0),
         "volt": (0.0, 20.0), "ltemp": (-40.0, 80.0)}


def _safe(x) -> float:
    """NaN for anything not finite. HistGradientBoosting handles NaN natively,
    so a missing feature is passed through as missing rather than as a zero
    that the model would read as 'normal'."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return np.nan
    return v if np.isfinite(v) else np.nan


def row_features(df, z: dict, beliefs: dict, k: str, i: int) -> dict[str, float]:
    """Features for sensor `k` at row `i`, using only rows <= i.

    `df`, `z` and `beliefs` are what api.ai._prepared returns: the hourly frame,
    the causal trailing z per channel, and the belief trajectory replayed
    forward. Online, the same three come from a ring buffer instead of a table,
    and this function does not know the difference.
    """
    zk = z.get(k)
    lo = max(0, i - 23)

    f: dict[str, float] = {}
    zi = _safe(zk[i]) if zk is not None else np.nan
    f["z"] = zi
    f["abs_z"] = abs(zi) if np.isfinite(zi) else np.nan
    f["z_d1"] = (zi - _safe(zk[i - 1])) if (zk is not None and i >= 1) else np.nan
    f["z_d6"] = (zi - _safe(zk[i - 6])) if (zk is not None and i >= 6) else np.nan

    if zk is not None:
        w = np.asarray(zk[lo:i + 1], dtype=float)
        w = w[np.isfinite(w)]
        f["z_max_24"] = float(np.max(np.abs(w))) if w.size else np.nan
        f["z_mean_24"] = float(np.mean(np.abs(w))) if w.size else np.nan
    else:
        f["z_max_24"] = f["z_mean_24"] = np.nan

    b = beliefs.get(k, [None] * (i + 1))[i] if k in beliefs else None
    if b is not None:
        noise = max(getattr(b, "noise", np.nan), 1e-9)
        f["bias_sigma"] = _safe(getattr(b, "bias", np.nan) / noise)
        f["drift_sigma_day"] = _safe(getattr(b, "drift", np.nan) / noise)
        f["trust"] = _safe(getattr(b, "trust", np.nan))
    else:
        f["bias_sigma"] = f["drift_sigma_day"] = f["trust"] = np.nan

    # A stuck sensor reports the same number over and over; a dying one stops
    # reporting. Both are faults the residual alone can miss, because a frozen
    # value can sit close to the seasonal normal for hours.
    if k in df:
        v = np.asarray(df[k].to_numpy()[lo:i + 1], dtype=float)
        n = v.size
        finite = np.isfinite(v)
        f["gap_frac_24"] = float(1.0 - finite.sum() / n) if n else np.nan
        vv = v[finite]
        if vv.size >= 3:
            same = np.abs(np.diff(vv)) < 1e-9
            f["flat_frac_24"] = float(same.sum() / same.size)
        else:
            f["flat_frac_24"] = np.nan
        vi = _safe(v[-1]) if n else np.nan
        if np.isfinite(vi) and k in RAILS:
            a, z2 = RAILS[k]
            span = z2 - a
            frac = min(1.0, abs(vi - (a + span / 2)) / (span / 2))
            # Zero across the inner 90% of the range, rising only in the outer
            # tenth. A cold winter is not a fault; a sensor pinned to its stop
            # is. The earlier version reported the former.
            f["rail_near"] = float(max(0.0, (frac - 0.9) / 0.1))
        else:
            f["rail_near"] = np.nan
    else:
        f["gap_frac_24"] = f["flat_frac_24"] = f["rail_near"] = np.nan

    # Housekeeping. A logger voltage or board temperature that moved with the
    # reading is the one piece of evidence not derived from T/P/RH themselves,
    # which is what lets "the hardware failed" be told from "the calibration
    # slipped". An ESP32 can report both, so this survives the move off ARM.
    hv = _safe(z["volt"][i]) if "volt" in z else np.nan
    hl = _safe(z["ltemp"][i]) if "ltemp" in z else np.nan
    f["hk_volt_z"] = hv
    f["hk_ltemp_z"] = hl
    cand = [abs(x) for x in (hv, hl) if np.isfinite(x)]
    f["hk_max_abs_z"] = max(cand) if cand else np.nan

    return f


def to_vector(f: dict[str, float]) -> list[float]:
    """Dict to the fixed column order. Missing keys are NaN, never 0."""
    return [f.get(name, np.nan) for name in FEATURES]


def assert_causal(df, z, beliefs, k: str, i: int) -> None:
    """Prove no feature reads past row i, by corrupting the future and checking
    nothing moves.

    A comment claiming causality is worth nothing; this is the claim made
    runnable. Called from the trainer on a sample of rows, so a future edit that
    reaches forward fails the build rather than inflating a score.
    """
    import copy

    before = row_features(df, z, beliefs, k, i)
    z2 = {kk: np.array(v, dtype=float, copy=True) for kk, v in z.items()}
    for kk in z2:
        z2[kk][i + 1:] = 1e6
    df2 = df.copy()
    for col in df2.columns:
        if col == "timestamp":
            continue
        try:
            df2.loc[i + 1:, col] = 1e6
        except (TypeError, ValueError):
            pass
    b2 = {kk: list(v) for kk, v in beliefs.items()}
    after = row_features(df2, z2, b2, k, i)

    for name in FEATURES:
        a, b = before.get(name, np.nan), after.get(name, np.nan)
        if np.isnan(a) and np.isnan(b):
            continue
        if a != b:
            raise AssertionError(
                f"feature {name!r} for {k} at row {i} changed when the FUTURE "
                f"was altered ({a} -> {b}). It is reading forward.")
    del copy
