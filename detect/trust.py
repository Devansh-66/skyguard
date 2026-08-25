"""A network that holds a belief about its own stations, and reroutes around the sick ones.

    from detect.trust import trust_weighted_difference

WHAT THIS IS FOR

PS26073's grand challenge asks whether AI can build a "self-aware and self-healing
weather observation network". Those words have to cash out as code or they are
decoration. Here is the cash:

    self-aware     every station carries a TRUST value per variable, updated from
                   evidence, that says how much the network currently believes
                   its readings
    self-healing   a station that loses trust is automatically demoted as a
                   REFERENCE for its neighbours, with no human in the loop, and
                   is promoted back when it starts agreeing again

THE PROBLEM IT SOLVES

The neighbour difference is the strongest channel in this system, and until now it
was `wide[neighbours].median(axis=1)` -- every neighbour counted equally no matter
how sick it was. So a station with a broken thermometer went on polluting the
reference that its neighbours were being judged against. One fault degraded the
whole neighbourhood, and the more it drifted the more it corrupted the yardstick
used to catch it.

Trust weighting closes that loop. The reference becomes a weighted combination in
which a distrusted neighbour barely contributes.

THE LOOP, AND WHY IT NEEDS DAMPING

Trust depends on the residual; the residual depends on the reference; the
reference depends on trust. That is a fixed point, and it is solved by iteration
rather than in one pass. Iterating an unstable feedback loop is how a
"self-healing" system heals itself to death, so three brakes are built in.

THE FAILURE MODE THAT MATTERS: MUTUAL DELUSION

If trust is inferred from neighbours and neighbours' trust is inferred from each
other, the network can converge on a confident consensus that is simply wrong --
most dangerously for a correlated failure, since AWS are bought in tender lots and
a whole batch can drift together. Three anchors stop it:

  1. RELATIVE, NOT ABSOLUTE.  Trust is normalised within each neighbourhood. If
     every station in a region disagrees with every other by the same amount,
     nobody loses trust -- that pattern is weather, or a regional event, not a
     fault. Only a station that stands out from its own neighbourhood is demoted.
     This is what makes a common-mode drift show up as "no fault anywhere"
     instead of "everyone is broken", which is the honest answer: a relative
     method cannot see a network-wide bias, and it should not pretend to.

  2. A FLOOR.  Trust never reaches zero, so no station is ever permanently
     excommunicated and every station can recover. A station that is serviced
     starts agreeing again and climbs back on its own.

  3. DAMPING.  Each iteration moves trust only part of the way, so the loop
     cannot oscillate or collapse in one step.

Trust is also computed on a TRAILING window, so it is causal: the trust used to
judge today was earned yesterday. A station that fails in October loses trust in
October, not retroactively across its whole year.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Trust floor. Nothing is ever excommunicated -- see anchor 2.
TRUST_FLOOR = 0.05

# How many days of trailing evidence a trust value rests on.
TRUST_WINDOW_D = 14

# Fraction of the way trust moves per iteration. Below 1.0 for anchor 3.
DAMPING = 0.5

# Fixed-point iterations. Three is enough on graphs this small; the update is a
# contraction under damping, and the change after the third pass is negligible.
N_ITER = 3

# Disagreement, in robust sigmas, at which a station retains half its trust.
# Not tuned against labels -- it is set from the same 3-sigma convention the
# detectors use, so a station is half-trusted where a detector would be
# starting to flag it.
HALF_TRUST_AT = 3.0


def _wide(df: pd.DataFrame, resid: np.ndarray) -> pd.DataFrame:
    """Residuals as a (run, time) x station matrix."""
    return (pd.DataFrame({"run_id": df.run_id, "t": df.timestamp,
                          "s": df.station_name, "r": resid})
            .pivot_table(index=["run_id", "t"], columns="s", values="r"))


def _weighted_reference(wide: pd.DataFrame, station: str, neighbours: list[str],
                        w: pd.DataFrame) -> pd.Series:
    """Trust-weighted combination of a station's neighbours.

    A weighted MEAN rather than a weighted median, deliberately: with a small
    neighbour set a weighted median degenerates to picking one neighbour, which
    throws away the very weighting this function exists to apply. Robustness to
    a bad neighbour comes from the trust weight itself -- that is the whole
    mechanism -- rather than from the choice of estimator.
    """
    if not neighbours:
        return pd.Series(np.nan, index=wide.index)
    vals = wide[neighbours]
    wt = w[neighbours].reindex(wide.index).fillna(TRUST_FLOOR)
    wt = wt.where(vals.notna(), np.nan)          # absent neighbour, no weight
    denom = wt.sum(axis=1, min_count=1)
    return (vals * wt).sum(axis=1, min_count=1) / denom.replace(0.0, np.nan)


def _trust_from_disagreement(d: pd.DataFrame) -> pd.DataFrame:
    """Turn a station's disagreement with its neighbours into a trust value.

    Per station and per day, on a TRAILING window, then shifted by one day so
    today's judgement uses only evidence already in hand.

    The normalisation across stations is anchor 1 and is the important line: it
    is the MEDIAN disagreement over the whole network that sets the scale, so a
    day on which everyone disagrees with everyone costs nobody any trust.
    """
    # Group by (run_id, day), NOT by day alone. Collapsing run_id mixes
    # independent replicates and, worse, produces an index that no longer
    # matches the trust table -- the reindex then yields all-NaN and every
    # station keeps full trust for ever, which is a broken mechanism that
    # looks exactly like a working one.
    daily = d.abs().groupby(level=[0, 1]).mean()
    roll = (daily.groupby(level=0, group_keys=False)
            .apply(lambda g: g.rolling(TRUST_WINDOW_D, min_periods=3)
                              .median().shift(1)))

    # Scale by the network's own typical disagreement that day, not by an
    # absolute constant. This is what makes the measure relative.
    scale = roll.median(axis=1)
    scale = scale.replace(0.0, np.nan).ffill().bfill()
    z = roll.div(scale, axis=0)

    # Smooth, bounded, and monotone: agreement near the network norm keeps full
    # trust, disagreement far beyond it decays toward the floor.
    t = 1.0 / (1.0 + (z / HALF_TRUST_AT) ** 2)
    return t.clip(lower=TRUST_FLOOR, upper=1.0)


def trust_weighted_difference(df: pd.DataFrame, var: str, resid: np.ndarray,
                              graph: dict, n_iter: int = N_ITER
                              ) -> tuple[np.ndarray, pd.DataFrame]:
    """Neighbour difference where sick neighbours count for less.

    Returns (difference series aligned to df, per-day trust table). The trust
    table is the network's belief about itself and is worth surfacing to an
    operator on its own -- "which of my stations am I currently trusting" is a
    question the existing system could not answer.
    """
    wide = _wide(df, resid)
    stations = list(wide.columns)

    # Day index for every row, so a per-day trust value can be broadcast back.
    day = pd.MultiIndex.from_arrays(
        [wide.index.get_level_values(0),
         wide.index.get_level_values(1).floor("D")])

    trust_daily = pd.DataFrame(
        1.0, index=pd.MultiIndex.from_tuples(sorted(set(day)),
                                             names=["run_id", "day"]),
        columns=stations)

    d = None
    for _ in range(max(1, n_iter)):
        w_rows = trust_daily.reindex(day)
        w_rows.index = wide.index

        cols = {}
        for s in stations:
            nb = [n for n in graph.get(s, {}).get("neighbours", []) if n in stations]
            ref = _weighted_reference(wide, s, nb, w_rows)
            cols[s] = wide[s] - ref.fillna(0.0)
        d = pd.DataFrame(cols, index=wide.index)

        d_day = d.copy()
        d_day.index = day
        proposed = _trust_from_disagreement(d_day)
        proposed = (proposed.reindex(trust_daily.index)
                    .groupby(level=0, group_keys=False).ffill().fillna(1.0))
        # Anchor 3: move only part of the way.
        trust_daily = ((1 - DAMPING) * trust_daily + DAMPING * proposed
                       ).clip(lower=TRUST_FLOOR, upper=1.0)

    key = pd.MultiIndex.from_arrays([df.run_id, df.timestamp])
    out = np.full(len(df), np.nan)
    for s in stations:
        m = (df.station_name == s).to_numpy()
        if m.any():
            out[m] = d[s].reindex(key[m]).to_numpy()
    return out, trust_daily


def demoted(trust_daily: pd.DataFrame, threshold: float = 0.5) -> pd.DataFrame:
    """Which stations the network has demoted as references, and when.

    This is the self-healing action made auditable. An operator can ask why a
    station stopped being used as a yardstick and get a date and a trust curve,
    rather than a system that quietly changed its mind.
    """
    return trust_daily < threshold
