"""A small, Termux-friendly display for text files in the terminal.

Features that matter on a phone-sized terminal: optional line numbers, hard
wrapping to the real terminal width, line ranges, a byte cap, tab expansion,
binary detection and an optional pager (``less`` if present).
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

TEXT_EXTENSIONS = (
    "*.txt", "*.md", "*.markdown", "*.log", "*.rst", "*.ini", "*.cfg",
    "*.conf", "*.yaml", "*.yml", "*.json", "*.toml", "*.csv", "*.env",
)

Range = Tuple[int, Optional[int]]


def parse_ranges(specs: Optional[Sequence[str]]) -> List[Range]:
    ranges: List[Range] = []
    for spec in specs or []:
        for part in str(spec).split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                low, _, high = part.partition("-")
                start = int(low) if low.strip() else 1
                end = int(high) if high.strip() else None
            else:
                start = int(part)
                end = start
            if start < 1:
                raise ValueError("line numbers start at 1 (got {})".format(part))
            if end is not None and end < start:
                raise ValueError("invalid range '{}'".format(part))
            ranges.append((start, end))
    return ranges


def read_lines(source: str, base: Optional[Path] = None, encoding: str = "utf-8") -> Tuple[List[str], str]:
    """Return (lines, label) for a path or ``-`` for stdin."""
    if source == "-":
        data = sys.stdin.read().replace("\r\n", "\n").replace("\r", "\n")
        if data.endswith("\n"):
            data = data[:-1]
        return data.split("\n"), "<stdin>"
    path = Path(source).expanduser()
    if not path.is_absolute() and base is not None:
        path = Path(base) / path
    if not path.exists():
        raise FileNotFoundError("no such file: {}".format(path))
    if path.is_dir():
        raise IsADirectoryError("{} is a directory (use --list)".format(path))
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("{} looks like a binary file".format(path))
    text = raw.decode(encoding, errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    return text.split("\n"), str(path)


def find_text_files(base: Optional[Path] = None, limit: int = 60, any_extension: bool = False) -> List[Path]:
    root = Path(base or Path.cwd())
    if not root.is_dir():
        return []
    patterns = TEXT_EXTENSIONS if any_extension else ("*.txt",)
    found = []
    for entry in sorted(root.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name.lower()
        if any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
            found.append(entry)
        if len(found) >= limit:
            break
    return found


def _chunks(text: str, size: int) -> List[str]:
    if size <= 0 or len(text) <= size:
        return [text]
    return [text[index:index + size] for index in range(0, len(text), size)]


def _select(total: int, ranges: Sequence[Range]) -> List[int]:
    if not ranges:
        return list(range(1, total + 1))
    picked: List[int] = []
    seen = set()
    for start, end in ranges:
        stop = total if end is None else min(end, total)
        for number in range(start, stop + 1):
            if number not in seen:
                seen.add(number)
                picked.append(number)
    return picked


def render(
    lines: Sequence[str],
    numbers: bool = False,
    width: Optional[int] = None,
    wrap: bool = True,
    color: bool = False,
    ranges: Optional[Sequence[Range]] = None,
    max_lines: Optional[int] = None,
) -> str:
    total = len(lines)
    selected = _select(total, ranges or [])
    if max_lines is not None and max_lines >= 0:
        selected = selected[:max_lines]

    number_width = len(str(selected[-1])) if selected and numbers else 0
    available = None
    if wrap:
        columns = width or shutil.get_terminal_size((80, 24)).columns
        available = max(16, columns - (number_width + 2 if numbers else 0))

    out: List[str] = []
    for number in selected:
        line = lines[number - 1].expandtabs(4)
        parts = _chunks(line, available) if available else [line]
        for offset, part in enumerate(parts):
            if numbers and offset == 0:
                label = str(number).rjust(number_width) + " "
                if color:
                    label = "\033[2;36m" + label + "\033[0m"
            elif numbers:
                label = " " * (number_width + 1)
            else:
                label = ""
            out.append(label + part)
    return "\n".join(out)


def page(text: str, pager: Optional[str] = None) -> None:
    command = pager or os.environ.get("PAGER") or "less"
    binary = None
    for candidate in command.split():
        binary = shutil.which(candidate)
        if binary:
            break
    if not binary:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return
    flags = ["-R"] if Path(binary).name == "less" else []
    try:
        process = subprocess.Popen([binary] + flags, stdin=subprocess.PIPE)
        assert process.stdin is not None
        process.stdin.write((text if text.endswith("\n") else text + "\n").encode("utf-8", "replace"))
        process.stdin.close()
        process.wait()
    except (OSError, ValueError):
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def byte_cap_note(lines: Sequence[str], shown: int) -> str:
    return "{} line(s) shown of {}".format(shown, len(lines))


def describe(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return "{:<44} {:>7} B".format(str(path.name), size)
