"""Review parsing, ids, merging and rendering."""

import re
import unittest

from orchestra_tx.egm import report

HEADING_REPORT = """# Goldfish review - feature.md

Host: claude
Round: 2

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

BULLET_REPORT = """## Findings

- Major: the status board wraps mid-word
  and loses the finding id.
- [Nit] structure: two spaces before the dash
- loose bullet without severity
"""


class ParserTests(unittest.TestCase):
    def test_heading_shape(self):
        findings, meta = report.parse_report(HEADING_REPORT)
        self.assertEqual(len(findings), 3)
        self.assertEqual(meta["host"], "claude")
        self.assertEqual(meta["round"], "2")
        blocker, major, minor = findings
        self.assertEqual(blocker.severity, "blocker")
        self.assertEqual(blocker.persona, "security")
        self.assertEqual(blocker.location, "src/auth.py:42")
        self.assertIn("leaks timing", blocker.claim)
        self.assertEqual(major.severity, "major")
        self.assertEqual(major.persona, "ux")
        self.assertEqual(minor.severity, "minor")
        self.assertEqual(minor.persona, "docs")
        self.assertEqual(minor.location, "USAGE.txt")
        self.assertIn("glossary", minor.claim)

    def test_bullet_shape_and_unknown_severity(self):
        findings, _ = report.parse_report(BULLET_REPORT)
        self.assertEqual(len(findings), 3)
        self.assertEqual(findings[0].severity, "major")
        self.assertIn("wraps mid-word", findings[0].claim)
        self.assertIn("loses the finding id", findings[0].claim)
        self.assertEqual(findings[1].severity, "nit")
        self.assertEqual(findings[2].severity, "unknown")
        self.assertIn("loose bullet", findings[2].claim)

    def test_ids_are_stable_content_hashes(self):
        first, _ = report.parse_report(HEADING_REPORT)
        second, _ = report.parse_report(HEADING_REPORT)
        self.assertEqual([f.id for f in first], [f.id for f in second])
        for finding in first:
            self.assertTrue(re.fullmatch(r"[0-9a-f]{8}", finding.id))
        self.assertEqual(len({f.id for f in first}), 3)

    def test_raw_is_kept_for_unparsed_text(self):
        findings, _ = report.parse_report(BULLET_REPORT)
        self.assertIn("loose bullet without severity", findings[-1].raw)
        self.assertTrue(findings[-1].claim)

    def test_empty_report(self):
        findings, meta = report.parse_report("Nothing to see here.\n")
        self.assertEqual(findings, [])
        self.assertEqual(meta, {})


class MergeTests(unittest.TestCase):
    def test_new_changed_unchanged_and_decisions(self):
        previous = [{
            "id": report.finding_id("security", "src/auth.py:42", "old claim"),
            "severity": "blocker",
            "persona": "security",
            "location": "src/auth.py:42",
            "claim": "old claim",
            "decision": "propose",
        }]
        same = report.Finding(
            id=report.finding_id("security", "src/auth.py:42", "old claim"),
            severity="blocker", persona="security", location="src/auth.py:42", claim="old claim",
        )
        changed = report.Finding(
            id=report.finding_id("security", "src/auth.py:42", "new claim"),
            severity="blocker", persona="security", location="src/auth.py:42", claim="new claim",
        )
        fresh = report.Finding(
            id=report.finding_id("ux", "egm status", "board"), severity="major",
            persona="ux", location="egm status", claim="board",
        )
        merged, counts = report.merge(previous, [same, changed, fresh])
        self.assertEqual(counts, {"new": 1, "changed": 1, "unchanged": 1})
        by_state = {row["state"]: row for row in merged}
        self.assertEqual(by_state["unchanged"]["decision"], "propose")
        self.assertEqual(by_state["changed"]["decision"], "propose")
        self.assertEqual(by_state["new"]["decision"], "")

    def test_triage_file_wins(self):
        finding = report.Finding(
            id="abcd1234", severity="blocker", persona="security", location="x", claim="claim",
        )
        merged, _ = report.merge([], [finding], {"abcd1234": {"decision": "decline"}})
        self.assertEqual(merged[0]["decision"], "decline")


class SettleTests(unittest.TestCase):
    def test_decisions(self):
        self.assertTrue(report.is_settled({"decision": "propose"}))
        self.assertTrue(report.is_settled({"decision": {"decision": "p"}}))
        self.assertFalse(report.is_settled({"decision": "escalate"}))
        self.assertFalse(report.is_settled({}))

    def test_only_blockers_and_majors_block(self):
        rows = [
            {"id": "1", "severity": "blocker", "decision": ""},
            {"id": "2", "severity": "major", "decision": "contest"},
            {"id": "3", "severity": "minor", "decision": ""},
        ]
        self.assertEqual([row["id"] for row in report.unsettled(rows)], ["1"])

    def test_summarize(self):
        rows = [
            {"severity": "blocker", "persona": "security", "decision": "propose"},
            {"severity": "major", "persona": "ux", "decision": ""},
            {"severity": "minor", "persona": "ux", "decision": ""},
        ]
        stats = report.summarize(rows)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["settled"], 1)
        self.assertEqual(stats["open"], 2)
        self.assertEqual(stats["by_severity"]["major"], 1)
        self.assertEqual(stats["by_persona"]["ux"], 2)


class RenderTests(unittest.TestCase):
    def test_render_fits_40_columns(self):
        findings, _ = report.parse_report(HEADING_REPORT)
        rows = [finding.as_dict() for finding in findings]
        for width in (40, 60, 80, 120):
            for line in report.render_findings(rows, width):
                self.assertLessEqual(len(line), width, line)

    def test_severity_is_a_word(self):
        findings, _ = report.parse_report(HEADING_REPORT)
        text = "\n".join(report.render_findings([findings[0].as_dict()], 40))
        self.assertIn("Blocker", text)
        self.assertIn("security", text)


if __name__ == "__main__":
    unittest.main()
