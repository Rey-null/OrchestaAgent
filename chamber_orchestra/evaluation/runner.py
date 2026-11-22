"""Evaluation runner.

The runner is boring on purpose: it executes every task k times against a fixed
harness, records what happened, and refuses to hand back a report if the suite
changed underneath it. It never decides whether a change is good - that is the
gate's job, using the report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from chamber_orchestra.evaluation.models import CaseAttempt, EvalReport, new_report_id
from chamber_orchestra.evaluation.suite import (
    SuiteError,
    TaskSuite,
    assert_suite_is_protected,
    load_suite,
)
from chamber_orchestra.execution.executor import Executor
from chamber_orchestra.harness.manifest import HarnessManifest
from chamber_orchestra.harness.registry import HarnessStore

RunSink = Callable[[CaseAttempt, str, str, str | None], None]


class SuiteTamperedError(RuntimeError):
    """Raised when the suite changes between the start and the end of a run."""


class EvalRunner:
    def __init__(
        self,
        suite: TaskSuite,
        executor: Executor,
        *,
        store: HarnessStore | None = None,
        suite_path: str | Path | None = None,
        run_sink: RunSink | None = None,
    ) -> None:
        self.suite = suite
        self.executor = executor
        self.store = store
        self.suite_path = Path(suite_path) if suite_path is not None else None
        self.run_sink = run_sink

        if self.suite_path is not None and store is not None:
            assert_suite_is_protected(self.suite_path, store.root)

    def evaluate(
        self,
        harness: HarnessManifest,
        *,
        split: str,
        repetitions: int = 3,
        experiment_id: str | None = None,
    ) -> EvalReport:
        if repetitions < 1:
            raise ValueError("repetitions must be at least 1")
        tasks = self.suite.split(split)
        if not tasks:
            raise SuiteError(f"split {split!r} has no tasks")

        # A harness must be stored before it can produce evidence; otherwise a
        # report could reference a version that no one can retrieve later.
        if self.store is not None:
            stored = self.store.get(harness.id)
            if stored.id != harness.id:
                raise SuiteError("harness does not match the stored version")

        if self.suite_path is not None:
            if self.store is not None:
                assert_suite_is_protected(self.suite_path, self.store.root)
            before = load_suite(self.suite_path).digest
            if before != self.suite.digest:
                raise SuiteTamperedError(
                    f"suite on disk ({before}) differs from the loaded suite "
                    f"({self.suite.digest}) before evaluation"
                )

        report_id = new_report_id()
        attempts: list[CaseAttempt] = []
        for task in tasks:
            for attempt in range(repetitions):
                outcome = self.executor.execute(task, harness, attempt)
                attempts.append(outcome)
                if self.run_sink is not None:
                    self.run_sink(outcome, report_id, split, experiment_id)

        if self.suite_path is not None:
            after = load_suite(self.suite_path).digest
            if after != self.suite.digest:
                raise SuiteTamperedError("suite changed during evaluation")

        return EvalReport(
            report_id=report_id,
            harness_id=harness.id,
            suite_name=self.suite.name,
            suite_digest=self.suite.digest,
            split=split,
            repetitions=repetitions,
            attempts=tuple(attempts),
        )
