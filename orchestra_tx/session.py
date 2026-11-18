"""Session lifecycle: a goal, a plan snapshot, and durable notes per session."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import memory, plan as plan_mod, store

SESSIONS_DIR = "sessions"
CURRENT_FILE = "current"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sessions_dir(project: Optional[str] = None) -> Path:
    return store.project_store(project) / SESSIONS_DIR


def _session_path(session_id: str, project: Optional[str] = None) -> Path:
    return sessions_dir(project) / (session_id + ".json")


def current_id(project: Optional[str] = None) -> str:
    return (store.read_json(store.project_store(project) / CURRENT_FILE, {}) or {}).get("id", "")


def set_current(session_id: str, project: Optional[str] = None) -> None:
    store.write_json(store.project_store(project) / CURRENT_FILE, {"id": session_id, "updated": now()})


def load(session_id: str, project: Optional[str] = None) -> Optional[dict]:
    if not session_id:
        return None
    data = store.read_json(_session_path(session_id, project), None)
    return data if isinstance(data, dict) else None


def current(project: Optional[str] = None) -> Optional[dict]:
    return load(current_id(project), project)


def start(goal: str = "", project: Optional[str] = None, notes: Optional[List[str]] = None) -> dict:
    plan = plan_mod.load(project)
    session = {
        "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4],
        "goal": goal or plan.get("goal", ""),
        "started": now(),
        "updated": now(),
        "notes": list(notes or []),
        "plan": {
            "goal": plan.get("goal", ""),
            "steps": [{"id": s.get("id"), "text": s.get("text"), "status": s.get("status")} for s in plan.get("steps", [])],
        },
        "ended": "",
    }
    with store.project_lock(project):
        store.write_json(_session_path(session["id"], project), session)
        set_current(session["id"], project)
    return session


def touch(project: Optional[str] = None, note: Optional[str] = None) -> Optional[dict]:
    session = current(project)
    if session is None:
        return None
    session["updated"] = now()
    if note:
        session.setdefault("notes", []).append(note)
    store.write_json(_session_path(session["id"], project), session)
    return session


def end(summary: str = "", remember: bool = True, project: Optional[str] = None) -> Optional[dict]:
    session = current(project)
    if session is None:
        return None
    session["ended"] = now()
    session["updated"] = session["ended"]
    if summary:
        session.setdefault("notes", []).append(summary)
    plan = plan_mod.load(project)
    stats = plan_mod.progress(plan)
    session["progress"] = stats
    store.write_json(_session_path(session["id"], project), session)
    if remember and summary:
        memory.add(
            summary,
            tags=["session", session["id"]],
            scope="project",
            project=project,
            session=session["id"],
        )
    store.write_json(store.project_store(project) / CURRENT_FILE, {"id": "", "updated": now()})
    return session


def recent(limit: int = 5, project: Optional[str] = None) -> List[dict]:
    directory = sessions_dir(project)
    if not directory.is_dir():
        return []
    rows = []
    for file in directory.glob("*.json"):
        data = store.read_json(file, None)
        if isinstance(data, dict) and data.get("id"):
            rows.append(data)
    rows.sort(key=lambda item: str(item.get("started", "")), reverse=True)
    return rows[: max(1, limit)]
