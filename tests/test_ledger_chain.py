"""The chain must make alteration, deletion, reordering and corruption visible."""

from __future__ import annotations

import pytest

from chamber_orchestra.experiment.prereg import PreRegistration
from chamber_orchestra.ledger.store import Ledger


def _record_run(ledger: Ledger, task_id: str) -> str:
    return ledger.record_run(
        report_id="rep-1",
        scope="coding",
        harness_id="h1",
        task_id=task_id,
        split="dev",
        attempt=0,
        success=True,
    )


def test_clean_ledger_verifies_and_keeps_its_key_outside_the_database(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    with Ledger(path) as ledger:
        _record_run(ledger, "t1")
        report = ledger.verify()

    assert report.ok, report.issues
    assert report.entries == 1
    key = tmp_path / "ledger.sqlite3.key"
    assert key.is_file()
    assert key.stat().st_mode & 0o777 == 0o600


def test_an_empty_ledger_verifies(tmp_path):
    with Ledger(tmp_path / "ledger.sqlite3") as ledger:
        assert ledger.verify().ok


def test_tampered_payload_is_detected(tmp_path):
    with Ledger(tmp_path / "ledger.sqlite3") as ledger:
        run_id = _record_run(ledger, "t1")
        ledger._conn.execute("DROP TRIGGER runs_no_update")
        ledger._conn.execute("UPDATE runs SET success = 0 WHERE run_id = ?", (run_id,))
        ledger._conn.commit()

        report = ledger.verify()

    assert not report.ok
    assert any("payload changed" in issue for issue in report.issues)


def test_deleted_record_is_detected(tmp_path):
    with Ledger(tmp_path / "ledger.sqlite3") as ledger:
        run_id = _record_run(ledger, "t1")
        _record_run(ledger, "t2")
        ledger._conn.execute("DROP TRIGGER runs_no_delete")
        ledger._conn.execute("DELETE FROM runs WHERE run_id != ?", (run_id,))
        ledger._conn.commit()

        report = ledger.verify()

    assert not report.ok
    assert any("no record" in issue or "records but" in issue for issue in report.issues)


def test_reordered_entries_are_detected(tmp_path):
    with Ledger(tmp_path / "ledger.sqlite3") as ledger:
        for task_id in ("t1", "t2", "t3"):
            _record_run(ledger, task_id)
        rows = ledger.chain_rows()
        first, second = rows[1], rows[2]
        ledger._conn.execute(
            "UPDATE chain SET entry_id = ?, payload_digest = ? WHERE seq = ?",
            (second["entry_id"], second["payload_digest"], first["seq"]),
        )
        ledger._conn.execute(
            "UPDATE chain SET entry_id = ?, payload_digest = ? WHERE seq = ?",
            (first["entry_id"], first["payload_digest"], second["seq"]),
        )
        ledger._conn.commit()

        report = ledger.verify()

    assert not report.ok
    assert any("reordered" in issue for issue in report.issues)


def test_corrupted_seal_is_detected(tmp_path):
    with Ledger(tmp_path / "ledger.sqlite3") as ledger:
        _record_run(ledger, "t1")
        ledger._conn.execute("UPDATE chain SET mac = ? WHERE seq = 1", ("0" * 64,))
        ledger._conn.commit()

        report = ledger.verify()

    assert not report.ok
    assert any("invalid seal" in issue for issue in report.issues)


def test_deleted_chain_entry_is_detected(tmp_path):
    with Ledger(tmp_path / "ledger.sqlite3") as ledger:
        for task_id in ("t1", "t2", "t3"):
            _record_run(ledger, task_id)
        ledger._conn.execute("DELETE FROM chain WHERE seq = 2")
        ledger._conn.commit()

        report = ledger.verify()

    assert not report.ok
    assert any("not contiguous" in issue for issue in report.issues)


def test_opening_an_older_database_backfills_the_chain(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    with Ledger(path) as ledger:
        _record_run(ledger, "before-the-chain")
        ledger._conn.execute("DELETE FROM chain")
        ledger._conn.execute("PRAGMA user_version = 1")
        ledger._conn.commit()

    with Ledger(path) as reopened:
        report = reopened.verify()
        assert report.ok, report.issues
        assert report.entries == 1


def test_pre_registration_is_chained(tmp_path):
    prereg = PreRegistration(
        scope="coding",
        baseline_id="base",
        candidate_id="cand",
        suite_name="tiny",
        suite_digest="suite",
    )
    with Ledger(tmp_path / "ledger.sqlite3") as ledger:
        ledger.register_experiment(prereg)
        assert ledger.verify().ok
        assert ledger.chain_counts()["experiment"] == 1
        assert ledger.chain_counts()["experiment_event"] == 1
