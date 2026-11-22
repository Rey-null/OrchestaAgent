"""Tests for the `chamber` CLI.

`app.main()` keeps serving from four environment variables (exercised below
without binding a port); `chamber` adds register/run/verify/export on top.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
import uvicorn

import chamber_orchestra.api.app as app_module
from chamber_orchestra.evaluation.suite import (
    SuiteError,
    default_suite,
    dump_suite,
)


VARIABLES = ("CHAMBER_ROOT", "CHAMBER_HOST", "CHAMBER_PORT", "CHAMBER_SUITE")


@pytest.fixture
def launched(monkeypatch):
    """Capture what `main()` would hand to uvicorn instead of serving it."""
    calls: dict[str, object] = {}

    def fake_run(app, **kwargs):
        calls["app"] = app
        calls.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    return calls


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_main_uses_loopback_defaults(launched, clean_environment):
    app_module.main()

    assert launched["host"] == "127.0.0.1"
    assert launched["port"] == 8000
    assert launched["app"].state.suite.name == "recurring-v1"
    # the default root is relative to the working directory
    assert (clean_environment / ".runtime" / "harnesses").is_dir()


def test_main_reads_the_environment(monkeypatch, launched, clean_environment):
    root = clean_environment / "state"
    monkeypatch.setenv("CHAMBER_ROOT", str(root))
    monkeypatch.setenv("CHAMBER_HOST", "0.0.0.0")
    monkeypatch.setenv("CHAMBER_PORT", "9111")

    app_module.main()

    assert launched["host"] == "0.0.0.0"
    assert launched["port"] == 9111
    assert (root / "harnesses").is_dir()
    assert (root / "ledger.sqlite3").exists()
    # nothing was written to the default root
    assert not (clean_environment / ".runtime").exists()


def test_main_loads_the_suite_behind_chamber_suite(
    monkeypatch, launched, clean_environment
):
    suite_path = clean_environment / "suite.json"
    custom = replace(default_suite(), name="piped-suite")
    dump_suite(custom, suite_path)
    monkeypatch.setenv("CHAMBER_ROOT", str(clean_environment / "state"))
    monkeypatch.setenv("CHAMBER_SUITE", str(suite_path))

    app_module.main()

    suite = launched["app"].state.suite
    assert suite.name == "piped-suite"
    assert suite.digest == custom.digest


def test_main_refuses_a_non_numeric_port(monkeypatch):
    monkeypatch.setenv("CHAMBER_PORT", "not-a-port")

    with pytest.raises(ValueError):
        app_module.main()


def test_verify_command_accepts_a_clean_ledger(tmp_path, capsys):
    from chamber_orchestra.cli import main as cli_main
    from chamber_orchestra.ledger.store import Ledger

    path = tmp_path / "ledger.sqlite3"
    with Ledger(path) as ledger:
        ledger.record_run(
            report_id="r",
            scope="coding",
            harness_id="h",
            task_id="t",
            split="dev",
            attempt=0,
            success=True,
        )

    assert cli_main(["verify", "--ledger", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_verify_command_rejects_a_tampered_ledger(tmp_path, capsys):
    from chamber_orchestra.cli import main as cli_main
    from chamber_orchestra.ledger.store import Ledger

    path = tmp_path / "ledger.sqlite3"
    with Ledger(path) as ledger:
        run_id = ledger.record_run(
            report_id="r",
            scope="coding",
            harness_id="h",
            task_id="t",
            split="dev",
            attempt=0,
            success=True,
        )
        ledger._conn.execute("DROP TRIGGER runs_no_update")
        ledger._conn.execute("UPDATE runs SET success = 0 WHERE run_id = ?", (run_id,))
        ledger._conn.commit()

    assert cli_main(["verify", "--ledger", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_register_run_and_export_over_the_cli(tmp_path, capsys):
    from chamber_orchestra.cli import main as cli_main
    from chamber_orchestra.evaluation.suite import dump_suite
    from chamber_orchestra.harness.registry import HarnessStore
    from tests.test_experiment_flow import _baseline, _candidate, _prereg, _suite

    store = HarnessStore(tmp_path / "harnesses")
    baseline = _baseline()
    store.initialize(baseline)
    candidate = _candidate(baseline)
    store.put(candidate)
    suite = _suite()
    dump_suite(suite, tmp_path / "suite.json")
    prereg = _prereg(suite, baseline, candidate)
    prereg_path = tmp_path / "prereg.json"
    prereg_path.write_text(json.dumps(prereg.document()), encoding="utf-8")
    ledger_path = str(tmp_path / "ledger.sqlite3")

    assert (
        cli_main(
            ["register", "--prereg", str(prereg_path), "--ledger", ledger_path]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["experiment_id"] == prereg.experiment_id

    assert (
        cli_main(
            [
                "run",
                "--prereg",
                str(prereg_path),
                "--root",
                str(tmp_path),
                "--suite",
                str(tmp_path / "suite.json"),
                "--ledger",
                ledger_path,
            ]
        )
        == 0
    )
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["state"] == "completed"

    export_path = tmp_path / "export.json"
    assert (
        cli_main(
            [
                "export",
                "--experiment",
                prereg.experiment_id,
                "--ledger",
                ledger_path,
                "--out",
                str(export_path),
            ]
        )
        == 0
    )
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["experiment"]["state"] == "completed"
    assert exported["verification"]["ok"] is True


def test_main_refuses_a_suite_with_a_stale_digest(
    monkeypatch, launched, clean_environment
):
    suite_path = clean_environment / "suite.json"
    document = default_suite().document()
    document["digest"] = "0" * 64
    suite_path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv("CHAMBER_ROOT", str(clean_environment / "state"))
    monkeypatch.setenv("CHAMBER_SUITE", str(suite_path))

    with pytest.raises(SuiteError):
        app_module.main()
