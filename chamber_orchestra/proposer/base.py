"""What the optimizer is allowed to know.

The information barrier is built here, not trusted to the caller: a context can
only be assembled from runs on the dev split, against the exact base harness
being patched. Held-out tasks never reach the proposer, so a proposal cannot be
tuned to the tasks that will decide whether it gets promoted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from chamber_orchestra.harness.manifest import HarnessManifest
from chamber_orchestra.harness.patch import HarnessPatch


class ProposalError(RuntimeError):
    """Raised when no evidence-backed proposal can be made."""


@dataclass(frozen=True, slots=True)
class ProposalContext:
    scope: str
    base_id: str
    evidence_run_ids: tuple[str, ...]
    missing_counts: Mapping[str, int]
    failed_tasks: tuple[str, ...]
    dropped_runs: int = 0

    @classmethod
    def from_runs(
        cls,
        *,
        scope: str,
        base_id: str,
        runs: Iterable[Mapping[str, Any]],
        allowed_splits: tuple[str, ...] = ("dev",),
    ) -> "ProposalContext":
        accepted: list[Mapping[str, Any]] = []
        dropped = 0
        for run in runs:
            split = run.get("split")
            if split not in allowed_splits or run.get("harness_id") != base_id:
                dropped += 1
                continue
            accepted.append(run)

        counts: Counter[str] = Counter()
        failed: list[str] = []
        for run in accepted:
            if run.get("success"):
                continue
            failed.append(str(run["task_id"]))
            for behavior in run.get("missing_behaviors", ()):
                counts[str(behavior)] += 1

        return cls(
            scope=scope,
            base_id=base_id,
            evidence_run_ids=tuple(str(run["run_id"]) for run in accepted),
            missing_counts=dict(sorted(counts.items())),
            failed_tasks=tuple(sorted(set(failed))),
            dropped_runs=dropped,
        )

    def document(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "base_id": self.base_id,
            "evidence_run_ids": list(self.evidence_run_ids),
            "missing_counts": dict(self.missing_counts),
            "failed_tasks": list(self.failed_tasks),
            "dropped_runs": self.dropped_runs,
        }


class Proposer(Protocol):
    def propose(
        self, manifest: HarnessManifest, context: ProposalContext
    ) -> HarnessPatch: ...
