"""One place for every glyph, colour and wrap decision.

No command invents its own visual vocabulary: severity always carries a word,
colour never carries meaning on its own, and every wrapped line stays inside the
terminal width so a 40-column Termux screen never scrolls sideways.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

_ANSI = {
    "blocker": "\033[1;31m",
    "major": "\033[1;33m",
    "minor": "\033[36m",
    "nit": "\033[2m",
    "ok": "\033[32m",
    "warn": "\033[1;33m",
    "dim": "\033[2m",
    "heading": "\033[1m",
}

ASCII_GLYPHS = {
    "blocker": "x",
    "major": "!",
    "minor": "-",
    "nit": ".",
    "ok": "ok",
    "warn": "!",
    "bullet": "-",
}

UNICODE_GLYPHS = {
    "blocker": "\u2716",
    "major": "\u25b2",
    "minor": "\u2022",
    "nit": "\u00b7",
    "ok": "\u2714",
    "warn": "!",
    "bullet": "\u2022",
}


def color_mode(choice: Optional[bool] = None) -> str:
    """Return ``always`` or ``never``; ``choice`` is the CLI flag (True/False)."""
    if choice is False:
        return "never"
    if choice is True:
        return "always"
    if os.environ.get("NO_COLOR"):
        return "never"
    if os.environ.get("CLICOLOR") == "0":
        return "never"
    if (os.environ.get("TERM") or "") == "dumb":
        return "never"
    return "always" if bool(getattr(sys.stdout, "isatty", lambda: False)()) else "never"


def ascii_only(explicit: bool = False) -> bool:
    if explicit:
        return True
    if (os.environ.get("LANG") or "").upper() in ("C", "POSIX"):
        return True
    return (os.environ.get("TERM") or "") == "dumb"


def glyphs(explicit_ascii: bool = False) -> dict:
    return dict(ASCII_GLYPHS if ascii_only(explicit_ascii) else UNICODE_GLYPHS)


def paint(text: str, role: str, mode: str = "never") -> str:
    code = _ANSI.get(role)
    if mode != "always" or not code:
        return text
    return code + text + "\033[0m"


def wrap(text, width: int, indent: int = 0, hang: int = 2) -> List[str]:
    """Hard-wrap at ``width``; continuation lines get a two-space hanging indent."""
    width = max(8, int(width))
    indent = max(0, int(indent))
    hang = max(0, int(hang))
    lines: List[str] = []
    for paragraph in str("" if text is None else text).splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        first = True
        pending = list(words)
        while pending:
            pad = indent if first else indent + hang
            if pad > width - 4:
                pad = max(0, width - 4)
            avail = max(4, width - pad)
            chosen: List[str] = []
            used = 0
            while pending:
                token = pending[0]
                extra = len(token) if not chosen else len(token) + 1
                if chosen and used + extra > avail:
                    break
                if not chosen and len(token) > avail:
                    cut = avail
                    slash = token[:avail].rfind("/")
                    if slash > 0:  # break paths after a separator, not mid-name
                        cut = slash + 1
                    chosen.append(token[:cut])
                    pending[0] = token[cut:]
                    used = cut
                    break
                chosen.append(pending.pop(0))
                used += extra
            lines.append(" " * pad + " ".join(chosen))
            first = False
    return lines
