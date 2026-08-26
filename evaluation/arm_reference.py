"""Two ways to say what a station should have read, and why only one of them works.

    from evaluation.arm_reference import trailing_innovation, neighbour_innovation

THE PROBLEM THIS EXISTS TO FIX

The first ARM evaluation built its reference from each station's own 168-hour
trailing window. Real ARM faults have a median duration of 96 hours and run out
to 614 days, so for most of a fault that window sits INSIDE the fault. The
reference adapts into the fault, the innovation collapses, and the station looks
healthy exactly when it is broken.

Measured consequence: stations scored a LARGER bias and HIGHER trust outside
their fault windows than inside them -- the metric ran backwards. This project
has documented that self-masking three times and instructed the station tier
never to do it, and then did it in its own harness.

WHY THE SOUTHERN GREAT PLAINS SITE MAKES THE FIX POSSIBLE

ARM's SGP facility runs several surface-meteorology stations within tens of
kilometres of each other -- E13, E31, E32, E33, E37, E39, E41. They see the same
weather and are wired independently, so one station's fault cannot reach its
neighbours' readings. That is a reference the fault has no access to, which is
the whole requirement.

The other ARM sites in this corpus, Eastern North Atlantic and North Slope
Alaska, are single stations. They have no neighbours and this method simply
cannot serve them, which is itself the argument for the neighbourless work
elsewhere in this project rather than something to paper over.

THE SCALE IS FROZEN, NOT ROLLING

The robust sigma used to standardise the difference is computed ONCE on rows
outside every human-written fault interval, then held. A rolling scale would
reintroduce the same self-masking one level down: a long fault inflates the
scale until its own excursion looks ordinary.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ARM's Southern Great Plains surface-met stations. Co-located, independently
# instrumented, and therefore usable as each other's reference.
SGP = ("sgpmetE13", "sgpmetE31", "sgpmetE32", "sgpmetE33",
       "sgpmetE37", "sgpmetE39", "sgpmetE41")

MIN_NEIGHBOURS = 2


def trailing_innovation(df: pd.DataFrame, var: str, window: int = 168
                        ) -> pd.Series:
    """The old way. Kept so the comparison can be shown rather than asserted.

    Self-masking by construction on any fault longer than the window.
    """
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for st, g in df.groupby("station"):
        g = g.sort_values("timestamp")
        s = g[var]
        med = s.rolling(window, min_periods=24).median().shift(1)
        mad = (s - med).abs().rolling(window, min_periods=24).median().shift(1)
        out.loc[g.index] = ((s - med) / (1.4826 * mad).replace(0, np.nan))
    return out


def neighbour_innovation(df: pd.DataFrame, var: str,
                         faulty_col: str = "faulty") -> pd.Series:
    """Departure from the co-located neighbours, standardised by a frozen scale.

    Two properties the trailing version does not have. The reference comes from
    instruments the station's own fault cannot touch, and a neighbour that is
    itself inside a human-written fault interval is excluded from the consensus,
    so one sick station does not drag the yardstick its neighbours are judged by.
    """
    sgp = df[df.station.isin(SGP)]
    if sgp.empty:
        return pd.Series(np.nan, index=df.index, dtype=float)

    # values and fault mask as (time x station) matrices
    wide = sgp.pivot_table(index="timestamp", columns="station", values=var)
    if faulty_col in sgp.columns:
        bad = sgp.pivot_table(index="timestamp", columns="station",
                              values=faulty_col, aggfunc="max").astype(bool)
        bad = bad.reindex_like(wide).fillna(False)
    else:
        bad = pd.DataFrame(False, index=wide.index, columns=wide.columns)

    # a neighbour that is itself faulted contributes nothing to the consensus
    healthy = wide.where(~bad)

    out = pd.Series(np.nan, index=df.index, dtype=float)
    for st in wide.columns:
        others = [c for c in healthy.columns if c != st]
        if not others:
            continue
        ref = healthy[others].median(axis=1)
        n_ref = healthy[others].notna().sum(axis=1)
        diff = (wide[st] - ref).where(n_ref >= MIN_NEIGHBOURS)

        # FROZEN scale: robust sigma over rows outside every fault interval,
        # computed once. A rolling scale would self-mask one level down.
        m = df.station == st
        idx = df.index[m]
        ts = df.loc[m, "timestamp"]
        d = diff.reindex(ts).to_numpy()
        clean = d.copy()
        if faulty_col in df.columns:
            clean = np.where(df.loc[m, faulty_col].to_numpy(), np.nan, d)
        med = np.nanmedian(clean) if np.isfinite(clean).any() else 0.0
        mad = (np.nanmedian(np.abs(clean - med))
               if np.isfinite(clean).any() else np.nan)
        sigma = 1.4826 * mad
        if not np.isfinite(sigma) or sigma <= 0:
            continue
        out.loc[idx] = (d - med) / sigma
    return out
