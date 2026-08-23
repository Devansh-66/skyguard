"""The six-dimensional residual vector. Shared by the learned and signature stages.

Choosing these six is the most consequential modelling decision in the repo, so
the reasoning is written down rather than left in someone's head.

One vector is assembled PER VARIABLE under test, six axes each:

    z_<var>        LEVEL   -- where is the value, relative to neighbours
    flat_<var>     SHAPE   -- has it stopped moving
    jump_<var>     SHAPE   -- did it move discontinuously
    spread_<var>   SHAPE   -- has its variance changed
    z_<other x2>   CONTEXT -- did the station's other two probes move as well

THE AXES ARE STRUCTURALLY DISTINCT, NOT MERELY DIFFERENT NUMBERS.

A Mahalanobis distance over the three level axes alone is a POINT detector and
is structurally blind to frozen, dropout, drift and noise burst -- four of seven
fault classes (CLAUDE.md). The three shape axes are what make the learned stage
able to see them at all. That is why the vector is 6-dim and not 3-dim.

WHAT IS DELIBERATELY ABSENT: dew point and specific humidity. Both are exact
functions of T, RH and P. Including a derived quantity alongside its parents
splits every attribution between them and makes the SHAP panel meaningless --
the explainability marks are lost to a feature-set mistake, not a model one. Td
and q are still computed and still shown to the operator; they just do not enter
the score vector.

All six are causal: they use the current sample and a trailing window, never a
future one. Latency cost is zero.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from detect.baseline import residual, robust_sigma, causal_scale, RESOLUTION

VARIABLES = ("temp", "rh", "pres")

# The vector is assembled PER VARIABLE. Four axes describe the variable under
# test and two carry its siblings' levels as cross-channel context -- that
# context is what lets the learned stage tell "the thermistor moved" from "the
# whole station moved". A single station-level vector cannot do this: scoring
# one joint distance against a per-sensor label is a category error, and it
# loses to a plain z-score because it dilutes the faulted channel with two
# healthy ones.
def features_for(var: str) -> tuple[str, ...]:
    others = [v for v in VARIABLES if v != var]
    return (f"z_{var}", f"flat_{var}", f"jump_{var}", f"spread_{var}",
            f"z_{others[0]}", f"z_{others[1]}")

WIN = 24          # trailing window, hours -- one full diurnal cycle
FLAT_SCALE = 6.0  # 6 identical samples is a z of about 1


def neighbour_residual(df: pd.DataFrame, var: str, coefs: dict,
                       graph: dict) -> pd.Series:
    """Harmonic residual minus the median residual of its chosen neighbours."""
    r = residual(df, var, coefs)
    wide = (pd.DataFrame({"run_id": df.run_id, "t": df.timestamp,
                          "s": df.station_name, "r": r})
            .pivot_table(index=["run_id", "t"], columns="s", values="r"))
    out = pd.Series(np.nan, index=df.index, dtype=float)
    key = pd.MultiIndex.from_arrays([df.run_id, df.timestamp])
    for s in wide.columns:
        nb = [n for n in graph.get(s, {}).get("neighbours", []) if n in wide.columns]
        d = wide[s] - (wide[nb].median(axis=1) if nb else 0.0)
        m = (df.station_name == s).to_numpy()
        if m.any():
            out.iloc[np.flatnonzero(m)] = d.reindex(key[m]).to_numpy()
    return out


def build(df: pd.DataFrame, coefs: dict, graph: dict,
          causal: bool = True) -> pd.DataFrame:
    """Return the 6-dim feature frame, aligned to df's index.

    Causal by default: every axis uses the current sample and a trailing window
    only. The centred variant is kept behind a flag so the cost of honesty can
    be measured rather than asserted.
    """
    f = pd.DataFrame(index=df.index, dtype=float)

    # --- three LEVEL axes -------------------------------------------------
    dres = {}
    for var in VARIABLES:
        d = neighbour_residual(df, var, coefs[var], graph)
        dres[var] = d
        z = np.full(len(df), np.nan)
        for _, g in df.groupby(["run_id", "station_name"], sort=False):
            pos = df.index.get_indexer(g.index)
            v = d.loc[g.index].to_numpy()
            if causal:
                med, sig = causal_scale(v, var)
                z[pos] = (v - med) / sig
            else:
                z[pos] = (v - np.nanmedian(v)) / robust_sigma(v, var)
        f[f"z_{var}"] = z

    # --- three SHAPE axes, kept PER VARIABLE ------------------------------
    # Not maxed across channels. A fault hits one probe, and a max would let a
    # frozen pressure sensor raise the flatness of a perfectly healthy
    # thermistor -- which is exactly the attribution error the signature stage
    # then has to undo.
    shape = {f"{k}_{v}": np.zeros(len(df))
             for k in ("flat", "jump", "spread") for v in VARIABLES}

    for _, g in df.groupby(["run_id", "station_name"], sort=False):
        pos = df.index.get_indexer(g.index)
        for var in VARIABLES:
            v = g[var].to_numpy(dtype=float)

            # flatness: length of the current run of identical values
            run = np.zeros(len(v))
            for i in range(1, len(v)):
                run[i] = run[i - 1] + 1 if (v[i] == v[i - 1]) else 0.0
            shape[f"flat_{var}"][pos] = run / FLAT_SCALE

            # jump: one-step change of the NEIGHBOUR residual, in sigma.
            # Taken on the residual so a genuine frontal passage -- which moves
            # the neighbours too -- does not register as a jump.
            d = pd.Series(dres[var].loc[g.index].to_numpy())
            dd = d.diff().to_numpy()
            shape[f"jump_{var}"][pos] = (np.abs(np.nan_to_num(dd))
                                         / robust_sigma(dd, var))

            # spread: trailing-window scatter against the station's own typical
            # scatter. This is the only axis that sees a noise burst.
            # The rolling window was already trailing; the BASELINE it was
            # compared against was not. A median over the whole series is a
            # lookahead, so it becomes an expanding median -- only what has
            # been seen so far.
            s_roll = d.rolling(WIN, min_periods=8).std().to_numpy()
            base = (pd.Series(s_roll).expanding(min_periods=24).median().to_numpy()
                    if causal else np.nanmedian(s_roll))
            base = np.maximum(np.nan_to_num(base, nan=0.0), RESOLUTION[var])
            shape[f"spread_{var}"][pos] = np.nan_to_num(s_roll / base, nan=1.0)

    for k, v in shape.items():
        f[k] = v

    # A dropout is not a borderline reading -- it is the absence of one. It gets
    # its own column rather than a large finite score, so nothing downstream has
    # to guess whether a big number means "extreme" or "missing".
    for var in VARIABLES:
        f[f"missing_{var}"] = ~np.isfinite(df[var].to_numpy(dtype=float))

    return f
