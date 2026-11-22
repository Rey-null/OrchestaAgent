from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from chamber_orchestra.evaluation.models import Task
from chamber_orchestra.evaluation.suite import TaskSuite
from chamber_orchestra.experiment.flow import (
    FlowError,
    PreregistrationError,
    run_experiment,
)
from chamber_orchestra.experiment.prereg import ExperimentLimits, PreRegistration
from chamber_orchestra.execution.executor import SimulatedExecutor
from chamber_orchestra.harness.manifest import HarnessManifest
from chamber_orchestra.harness.registry import HarnessStore
from chamber_orchestra.ledger.store import Ledger


def _suite() -> TaskSuite:
    dev = tuple(
        Task(
            id=f"dev-{index:02d}",
            split="dev",
            prompt=f"Dev coding task {index} about caching layers",
            kind="coding",
            required_behaviors=("runs_tests",),
        )
        for index in range(1, 4)
    )
    heldout = tuple(
        Task(
            id=f"held-{index:02d}",
            split="heldout",
            prompt=f"Held out coding task {index} about retry policies",
            kind="coding",
            required_behaviors=("runs_tests", "checks_requirements"),
        )
        for index in range(1, 10)
    )
    return TaskSuite(name="tiny-v1", tasks=dev + heldout)


def _baseline() -> HarnessManifest:
    return HarnessManifest(scope="coding", components={"prompt": "You are a coding agent."})


def _candidate(baseline: HarnessManifest) -> HarnessManifest:
    return HarnessManifest(
        scope="coding",
        components={
            "prompt": "You are a coding agent.",
            "tool_guidance": {
                "behaviors": ["runs_tests", "checks_requirements"]
            },
        },
        parent=baseline.id,
    )


def _prereg(
    suite: TaskSuite, baseline: HarnessManifest, candidate: HarnessManifest, **overrides
) -> PreRegistration:
    values = dict(
        scope="coding",
        baseline_id=baseline.id,
        candidate_id=candidate.id,
        suite_name=suite.name,
        suite_digest=suite.digest,
        limits=ExperimentLimits(repetitions=2, max_attempts=100),
    )
    values.update(overrides)
    return PreRegistration(**values)


def _setup(tmp_path: Path, **overrides):
    store = HarnessStore(tmp_path / "store")
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    suite = _suite()
    baseline = _baseline()
    store.initialize(baseline)
    candidate = _candidate(baseline)
    store.put(candidate)
    prereg = _prereg(suite, baseline, candidate, **overrides)
    ledger.register_experiment(prereg)
    return store, ledger, suite, baseline, candidate, prereg


def _run(tmp_path: Path, **overrides):
    store, ledger, suite, baseline, candidate, prereg = _setup(tmp_path, **overrides)
    outcome = run_experiment(
        ledger=ledger,
        store=store,
        suite=suite,
        executor=SimulatedExecutor(),
        prereg=prereg,
        artifacts_root=tmp_path / "artifacts",
    )
    return ledger, suite, baseline, candidate, prereg, outcome


def test_comparison_runs_end_to_end_and_records_provenance(tmp_path):
    ledger, suite, baseline, candidate, prereg, outcome = _run(tmp_path)

    assert outcome.state == "completed", outcome.reasons
    assert outcome.approved is True
    assert outcome.decision_id and outcome.candidate_report_id
    assert ledger.experiment_state(prereg.experiment_id) == "completed"
    assert [event["state"] for event in ledger.experiment_events(prereg.experiment_id)] == [
        "registered",
        "validated",
        "running",
        "evaluated",
        "completed",
    ]

    reports = ledger.reports_for_experiment(prereg.experiment_id)
    assert {item["harness_id"] for item in reports} == {baseline.id, candidate.id}
    assert all(item["suite_digest"] == suite.digest for item in reports)

    provenance = ledger.provenance(experiment_id=prereg.experiment_id)
    heldout_attempts = len(suite.split("heldout")) * 2
    assert len(provenance) == heldout_attempts * 2

    document = provenance[0]["document"]
    assert document["experiment_id"] == prereg.experiment_id
    assert document["suite_digest"] == suite.digest
    assert len(document["prompt_sha256"]) == 64
    assert document["executor"]["status"] == "available"
    assert document["executor"]["value"]["version"] == "simulator-1"
    # the simulator cannot take a seed, and that is stated rather than invented
    assert document["seed"]["status"] == "unsupported"
    assert document["model"]["status"] == "unsupported"
    assert document["tool_log"]["status"] == "available"
    assert Path(document["tool_log"]["value"]["uri"]).is_file()

    decision = ledger.decisions(experiment_id=prereg.experiment_id)[0]
    assert decision["approved"] is True
    assert decision["experiment_id"] == prereg.experiment_id
    assert ledger.verify().ok


