from __future__ import annotations

import pytest

from chamber_orchestra.evaluation.stats import (
    mcnemar_exact,
    paired_comparison,
    wilson_interval,
)


def test_mcnemar_known_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 0) == pytest.approx(2 / 32)
    assert mcnemar_exact(10, 0) == pytest.approx(2 / 1024)
    assert mcnemar_exact(0, 5) == pytest.approx(2 / 32)
    assert mcnemar_exact(3, 3) == pytest.approx(1.0)


def test_mcnemar_symmetric_and_bounded():
    for b in range(0, 8):
        for c in range(0, 8):
            p = mcnemar_exact(b, c)
            assert 0.0 <= p <= 1.0
            assert p == pytest.approx(mcnemar_exact(c, b))


def test_wilson_interval_contains_estimate():
    low, high = wilson_interval(8, 10)
    assert low < 0.8 < high
    assert 0.0 <= low <= high <= 1.0
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_paired_comparison_counts_discordant_tasks():
    baseline = {"a": 0.0, "b": 0.0, "c": 1.0, "d": 1.0}
    candidate = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 0.0}
    comparison = paired_comparison(baseline, candidate)

    assert comparison.tasks == 4
    assert comparison.candidate_only == 2
    assert comparison.baseline_only == 1
    assert comparison.delta == pytest.approx(0.25)
    assert comparison.p_value == pytest.approx(1.0)


def test_paired_comparison_requires_shared_tasks():
    with pytest.raises(ValueError):
        paired_comparison({"a": 1.0}, {"b": 1.0})
