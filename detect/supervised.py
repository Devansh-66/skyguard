"""Supervised detection. The first thing here that learns from a label.

READ THIS BEFORE TRUSTING ANY NUMBER IT PRODUCES.

The labels come from `inject/faults.py`. They describe MY injector, not IMD's
sensors. A gradient-boosted tree is perfectly capable of learning "a spike is
one sample displaced by a log-uniform amount and quantised to 0.1", which is a
fact about a hundred lines of Python and not about a thermistor. Such a model
scores beautifully on this harness and fails on the first real fault shape the
injector does not contain.

So this module ships with its own falsification test attached. `leave_one_out`
trains with an entire fault class removed and evaluates on that class. If recall
collapses, the model memorised the injector and must not be trusted beyond it.
If recall holds, it learned something transferable about SHAPE, which is the
only thing worth carrying to real data.

Two more deliberate constraints:

  * The features are the same six the unsupervised stage uses, plus nothing.
    Handing the model raw T/P/RH would let it learn the CLIMATE of the ten
    stations in the training set -- which is real information, and completely
    useless at station eleven.

  * It enters the system as ONE conformalised channel among several. If the
    supervised channel is removed the system degrades; it does not stop working.
    A pipeline whose accuracy rests entirely on a model trained on synthetic
    labels is a pipeline with a single point of failure.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from detect.features import features_for

VERSION = "supervised-1.0.0"

# MEASURED RESULT, 2026-08-23. This model is OFF BY DEFAULT and this block is
# why. Reproduce with `python -m evaluation.run_supervised`.
#
#   detection, 1 alert/station/week      PR-AUC / event recall
#     temp   unsupervised .160/.704   supervised .139/.519   both .167/.741
#     rh     unsupervised .084/.350   supervised .103/.500   both .098/.400
#     pres   unsupervised .282/.897   supervised .302/.759   both .207/.828
#
#   leave-one-fault-type-out            mean recall
#     class was in training                  0.698
#     class never seen                       0.537
#     gap                                   +0.161
#
# The gap is not uniform, and the per-class rows are the story. `dropout`
# generalises perfectly (absence is absence, and no injector defines that).
# `calibration_drift` on pressure goes 1.00 -> 0.00: with the class withheld the
# model cannot find a drift at all, which means on the harness it was not
# detecting drift, it was recognising a linear ramp of the shape my injector
# writes. Drift is the class that matters most in the field and the one you are
# least likely to have labelled examples of.
#
# No consistent win, and as a fourth ensemble channel it HURT pressure. The
# unsupervised ensemble stays the shipping detector because it finds things
# nobody labelled, which is the actual job.

# Modest capacity on purpose. With ~450 events the risk is memorising them, and
# a deeper forest memorises faster. If a bigger model helps on the harness and
# NOT on leave-one-out, that is the memorisation showing, not an improvement.
PARAMS = dict(max_depth=4, max_iter=250, learning_rate=0.06,
              min_samples_leaf=60, l2_regularization=1.0,
              early_stopping=True, validation_fraction=0.15,
              random_state=17)


@dataclass
class SupervisedDetector:
    variable: str = "temp"
    version: str = VERSION
    model: HistGradientBoostingClassifier | None = None
    feature_names: tuple[str, ...] = ()
    trained_on: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.feature_names:
            self.feature_names = features_for(self.variable)

    def fit(self, F: pd.DataFrame, y: np.ndarray,
            exclude_types: pd.Series | None = None,
            drop: tuple[str, ...] = ()) -> "SupervisedDetector":
        """Fit on labelled rows. `drop` removes whole fault classes.

        Class imbalance is handled by weighting rather than resampling.
        Resampling a time series breaks the autocorrelation the shape features
        depend on -- a resampled `flat` run is not a run any more.
        """
        X = F[list(self.feature_names)].to_numpy(dtype=float)
        y = np.asarray(y).astype(int)
        keep = np.isfinite(X).all(axis=1)
        if drop and exclude_types is not None:
            keep &= ~exclude_types.isin(drop).to_numpy()
        X, y = X[keep], y[keep]

        pos = max(y.sum(), 1)
        w = np.where(y == 1, len(y) / (2.0 * pos), len(y) / (2.0 * max(len(y) - pos, 1)))

        self.model = HistGradientBoostingClassifier(**PARAMS)
        self.model.fit(X, y, sample_weight=w)
        self.trained_on = {"rows": int(len(y)), "positives": int(y.sum()),
                           "dropped_types": list(drop),
                           "features": list(self.feature_names)}
        return self

    def score(self, F: pd.DataFrame) -> np.ndarray:
        """P(fault). Rows with a non-finite feature score NaN rather than 0 --
        "cannot say" and "confidently healthy" are different claims."""
        X = F[list(self.feature_names)].to_numpy(dtype=float)
        bad = ~np.isfinite(X).all(axis=1)
        p = self.model.predict_proba(np.nan_to_num(X))[:, 1]
        p[bad] = np.nan
        return p

    def importances(self, F: pd.DataFrame, y: np.ndarray,
                    n_repeats: int = 3, seed: int = 0) -> dict:
        """Permutation importance on HELD-OUT rows.

        Not the split-count importance trees report by default: that measures
        how often a feature was used, which rewards high-cardinality features
        regardless of whether they helped. Permutation importance measures what
        breaks when the feature is destroyed, which is the question.
        """
        from sklearn.inspection import permutation_importance
        X = F[list(self.feature_names)].to_numpy(dtype=float)
        ok = np.isfinite(X).all(axis=1)
        r = permutation_importance(self.model, X[ok], np.asarray(y)[ok],
                                   n_repeats=n_repeats, random_state=seed,
                                   scoring="average_precision")
        return {n: round(float(v), 4)
                for n, v in zip(self.feature_names, r.importances_mean)}
