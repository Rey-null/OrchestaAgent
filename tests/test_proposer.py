from __future__ import annotations

import pytest

from chamber_orchestra.harness.manifest import HarnessManifest
from chamber_orchestra.harness.patch import apply_patch
from chamber_orchestra.proposer.base import ProposalContext, ProposalError
from chamber_orchestra.proposer.deterministic import DeterministicProposer


def _base() -> HarnessManifest:
    return HarnessManifest(
        scope="coding",
        components={
            "prompt": "p",
            "tool_guidance": {"behaviors": ["reports_evidence"]},
        },
    )


def _runs(base_id: str) -> list[dict]:
    return [
        {
            "run_id": "run-1",
            "harness_id": base_id,
            "task_id": "dev-code-01",
            "split": "dev",
            "success": False,
            "missing_behaviors": ["runs_tests"],
        },
        {
            "run_id": "run-2",
            "harness_id": base_id,
            "task_id": "dev-code-09",
            "split": "dev",
            "success": False,
            "missing_behaviors": ["runs_tests", "checks_requirements"],
        },
        {
            "run_id": "run-3",
            "harness_id": base_id,
            "task_id": "dev-study-01",
            "split": "dev",
            "success": True,
            "missing_behaviors": [],
        },
        {
            "run_id": "run-4",
            "harness_id": base_id,
            "task_id": "held-code-01",
            "split": "heldout",
            "success": False,
            "missing_behaviors": ["runs_tests"],
        },
        {
            "run_id": "run-5",
            "harness_id": "other",
            "task_id": "dev-code-02",
            "split": "dev",
            "success": False,
            "missing_behaviors": ["confirms_scope"],
        },
    ]


def test_context_excludes_heldout_and_other_harnesses():
    base = _base()
    context = ProposalContext.from_runs(
        scope="coding", base_id=base.id, runs=_runs(base.id)
    )

    assert set(context.evidence_run_ids) == {"run-1", "run-2", "run-3"}
    assert context.dropped_runs == 2
    assert "held-code-01" not in context.failed_tasks
    assert "dev-code-02" not in context.failed_tasks
    assert context.missing_counts == {"checks_requirements": 1, "runs_tests": 2}


def test_proposer_adds_missing_behaviors_and_skills():
    base = _base()
    context = ProposalContext.from_runs(
        scope="coding", base_id=base.id, runs=_runs(base.id)
    )
    patch = DeterministicProposer().propose(base, context)
    candidate = apply_patch(base, patch)

    assert candidate.declared_behaviors() == (
        "checks_requirements",
        "reports_evidence",
        "runs_tests",
    )
    assert "skills/runs-tests" in {
        f"skills/{name}" for name in candidate.components["skills"]
    }
    assert "runs_tests" in patch.rationale
    assert candidate.parent == base.id


def test_proposal_is_deterministic():
    base = _base()
    context = ProposalContext.from_runs(
        scope="coding", base_id=base.id, runs=_runs(base.id)
    )
    proposer = DeterministicProposer()
    assert proposer.propose(base, context).proposal_id == proposer.propose(base, context).proposal_id


def test_proposer_requires_evidence():
    base = _base()
    empty = ProposalContext.from_runs(scope="coding", base_id=base.id, runs=[])
    with pytest.raises(ProposalError):
        DeterministicProposer().propose(base, empty)


def test_min_support_filters_weak_evidence():
    base = _base()
    context = ProposalContext.from_runs(
        scope="coding", base_id=base.id, runs=_runs(base.id)
    )
    patch = DeterministicProposer(min_support=2).propose(base, context)
    candidate = apply_patch(base, patch)
    assert "checks_requirements" not in candidate.declared_behaviors()
    assert "runs_tests" in candidate.declared_behaviors()


def test_context_for_other_base_is_rejected():
    base = _base()
    context = ProposalContext.from_runs(
        scope="coding", base_id="someone-else", runs=_runs(base.id)
    )
    with pytest.raises(ProposalError):
        DeterministicProposer().propose(base, context)
