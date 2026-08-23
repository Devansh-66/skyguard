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

VERSION = "learned-1.1.0"


# ------------------------------------------------------- marginal transform

def _probit(u: np.ndarray) -> np.ndarray:
    """Inverse standard normal CDF. Acklam's rational approximation, ~1e-9
    relative error, so evaluation/ and detect/ stay free of scipy."""
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    u = np.clip(u, 1e-12, 1 - 1e-12)
    lo, hi = u < 0.02425, u > 1 - 0.02425
    mid = ~(lo | hi)
    out = np.empty_like(u)

    q = np.sqrt(-2 * np.log(u[lo])) if lo.any() else np.array([])
    if lo.any():
        out[lo] = ((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])
                   / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1))
    q = np.sqrt(-2 * np.log(1 - u[hi])) if hi.any() else np.array([])
    if hi.any():
        out[hi] = -((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])
                    / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1))
    if mid.any():
        q = u[mid] - 0.5
        r = q * q
        out[mid] = ((((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q
                    / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1))
    return out


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
        # np.cov drops to a 0-d scalar for a single feature; atleast_2d keeps
        # the 1-dim case working so ablations can be run down to one axis.
        cov = np.atleast_2d(np.cov(Xs, rowvar=False))
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


def conformalize(ref_scores: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """Turn any score into a conformal p-value against a reference sample.

    This is what makes detectors comparable. A robust z, a Mahalanobis distance
    and a run length live on three incompatible scales, and combining them
    directly means picking arbitrary weights. Converted to p-values against the
    same reference window they are all "how often does a healthy station look at
    least this odd", and a minimum over them is meaningful.
    """
    cal = np.sort(ref_scores[np.isfinite(ref_scores)])
    n = len(cal)
    rank = n - np.searchsorted(cal, scores, side="left")
    p = (1.0 + rank) / (n + 1.0)
    p[~np.isfinite(scores)] = np.nan
    return p


def ensemble(p_values: list[np.ndarray],
             certain: np.ndarray | None = None) -> np.ndarray:
    """Combine conformal p-values by MINIMUM, returned as -log10.

    A minimum, not a mean. These detectors are built to be blind to different
    things -- a level detector cannot see a frozen probe, a run-length detector
    cannot see a drift -- so averaging asks a detector that is structurally
    incapable of seeing a fault to vote on it, and it always votes no.

    The minimum costs a multiplicity penalty: k independent tests at level a
    give up to k*a false alarms. It is not corrected here because the alert
    budget in evaluation/ sets the threshold empirically, which absorbs it. If
    a nominal false-alarm rate is ever quoted, apply Bonferroni or Simes first
    and say which.
    """
    P = np.vstack(p_values)
    with np.errstate(invalid="ignore"):
        m = np.nanmin(P, axis=0)
    out = -np.log10(np.clip(m, 1e-12, 1.0))

    # `certain` is for evidence that is not statistical at all -- a missing
    # observation. Every constituent detector returns NaN there, because none
    # of them can compute anything from an absent reading, so nanmin has nothing
    # to work with and dropout recall fell to zero. Absence is not a weak
    # signal to be pooled; it is a fact, and it is asserted rather than
    # inferred.
    if certain is not None:
        out = np.where(certain, 1e6, np.nan_to_num(out))
    return out


# ---------------------------------------------------------------- the model

@dataclass
class LearnedDetector:
    version: str = VERSION
    mu: np.ndarray | None = None
    cov: np.ndarray | None = None
    calib: np.ndarray | None = None          # calibration distances, sorted
    marginals: dict = field(default_factory=dict)   # reference ECDF per feature
    feature_names: tuple[str, ...] = ()
    variable: str = "temp"
    fitted_on: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.feature_names:
            self.feature_names = features_for(self.variable)

    # ---------------------------------------------------- marginal transform
    def _normal_score(self, X: np.ndarray, fit: bool = False) -> np.ndarray:
        """Map each axis to its reference rank, then to a standard normal.

        WHY THIS EXISTS. Three of the six axes -- flat, jump, spread -- are
        non-negative and heavily zero-inflated: `flat` is exactly zero for about
        97 % of a healthy reference window. Its variance is therefore almost
        zero, and a Mahalanobis distance weights each direction by 1 / variance,
        so that one axis took 99.9 % of the distance and the other five
        contributed nothing measurable. The detector was a flatness detector
        wearing a Mahalanobis costume, and it lost to a plain z-score on
        pressure by a factor of four.

        This is the same failure as an unfloored MAD (CLAUDE.md rule 5), one
        level up: a degenerate scale estimate produces an infinite weight. The
        fix there is a floor; here it is a rank transform, which is stronger --
        it makes every axis exactly standard normal by construction, so no axis
        can dominate by scale alone and the covariance then describes only what
        it should, the CORRELATION between axes.

        Ties matter and are handled by mid-rank: all the zeros in `flat` map to
        one point near the centre, and any non-zero run lands in the far tail,
        which is exactly the ordering we want.
        """
        out = np.empty_like(X, dtype=float)
        for j, name in enumerate(self.feature_names):
            col = X[:, j]
            if fit:
                self.marginals[name] = np.sort(col[np.isfinite(col)])
            ref = self.marginals[name]
            n = len(ref)
            lo = np.searchsorted(ref, col, side="left")
            hi = np.searchsorted(ref, col, side="right")
            u = ((lo + hi) / 2.0 + 0.5) / (n + 1.0)   # mid-rank, no 0 or 1
            out[:, j] = _probit(u)
        return out

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
        Z = self._normal_score(X[:cut], fit=True)
        self.mu, self.cov = _concentrate(Z)

        # Force the scatter to a CORRELATION matrix -- unit diagonal.
        #
        # The rank transform alone was not enough. Concentration keeps the
        # tightest 60 % of the sample, and for a zero-inflated axis like `flat`
        # that 60 % is entirely the atom at zero, so the kept subset has zero
        # variance on that axis and the degeneracy comes straight back. Two
        # rounds of this bug is enough to state the rule plainly: after a
        # marginal transform every axis is standard normal BY CONSTRUCTION, so
        # any scale the covariance reports is an artefact of which rows were
        # kept, never information. The only thing worth estimating robustly
        # here is the CORRELATION between axes.
        sd = np.sqrt(np.clip(np.diag(self.cov), 1e-6, None))
        self.cov = self.cov / np.outer(sd, sd)
        self.mu = np.zeros_like(self.mu)   # standard normal marginals, centred
        self.calib = np.sort(_mahal(self._normal_score(X[cut:]), self.mu, self.cov))
        self.fitted_on = {"n_fit": int(cut), "n_calib": int(len(X) - cut),
                          "features": list(self.feature_names)}
        return self

    # ------------------------------------------------------------ inference
    def distance(self, F: pd.DataFrame) -> np.ndarray:
        X = F[list(self.feature_names)].to_numpy(dtype=float)
        bad = ~np.isfinite(X).all(axis=1)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        d = _mahal(self._normal_score(X), self.mu, self.cov)
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
        X = self._normal_score(
            np.nan_to_num(F[list(self.feature_names)].to_numpy(dtype=float)))
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
