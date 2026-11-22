"""Executor boundary.

``Executor`` is the seam where a real coding/research agent plugs in. The
shipped implementation is a deterministic simulator: it consumes the behaviours
a harness declares and turns them into observable traces, with a fixed
compliance rate. It does not prove that a model is good. It proves the loop
around the model works - proposals change behaviour, behaviour changes
outcomes, and the gate can tell a real gain from a regression - which is the
part that must be trustworthy before any model is connected.

The simulator is seeded from (task, harness, attempt), so results are
reproducible and a rerun of the same configuration yields the same report.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol

from chamber_orchestra.evaluation.models import CaseAttempt, Task
from chamber_orchestra.harness.manifest import HarnessManifest


SIMULATOR_VERSION = "simulator-1"

# Markers of a harness whose prose contradicts its declared guidance. The
# simulator models them explicitly so a mutation test can prove the suite
# notices a sabotaged harness instead of averaging it away.
_SABOTAGE_MARKERS: tuple[str, ...] = (
    "skip verification",
    "skip the tests",
    "do not run tests",
    "without evidence",
    "report success without",
)


class Executor(Protocol):
    def execute(
        self, task: Task, harness: HarnessManifest, attempt: int
    ) -> CaseAttempt: ...


def _sabotage_marker(harness: HarnessManifest) -> str | None:
    texts: list[str] = []
    prompt = harness.components.get("prompt")
    if isinstance(prompt, str):
        texts.append(prompt)
    for component in ("skills", "tool_guidance"):
        value = harness.components.get(component)
        if isinstance(value, dict):
            texts.extend(item for item in value.values() if isinstance(item, str))
        elif isinstance(value, str):
            texts.append(value)
    folded = " ".join(texts).casefold()
    for marker in _SABOTAGE_MARKERS:
        if marker in folded:
            return marker
    return None


def _uniform(*parts: object) -> float:
    seed = "|".join(str(part) for part in parts).encode("utf-8")
    return int(hashlib.sha256(seed).hexdigest()[:16], 16) / float(1 << 64)


def declared_behaviors(harness: HarnessManifest) -> tuple[str, ...]:
    """Behaviours the harness claims to enforce, read from tool guidance."""
    guidance = harness.components.get("tool_guidance", {})
    if not isinstance(guidance, dict):
        return ()
    raw = guidance.get("behaviors", ())
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(sorted({str(item) for item in raw}))


@dataclass(frozen=True, slots=True)
class SimulatedExecutor:
    """Deterministic stand-in for a real agent, driven by harness guidance."""

    compliance: float = 0.9
    base_cost_usd: float = 0.02
    cost_per_declared_usd: float = 0.002
    cost_per_missing_usd: float = 0.004
    base_iterations: int = 3

    @property
    def version(self) -> str:
        return SIMULATOR_VERSION

    def execute(
        self, task: Task, harness: HarnessManifest, attempt: int
    ) -> CaseAttempt:
        declared = set(declared_behaviors(harness))
        required = tuple(sorted(set(task.required_behaviors)))
        sabotage = _sabotage_marker(harness)

        observed: list[str] = []
        if sabotage is None:
            for behavior in required:
                if behavior not in declared:
                    continue
                draw = _uniform(task.id, harness.id, attempt, behavior)
                if draw < self.compliance:
                    observed.append(behavior)

        missing = tuple(behavior for behavior in required if behavior not in observed)
        success = not missing

        iterations = self.base_iterations + 2 * len(missing)
        cost = (
            self.base_cost_usd
            + self.cost_per_declared_usd * len(declared)
            + self.cost_per_missing_usd * len(missing)
        )
        jitter = _uniform(task.id, harness.id, attempt, "latency")
        latency_ms = 120 + 35 * iterations + int(jitter * 200)

        return CaseAttempt(
            task_id=task.id,
            harness_id=harness.id,
            attempt=attempt,
            success=success,
            behaviors=tuple(observed),
            missing_behaviors=missing,
            cost_usd=round(cost, 6),
            latency_ms=latency_ms,
            iterations=iterations,
            interventions=0,
            detail={
                "kind": task.kind,
                "declared_behaviors": sorted(declared),
                "difficulty": task.difficulty,
                "simulated": True,
                "sabotage_marker": sabotage,
            },
        )


def deterministic_ratio(*parts: object) -> float:
    """Exposed for tests that need the same deterministic draw."""
    return math.floor(_uniform(*parts) * 1_000_000) / 1_000_000
