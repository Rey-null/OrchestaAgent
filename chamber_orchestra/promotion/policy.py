"""Promotion policy: the criteria that must be fixed *before* an experiment.

Tuning the bar after seeing the results is how a self-improvement loop turns
into a scoring loop. The policy is a value object with a content digest; the
decision records that digest, and the gate refuses to decide if the caller
presents a different digest than the one that was registered for the
experiment.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from chamber_orchestra.harness.manifest import content_digest


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    # Statistical bar.
    alpha: float = 0.05
    min_effect: float = 0.10
    min_tasks: int = 8

    # Cost and regression guards.
    max_cost_ratio: float = 1.35
    max_task_regression: float = 0.25
    max_regressed_tasks: int = 0
    min_behavior_rate_delta: float = 0.0

    # Evidence requirements.
    require_heldout: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        if not 0 <= self.min_effect <= 1:
            raise ValueError("min_effect must be in [0, 1]")
        if self.min_tasks < 1:
            raise ValueError("min_tasks must be at least 1")
        if self.max_cost_ratio <= 0:
            raise ValueError("max_cost_ratio must be positive")
        if not 0 <= self.max_task_regression <= 1:
            raise ValueError("max_task_regression must be in [0, 1]")
        if self.max_regressed_tasks < 0:
            raise ValueError("max_regressed_tasks must be non-negative")

    def document(self) -> dict[str, Any]:
        return asdict(self)

    def digest(self) -> str:
        return content_digest(self.document())


def default_policy() -> PromotionPolicy:
    return PromotionPolicy()
