"""Paths, atomic writes and advisory locking for orchestra-tx.

Termux-friendly: stdlib only, no native builds, no network. Every write is
atomic (temp file + ``os.replace``) so a killed shell cannot leave a truncated
plan or memory file behind.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional

try:  # Termux and every POSIX target have fcntl; keep Windows importable.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

STATE_DIRNAME = ".orchestra"
ENV_HOME = "ORCHESTRA_TX_HOME"


def home_root() -> Path:
    """Root of the persistent store (survives sessions and reboots)."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "orchestra-tx"


def project_root(start: Optional[str] = None) -> Path:
    path = Path(start) if start else Path.cwd()
    try:
        return path.resolve()
    except OSError:  # pragma: no cover
        return Path(os.path.abspath(str(path)))


def project_key(start: Optional[str] = None) -> str:
    """Stable, readable, collision-free key for a project directory."""
    root = project_root(start)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-._") or "project"
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:10]
    return "{}-{}".format(name, digest)


def project_store(start: Optional[str] = None) -> Path:
    return home_root() / "projects" / project_key(start)


def global_store() -> Path:
    return home_root() / "global"


def state_dir(start: Optional[str] = None) -> Path:
    """Project-local scratch dir for context files handed to orchestraCLI."""
    return project_root(start) / STATE_DIRNAME


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_text(target: Path, text: str) -> Path:
    ensure_dir(target.parent)
    fd, tmp = tempfile.mkstemp(prefix="." + target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def read_text(target: Path, default: str = "") -> str:
    try:
        with target.open("r", encoding="utf-8") as handle:
            return handle.read()
    except (FileNotFoundError, OSError, ValueError):
        return default


def write_json(target: Path, data: Any) -> Path:
    return write_text(target, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(target: Path, default: Any = None) -> Any:
    try:
        with target.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        return default


def write_jsonl(target: Path, rows: Iterable[dict]) -> Path:
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    return write_text(target, body)


def read_jsonl(target: Path) -> List[dict]:
    rows: List[dict] = []
    try:
        with target.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    continue  # skip a torn line instead of losing the store
                if isinstance(value, dict):
                    rows.append(value)
    except (FileNotFoundError, OSError):
        pass
    return rows


class LockTimeout(RuntimeError):
    """Another process held the advisory lock past the caller's deadline."""


def _lock_pid(directory: Path) -> str:
    try:
        text = (directory / ".lock").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return text.splitlines()[0].strip() if text else ""


@contextmanager
def locked(directory: Path, timeout: Optional[float] = None) -> Iterator[None]:
    """Advisory lock so concurrent Termux sessions cannot clobber each other.

    ``timeout=None`` waits forever; a number of seconds raises
    :class:`LockTimeout` instead, naming the holder recorded in the lock file.
    """
    ensure_dir(directory)
    handle = (directory / ".lock").open("a+")
    try:
        if fcntl is not None:
            if timeout is None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            else:
                deadline = time.monotonic() + max(0.0, float(timeout))
                while True:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            pid = _lock_pid(directory)
                            holder = "pid " + pid if pid else "another session"
                            raise LockTimeout(
                                "orchestra-tx lock is held by {}; retry when it finishes".format(holder)
                            )
                        time.sleep(0.05)
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover
                pass
        handle.close()


def project_lock(start: Optional[str] = None):
    return locked(project_store(start))


def global_lock():
    return locked(global_store())
