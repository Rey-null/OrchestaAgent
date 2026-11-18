"""Termux and orchestraCLI environment detection."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import store

TERMUX_PREFIX = "/data/data/com.termux/files/usr"
ORCHESTRA_NAMES = ("orchestra", "orchestra-cli")


def is_termux() -> bool:
    prefix = os.environ.get("PREFIX", "")
    if "com.termux" in prefix:
        return True
    return Path(TERMUX_PREFIX).is_dir()


def orchestra_binary() -> Optional[str]:
    override = os.environ.get("ORCHESTRA_BIN")
    if override:
        resolved = shutil.which(override) or (override if Path(override).exists() else None)
        if resolved:
            return resolved
    for name in ORCHESTRA_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def report(project_store: Path) -> List[Tuple[str, str, bool]]:
    """(label, value, ok) rows for ``orchestra-tx doctor``."""
    rows: List[Tuple[str, str, bool]] = []
    rows.append(("platform", "Termux" if is_termux() else platform.system() or "unknown", True))
    rows.append(("python", "{} ({})".format(platform.python_version(), sys.executable), sys.version_info >= (3, 9)))
    binary = orchestra_binary()
    rows.append(("orchestraCLI", binary or "not found (pip install orchestra-cli)", bool(binary)))
    rows.append(("store", str(project_store), project_store.exists()))
    writable, detail = _writable(project_store)
    rows.append(("storage access", detail, writable))
    rows.append(("lock support", "fcntl" if _has_fcntl() else "none (single-session only)", _has_fcntl()))
    return rows


def _writable(project_store: Path) -> Tuple[bool, str]:
    try:
        store.ensure_dir(project_store)
        probe = project_store / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, "writable: " + str(store.home_root())
    except OSError as exc:
        return False, "not writable: {} ({})".format(store.home_root(), exc)


def _has_fcntl() -> bool:
    try:
        import fcntl  # noqa: F401
    except ImportError:
        return False
    return True


def install_hint() -> str:
    if is_termux():
        return "pkg install python && pip install orchestra-cli && pip install -e ."
    return "pip install orchestra-cli"
