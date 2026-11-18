"""End-to-end tests for `orchestra-tx egm init|status|brief|review|check`."""

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


class EgmCliTests(unittest.TestCase):
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

    def assert_fits(self, text, width=40):
        for line in text.splitlines():
            self.assertLessEqual(len(line), width, line)

    def flat(self, text):
        return re.sub(r"\s+", " ", text)

    def write_report(self, text=REPORT, name="review.md"):
        path = self.project / name
        path.write_text(text, encoding="utf-8")
        return path

    def write_design(self, name="feature.md", status="In Review"):
        self.designs.mkdir(parents=True, exist_ok=True)
        path = self.designs / name
        path.write_text("# Feature\n\n**Status:** {}\n\nDraft text.\n".format(status), encoding="utf-8")
        return path

    def findings(self):
        return json.loads((self.egm_dir / "findings.json").read_text(encoding="utf-8"))

    def state(self):
        return json.loads((self.egm_dir / "state.json").read_text(encoding="utf-8"))

    def settle(self, decisions="propose"):
        rows = self.findings()
        triage = {
            row["id"]: {"decision": decisions, "decided_at": "2026-11-18T00:00:00+00:00"}
            for row in rows if row["severity"] in ("blocker", "major")
        }
        (self.egm_dir / "triage.json").write_text(json.dumps(triage), encoding="utf-8")

    # tests ---------------------------------------------------------------

    def test_init_json_and_idempotent(self):
        code, out, _ = self.egm("init", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        for key in ("design_dir", "sitemap", "state", "created", "existed"):
            self.assertIn(key, payload)
        self.assertTrue((self.designs / "SITEMAP.md").is_file())
        self.assertTrue((self.egm_dir / "state.json").is_file())

        code, out, _ = self.egm("init", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["created"], [])

    def test_init_human_fits_40(self):
        code, out, _ = self.egm("init")
        self.assertEqual(code, 0)
        self.assertIn("EGM initialized", out)
        self.assert_fits(out)

    def test_status_empty_state_names_next_command(self):
        code, out, _ = self.egm("status")
        self.assertEqual(code, 0)
        self.assertIn("orchestra-tx egm init", out)
        self.assert_fits(out)

        code, out, _ = self.egm("status", "--json")
        payload = json.loads(out)
        self.assertFalse(payload["initialized"])
        self.assertEqual(payload["status"], "uninitialized")
        self.assertTrue(payload["next"].endswith("egm init"))

    def test_status_board_fits_40_and_is_json_clean(self):
        self.egm("init")
        self.write_design()
        code, out, _ = self.egm("status")
        self.assertEqual(code, 0)
        self.assertIn("EGM status", out)
        self.assertIn("feature.md", self.flat(out))
        self.assertIn("In Review", self.flat(out))
        self.assert_fits(out)

        code, out, _ = self.egm("status", "--json")
        payload = json.loads(out)
        self.assertEqual(payload["status"], "In Review")
        self.assertEqual(payload["design"], ".orchestra/designs/feature.md")
        self.assertEqual(payload["counts"]["total"], 0)

    def test_brief_requires_init_for_write(self):
        code, _, err = self.egm("brief", "--write")
        self.assertEqual(code, 3)
        self.assertIn("egm init", err)

    def test_brief_write_renders_plan_and_memory_and_keeps_hand_notes(self):
        self.egm("init")
        self.plugin("plan", "new", "Ship the design loop", "--step", "Draft the brief")
        self.plugin("memory", "add", "Use stdlib only", "--pin")
        code, out, _ = self.egm("brief", "--write")
        self.assertEqual(code, 0)
        self.assertIn("concepts_brief.md", out)
        self.assert_fits(out)

        path = self.designs / "concepts_brief.md"
        doc = path.read_text(encoding="utf-8")
        self.assertIn("Ship the design loop", doc)
        self.assertIn("Use stdlib only", doc)
        self.assertIn("orchestra-tx:generated:start", doc)

        path.write_text(doc + "\nHand note: keep this line.\n", encoding="utf-8")
        self.egm("brief", "--write")
        again = path.read_text(encoding="utf-8")
        self.assertIn("Hand note: keep this line.", again)
        self.assertEqual(again.count("orchestra-tx:generated:start"), 1)

    def test_brief_print_fits_40_and_json_is_clean(self):
        self.egm("init")
        self.plugin("plan", "new", "Ship it", "--step", "Draft it")
        code, out, _ = self.egm("brief")
        self.assertEqual(code, 0)
        self.assertIn("Concepts brief", out)
        self.assertIn("Ship it", out)
        self.assert_fits(out)

        code, out, _ = self.egm("brief", "--json")
        payload = json.loads(out)
        self.assertFalse(payload["written"])
        self.assertIn("orchestra-tx:generated:start", payload["brief"])

    def test_brief_redacts_and_names_families(self):
        self.egm("init")
        self.plugin("memory", "add", "deploy key sk-" + "a" * 32, "--pin")
        code, out, _ = self.egm("brief", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("deploy key [redacted]", payload["brief"])
        self.assertNotIn("a" * 32, payload["brief"])
        self.assertIn("sk-", payload["redaction_note"])
        self.assertTrue(payload["redaction_note"].startswith("redacted 1 match"))

    def test_review_import_then_check_gate(self):
        self.egm("init")
        self.write_design()
        self.write_report()
        code, out, _ = self.egm("review", "review.md", "--design", ".orchestra/designs/feature.md")
        self.assertEqual(code, 0)
        self.assertIn("import report", out)
        self.assertIn("Blocker", out)
        self.assert_fits(out)

        self.assertEqual(len(self.findings()), 3)
        state = self.state()
        self.assertEqual(state["round"], 1)
        self.assertEqual(state["design"], ".orchestra/designs/feature.md")
        self.assertEqual(state["last_review"]["host"], "claude")

        code, out, _ = self.egm("review", "review.md")
        self.assertEqual(code, 0)
        self.assertIn("already imported", self.flat(out))
        self.assertEqual(self.state()["round"], 1)

        code, out, _ = self.egm("check")
        self.assertEqual(code, 4)
        self.assertIn("blocked", out)
        self.assert_fits(out)

        self.settle("propose")
        code, out, _ = self.egm("check")
        self.assertEqual(code, 0)
        self.assertIn("ok", out)
        self.assert_fits(out)

    def test_review_json(self):
        self.egm("init")
        self.write_design()
        self.write_report()
        code, out, _ = self.egm("review", "review.md", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["round"], 1)
        self.assertEqual(payload["new"], 3)
        self.assertEqual(payload["counts"]["by_severity"]["blocker"], 1)
        self.assertEqual(payload["design"], ".orchestra/designs/feature.md")

    def test_check_without_import_exits_3(self):
        self.egm("init")
        code, _, err = self.egm("check")
        self.assertEqual(code, 3)
        self.assertIn("no review report imported", err)

    def test_check_json_shape(self):
        self.egm("init")
        self.write_design()
        self.write_report()
        self.egm("review", "review.md")
        code, out, _ = self.egm("check", "--json")
        self.assertEqual(code, 4)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(len(payload["unsettled"]), 2)
        self.assertEqual(payload["counts"]["total"], 3)
        self.assertEqual(payload["code"], 4)

    def test_review_rejects_report_without_findings(self):
        self.egm("init")
        self.write_design()
        self.write_report("# Nothing\n\nJust prose.\n", name="empty.md")
        code, _, err = self.egm("review", "empty.md")
        self.assertEqual(code, 1)
        self.assertIn("no findings", err)

    def test_review_missing_report_is_3(self):
        self.egm("init")
        code, _, err = self.egm("review", "nope.md")
        self.assertEqual(code, 3)
        self.assertIn("no such report", err)

    def test_pre_review_warning_for_instruction_files(self):
        (self.project / "AGENTS.md").write_text("# Agent instructions\n", encoding="utf-8")
        self.egm("init")
        code, out, _ = self.egm("status")
        self.assertEqual(code, 0)
        self.assertIn("AGENTS.md", out)
        self.assertIn("fresh-context", out)
        self.assert_fits(out)

        code, out, _ = self.egm("brief", "--write")
        self.assertEqual(code, 0)
        self.assertIn("AGENTS.md", out)
        self.assertIn("warning:", out)
        self.assert_fits(out)

        code, out, _ = self.egm("brief")
        self.assertEqual(code, 0)
        self.assertNotIn("AGENTS.md", out)  # stdout stays the document

        self.write_design()
        self.write_report()
        code, out, _ = self.egm("review", "review.md")
        self.assertEqual(code, 0)
        self.assertIn("AGENTS.md", self.flat(out))
        self.assert_fits(out)

        code, out, _ = self.egm("check")
        self.assertEqual(code, 4)
        self.assertIn("AGENTS.md", self.flat(out))
        self.assert_fits(out)

    def test_json_keeps_prose_out_of_stdout(self):
        (self.project / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
        self.egm("init")
        self.write_design()
        self.write_report()
        for argv in (("status", "--json"), ("brief", "--json"), ("review", "review.md", "--json"), ("check", "--json")):
            with self.subTest(argv=argv):
                code, out, err = self.egm(*argv)
                json.loads(out)  # stdout must parse on its own
                self.assertIn("CLAUDE.md", self.flat(err))


if __name__ == "__main__":
    unittest.main()
