"""Width detection and the two layout blocks the egm commands use."""

from __future__ import annotations

import os
import shutil
from typing import List, Optional, Sequence, Tuple

from . import theme

FLOOR = 40
CEILING = 200

_LABELS = {
    "blocker": "Blocker",
    "major": "Major",
    "minor": "Minor",
    "nit": "Nit",
    "unknown": "Unknown",
}


def clamp_width(width: int) -> int:
    return max(FLOOR, min(CEILING, int(width)))


def terminal_width(clamp: Tuple[int, int] = (FLOOR, CEILING)) -> int:
    raw = (os.environ.get("COLUMNS") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        width = int(raw)
    else:
        width = shutil.get_terminal_size((80, 24)).columns
    return max(clamp[0], min(clamp[1], width))


def resolve_width(given: Optional[int] = None) -> int:
    return clamp_width(given) if given else terminal_width()


def severity_label(level) -> str:
    return _LABELS.get(str(level or "").lower(), "Unknown")


def rule(width: int, char: str = "-") -> str:
    return char * max(0, int(width))


def key_value(rows: Sequence[Tuple[str, str]], width: int, color_mode: str = "never") -> List[str]:
    """``key : value`` block with wrapped values; no line exceeds ``width``."""
    rows = [(str(key), "" if value is None else str(value)) for key, value in rows]
    if not rows:
        return []
    key_width = min(max(len(key) for key, _ in rows), max(4, width // 2))
    lines: List[str] = []
    for key, value in rows:
        pad = key.ljust(key_width) + " : "
        if len(pad) >= width - 8:
            pad = key + ": "
        avail = max(8, width - len(pad))
        pieces = theme.wrap(value, avail, indent=0, hang=2)
        if not pieces:
            pieces = [""]
        lines.append(theme.paint(pad, "dim", color_mode) + pieces[0])
        for piece in pieces[1:]:
            lines.append(" " * len(pad) + piece)
    return lines
