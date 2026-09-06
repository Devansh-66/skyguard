"""The one-row feature builder must agree with the vectorised one, exactly.

Serving builds features a row at a time because materialising every row costs
over 300 MB across three channels. That leaves two implementations of one
feature set in the repository, which is the failure this project keeps meeting:
they agree on the day they are written, drift apart in some later edit, and the
symptom is a model quietly served the wrong numbers and answering nonsense with
full confidence.

So the agreement is asserted rather than assumed. If this test fails, the
served explanations are wrong -- not the test.

    python -m pytest tests/test_reference_row.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("lightgbm")

from learn.reference_model import (CLEAN, PER_DAY, TRAIN_DAYS, FEATURE_NAMES,
                                   build_matrix, climatology_for, load,
                                   neighbours, row_features)

CHANNELS = ("temp", "rh", "pres")
SAMPLES = 60


@pytest.fixture(scope="module")
def fixtures():
    if not CLEAN.exists():
        pytest.skip(f"{CLEAN} not present")
    d = load(CLEAN)
    nb_idx, nb_dist = neighbours(d)
    return d, nb_idx, nb_dist, TRAIN_DAYS * PER_DAY


def test_feature_names_match_the_vectorised_builder(fixtures):
    d, nb_idx, nb_dist, split = fixtures
    _, _, _, _, names, _ = build_matrix(d, "temp", nb_idx, nb_dist, split)
    assert names == FEATURE_NAMES, (
        "the served feature order no longer matches the trained one; every "
        "explanation would be attributing the wrong value to the wrong feature"
    )


@pytest.mark.parametrize("ch", CHANNELS)
def test_row_matches_matrix(fixtures, ch):
    d, nb_idx, nb_dist, split = fixtures
    X, _, step, st, _, _ = build_matrix(d, ch, nb_idx, nb_dist, split)
    clim = climatology_for(d, ch, split)

    rng = np.random.default_rng(0)
    # Deliberately sampled from the WHOLE record rather than the test window:
    # the climatology is fitted on the training window, and a row builder that
    # silently used the wrong window would agree on one side of the split and
    # not the other.
    rows = rng.choice(X.shape[0], size=SAMPLES, replace=False)

    for r in rows:
        got = row_features(d, ch, nb_idx, nb_dist, clim,
                           int(st[r]), int(step[r]))[0]
        want = X[r]
        # NaN is a value here -- a station with fewer than three neighbours in
        # range genuinely has no trimmed mean -- so the two must agree about
        # WHERE the NaNs are as well as about the numbers.
        assert np.array_equal(np.isnan(got), np.isnan(want)), (
            f"{ch} row {r}: NaN pattern differs\n got {got}\nwant {want}")
        m = ~np.isnan(want)
        assert np.allclose(got[m], want[m], rtol=1e-9, atol=1e-9), (
            f"{ch} row {r}:\n got {got}\nwant {want}")
