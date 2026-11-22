from __future__ import annotations

import uuid

import pytest

from chamber_orchestra.evaluation.models import CaseAttempt, EvalReport
from chamber_orchestra.promotion.gate import PolicyMutationError, decide
from chamber_orchestra.promotion.policy import PromotionPolicy
from tests.conftest import fake_report

TASKS = {f"held-{index}": 0.0 for index in range(8)}


def test_improvement_is_approved():
    baseline = fake_report(TASKS, harness_id="base")
    candidate = fake_report(
        {task: 1.0 for task in TASKS}, harness_id="cand"
    )
    decision = decide(
        candidate, baseline, PromotionPolicy(), active_harness_id=baseline.harness_id
    )

    assert decision.approved, decision.reasons
    assert decision.metrics["delta"] == pytest.approx(1.0)
    assert decision.metrics["p_value"] < 0.05
    assert decision.candidate_id == "cand"
    assert decision.evidence_digest


def test_regression_is_rejected():
    baseline = fake_report({task: 1.0 for task in TASKS}, harness_id="base")
    candidate = fake_report(TASKS, harness_id="cand")
    decision = decide(
        candidate, baseline, PromotionPolicy(), active_harness_id=baseline.harness_id
    )

    assert not decision.approved
    assert any("delta" in reason for reason in decision.reasons)
    assert decision.metrics["regressed_tasks"] == 8


def test_dev_evidence_is_not_enough():
    baseline = fake_report(TASKS, split="dev")
    candidate = fake_report({task: 1.0 for task in TASKS}, split="dev")
    decision = decide(
        candidate, baseline, PromotionPolicy(), active_harness_id=baseline.harness_id
    )

    assert not decision.approved
    assert any("held-out" in reason for reason in decision.reasons)


def test_suite_mismatch_is_rejected():
    baseline = fake_report(TASKS, suite_digest="suite-a")
    candidate = fake_report(
        {task: 1.0 for task in TASKS}, suite_digest="suite-b"
    )
    decision = decide(
        candidate, baseline, PromotionPolicy(), active_harness_id=baseline.harness_id
    )

    assert not decision.approved
    assert any("different suites" in reason for reason in decision.reasons)


def test_cost_guard_rejects_expensive_candidate():
    baseline = fake_report(TASKS, cost_per_task=0.02)
    candidate = fake_report(
        {task: 1.0 for task in TASKS}, cost_per_task=0.20
    )
    decision = decide(
        candidate, baseline, PromotionPolicy(), active_harness_id=baseline.harness_id
    )

    assert not decision.approved
    assert any("cost ratio" in reason for reason in decision.reasons)


def test_small_effect_is_rejected():
    baseline = fake_report({task: 0.5 for task in TASKS})
    candidate = fake_report({task: 0.5 for task in TASKS})
    decision = decide(
        candidate, baseline, PromotionPolicy(), active_harness_id=baseline.harness_id
    )

    assert not decision.approved
    assert any("below the required" in reason for reason in decision.reasons)


def test_minimum_task_count_is_enforced():
    baseline = fake_report({"held-1": 0.0, "held-2": 0.0})
    candidate = fake_report({"held-1": 1.0, "held-2": 1.0})
    decision = decide(
        candidate, baseline, PromotionPolicy(), active_harness_id=baseline.harness_id
    )

    assert not decision.approved
    assert any("shared tasks" in reason for reason in decision.reasons)


def test_behavior_regression_is_rejected():
    def report(behaviors, missing, success):
        attempts = tuple(
            CaseAttempt(
                task_id=f"held-{index}",
                harness_id="h",
                attempt=0,
                success=success,
                behaviors=behaviors,
                missing_behaviors=missing,
                cost_usd=0.02,
            )
            for index in range(8)
        )
        return EvalReport(
            report_id=uuid.uuid4().hex,
            harness_id="h",
            suite_name="s",
            suite_digest="suite-1",
            split="heldout",
            repetitions=1,
            attempts=attempts,
        )

    baseline = report(("runs_tests",), (), True)
    candidate = report((), ("runs_tests",), True)
    decision = decide(
        candidate, baseline, PromotionPolicy(), active_harness_id=baseline.harness_id
    )

    assert not decision.approved
    assert any("compliance dropped" in reason for reason in decision.reasons)


def test_policy_cannot_move_after_registration():
    baseline = fake_report(TASKS)
    candidate = fake_report({task: 1.0 for task in TASKS})
    registered = PromotionPolicy().digest()

    with pytest.raises(PolicyMutationError):
        decide(
            candidate,
            baseline,
            PromotionPolicy(min_effect=0.9),
            registered_policy_digest=registered,
            active_harness_id=baseline.harness_id,
        )

    decision = decide(
        candidate,
        baseline,
        PromotionPolicy(),
        registered_policy_digest=registered,
        active_harness_id=baseline.harness_id,
    )
    assert decision.policy_digest == registered


def test_baseline_must_be_the_active_harness():
    active = fake_report(TASKS, harness_id="harness-active")
    stale = fake_report(TASKS, harness_id="harness-retired")
    candidate = fake_report({task: 1.0 for task in TASKS}, harness_id="cand")

    decision = decide(
        candidate, stale, PromotionPolicy(), active_harness_id=active.harness_id
    )

    assert not decision.approved
    assert any("is not the active harness" in reason for reason in decision.reasons)


def test_missing_active_harness_is_rejected():
    baseline = fake_report(TASKS, harness_id="harness-active")
    candidate = fake_report({task: 1.0 for task in TASKS}, harness_id="cand")

    decision = decide(candidate, baseline, PromotionPolicy(), active_harness_id=None)

    assert not decision.approved
    assert any("no active harness" in reason for reason in decision.reasons)
