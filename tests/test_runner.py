from __future__ import annotations

import pytest

from chamber_orchestra.evaluation.models import Task
from chamber_orchestra.evaluation.runner import EvalRunner, SuiteTamperedError
from chamber_orchestra.evaluation.suite import (
    SuiteError,
    TaskSuite,
    assert_suite_is_protected,
    dump_suite,
    load_suite,
)
from chamber_orchestra.execution.executor import SimulatedExecutor
from chamber_orchestra.harness.manifest import HarnessManifest
from chamber_orchestra.harness.registry import HarnessStore


def _manifest() -> HarnessManifest:
    return HarnessManifest(
        scope="coding",
        components={"tool_guidance": {"behaviors": ["reports_evidence"]}},
    )


def test_repetitions_and_splits(tmp_path, suite):
    store = HarnessStore(tmp_path / "store")
    manifest = _manifest()
    store.put(manifest)

    runner = EvalRunner(suite, SimulatedExecutor(), store=store)
    report = runner.evaluate(manifest, split="dev", repetitions=2)

    assert len(report.attempts) == len(suite.split("dev")) * 2
    assert report.repetitions == 2
    assert report.suite_digest == suite.digest
    assert report.harness_id == manifest.id


def test_evaluation_is_deterministic(tmp_path, suite):
    store = HarnessStore(tmp_path / "store")
    manifest = _manifest()
    store.put(manifest)
    runner = EvalRunner(suite, SimulatedExecutor(), store=store)

    first = runner.evaluate(manifest, split="heldout", repetitions=3)
    second = runner.evaluate(manifest, split="heldout", repetitions=3)

    assert first.per_task_success() == second.per_task_success()
    assert first.report_id != second.report_id
    assert first.digest() != second.digest()


def test_run_sink_receives_split(tmp_path, suite):
    store = HarnessStore(tmp_path / "store")
    manifest = _manifest()
    store.put(manifest)

    seen: list[tuple[str, str, str | None]] = []
    runner = EvalRunner(
        suite,
        SimulatedExecutor(),
        store=store,
        run_sink=lambda outcome, report_id, split, experiment_id: seen.append(
            (outcome.task_id, split, experiment_id)
        ),
    )
    runner.evaluate(manifest, split="dev", repetitions=1, experiment_id="exp-test")

    assert seen
    assert {split for _, split, _ in seen} == {"dev"}
    assert {experiment_id for _, _, experiment_id in seen} == {"exp-test"}


def test_suite_change_during_experiment_is_detected(tmp_path, suite):
    suite_path = tmp_path / "suite.json"
    dump_suite(suite, suite_path)
    loaded = load_suite(suite_path)

    runner = EvalRunner(loaded, SimulatedExecutor(), suite_path=suite_path)
    replacement = TaskSuite(
        name="tampered",
        tasks=(Task(id="dev-1", split="dev", prompt="rewritten after registration"),),
    )
    dump_suite(replacement, suite_path)

    with pytest.raises(SuiteTamperedError):
        runner.evaluate(_manifest(), split="dev", repetitions=1)


def test_suite_inside_editable_store_is_refused(tmp_path):
    store_root = tmp_path / "store"
    suite_path = store_root / "harnesses" / "suite.json"
    suite_path.parent.mkdir(parents=True)
    suite_path.write_text("{}", encoding="utf-8")

    with pytest.raises(SuiteError):
        assert_suite_is_protected(suite_path, store_root)
