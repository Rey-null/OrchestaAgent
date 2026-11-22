from __future__ import annotations

import pytest

from chamber_orchestra.experiment.prereg import (
    PreRegistration,
    PreRegistrationError,
)
from chamber_orchestra.promotion.policy import PromotionPolicy

BASE = dict(
    scope="coding",
    baseline_id="baseline-hash",
    candidate_id="candidate-hash",
    suite_name="tiny-v1",
    suite_digest="suite-digest",
)


def test_identity_is_stable_and_ignores_registration_time():
    first = PreRegistration(**BASE, created_at="2026-01-01T00:00:00.000+00:00")
    second = PreRegistration(**BASE, created_at="2026-06-01T00:00:00.000+00:00")

    assert first.experiment_id == second.experiment_id
    assert first.digest() == second.digest()
    assert first.document()["created_at"] != second.document()["created_at"]


def test_changing_a_criterion_changes_the_id_and_the_digest():
    default = PreRegistration(**BASE)
    stricter = PreRegistration(**BASE, policy=PromotionPolicy(min_effect=0.4))

    assert default.experiment_id != stricter.experiment_id
    assert default.digest() != stricter.digest()
    assert default.document()["threshold"] == default.policy.min_effect


def test_document_roundtrip_preserves_the_hash():
    original = PreRegistration(**BASE)
    restored = PreRegistration.from_document(original.document())

    assert restored.digest() == original.digest()
    assert restored.experiment_id == original.experiment_id


def test_tampered_document_is_refused():
    document = PreRegistration(**BASE).document()
    document["policy"]["alpha"] = 0.5

    with pytest.raises(PreRegistrationError, match="digest mismatch"):
        PreRegistration.from_document(document)


def test_threshold_must_match_the_policy():
    document = PreRegistration(**BASE).document()
    document["threshold"] = 0.99

    with pytest.raises(PreRegistrationError, match="threshold"):
        PreRegistration.from_document(document)


def test_context_and_evaluation_splits_must_differ():
    with pytest.raises(PreRegistrationError, match="must differ"):
        PreRegistration(**BASE, evaluation_split="dev", context_split="dev")


def test_baseline_and_candidate_must_differ():
    with pytest.raises(PreRegistrationError, match="different harness"):
        PreRegistration(**{**BASE, "candidate_id": "baseline-hash"})


def test_unsupported_primary_metric_is_refused():
    with pytest.raises(PreRegistrationError, match="primary metric"):
        PreRegistration(**BASE, primary_metric="mean_latency")
