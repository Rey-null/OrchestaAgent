"""Artifacts: redaction, brief markers, merge and scaffolding."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from orchestra_tx import store
from orchestra_tx.egm import artifacts, scaffold, state

SECRETS = (
    "api_key = abcdefgh12345678\n"
    "TOKEN=zzzzzzzzzzzzzzzz\n"
    "password: hunter22\n"
    "ghp_" + "a" * 36 + "\n"
    "sk-" + "b" * 32 + "\n"
    "AKIA" + "C" * 16 + "\n"
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEsecretbody\n-----END RSA PRIVATE KEY-----\n"
)


class RedactionTests(unittest.TestCase):
    def test_names_every_pattern_family(self):
        clean, families = artifacts.redact(SECRETS)
        names = [name for name, _ in families]
        for expected in ("PRIVATE KEY", "API_KEY", "TOKEN", "PASSWORD", "ghp_", "sk-", "AKIA"):
            self.assertIn(expected, names)
        for leaked in ("hunter22", "zzzzzzzzzzzzzzzz", "MIIEsecretbody", "abcdefgh12345678"):
            self.assertNotIn(leaked, clean)
        self.assertIn(artifacts.REDACTED, clean)

    def test_clean_text_is_untouched(self):
        text = "Use the stdlib only; no wheels on Termux."
        clean, families = artifacts.redact(text)
        self.assertEqual(clean, text)
        self.assertEqual(families, [])
        self.assertEqual(artifacts.redaction_note(families), "")

    def test_note_wording(self):
        self.assertEqual(artifacts.redaction_note([("sk-", 1)]), "redacted 1 match: sk-")
        self.assertEqual(
            artifacts.redaction_note([("API_KEY", 1), ("ghp_", 2)]),
            "redacted 3 matches: API_KEY, ghp_",
        )


class BriefTests(unittest.TestCase):
    PLAN = {
        "goal": "Ship the design loop",
        "steps": [
            {"id": 1, "text": "Draft the brief", "status": "done"},
            {"id": 2, "text": "Import the review", "status": "active"},
        ],
    }

    def render(self):
        return artifacts.render_brief(
            self.PLAN,
            [{"text": "Use stdlib only"}],
            [{"id": "abcd1234", "text": "phone has 40 columns"}],
            {"id": "20260101-000000-aaaa", "started": "2026-01-01", "notes": ["first pass done"]},
        )

    def test_generated_block_has_markers_and_facts(self):
        text = self.render()
        self.assertTrue(text.startswith(artifacts.START_MARKER))
        self.assertIn(artifacts.END_MARKER, text)
        self.assertIn("Ship the design loop", text)
        self.assertIn("[x] 1. Draft the brief", text)
        self.assertIn("[~] 2. Import the review", text)
        self.assertIn("Use stdlib only", text)
        self.assertIn("first pass done", text)

    def test_empty_plan_names_the_next_command(self):
        text = artifacts.render_brief({"goal": "", "steps": []}, [], [], None)
        self.assertIn("orchestra-tx plan new", text)

    def test_merge_preserves_hand_written_text(self):
        existing = "# My brief\n\nHand-written constraint: keep it short.\n"
        merged = artifacts.merge_brief(existing, self.render())
        self.assertIn("Hand-written constraint", merged)
        self.assertIn(artifacts.START_MARKER, merged)

    def test_merge_is_idempotent(self):
        once = artifacts.merge_brief("# Hand note\n", self.render())
        twice = artifacts.merge_brief(once, self.render())
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(artifacts.START_MARKER), 1)


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(str(self.tmp), ignore_errors=True))
        patcher = mock.patch.dict(os.environ, {"ORCHESTRA_TX_HOME": str(self.tmp / "store")}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.project = self.tmp / "proj"
        self.project.mkdir()

    def test_init_creates_and_is_idempotent(self):
        first = scaffold.init(str(self.project))
        self.assertTrue(Path(first["design_dir"]).is_dir())
        self.assertIn("| Document |", Path(first["sitemap"]).read_text())
        self.assertGreaterEqual(len(first["created"]), 3)
        self.assertTrue(state.initialized(str(self.project)))

        second = scaffold.init(str(self.project))
        self.assertEqual(second["created"], [])
        self.assertTrue(second["existed"])

    def test_force_resets_state(self):
        scaffold.init(str(self.project))
        current, _ = state.load_state(str(self.project))
        current["round"] = 3
        state.save_state(current, str(self.project))
        scaffold.init(str(self.project), force=True)
        reset, _ = state.load_state(str(self.project))
        self.assertEqual(reset["round"], 0)

    def test_design_status_header(self):
        design = self.project / "a.md"
        design.write_text("# A\n\n**Status:** In Review\n\nText.\n")
        self.assertEqual(scaffold.design_status(design), "In Review")
        design.write_text("# A\n\nStatus: Approved\n")
        self.assertEqual(scaffold.design_status(design), "Approved")
        design.write_text("# A\n\nNo header here.\n")
        self.assertEqual(scaffold.design_status(design), "")

    def test_corrupt_state_is_quarantined(self):
        scaffold.init(str(self.project))
        path = state.state_path(str(self.project))
        path.write_text("{not json")
        current, warning = state.load_state(str(self.project))
        self.assertIn("corrupt", warning)
        self.assertEqual(current["round"], 0)
        self.assertTrue(any(p.name.startswith("state.json.corrupt-") for p in path.parent.iterdir()))

    def test_list_designs_skips_sitemap(self):
        directory = Path(scaffold.init(str(self.project))["design_dir"])
        scaffold.ensure_sitemap(directory)
        (directory / "b.md").write_text("# B\n")
        (directory / "a.md").write_text("# A\n")
        self.assertEqual([p.name for p in scaffold.list_designs(directory)], ["a.md", "b.md"])


if __name__ == "__main__":
    unittest.main()
