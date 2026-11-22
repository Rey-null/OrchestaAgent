"""Deterministic proposer: a baseline that costs nothing and can be audited.

It reads the behaviour gaps observed on dev runs and proposes the smallest
declarative change that addresses them. Swapping in a model-backed proposer is
a drop-in replacement behind the same protocol; this one exists so the
machinery can be tested without spending a token, and so the boundary between
"proposal" and "evidence" is visible in the code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from chamber_orchestra.harness.manifest import HarnessManifest, content_digest
from chamber_orchestra.harness.patch import HarnessPatch, PatchOp
from chamber_orchestra.proposer.base import ProposalContext, ProposalError

_SKILL_LIBRARY: dict[str, str] = {
    "runs_tests": (
        "Before declaring the task complete, run the project's test suite. "
        "Record the exact command and its result in the final report."
    ),
    "checks_requirements": (
        "Restate every acceptance criterion, then verify each one against the "
        "deliverable before finishing. Unverified criteria are reported as gaps."
    ),
    "reports_evidence": (
        "Cite the command, file or source supporting each claim. A claim "
        "without evidence is not reported as done."
    ),
    "confirms_scope": (
        "Confirm ambiguous requirements before implementing them. Do not "
        "silently widen the scope of the task."
    ),
}


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "behavior"


def skill_text_for(behavior: str) -> str:
    return _SKILL_LIBRARY.get(
        behavior,
        f"Apply {behavior!r} as a required step, and show the evidence that it happened.",
    )


@dataclass(frozen=True, slots=True)
class DeterministicProposer:
    """Proposes the missing behaviours with the strongest dev evidence."""

    min_support: int = 1

    def propose(
        self, manifest: HarnessManifest, context: ProposalContext
    ) -> HarnessPatch:
        if context.base_id != manifest.id:
            raise ProposalError(
                f"context was built for base {context.base_id}, not {manifest.id}"
            )

        declared = set(manifest.declared_behaviors())
        candidates = [
            (behavior, count)
            for behavior, count in context.missing_counts.items()
            if count >= self.min_support and behavior not in declared
        ]
        if not candidates:
            raise ProposalError(
                "no evidence-backed behavior gap found for this base harness"
            )

        candidates.sort(key=lambda item: (-item[1], item[0]))
        new_behaviors = [behavior for behavior, _ in candidates]
        merged = sorted(declared | set(new_behaviors))

        ops: list[PatchOp] = [
            PatchOp(op="set", target="tool_guidance/behaviors", value=merged)
        ]
        for behavior in new_behaviors:
            ops.append(
                PatchOp(
                    op="set",
                    target=f"skills/{_slug(behavior)}",
                    value=skill_text_for(behavior),
                )
            )

        rationale = "; ".join(
            f"{behavior}: missed in {count} failed dev run(s)"
            for behavior, count in candidates
        )
        proposal_id = "prop-" + content_digest(
            {"base": manifest.id, "behaviors": merged, "ops": [op.document() for op in ops]}
        )[:20]

        return HarnessPatch(
            proposal_id=proposal_id,
            base=manifest.id,
            rationale=rationale,
            ops=tuple(ops),
        )
