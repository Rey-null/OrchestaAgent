"""Document rendering: the generated brief block and secret redaction."""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

START_MARKER = "<!-- orchestra-tx:generated:start -->"
END_MARKER = "<!-- orchestra-tx:generated:end -->"

REDACTED = "[redacted]"

# Ordered: the broadest patterns first, so a private key is not partly eaten by
# a narrower match. Families are reported back by name (D5).
_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("PRIVATE KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("API_KEY", re.compile(r"(?i)\b[a-z0-9_.-]*api[_-]?key\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+=]{8,}[\"']?")),
    ("TOKEN", re.compile(r"(?i)\b(?:access[_-]?|auth[_-]?|bearer\s+)?token\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+=]{8,}[\"']?")),
    ("SECRET", re.compile(r"(?i)\b[a-z0-9_.-]*secret\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+=]{8,}[\"']?")),
    ("PASSWORD", re.compile(r"(?i)\b[a-z0-9_.-]*passw(?:or)?d\b\s*[:=]\s*[\"']?[^\s\"']{4,}[\"']?")),
    ("ghp_", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("sk-", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("AKIA", re.compile(r"\bAKIA[0-9A-Z]{12,}")),
]


def redact(text: str) -> Tuple[str, List[Tuple[str, int]]]:
    """Replace secrets and return the matched pattern families with counts."""
    families: List[Tuple[str, int]] = []
    result = str(text or "")
    for name, pattern in _PATTERNS:
        result, count = pattern.subn(REDACTED, result)
        if count:
            families.append((name, count))
    return result, families


def redaction_note(families: Sequence[Tuple[str, int]]) -> str:
    if not families:
        return ""
    total = sum(count for _, count in families)
    names = ", ".join(name for name, _ in families)
    return "redacted {} match{}: {}".format(total, "" if total == 1 else "es", names)


def _step_line(step: dict) -> str:
    status = step.get("status") or "pending"
    mark = {"done": "x", "active": "~", "blocked": "!"}.get(status, " ")
    line = "- [{}] {}. {}".format(mark, step.get("id"), (step.get("text") or "").strip())
    if status in ("active", "blocked"):
        line += " ({})".format(status)
    return line


def render_brief(plan: dict, pinned: Sequence[dict], recent: Sequence[dict], session=None,
                 title: str = "Concepts brief") -> str:
    """Render the generated block, fenced by markers so hand-written text survives."""
    goal = (plan.get("goal") or "").strip()
    lines: List[str] = [
        START_MARKER,
        "",
        "## Goal",
        "",
        goal or "(no goal recorded: orchestra-tx plan new \"<goal>\" --step \"<first step>\")",
        "",
        "## Constraints and decisions",
        "",
    ]
    if pinned:
        for entry in pinned:
            lines.append("- " + (entry.get("text") or "").strip())
    else:
        lines.append("(nothing pinned yet: orchestra-tx memory add \"<decision>\" --pin)")

    lines += ["", "## Plan", ""]
    steps = plan.get("steps") or []
    if steps:
        lines.extend(_step_line(step) for step in steps)
    else:
        lines.append("(no plan steps yet: orchestra-tx plan add \"<step>\")")

    if recent:
        lines += ["", "## Recent memory", ""]
        for entry in recent:
            lines.append("- [{}] {}".format(entry.get("id", "--------"), (entry.get("text") or "").strip()))

    if session:
        summary = ""
        notes = session.get("notes") or []
        if notes:
            summary = str(notes[-1]).strip()
        lines += ["", "## Last session", ""]
        line = "- {} ({})".format(session.get("id") or "unknown", session.get("ended") or session.get("started") or "")
        lines.append(line.strip())
        if summary:
            lines.append("- summary: " + summary)

    lines += ["", END_MARKER]
    return "\n".join(lines) + "\n"


def merge_brief(existing: str, generated: str) -> str:
    """Replace only the generated block; every hand-written line is preserved."""
    generated = generated.rstrip() + "\n"
    if START_MARKER in existing and END_MARKER in existing:
        head = existing.split(START_MARKER, 1)[0]
        tail = existing.split(END_MARKER, 1)[1]
        return head + generated + tail.lstrip("\n")
    if not existing.strip():
        return "# Concepts brief\n\n" + generated
    return existing.rstrip() + "\n\n" + generated
