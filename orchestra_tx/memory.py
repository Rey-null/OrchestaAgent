"""Persistent memory that outlives a shell session.

Entries are appended to a JSONL file per scope (``project`` or ``global``) so a
crash or a killed Termux session can never corrupt earlier notes.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from . import store

MEMORY_FILE = "memory.jsonl"
SCOPES = ("project", "global")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def path_for(scope: str = "project", project: Optional[str] = None):
    if scope == "global":
        return store.global_store() / MEMORY_FILE
    return store.project_store(project) / MEMORY_FILE


def load(scope: str = "project", project: Optional[str] = None) -> List[dict]:
    return store.read_jsonl(path_for(scope, project))


def load_all(project: Optional[str] = None) -> List[dict]:
    """Project memory first, then global memory (each tagged by scope)."""
    rows: List[dict] = []
    for scope in ("project", "global"):
        for entry in load(scope, project):
            entry.setdefault("scope", scope)
            rows.append(entry)
    return rows


def _lock(scope: str, project: Optional[str]):
    if scope == "global":
        return store.global_lock()
    return store.project_lock(project)


def _new_id(rows: Sequence[dict]) -> str:
    taken = {entry.get("id") for entry in rows}
    while True:
        candidate = uuid.uuid4().hex[:8]
        if candidate not in taken:
            return candidate


def add(
    text: str,
    tags: Optional[Sequence[str]] = None,
    scope: str = "project",
    project: Optional[str] = None,
    session: Optional[str] = None,
    pinned: bool = False,
) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("memory text cannot be empty")
    if scope not in SCOPES:
        raise ValueError("scope must be one of: {}".format(", ".join(SCOPES)))
    clean_tags = []
    for tag in tags or []:
        for piece in str(tag).split(","):
            piece = piece.strip().lstrip("#")
            if piece and piece not in clean_tags:
                clean_tags.append(piece)
    with _lock(scope, project):
        rows = load(scope, project)
        entry = {
            "id": _new_id(rows),
            "text": text,
            "tags": clean_tags,
            "scope": scope,
            "session": session or "",
            "pinned": bool(pinned),
            "created": now(),
        }
        rows.append(entry)
        store.write_jsonl(path_for(scope, project), rows)
    return entry


def remove(entry_id: str, scope: str = "project", project: Optional[str] = None) -> bool:
    if scope not in SCOPES:
        raise ValueError("scope must be one of: {}".format(", ".join(SCOPES)))
    with _lock(scope, project):
        rows = load(scope, project)
        kept = [row for row in rows if row.get("id") != entry_id]
        if len(kept) == len(rows):
            return False
        store.write_jsonl(path_for(scope, project), kept)
    return True


def _tokens(query: str) -> List[str]:
    return [tok for tok in re.split(r"[^0-9a-zA-Z_\-]+", (query or "").lower()) if tok]


def score(entry: dict, tokens: Sequence[str]) -> float:
    if not tokens:
        return 1.0
    text = str(entry.get("text", "")).lower()
    tags = " ".join(str(tag) for tag in entry.get("tags", [])).lower()
    total = 0.0
    for token in tokens:
        if token in tags:
            total += 3.0
        if token in text:
            total += 2.0
    if entry.get("pinned"):
        total += 0.5
    return total


def search(
    query: str,
    limit: int = 10,
    scope: str = "all",
    project: Optional[str] = None,
) -> List[dict]:
    pool = load_all(project) if scope == "all" else load(scope, project)
    tokens = _tokens(query)
    ranked = []
    for index, entry in enumerate(pool):
        value = score(entry, tokens)
        if value <= 0:
            continue
        ranked.append((value, str(entry.get("created", "")), index, entry))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [item[3] for item in ranked[: max(1, limit)]]


def recent(limit: int = 10, scope: str = "all", project: Optional[str] = None) -> List[dict]:
    pool = load_all(project) if scope == "all" else load(scope, project)
    pool.sort(key=lambda entry: str(entry.get("created", "")), reverse=True)
    return pool[: max(1, limit)]


def pinned(project: Optional[str] = None) -> List[dict]:
    return [entry for entry in load_all(project) if entry.get("pinned")]


def render_entry(entry: dict, color: bool = False) -> str:
    tags = " ".join("#" + str(tag) for tag in entry.get("tags", []))
    ident = entry.get("id", "--------")
    scope = entry.get("scope", "project")
    created = str(entry.get("created", ""))[:10]
    head = "[{id}] {text}".format(id=ident, text=entry.get("text", ""))
    if color:
        head = "\033[36m[{id}]\033[0m {text}".format(id=ident, text=entry.get("text", ""))
    meta = "      {scope} \u00b7 {created}".format(scope=scope, created=created)
    if entry.get("pinned"):
        meta += " \u00b7 pinned"
    if tags:
        meta += " \u00b7 " + tags
    return head + "\n" + meta


def render(entries: Sequence[dict], color: bool = False, empty: str = "(no memory entries)") -> str:
    if not entries:
        return empty
    return "\n".join(render_entry(entry, color=color) for entry in entries)


def export(scope: str = "all", fmt: str = "jsonl", project: Optional[str] = None) -> str:
    rows = load_all(project) if scope == "all" else load(scope, project)
    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
    if fmt == "md":
        lines = ["# orchestra-tx memory", ""]
        for entry in rows:
            tags = " ".join("#" + str(tag) for tag in entry.get("tags", []))
            lines.append("- **{id}** ({scope}, {created}) {text}".format(
                id=entry.get("id"),
                scope=entry.get("scope", scope),
                created=str(entry.get("created", ""))[:10],
                text=entry.get("text", ""),
            ))
            if tags:
                lines.append("  - " + tags)
        return "\n".join(lines) + "\n"
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
