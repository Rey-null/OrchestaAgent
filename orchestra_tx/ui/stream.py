"""Append-only progress lines, diagnostics and the shared exit-code table."""

from __future__ import annotations

import sys
from typing import Optional

from . import theme


class ExitCode:
    OK = 0
    STATE = 1
    USAGE = 1
    ARGS = 2
    MISSING = 3
    UNSETTLED = 4
    LOCKED = 5
    INTERRUPT = 130


def stage(index: int, total: int, name: str, result: str = "", width: Optional[int] = None,
          quiet: bool = False) -> None:
    """One motion-free status line, e.g. ``[1/1] import report .. 3 findings``."""
    if quiet:
        return
    width = max(40, int(width or 80))
    left = "[{}/{}] {}".format(index, total, name)
    if not result:
        lines = theme.wrap(left, width, indent=0, hang=2)
    else:
        room = width - len(left) - len(result) - 2
        if room >= 2:
            lines = [left + " " + "." * room + " " + result]
        else:
            lines = theme.wrap(left, width, indent=0, hang=2)
            lines += theme.wrap(result, width, indent=2, hang=2)
    for line in lines:
        sys.stdout.write(line + "\n")


def diagnostic(message: str) -> None:
    sys.stderr.write(str(message).rstrip() + "\n")
