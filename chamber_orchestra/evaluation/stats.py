"""Paired statistics for promotion decisions.

Per-task outcomes are paired: the same task is run against the baseline and the
candidate, k times each. Comparing means without pairing hides which tasks
changed, and with a dozen tasks a single task is noise. McNemar's exact test on
the discordant pairs answers the question the gate actually asks: is the
candidate better often enough that chance is an unlikely explanation?
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping


def mean(values: list[float] | tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[int] | tuple[int, ...], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return (0.0, 1.0)
    phat = successes / n
    denominator = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for discordant counts ``b`` and ``c``."""
    if b < 0 or c < 0:
        raise ValueError("discordant counts must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, 2 * tail / (2**n))


@dataclass(frozen=True, slots=True)
class PairedComparison:
    """Per-task comparison of candidate against baseline."""

    tasks: int
    candidate_only: int  # tasks the candidate passes and the baseline does not
    baseline_only: int  # tasks the baseline passes and the candidate does not
    delta: float  # mean(candidate) - mean(baseline) over shared tasks
    p_value: float

    def document(self) -> dict[str, float | int]:
        return {
            "tasks": self.tasks,
            "candidate_only": self.candidate_only,
            "baseline_only": self.baseline_only,
            "delta": round(self.delta, 6),
            "p_value": round(self.p_value, 6),
        }


def paired_comparison(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    *,
    threshold: float = 0.5,
) -> PairedComparison:
    """Compare per-task pass rates on the tasks present in both reports."""
    shared = sorted(set(baseline) & set(candidate))
    if not shared:
        raise ValueError("no shared tasks between baseline and candidate reports")

    candidate_only = baseline_only = 0
    for task_id in shared:
        base_pass = baseline[task_id] >= threshold
        cand_pass = candidate[task_id] >= threshold
        if cand_pass and not base_pass:
            candidate_only += 1
        elif base_pass and not cand_pass:
            baseline_only += 1

    delta = mean([candidate[t] for t in shared]) - mean([baseline[t] for t in shared])
    return PairedComparison(
        tasks=len(shared),
        candidate_only=candidate_only,
        baseline_only=baseline_only,
        delta=delta,
        p_value=mcnemar_exact(candidate_only, baseline_only),
    )
