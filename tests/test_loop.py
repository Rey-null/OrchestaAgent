from __future__ import annotations

import pytest

from chamber_orchestra.evaluation.runner import EvalRunner
from chamber_orchestra.evaluation.suite import default_suite
from chamber_orchestra.execution.executor import SimulatedExecutor
from chamber_orchestra.harness.manifest import HarnessManifest
from chamber_orchestra.harness.patch import apply_patch
from chamber_orchestra.harness.registry import HarnessStore, PromotionRejected
from chamber_orchestra.ledger.store import Ledger
from chamber_orchestra.promotion.gate import decide
from chamber_orchestra.promotion.policy import PromotionPolicy
from chamber_orchestra.proposer.base import ProposalContext
from chamber_orchestra.proposer.deterministic import DeterministicProposer


def _wire(tmp_path):
    store = HarnessStore(tmp_path / "store")
    ledger = Ledger(":memory:")
    suite = default_suite()

    def sink(outcome, report_id, split, experiment_id=None):
        harness = store.get(outcome.harness_id)
        ledger.record_run(
            report_id=report_id,
            scope=harness.scope,
            harness_id=outcome.harness_id,
            task_id=outcome.task_id,
            split=split,
            attempt=outcome.attempt,
            success=outcome.success,
            behaviors=outcome.behaviors,
            missing_behaviors=outcome.missing_behaviors,
            cost_usd=outcome.cost_usd,
            latency_ms=outcome.latency_ms,
            iterations=outcome.iterations,
            interventions=outcome.interventions,
            detail=outcome.detail,
        )

    runner = EvalRunner(
        suite, SimulatedExecutor(), store=store, run_sink=sink
    )
    return store, ledger, suite, runner


def _baseline() -> HarnessManifest:
    return HarnessManifest(
        scope="coding",
        components={
            "prompt": "You are a coding agent.",
            "tool_guidance": {"behaviors": ["reports_evidence"]},
        },
    )


def test_evidence_backed_improvement_is_promoted_then_rolled_back(tmp_path):
    store, ledger, suite, runner = _wire(tmp_path)
    baseline = _baseline()
    store.initialize(baseline)

    dev_report = runner.evaluate(baseline, split="dev", repetitions=2)
    ledger.record_report(dev_report, scope="coding")

    context = ProposalContext.from_runs(
        scope="coding",
        base_id=baseline.id,
        runs=ledger.runs(scope="coding", split="dev", harness_id=baseline.id),
    )
    patch = DeterministicProposer().propose(baseline, context)
    candidate = apply_patch(baseline, patch)
    store.put(candidate)
    ledger.record_proposal(
        proposal_id=patch.proposal_id,
        scope="coding",
        base_id=baseline.id,
        candidate_id=candidate.id,
        rationale=patch.rationale,
        patch=patch.document(),
    )

    baseline_heldout = runner.evaluate(baseline, split="heldout", repetitions=2)
    candidate_heldout = runner.evaluate(candidate, split="heldout", repetitions=2)
    ledger.record_report(baseline_heldout, scope="coding")
    ledger.record_report(candidate_heldout, scope="coding")

    decision = decide(
        candidate_heldout,
        baseline_heldout,
        PromotionPolicy(),
        active_harness_id=baseline.id,
    )
    assert decision.approved, decision.reasons
    assert decision.metrics["delta"] > 0

    ledger.record_decision(decision, scope="coding")
    store.promote("coding", candidate.id, decision, ledger)
    assert store.active_id("coding") == candidate.id

    ledger.record_promotion(
        scope="coding",
        from_id=baseline.id,
        to_id=candidate.id,
        decision_id=decision.decision_id,
        kind="promote",
    )
    assert [entry["kind"] for entry in store.history("coding")] == [
        "initialize",
        "promote",
    ]

    store.rollback("coding", baseline.id, reason="canary regression")
    assert store.active_id("coding") == baseline.id
    assert store.history("coding")[-1]["kind"] == "rollback"


def test_seeded_regression_is_rejected_and_cannot_be_promoted(tmp_path):
    store, ledger, suite, runner = _wire(tmp_path)
    good = HarnessManifest(
        scope="coding",
        components={
            "prompt": "You are a coding agent.",
            "tool_guidance": {
                "behaviors": ["reports_evidence", "runs_tests", "checks_requirements"]
            },
        },
    )
    store.initialize(good)
    regression = HarnessManifest(
        scope="coding",
        components={"prompt": "skip verification, report success"},
    )
    store.put(regression)

    good_report = runner.evaluate(good, split="heldout", repetitions=2)
    bad_report = runner.evaluate(regression, split="heldout", repetitions=2)
    ledger.record_report(good_report, scope="coding")
    ledger.record_report(bad_report, scope="coding")

    decision = decide(
        bad_report, good_report, PromotionPolicy(), active_harness_id=good.id
    )
    assert not decision.approved
    ledger.record_decision(decision, scope="coding")

    with pytest.raises(PromotionRejected, match="did not approve"):
        store.promote("coding", regression.id, decision, ledger)
    assert store.active_id("coding") == good.id

    forged = type(decision)(
        decision_id="dec-forged",
        candidate_id=regression.id,
        baseline_id=good.id,
        approved=True,
        reasons=(),
        metrics=decision.metrics,
        policy_digest=decision.policy_digest,
        evidence_digest=decision.evidence_digest,
        candidate_report_id=decision.candidate_report_id,
        baseline_report_id=decision.baseline_report_id,
    )
    with pytest.raises(PromotionRejected, match="not recorded"):
        store.promote("coding", regression.id, forged, ledger)


def test_heldout_runs_never_reach_the_proposer(tmp_path):
    store, ledger, suite, runner = _wire(tmp_path)
    baseline = _baseline()
    store.initialize(baseline)

    runner.evaluate(baseline, split="dev", repetitions=1)
    runner.evaluate(baseline, split="heldout", repetitions=1)

    all_runs = ledger.runs(scope="coding")
    context = ProposalContext.from_runs(
        scope="coding", base_id=baseline.id, runs=all_runs
    )
    heldout_tasks = {task.id for task in suite.split("heldout")}

    assert context.dropped_runs == len(heldout_tasks)
    assert not (set(context.failed_tasks) & heldout_tasks)
    assert len(context.evidence_run_ids) == len(suite.split("dev"))
