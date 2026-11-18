"""Artifact creation: the designs directory, SITEMAP.md and egm state."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from .. import store
from . import state as state_mod

DESIGNS_DIRNAME = "designs"
SITEMAP_NAME = "SITEMAP.md"
BRIEF_NAME = "concepts_brief.md"
# Generated artifacts that live beside designs but are not designs themselves.
NOT_DESIGNS = (SITEMAP_NAME, BRIEF_NAME)

SITEMAP_HEADER = (
    "# Design sitemap\n"
    "\n"
    "| Document | Status | Date | Components | Description |\n"
    "| --- | --- | --- | --- | --- |\n"
)

_STATUS_RE = re.compile(r"^\s*(?:\*\*)?Status(?:\*\*)?\s*:\s*(.+?)\s*$", re.MULTILINE)


def designs_dir(project: Optional[str] = None, directory: Optional[str] = None) -> Path:
    if directory:
        path = Path(directory).expanduser()
        if not path.is_absolute():
            path = store.project_root(project) / path
        return path
    return store.state_dir(project) / DESIGNS_DIRNAME


def sitemap_path(directory: Path) -> Path:
    return Path(directory) / SITEMAP_NAME


def ensure_sitemap(directory: Path) -> Path:
    path = sitemap_path(directory)
    if not path.is_file():
        store.write_text(path, SITEMAP_HEADER)
    return path


def list_designs(directory: Path) -> List[Path]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return [
        path for path in sorted(directory.glob("*.md"))
        if path.is_file() and path.name not in NOT_DESIGNS
    ]


def design_status(path) -> str:
    """Read the ``**Status:**`` header of a design; ``""`` when it has none."""
    text = store.read_text(Path(path))
    if not text:
        return ""
    match = _STATUS_RE.search(text)
    if not match:
        return ""
    return match.group(1).strip().strip("*_` ")


def init(project: Optional[str], directory: Optional[str] = None, force: bool = False) -> Dict[str, object]:
    """Create the design directory, SITEMAP.md and the egm state file."""
    target = designs_dir(project, str(directory) if directory else None)
    created: List[str] = []
    existed: List[str] = []

    if target.is_dir():
        existed.append(str(target))
    else:
        store.ensure_dir(target)
        created.append(str(target))

    sitemap = sitemap_path(target)
    if sitemap.is_file():
        existed.append(str(sitemap))
    else:
        store.write_text(sitemap, SITEMAP_HEADER)
        created.append(str(sitemap))

    egm = state_mod.egm_dir(project)
    if egm.is_dir():
        existed.append(str(egm))
    else:
        store.ensure_dir(egm)
        created.append(str(egm))

    state = state_mod.state_path(project)
    if state.is_file() and not force:
        existed.append(str(state))
    else:
        current, _ = state_mod.load_state(project)
        if force or not state.is_file():
            current = dict(state_mod.DEFAULTS, last_review={})
        current["updated"] = state_mod.now()
        if not current.get("status"):
            current["status"] = "uninitialized"
        state_mod.save_state(current, project)
        created.append(str(state))

    return {
        "design_dir": str(target),
        "sitemap": str(sitemap),
        "state": str(state),
        "findings": str(state_mod.findings_path(project)),
        "created": created,
        "existed": existed,
        "initialized": True,
    }
