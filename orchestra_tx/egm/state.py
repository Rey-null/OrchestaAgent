"""Durable egm state: state.json, findings.json and triage.json.

Every write is atomic and a corrupt ``state.json`` is moved aside rather than
silently replaced, so a killed Termux shell never loses the round history.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import store

STATE_FILE = "state.json"
FINDINGS_FILE = "findings.json"
TRIAGE_FILE = "triage.json"

DEFAULTS = {
    "design": "",
    "status": "uninitialized",
    "round": 0,
    "stage": "none",
    "updated": "",
    "last_review": {},
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def egm_dir(project: Optional[str] = None) -> Path:
    return store.state_dir(project) / "egm"


def state_path(project: Optional[str] = None) -> Path:
    return egm_dir(project) / STATE_FILE


def findings_path(project: Optional[str] = None) -> Path:
    return egm_dir(project) / FINDINGS_FILE


def triage_path(project: Optional[str] = None) -> Path:
    return egm_dir(project) / TRIAGE_FILE


def initialized(project: Optional[str] = None) -> bool:
    return state_path(project).is_file()


def _quarantine(path: Path) -> str:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = path.with_name(path.name + ".corrupt-" + stamp)
    try:
        path.replace(target)
    except OSError:
        return ""
    return str(target)


def load_state(project: Optional[str] = None) -> Tuple[dict, str]:
    """Return ``(state, warning)``; a corrupt file is quarantined, not trusted."""
    path = state_path(project)
    raw = store.read_text(path)
    if not raw.strip():
        return dict(DEFAULTS, last_review={}), ""
    try:
        data = json.loads(raw)
    except ValueError:
        moved = _quarantine(path)
        warning = "state.json was corrupt; rebuilt it"
        if moved:
            warning += " (old file kept as {})".format(Path(moved).name)
        return dict(DEFAULTS, last_review={}), warning
    if not isinstance(data, dict):
        moved = _quarantine(path)
        warning = "state.json did not hold an object; rebuilt it"
        if moved:
            warning += " (old file kept as {})".format(Path(moved).name)
        return dict(DEFAULTS, last_review={}), warning
    state = dict(DEFAULTS)
    state.update(data)
    if not isinstance(state.get("last_review"), dict):
        state["last_review"] = {}
    return state, ""


def save_state(state: dict, project: Optional[str] = None) -> Path:
    return store.write_json(state_path(project), state)


def load_findings(project: Optional[str] = None) -> List[dict]:
    data = store.read_json(findings_path(project), [])
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def save_findings(findings: List[dict], project: Optional[str] = None) -> Path:
    return store.write_json(findings_path(project), list(findings))


def load_triage(project: Optional[str] = None) -> Dict[str, Any]:
    data = store.read_json(triage_path(project), {})
    return data if isinstance(data, dict) else {}
