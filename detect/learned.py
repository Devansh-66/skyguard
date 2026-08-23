"""Stage 3 -- the learned layer. Robust covariance plus a conformal p-value.

Two deliberate choices, both of which cost accuracy on paper and buy it in the
field.

ROBUST COVARIANCE, NOT SAMPLE COVARIANCE. The reference period contains
unlabelled faults. A sample covariance fitted on it widens along exactly the
directions the faults occupy, and the detector then declares those directions
normal -- it learns to ignore what it was built to find. Concentration steps
(the core of Fast-MCD) fix this by repeatedly refitting on the tightest half.

CONFORMAL, NOT A CHI-SQUARED TABLE. The chi-squared quantile of a Mahalanobis
distance is only valid if the features are jointly Gaussian, and `flat` and
`spread` are emphatically not -- `flat` is zero almost everywhere with a long
right tail. Split conformal makes no distributional assumption at all: it gives
a p-value whose false-alarm rate is guaranteed by exchangeability alone, which
is the honest way to promise an operator "one alert per week".

The output p-value is what the alerting layer and the dashboard consume. It is
comparable across stations, across variables and across time, which a raw
distance is not.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from detect.features import features_for

VERSION = "learned-1.0.0"


# --------------------------------------------------------- robust covariance

def _concentrate(X: np.ndarray, h_frac: float = 0.6, iters: int = 12
                 ) -> tuple[np.ndarray, np.ndarray]:
    """Fast-MCD style concentration: refit on the h_frac tightest points.

    Converges to a location/scatter pair that ignores up to (1 - h_frac) of the
    sample. With h_frac = 0.6 the estimate tolerates 40 % contamination, which
    is far more than any plausible fault rate -- the margin is deliberate,
    because the contamination is unlabelled and cannot be checked.
    """
    n, d = X.shape
    h = max(d + 1, int(h_frac * n))
    mu = np.median(X, axis=0)
    keep = np.arange(n)
    cov = np.eye(d)
    for _ in range(iters):
        Xs = X[keep]
        mu = Xs.mean(axis=0)
        cov = np.cov(Xs, rowvar=False)
        cov += np.eye(d) * 1e-6 * np.trace(cov) / d   # ridge: never singular
        dist = _mahal(X, mu, cov)
        new = np.argsort(dist)[:h]
        if len(new) == len(keep) and np.array_equal(np.sort(new), np.sort(keep)):
            break
        keep = new

    # consistency correction: concentration shrinks the scatter, so rescale so
    # that the median distance matches what a Gaussian would give
    dist = _mahal(X, mu, cov)
    med = np.median(dist)
    if med > 0:
        from math import inf
        chi2_med = _chi2_median(d)
        cov *= med / chi2_med
    return mu, cov


def _chi2_median(d: int) -> float:
    """Median of a chi-squared with d df, via Wilson-Hilferty. Avoids scipy."""
    return d * (1.0 - 2.0 / (9.0 * d)) ** 3


def _mahal(X: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> np.ndarray:
    diff = X - mu
    return np.einsum("ij,jk,ik->i", diff, np.linalg.pinv(cov), diff)


# ---------------------------------------------------------------- the model

@dataclass
class LearnedDetector:
    version: str = VERSION
    mu: np.ndarray | None = None
    cov: np.ndarray | None = None
    calib: np.ndarray | None = None          # calibration distances, sorted
    feature_names: tuple[str, ...] = ()
    variable: str = "temp"
    fitted_on: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.feature_names:
            self.feature_names = features_for(self.variable)

    # ------------------------------------------------------------------ fit
    def fit(self, F: pd.DataFrame, calib_frac: float = 0.35,
            seed: int = 11) -> "LearnedDetector":
        """Fit on the frozen reference window. NO LABELS ARE USED.

        The frame is split into a fitting half and a calibration half. The
        split is by TIME BLOCK, not at random: residuals are autocorrelated over
        days, so a random split leaks the answer across the boundary and the
        conformal guarantee quietly stops holding.
        """
        X = F[list(self.feature_names)].to_numpy(dtype=float)
        ok = np.isfinite(X).all(axis=1)
        X = X[ok]
        if len(X) < 500:
            raise ValueError(f"only {len(X)} usable reference rows")

        cut = int(len(X) * (1 - calib_frac))
        self.mu, self.cov = _concentrate(X[:cut])
        self.calib = np.sort(_mahal(X[cut:], self.mu, self.cov))
        self.fitted_on = {"n_fit": int(cut), "n_calib": int(len(X) - cut),
                          "features": list(self.feature_names)}
        return self

    # ------------------------------------------------------------ inference
    def distance(self, F: pd.DataFrame) -> np.ndarray:
        X = F[list(self.feature_names)].to_numpy(dtype=float)
        bad = ~np.isfinite(X).all(axis=1)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        d = _mahal(X, self.mu, self.cov)
        d[bad] = np.nan
        return d

    def p_value(self, F: pd.DataFrame) -> np.ndarray:
        """Split-conformal p-value. Small p = anomalous.

        p = (1 + #{calibration >= observed}) / (n_calib + 1)

        The +1 is not cosmetic: without it the p-value is anti-conservative and
        the promised alert rate is exceeded.
        """
        d = self.distance(F)
        n = len(self.calib)
        rank = n - np.searchsorted(self.calib, d, side="left")
        p = (1.0 + rank) / (n + 1.0)
        p[~np.isfinite(d)] = np.nan
        return p

    def score(self, F: pd.DataFrame) -> np.ndarray:
        """Higher = more anomalous, for the harness. -log10(p), with dropout
        pinned above everything because a missing observation is certain, not
        merely extreme."""
        p = self.p_value(F)
        s = -np.log10(np.clip(p, 1e-12, 1.0))
        col = f"missing_{self.variable}"
        if col in F.columns:
            s = np.where(F[col].to_numpy(), 1e6, np.nan_to_num(s))
        return s

    # --------------------------------------------------------- attribution
    def contributions(self, F: pd.DataFrame) -> pd.DataFrame:
        """Per-feature contribution to the Mahalanobis distance.

        At d = 6 the exact Shapley value is a 64-coalition sum and is affordable
        per alert; this cheaper decomposition -- the elementwise terms of the
        quadratic form -- is what the dashboard shows for EVERY point. The
        expensive exact version runs only when an operator opens an alert.

        It is not a Shapley value and is not labelled as one.
        """
        X = np.nan_to_num(F[list(self.feature_names)].to_numpy(dtype=float))
        diff = X - self.mu
        P = np.linalg.pinv(self.cov)
        contrib = diff * (diff @ P)          # rows sum exactly to the distance
        return pd.DataFrame(contrib, columns=list(self.feature_names),
                            index=F.index)

    def shapley(self, x: np.ndarray) -> dict:
        """EXACT Shapley values for one point, over 2^6 = 64 coalitions.

        Exact rather than KernelSHAP because at d = 6 the exact computation is
        cheaper than the approximation and carries no sampling error to defend
        in a review. Absent features are set to the fitted centre, which is an
        interventional value function -- stated explicitly because the
        conditional and interventional variants disagree when features are
        correlated, and ours are.
        """
        from itertools import combinations
        from math import factorial

        d = len(self.feature_names)
        P = np.linalg.pinv(self.cov)

        def v(S: tuple[int, ...]) -> float:
            z = self.mu.copy()
            for i in S:
                z[i] = x[i]
            diff = z - self.mu
            return float(diff @ P @ diff)

        idx = range(d)
        phi = np.zeros(d)
        for i in idx:
            rest = [j for j in idx if j != i]
            for k in range(d):
                w = factorial(k) * factorial(d - k - 1) / factorial(d)
                for S in combinations(rest, k):
                    phi[i] += w * (v(tuple(S) + (i,)) - v(tuple(S)))
        return dict(zip(self.feature_names, np.round(phi, 4)))
