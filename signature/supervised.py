"""Supervised fault naming, as a challenger to the hand-written templates.

The templates in signature/classify.py get 0.587 naming accuracy on real faults.
This asks whether a classifier over the same eight descriptors does better.

WHY IT IS A CHALLENGER AND NOT A REPLACEMENT. The templates carry two things a
learned model does not:

  * They are auditable. "Saturation because the probe sat at its rail for
    fourteen hours AND disagreed with its neighbours" is a sentence a
    meteorologist can dispute. A probability vector is not, and PS26073 puts
    ten marks on explainability.
  * They encode physics that is true independent of any dataset. Fog wets the
    whole valley; a broken probe does not. A model trained on 458 events can
    only learn that if the training set happens to contain it.

So this runs alongside, and it replaces the templates only where it wins on the
harness AND survives leave-one-fault-type-out. Where the two disagree, the
disagreement is worth showing to an operator rather than silently resolving.

It abstains. Below `MIN_PROB` it returns `unknown`, exactly like the templates,
because a confidently wrong root cause is the failure that destroys trust.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

VERSION = "signature-ml-1.0.0"

# MEASURED RESULT, 2026-08-23. The templates win and this model is not used.
# Reproduce with `python -m evaluation.run_signature_ml`.
#
#   naming accuracy on real faults   templates 0.710      supervised 0.500
#   abstention rate                  templates 38 %       supervised 0 %
#
# The abstention column is the damning one. Withhold a class entirely and the
# model is CONFIDENTLY WRONG -- probability >= 0.7 on a cause it has no basis
# for -- on 100 % of calibration_drift, dropout and frozen windows, and 82 % of
# step_offset. It has no way to represent "I have never seen this", so it
# projects every unfamiliar shape onto the nearest familiar one.
#
# It also dumped 14 of 17 real step offsets into "(false alarm)", which looks
# like a good false-alarm filter until you notice it is just predicting the
# majority class for anything ambiguous.
#
# Templates abstain because a human wrote a floor. That floor is worth more
# than 21 points of accuracy on a harness whose labels came from a file in
# this repo.

# The eight scale-free descriptors, in a fixed order. Amplitude is deliberately
# absent: the same template must fire for a 0.4 K step and a 4 K step, or the
# classifier degenerates into an amplitude detector that calls every large
# excursion the same thing.
DESCRIPTORS = ("missing", "flat", "rail", "level", "ramp", "linearity",
               "spread", "brevity", "coherence")

MIN_PROB = 0.45

PARAMS = dict(max_depth=4, max_iter=200, learning_rate=0.08,
              min_samples_leaf=8, l2_regularization=1.0, random_state=23)


@dataclass
class SignatureModel:
    version: str = VERSION
    model: HistGradientBoostingClassifier | None = None
    classes_: list = field(default_factory=list)
    trained_on: dict = field(default_factory=dict)

    def fit(self, windows: pd.DataFrame, labels, drop: tuple[str, ...] = ()
            ) -> "SignatureModel":
        """`windows` holds one row of descriptors per detected window."""
        y = pd.Series(labels).astype(str)
        keep = ~y.isin(drop) if drop else pd.Series(True, index=y.index)
        X = windows.loc[keep.to_numpy(), list(DESCRIPTORS)].to_numpy(dtype=float)
        y = y[keep.to_numpy()]

        self.model = HistGradientBoostingClassifier(**PARAMS)
        self.model.fit(np.nan_to_num(X), y)
        self.classes_ = list(self.model.classes_)
        self.trained_on = {"windows": int(len(y)), "dropped": list(drop),
                           "classes": self.classes_}
        return self

    def predict(self, windows: pd.DataFrame,
                min_prob: float = MIN_PROB) -> pd.DataFrame:
        X = np.nan_to_num(windows[list(DESCRIPTORS)].to_numpy(dtype=float))
        P = self.model.predict_proba(X)
        best = P.argmax(axis=1)
        top = P[np.arange(len(P)), best]
        label = np.where(top >= min_prob,
                         np.array(self.classes_)[best], "unknown")
        # Second choice is worth carrying: when the model is torn between
        # step_offset and calibration_drift that is genuinely useful to an
        # operator, and it is exactly what a bare argmax throws away.
        second = np.argsort(-P, axis=1)[:, 1]
        return pd.DataFrame({
            "label": label,
            "probability": np.round(top, 3),
            "runner_up": np.array(self.classes_)[second],
            "runner_up_probability": np.round(P[np.arange(len(P)), second], 3),
        }, index=windows.index)
