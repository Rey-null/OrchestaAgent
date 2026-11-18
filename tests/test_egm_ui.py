"""Presentation contract: wrapping, width, glyphs, colour and exit codes."""

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from orchestra_tx.ui import layout, stream, theme

WIDTHS = (40, 60, 80, 120)
LONG = "the board does not say what to run next when no design exists yet "


class WrapTests(unittest.TestCase):
    def test_never_exceeds_width(self):
        for width in WIDTHS:
            with self.subTest(width=width):
                for line in theme.wrap(LONG * 6, width):
                    self.assertLessEqual(len(line), width)

    def test_long_token_is_split(self):
        for width in WIDTHS:
            lines = theme.wrap("x" * 400, width)
            self.assertTrue(lines)
            for line in lines:
                self.assertLessEqual(len(line), width)

    def test_hanging_indent_on_continuation(self):
        lines = theme.wrap(LONG * 3, 40)
        self.assertGreater(len(lines), 1)
        for line in lines[1:]:
            self.assertTrue(line.startswith("  "), line)
            self.assertLessEqual(len(line), 40)

    def test_empty_text(self):
        self.assertEqual(theme.wrap("", 40), [""])

    def test_key_value_fits(self):
        rows = [
            ("design", ".orchestra/designs/a-really-long-design-file-name.md"),
            ("status", "In Review"),
            ("findings", "12 imported, 3 open, 1 settled"),
        ]
        for width in WIDTHS:
            for line in layout.key_value(rows, width):
                self.assertLessEqual(len(line), width, line)


class WidthTests(unittest.TestCase):
    def test_clamped_to_floor_and_ceiling(self):
        self.assertEqual(layout.clamp_width(10), 40)
        self.assertEqual(layout.clamp_width(500), 200)

    def test_reads_columns(self):
        with mock.patch.dict(os.environ, {"COLUMNS": "40"}, clear=False):
            self.assertEqual(layout.terminal_width(), 40)
        with mock.patch.dict(os.environ, {"COLUMNS": "5"}, clear=False):
            self.assertEqual(layout.terminal_width(), 40)

    def test_explicit_width_is_clamped(self):
        self.assertEqual(layout.resolve_width(12), 40)
        self.assertEqual(layout.resolve_width(70), 70)


class GlyphAndColourTests(unittest.TestCase):
    def test_severity_always_has_a_word(self):
        self.assertEqual(layout.severity_label("blocker"), "Blocker")
        self.assertEqual(layout.severity_label("major"), "Major")
        self.assertEqual(layout.severity_label(""), "Unknown")

    def test_ascii_glyphs(self):
        with mock.patch.dict(os.environ, {"LANG": "C.UTF-8", "TERM": "xterm"}, clear=False):
            self.assertEqual(theme.glyphs()["bullet"], "\u2022")
            self.assertEqual(theme.glyphs(True)["bullet"], "-")

    def test_no_color_environment(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            self.assertEqual(theme.color_mode(), "never")
        with mock.patch.dict(os.environ, {"TERM": "dumb"}, clear=False):
            os.environ.pop("NO_COLOR", None)
            self.assertEqual(theme.color_mode(), "never")

    def test_flags_win(self):
        self.assertEqual(theme.color_mode(True), "always")
        self.assertEqual(theme.color_mode(False), "never")
        self.assertEqual(theme.paint("x", "blocker", "never"), "x")
        self.assertIn("\033[", theme.paint("x", "blocker", "always"))


class StreamTests(unittest.TestCase):
    def test_stage_fits_at_40(self):
        out = io.StringIO()
        with redirect_stdout(out):
            stream.stage(2, 5, "critic review", "3 findings (1 blocker)", width=40)
        lines = out.getvalue().splitlines()
        self.assertTrue(lines)
        for line in lines:
            self.assertLessEqual(len(line), 40, line)
        self.assertIn("[2/5]", lines[0])

    def test_quiet_suppresses(self):
        out = io.StringIO()
        with redirect_stdout(out):
            stream.stage(1, 1, "import report", "3 findings", width=80, quiet=True)
        self.assertEqual(out.getvalue(), "")

    def test_exit_codes(self):
        self.assertEqual(stream.ExitCode.OK, 0)
        self.assertEqual(stream.ExitCode.STATE, 1)
        self.assertEqual(stream.ExitCode.ARGS, 2)
        self.assertEqual(stream.ExitCode.MISSING, 3)
        self.assertEqual(stream.ExitCode.UNSETTLED, 4)
        self.assertEqual(stream.ExitCode.LOCKED, 5)


if __name__ == "__main__":
    unittest.main()
