"""The promotion gate.

Inputs: a baseline report, a candidate report, and the policy that was
registered before the experiment. Output: a decision with the evidence digest,
the metrics it used, and explicit reasons for rejection. The gate never runs a
model and never edits a harness; it only reads evidence and applies fixed
criteria, so it cannot be talked into a promotion.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from chamber_orchestra.evaluation.models import EvalReport
from chamber_orchestra.evaluation.stats import paired_comparison
from chamber_orchestra.harness.manifest import content_digest
from chamber_orchestra.promotion.policy import PromotionPolicy


class PolicyMutationError(RuntimeError):
    """Raised when the policy in force differs from the registered one."""


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    decision_id: str
    candidate_id: str
    baseline_id: str
    approved: bool
    reasons: tuple[str, ...]
    metrics: Mapping[str, float]
    policy_digest: str
    evidence_digest: str
    candidate_report_id: str
    baseline_report_id: str

    def document(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "candidate_id": self.candidate_id,
            "baseline_id": self.baseline_id,
            "approved": self.approved,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
            "policy_digest": self.policy_digest,
            "evidence_digest": self.evidence_digest,
            "candidate_report_id": self.candidate_report_id,
            "baseline_report_id": self.baseline_report_id,
        }


def _decision_id(payload: Mapping[str, Any]) -> str:
    return "dec-" + content_digest(payload)[:20]


def decide(
    candidate: EvalReport,
    baseline: EvalReport,
    policy: PromotionPolicy | None = None,
    *,
    registered_policy_digest: str | None = None,
    active_harness_id: str | None,
) -> PromotionDecision:
    policy = policy or PromotionPolicy()
    policy_digest = policy.digest()

    if registered_policy_digest is not None and registered_policy_digest != policy_digest:
        raise PolicyMutationError(
            "the promotion policy changed after the experiment was registered; "
            "register a new experiment instead of moving the bar"
        )

    reasons: list[str] = []

    # A comparison is only meaningful against what is actually deployed: any
    # other baseline would let a candidate beat a straw man instead of the
    # harness it is meant to replace.
    if not active_harness_id:
        reasons.append(
            "no active harness was supplied; the baseline cannot be confirmed as current"
        )
    elif baseline.harness_id != active_harness_id:
        reasons.append(
            f"baseline harness {baseline.harness_id[:12]} is not the active harness "
            f"{active_harness_id[:12]}"
        )

    if candidate.suite_digest != baseline.suite_digest:
        reasons.append("baseline and candidate were evaluated against different suites")
    if policy.require_heldout and (
        candidate.split != "heldout" or baseline.split != "heldout"
    ):
        reasons.append(
            "promotion requires held-out evidence; evaluate both versions on the "
            "held-out split"
        )
    if candidate.repetitions != baseline.repetitions:
        reasons.append("baseline and candidate used different repetition counts")

    baseline_tasks = baseline.per_task_success()
    candidate_tasks = candidate.per_task_success()
    shared = sorted(set(baseline_tasks) & set(candidate_tasks))
    if len(shared) < policy.min_tasks:
        reasons.append(
            f"only {len(shared)} shared tasks; policy requires at least {policy.min_tasks}"
        )

    metrics: dict[str, float] = {
        "shared_tasks": float(len(shared)),
        "baseline_success_rate": round(baseline.success_rate, 6),
        "candidate_success_rate": round(candidate.success_rate, 6),
        "baseline_cost_per_task_usd": round(baseline.cost_per_task, 6),
        "candidate_cost_per_task_usd": round(candidate.cost_per_task, 6),
        "behavior_rate_delta": round(candidate.behavior_rate() - baseline.behavior_rate(), 6),
    }

    if shared:
        comparison = paired_comparison(baseline_tasks, candidate_tasks)
        metrics.update(
            {
                "delta": round(comparison.delta, 6),
                "p_value": round(comparison.p_value, 6),
                "candidate_only_tasks": float(comparison.candidate_only),
                "baseline_only_tasks": float(comparison.baseline_only),
            }
        )
        if comparison.delta < policy.min_effect:
            reasons.append(
                f"success delta {comparison.delta:+.3f} is below the required "
                f"{policy.min_effect:+.3f}"
            )
        if comparison.p_value > policy.alpha:
            reasons.append(
                f"paired p-value {comparison.p_value:.4f} exceeds alpha {policy.alpha}"
            )

        regressed = [
            task_id
            for task_id in shared
            if candidate_tasks[task_id] - baseline_tasks[task_id]
            < -policy.max_task_regression
        ]
        metrics["regressed_tasks"] = float(len(regressed))
        if len(regressed) > policy.max_regressed_tasks:
            reasons.append(
                "regressions on: " + ", ".join(regressed[:5])
            )

    baseline_cost = baseline.cost_per_task
    if baseline_cost > 0:
        cost_ratio = candidate.cost_per_task / baseline_cost
        metrics["cost_ratio"] = round(cost_ratio, 6)
        if cost_ratio > policy.max_cost_ratio:
            reasons.append(
                f"cost ratio {cost_ratio:.2f} exceeds the allowed {policy.max_cost_ratio:.2f}"
            )

    if metrics["behavior_rate_delta"] < policy.min_behavior_rate_delta:
        reasons.append(
            f"behaviour compliance dropped by {metrics['behavior_rate_delta']:+.3f}"
        )

    evidence_digest = content_digest(
        {
            "baseline_report": baseline.digest(),
            "candidate_report": candidate.digest(),
            "policy": policy_digest,
        }
    )

    payload = {
        "candidate_id": candidate.harness_id,
        "baseline_id": baseline.harness_id,
        "approved": not reasons,
        "metrics": metrics,
        "policy_digest": policy_digest,
        "evidence_digest": evidence_digest,
        "candidate_report_id": candidate.report_id,
        "baseline_report_id": baseline.report_id,
    }

    return PromotionDecision(
        decision_id=_decision_id(payload),
        candidate_id=candidate.harness_id,
        baseline_id=baseline.harness_id,
        approved=not reasons,
        reasons=tuple(reasons),
        metrics=metrics,
        policy_digest=policy_digest,
        evidence_digest=evidence_digest,
        candidate_report_id=candidate.report_id,
        baseline_report_id=baseline.report_id,
    )
