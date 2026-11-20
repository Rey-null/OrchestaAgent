"""End-to-end tests for `orchestra-tx egm report` and `egm resolve`."""

import io
import json
import os
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from orchestra_tx import store
from orchestra_tx.cli import main as cli_main

REPORT = """# Goldfish review - feature.md

Host: claude
Round: 1

## Blockers

### B1 - Persona: security - Location: src/auth.py:42
Token is compared with ==, which leaks timing.

## Major

### M1 - Persona: ux - Location: egm status
The board does not say what to run next.

## Minor

- **Persona:** docs - **Location:** USAGE.txt
  The glossary omits the word Heilmeier.
"""


class Tty(io.StringIO):
    """A StringIO that claims to be a terminal, echoing input like one."""

    def __init__(self, value="", echo=None):
        super().__init__(value)
        self.echo = echo

    def isatty(self):
        return True

    def readline(self, *args):
        line = super().readline(*args)
        if line and self.echo is not None:
            self.echo.write(line)
        return line


class EgmReportResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(str(self.tmp), ignore_errors=True))
        self.project = self.tmp / "proj"
        self.project.mkdir()
        self.designs = self.project / ".orchestra" / "designs"
        self.egm_dir = self.project / ".orchestra" / "egm"
        patcher = mock.patch.dict(
            os.environ,
            {"ORCHESTRA_TX_HOME": str(self.tmp / "store"), "COLUMNS": "40", "NO_COLOR": "1"},
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cwd = os.getcwd()
        os.chdir(str(self.project))
        self.addCleanup(os.chdir, self.cwd)

    # helpers -------------------------------------------------------------

    def egm(self, *argv):
        return self.cli("egm", *argv)

    def plugin(self, *argv):
        return self.cli(*argv)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli_main(list(argv))
            except SystemExit as exc:  # argparse errors
                code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def interactive(self, *argv, keys=""):
        out, err = Tty(), io.StringIO()
        with mock.patch("sys.stdin", Tty(keys, echo=out)), mock.patch("sys.stdout", out), redirect_stderr(err):
            try:
                code = cli_main(list(argv))
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def flat(self, text):
        return re.sub(r"\s+", " ", text)

    def assert_fits(self, text, width=40):
        for line in text.splitlines():
            self.assertLessEqual(len(line), width, line)

    def write_design(self, name="feature.md", status="In Review"):
        self.designs.mkdir(parents=True, exist_ok=True)
        path = self.designs / name
        path.write_text("# Feature\n\n**Status:** {}\n\nDraft text.\n".format(status), encoding="utf-8")
        return path

    def imported(self):
        """init + design + review import, ready for report/resolve."""
        self.egm("init")
        self.write_design()
        review = self.project / "review.md"
        review.write_text(REPORT, encoding="utf-8")
        code, _, err = self.egm("review", "review.md")
        self.assertEqual(code, 0, err)
        return self.findings()

    def findings(self):
        return json.loads((self.egm_dir / "findings.json").read_text(encoding="utf-8"))

    def triage(self):
        path = self.egm_dir / "triage.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def state(self):
        return json.loads((self.egm_dir / "state.json").read_text(encoding="utf-8"))

    # report --------------------------------------------------------------

    def test_report_without_findings_exits_3(self):
        self.egm("init")
        code, _, err = self.egm("report")
        self.assertEqual(code, 3)
        self.assertIn("no findings", err)
        self.assertIn("egm review", err)

    def test_report_groups_blockers_first_and_fits_40(self):
        self.imported()
        code, out, _ = self.egm("report")
        self.assertEqual(code, 0)
        self.assertIn("EGM report", out)
        self.assertIn("Blocker (1)", out)
        self.assertIn("Major (1)", out)
        self.assertIn("Minor (1)", out)
        self.assertLess(out.index("Blocker (1)"), out.index("Major (1)"))
        self.assertLess(out.index("Major (1)"), out.index("Minor (1)"))
        self.assertIn("review is not a test", self.flat(out))
        self.assert_fits(out)

    def test_report_severity_and_persona_filters(self):
        self.imported()
        code, out, _ = self.egm("report", "--severity", "blocker")
        self.assertEqual(code, 0)
        self.assertIn("leaks timing", self.flat(out))
        self.assertNotIn("Major (", out)

        code, out, _ = self.egm("report", "--persona", "ux")
        self.assertEqual(code, 0)
        self.assertIn("egm status", self.flat(out))
        self.assertNotIn("src/auth.py", out)

        code, out, _ = self.egm("report", "--severity", "blocker", "--persona", "ux")
        self.assertEqual(code, 0)
        self.assertIn("no findings match", out)
        self.assert_fits(out)

    def test_report_raw_shows_reviewer_text(self):
        self.imported()
        code, out, _ = self.egm("report", "--persona", "docs")
        self.assertEqual(code, 0)
        self.assertNotIn("**Persona:**", out)
        self.assertIn("glossary", self.flat(out))

        code, out, _ = self.egm("report", "--persona", "docs", "--raw")
        self.assertEqual(code, 0)
        self.assertIn("**Persona:**", out)
        self.assert_fits(out)

    def test_report_ranges_limit_lines(self):
        self.imported()
        code, out, _ = self.egm("report", "-r", "1-2")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 2)

    def test_report_unknown_severity_exits_2(self):
        self.imported()
        code, _, err = self.egm("report", "--severity", "catastrophe")
        self.assertEqual(code, 2)
        self.assertIn("unknown severity", err)

    def test_report_json_shape_and_clean_stdout(self):
        (self.project / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
        self.imported()
        code, out, err = self.egm("report", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        for key in ("status", "design", "round", "stage", "findings", "counts", "next", "note", "imported"):
            self.assertIn(key, payload)
        self.assertEqual(payload["imported"], 3)
        self.assertEqual(payload["counts"]["by_severity"]["blocker"], 1)
        self.assertEqual(payload["design"], ".orchestra/designs/feature.md")
        self.assertIn("review is not a test", payload["note"])
        self.assertIn("CLAUDE.md", err)

    # resolve -------------------------------------------------------------

    def test_resolve_without_terminal_exits_1(self):
        self.imported()
        code, _, err = self.egm("resolve")
        self.assertEqual(code, 1)
        self.assertIn("--decide", err)
        self.assertIn("interactive terminal", err)
        self.assertEqual(self.triage(), {})

    def test_resolve_decide_all_json_settles_the_gate(self):
        self.imported()
        code, out, _ = self.egm("resolve", "--decide", "propose", "--all", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["decided"]), 3)
        self.assertEqual(payload["remaining"], [])
        self.assertEqual(payload["stage"], "triaged")
        self.assertEqual(len(self.triage()), 3)

        code, output, _ = self.egm("check")
        self.assertEqual(code, 0, output)

        code, output, _ = self.plugin("memory", "list", "--json")
        rows = [row for row in json.loads(output) if "egm" in row.get("tags", [])]
        self.assertEqual(len(rows), 3)
        self.assertIn("decision", rows[0]["tags"])

    def test_resolve_decide_settles_only_the_first_open_finding(self):
        self.imported()
        code, out, _ = self.egm("resolve", "--decide", "d", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["decided"]), 1)
        self.assertEqual(payload["decided"][0]["severity"], "blocker")
        self.assertEqual(len(payload["remaining"]), 2)
        self.assertEqual(self.state()["stage"], "triaged")

        code, _, _ = self.egm("check")
        self.assertEqual(code, 4)

    def test_resolve_rejects_bad_arguments(self):
        self.imported()
        code, _, err = self.egm("resolve", "--decide", "maybe")
        self.assertEqual(code, 2)
        self.assertIn("unknown decision", err)

        code, _, err = self.egm("resolve", "--all")
        self.assertEqual(code, 2)
        self.assertIn("--decide", err)

    def test_resolve_one_key_loop_stops_and_resumes(self):
        self.imported()
        code, out, _ = self.interactive("egm", "resolve", keys="p\ns\nq\n")
        self.assertEqual(code, 0)
        self.assertIn("choice [p/c/e/d/s/q]", out)
        self.assertIn("stopped (quit)", self.flat(out))
        self.assertIn("Blocker", out)
        self.assert_fits(out)
        self.assertEqual(len(self.triage()), 1)

        decided = self.triage()
        blocker = [row for row in self.findings() if row["severity"] == "blocker"][0]
        self.assertEqual(decided[blocker["id"]]["decision"], "propose")

        # re-running resumes at the first undecided finding: the Major
        code, out, _ = self.interactive("egm", "resolve", keys="c\n")
        self.assertEqual(code, 0)
        self.assertIn("Major", out)
        self.assertEqual(len(self.triage()), 2)
        major = [row for row in self.findings() if row["severity"] == "major"][0]
        self.assertEqual(self.triage()[major["id"]]["decision"], "contest")

    def test_resolve_waits_for_the_lock_then_exits_5(self):
        self.imported()
        with store.locked(self.egm_dir):
            code, _, err = self.egm("resolve", "--decide", "propose", "--all", "--lock-timeout", "0.1")
        self.assertEqual(code, 5)
        self.assertIn("held by pid", err)


if __name__ == "__main__":
    unittest.main()
