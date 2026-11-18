"""Render plan + memory + session into one Markdown context block.

The block is written to ``<project>/.orchestra/context.md`` and exported to
orchestraCLI through environment variables so any wrapper script, prompt or
agent invocation can pick it up.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from . import store

CONTEXT_FILE = "context.md"


def context_path(project: Optional[str] = None) -> Path:
    return store.state_dir(project) / CONTEXT_FILE


def build(
    session: Optional[dict],
    plan: dict,
    memories: Sequence[dict],
    project: Optional[str] = None,
) -> str:
    lines: List[str] = []
    lines.append("# orchestra-tx session context")
    lines.append("")
    lines.append("Project: `{}`".format(store.project_root(project)))
    lines.append("Store: `{}`".format(store.project_store(project)))
    if session:
        lines.append("Session: `{}` (started {})".format(session.get("id", ""), session.get("started", "")))
    else:
        lines.append("Session: (none started \u2014 run `orchestra-tx session start`)")
    lines.append("")

    lines.append("## Goal")
    lines.append(session.get("goal") if session and session.get("goal") else (plan.get("goal") or "(unset)"))
    lines.append("")

    lines.append("## Plan")
    steps = plan.get("steps", [])
    if not steps:
        lines.append("_No plan steps yet._")
    for step in steps:
        lines.append(
            "- [{status}] {id}. {text}".format(
                status=step.get("status", "pending"),
                id=step.get("id"),
                text=step.get("text", ""),
            )
        )
        if step.get("note"):
            lines.append("      " + str(step["note"]).replace("\n", "\n      "))
    lines.append("")

    lines.append("## Memory")
    if not memories:
        lines.append("_No remembered facts yet._")
    for entry in memories:
        tags = " ".join("#" + str(tag) for tag in entry.get("tags", []))
        line = "- ({scope}, {created}) {text}".format(
            scope=entry.get("scope", "project"),
            created=str(entry.get("created", ""))[:10],
            text=entry.get("text", ""),
        )
        if tags:
            line += "  " + tags
        lines.append(line)
    if session and session.get("notes"):
        lines.append("")
        lines.append("## Session notes")
        for note in session["notes"]:
            lines.append("- " + str(note))
    lines.append("")
    return "\n".join(lines)


def write(project: Optional[str] = None, text: str = "") -> Path:
    return store.write_text(context_path(project), text)