def test_rerunning_a_finished_experiment_reuses_its_evidence(tmp_path):
    ledger, _, _, _, prereg, first = _run(tmp_path)
    before = (ledger.counts()["runs"], ledger.counts()["reports"], ledger.counts()["decisions"])

    second = run_experiment(
        ledger=ledger,
        store=HarnessStore(tmp_path / "store"),
        suite=_suite(),
        executor=SimulatedExecutor(),
        prereg=prereg,
        artifacts_root=tmp_path / "artifacts",
    )

    after = (ledger.counts()["runs"], ledger.counts()["reports"], ledger.counts()["decisions"])
    assert before == after
    assert second.document() == first.document()


def test_changed_criteria_cannot_produce_a_decision(tmp_path):
    store, ledger, suite, baseline, candidate, prereg = _setup(tmp_path)
    run_experiment(
        ledger=ledger,
        store=store,
        suite=suite,
        executor=SimulatedExecutor(),
        prereg=prereg,
        artifacts_root=tmp_path / "artifacts",
    )

    edited = _prereg(
        suite,
        baseline,
        candidate,
        policy=prereg.policy.__class__(min_effect=0.9),
    )
    assert edited.experiment_id != prereg.experiment_id

    with pytest.raises(PreregistrationError):
        run_experiment(
            ledger=ledger,
            store=store,
            suite=suite,
            executor=SimulatedExecutor(),
            prereg=edited,
            artifacts_root=tmp_path / "artifacts",
        )

    assert len(ledger.decisions(experiment_id=edited.experiment_id)) == 0


def test_an_unregistered_comparison_cannot_start(tmp_path):
    store, ledger, suite, baseline, candidate, _ = _setup(tmp_path)
    unregistered = _prereg(
        suite, baseline, candidate, inclusion_criteria=("a criterion nobody registered",)
    )
    assert ledger.get_experiment(unregistered.experiment_id) is None

    with pytest.raises(PreregistrationError):
        run_experiment(
            ledger=ledger,
            store=store,
            suite=suite,
            executor=SimulatedExecutor(),
            prereg=unregistered,
            artifacts_root=tmp_path / "artifacts",
        )

    assert ledger.counts()["runs"] == 0


def test_suite_mismatch_leaves_the_experiment_invalid(tmp_path):
    store, ledger, suite, baseline, candidate, _ = _setup(tmp_path)
    prereg = _prereg(suite, baseline, candidate, suite_digest="0" * 64)
    ledger.register_experiment(prereg)

    with pytest.raises(FlowError, match="suite"):
        run_experiment(
            ledger=ledger,
            store=store,
            suite=suite,
            executor=SimulatedExecutor(),
            prereg=prereg,
            artifacts_root=tmp_path / "artifacts",
        )

    assert ledger.experiment_state(prereg.experiment_id) == "invalid"
    assert ledger.decisions(experiment_id=prereg.experiment_id) == []
    assert ledger.provenance(experiment_id=prereg.experiment_id) == []


def test_baseline_must_be_active_before_the_run_starts(tmp_path):
    store, ledger, suite, baseline, candidate, _ = _setup(tmp_path)
    # a stored harness that was never promoted cannot act as the baseline
    stored = HarnessManifest(
        scope="coding", components={"prompt": "Another harness"}, parent=baseline.id
    )
    store.put(stored)
    prereg = _prereg(suite, stored, candidate)
    ledger.register_experiment(prereg)

    with pytest.raises(FlowError, match="active"):
        run_experiment(
            ledger=ledger,
            store=store,
            suite=suite,
            executor=SimulatedExecutor(),
            prereg=prereg,
            artifacts_root=tmp_path / "artifacts",
        )
    assert ledger.experiment_state(prereg.experiment_id) == "invalid"


def test_leaked_context_blocks_before_any_task_runs(tmp_path):
    store, ledger, suite, baseline, candidate, prereg = _setup(tmp_path)
    context = SimpleNamespace(
        document=lambda: {"failed_tasks": ["dev-01", "held-01"]}
    )

    with pytest.raises(Exception, match="held-01"):
        run_experiment(
            ledger=ledger,
            store=store,
            suite=suite,
            executor=SimulatedExecutor(),
            prereg=prereg,
            context=context,
            artifacts_root=tmp_path / "artifacts",
        )

    assert ledger.experiment_state(prereg.experiment_id) == "invalid"
    assert ledger.counts()["runs"] == 0
    assert ledger.decisions(experiment_id=prereg.experiment_id) == []


class _FailingExecutor(SimulatedExecutor):
    def execute(self, task, harness, attempt):
        if harness.components.get("tool_guidance"):
            raise RuntimeError("executor crashed on the candidate")
        return super().execute(task, harness, attempt)


def test_executor_failure_is_failed_never_approved(tmp_path):
    store, ledger, suite, baseline, candidate, prereg = _setup(tmp_path)

    with pytest.raises(RuntimeError, match="crashed"):
        run_experiment(
            ledger=ledger,
            store=store,
            suite=suite,
            executor=_FailingExecutor(),
            prereg=prereg,
            artifacts_root=tmp_path / "artifacts",
        )

    assert ledger.experiment_state(prereg.experiment_id) == "failed"
    assert ledger.decisions(experiment_id=prereg.experiment_id) == []
    assert ledger.verify().ok
