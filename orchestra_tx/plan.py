"""The session plan: a small ordered checklist persisted per project."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from . import store

PLAN_FILE = "plan.json"
STATUSES = ("pending", "active", "done", "blocked")

_ASCII_GLYPHS = {"pending": "[ ]", "active": "[~]", "done": "[x]", "blocked": "[!]"}
_UNICODE_GLYPHS = {"pending": "\u25a1", "active": "\u25b8", "done": "\u2714", "blocked": "\u2716"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def path_for(project: Optional[str] = None):
    return store.project_store(project) / PLAN_FILE


def load(project: Optional[str] = None) -> dict:
    data = store.read_json(path_for(project), None)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("goal", "")
    data.setdefault("steps", [])
    data.setdefault("created", now())
    data.setdefault("updated", data["created"])
    data.setdefault("project", str(store.project_root(project)))
    return data


def save(plan: dict, project: Optional[str] = None) -> dict:
    plan["updated"] = now()
    store.write_json(path_for(project), plan)
    return plan


def _next_id(plan: dict) -> int:
    ids = [int(step.get("id", 0)) for step in plan["steps"]]
    return (max(ids) + 1) if ids else 1


def _step(plan: dict, step_id: int) -> dict:
    for step in plan["steps"]:
        if int(step.get("id", 0)) == int(step_id):
            return step
    raise KeyError("no step with id {}".format(step_id))


def create(goal: str, steps: Optional[List[str]] = None, project: Optional[str] = None) -> dict:
    plan = load(project)
    plan["goal"] = goal or plan.get("goal", "")
    plan["steps"] = []
    for text in steps or []:
        plan["steps"].append(
            {"id": _next_id(plan), "text": text, "status": "pending", "note": "", "created": now(), "updated": now()}
        )
    if plan["steps"]:
        plan["steps"][0]["status"] = "active"
    return save(plan, project)


def add(text: str, note: str = "", project: Optional[str] = None) -> dict:
    plan = load(project)
    step = {"id": _next_id(plan), "text": text, "status": "pending", "note": note, "created": now(), "updated": now()}
    plan["steps"].append(step)
    if step["status"] == "pending" and not any(s["status"] == "active" for s in plan["steps"]):
        step["status"] = "active"
    save(plan, project)
    return step


def set_status(step_id: int, status: str, note: Optional[str] = None, project: Optional[str] = None) -> dict:
    if status not in STATUSES:
        raise ValueError("status must be one of: {}".format(", ".join(STATUSES)))
    plan = load(project)
    step = _step(plan, step_id)
    if status == "active":
        for other in plan["steps"]:
            if other.get("status") == "active" and other is not step:
                other["status"] = "pending"
                other["updated"] = now()
    step["status"] = status
    step["updated"] = now()
    if note is not None:
        step["note"] = note
    # Finishing the active step should hand over to the next pending one, so a
    # session always has exactly one thing it is working on.
    if status == "done" and not any(s.get("status") == "active" for s in plan["steps"]):
        for other in plan["steps"]:
            if other.get("status") == "pending":
                other["status"] = "active"
                other["updated"] = now()
                break
    save(plan, project)
    return step


def set_note(step_id: int, note: str, project: Optional[str] = None) -> dict:
    plan = load(project)
    step = _step(plan, step_id)
    step["note"] = note
    step["updated"] = now()
    save(plan, project)
    return step


def progress(plan: dict) -> dict:
    steps = plan.get("steps", [])
    done = sum(1 for s in steps if s.get("status") == "done")
    total = len(steps)
    percent = int(round((done / total) * 100)) if total else 0
    return {"done": done, "total": total, "percent": percent, "complete": bool(total) and done == total}


def active_step(plan: dict) -> Optional[dict]:
    for step in plan.get("steps", []):
        if step.get("status") == "active":
            return step
    return None


def render(plan: dict, ascii_only: bool = False, color: bool = False) -> str:
    glyphs = _ASCII_GLYPHS if ascii_only else _UNICODE_GLYPHS
    colors = {
        "pending": "\033[2m",
        "active": "\033[1;36m",
        "done": "\033[32m",
        "blocked": "\033[1;31m",
    }
    stats = progress(plan)
    lines: List[str] = []
    goal = plan.get("goal") or "(no goal set)"
    lines.append("Plan: " + goal)
    lines.append(
        "Progress: {done}/{total} done ({percent}%)".format(**stats)
        + ("  \u2014 complete" if stats["complete"] else "")
    )
    if not plan.get("steps"):
        lines.append("")
        lines.append("No steps yet. Add one with: orchestra-tx plan add \"<step>\"")
        return "\n".join(lines)
    lines.append("")
    for step in plan["steps"]:
        status = step.get("status", "pending")
        marker = glyphs.get(status, "[?]")
        head = "{marker} {id}. {text}".format(marker=marker, id=step.get("id"), text=step.get("text", ""))
        if color:
            head = colors.get(status, "") + head + "\033[0m"
        lines.append(head)
        note = (step.get("note") or "").strip()
        if note:
            for piece in note.splitlines():
                lines.append("      " + piece)
    return "\n".join(lines)
