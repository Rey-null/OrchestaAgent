from __future__ import annotations

import sqlite3

import pytest

from chamber_orchestra.ledger.store import Ledger
from tests.conftest import fake_report


@pytest.fixture
def ledger() -> Ledger:
    with Ledger(":memory:") as store:
        yield store


def test_record_and_filter_runs(ledger):
    run_id = ledger.record_run(
        report_id="rep-1",
        scope="coding",
        harness_id="h1",
        task_id="dev-code-01",
        split="dev",
        attempt=0,
        success=False,
        behaviors=["reports_evidence"],
        missing_behaviors=["runs_tests"],
        cost_usd=0.03,
        latency_ms=250,
        iterations=5,
        interventions=1,
        detail={"kind": "coding"},
    )
    ledger.record_run(
        report_id="rep-2",
        scope="coding",
        harness_id="h1",
        task_id="held-code-01",
        split="heldout",
        attempt=0,
        success=True,
    )

    assert run_id
    dev_runs = ledger.runs(scope="coding", split="dev")
    assert len(dev_runs) == 1
    assert dev_runs[0]["task_id"] == "dev-code-01"
    assert dev_runs[0]["success"] is False
    assert dev_runs[0]["missing_behaviors"] == ["runs_tests"]
    assert dev_runs[0]["detail"] == {"kind": "coding"}


def test_runs_are_listed_newest_first(ledger):
    for task_id in ("t1", "t2", "t3"):
        ledger.record_run(
            report_id="rep",
            scope="coding",
            harness_id="h1",
            task_id=task_id,
            split="dev",
            attempt=0,
            success=True,
        )

    page = ledger.runs(scope="coding", split="dev", limit=2)
    assert [run["task_id"] for run in page] == ["t3", "t2"]


def test_runs_are_append_only(ledger):
    ledger.record_run(
        report_id="rep-1",
        scope="coding",
        harness_id="h1",
        task_id="t1",
        split="dev",
        attempt=0,
        success=True,
    )
    with pytest.raises(sqlite3.IntegrityError):
        ledger._conn.execute("UPDATE runs SET success = 0")
    with pytest.raises(sqlite3.IntegrityError):
        ledger._conn.execute("DELETE FROM runs")


def test_decisions_are_append_only_and_queryable(ledger):
    report = fake_report({"t1": 1.0, "t2": 1.0})
    ledger.record_report(report, scope="coding")
    decision_payload = type(
        "Decision",
        (),
        {
            "decision_id": "dec-1",
            "candidate_id": "cand",
            "baseline_id": "base",
            "approved": True,
            "policy_digest": "pd",
            "metrics": {"delta": 0.5},
            "reasons": [],
            "evidence_digest": "ev",
        },
    )()
    ledger.record_decision(decision_payload, scope="coding")

    assert ledger.is_approved("dec-1")
    assert ledger.get_decision("dec-1")["metrics"] == {"delta": 0.5}
    with pytest.raises(sqlite3.IntegrityError):
        ledger._conn.execute("UPDATE decisions SET approved = 0")


def test_report_roundtrip_and_counts(ledger):
    report = fake_report({"t1": 1.0})
    ledger.record_report(report, scope="coding")

    payload = ledger.get_report(report.report_id)
    assert payload is not None
    assert payload["harness_id"] == report.harness_id
    assert ledger.counts()["reports"] == 1
    assert ledger.get_report("missing") is None
