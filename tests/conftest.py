from __future__ import annotations

import uuid
from typing import Mapping

import pytest

from chamber_orchestra.evaluation.models import CaseAttempt, EvalReport
from chamber_orchestra.evaluation.suite import default_suite
from chamber_orchestra.harness.manifest import HarnessManifest


@pytest.fixture
def suite():
    return default_suite()


@pytest.fixture
def baseline_manifest() -> HarnessManifest:
    return HarnessManifest(
        scope="coding",
        components={
            "prompt": "You are a coding agent.",
            "tool_guidance": {"behaviors": ["reports_evidence"]},
        },
    )


def fake_report(
    tasks: Mapping[str, float],
    *,
    cost_per_task: float = 0.02,
    split: str = "heldout",
    suite_digest: str = "suite-1",
    harness_id: str = "harness-baseline",
    repetitions: int = 2,
    report_id: str | None = None,
) -> EvalReport:
    attempts: list[CaseAttempt] = []
    for task_id, rate in tasks.items():
        passes = round(rate * repetitions)
        for attempt in range(repetitions):
            attempts.append(
                CaseAttempt(
                    task_id=task_id,
                    harness_id=harness_id,
                    attempt=attempt,
                    success=attempt < passes,
                    cost_usd=cost_per_task / repetitions,
                    latency_ms=100,
                    iterations=3,
                )
            )
    return EvalReport(
        report_id=report_id or uuid.uuid4().hex,
        harness_id=harness_id,
        suite_name="fake",
        suite_digest=suite_digest,
        split=split,
        repetitions=repetitions,
        attempts=tuple(attempts),
    )
