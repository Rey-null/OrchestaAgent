"""Tamper-evident chain over every ledger entry.

Each recorded entry appends a row to ``chain`` that commits to the previous
entry's hash, to the entry's identity and to a digest of its document. An HMAC
keyed with a secret kept outside the SQLite file (default: ``<ledger>.key``,
mode 0600; override with ``CHAMBER_LEDGER_KEY_FILE``) seals each entry, so
rewriting a row, deleting one, reordering them or corrupting the chain is
detectable rather than merely discouraged.

The chain detects modification of recorded history; it cannot detect an
attacker who removes the newest entries *and* the key, which is why exports
are meant to be kept elsewhere as checkpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chamber_orchestra.harness.manifest import canonical_json

if TYPE_CHECKING:  # pragma: no cover - typing only
    from chamber_orchestra.ledger.store import Ledger

GENESIS = "0" * 64
KEY_SUFFIX = ".key"
KEY_ENV = "CHAMBER_LEDGER_KEY_FILE"
_KEY_BYTES = 32


class ChainError(RuntimeError):
    """Raised when the chain key is unusable or the chain cannot be verified."""


def key_path(ledger_path: Path) -> Path:
    override = os.environ.get(KEY_ENV)
    if override:
        return Path(override)
    return ledger_path.with_name(ledger_path.name + KEY_SUFFIX)


def load_or_create_key(ledger_path: Path) -> bytes:
    """Read the sealing key, creating it next to (never inside) the database."""
    path = key_path(ledger_path)
    if path.is_file():
        data = path.read_bytes().strip()
        if len(data) < 16:
            raise ChainError(f"ledger key at {path} is too short to seal the chain")
        return data
    path.parent.mkdir(parents=True, exist_ok=True)
    data = os.urandom(_KEY_BYTES)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # a concurrent writer won the race
        return path.read_bytes().strip()
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return data


def entry_digest(
    prev_hash: str, kind: str, entry_id: str, payload_digest: str
) -> str:
    body = canonical_json(
        {
            "prev": prev_hash,
            "kind": kind,
            "entry_id": entry_id,
            "payload": payload_digest,
        }
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def seal(key: bytes, entry_hash: str) -> str:
    return hmac.new(key, entry_hash.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class ChainReport:
    """Result of walking the chain and recomputing every commitment."""

    entries: int
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def document(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "entries": self.entries,
            "issues": list(self.issues),
        }


def verify(ledger: "Ledger") -> ChainReport:
    """Recompute the chain and compare it with the recorded state."""
    rows = ledger.chain_rows()
    issues: list[str] = []
    prev_hash = GENESIS
    previous_seq: int | None = None
    for index, row in enumerate(rows, start=1):
        seq = int(row["seq"])
        if previous_seq is not None and seq != previous_seq + 1:
            issues.append(
                f"chain is not contiguous: {previous_seq} is followed by {seq}"
            )
        if previous_seq is None and row["prev_hash"] != GENESIS:
            issues.append("chain does not start at genesis; earlier entries were removed")
        previous_seq = seq
        expected = entry_digest(
            prev_hash, row["kind"], row["entry_id"], row["payload_digest"]
        )
        if not hmac.compare_digest(expected, row["entry_hash"]):
            issues.append(
                f"entry {index} ({row['kind']} {row['entry_id']}) was altered or reordered"
            )
        if not hmac.compare_digest(prev_hash, row["prev_hash"]):
            issues.append(
                f"entry {index} ({row['kind']} {row['entry_id']}) has a broken link"
            )
        if not hmac.compare_digest(seal(ledger.seal_key, row["entry_hash"]), row["mac"]):
            issues.append(f"entry {index} ({row['kind']} {row['entry_id']}) has an invalid seal")
        document = ledger.document_for(row["kind"], row["entry_id"])
        if document is None:
            issues.append(
                f"entry {index} ({row['kind']} {row['entry_id']}) has no record"
            )
        else:
            from chamber_orchestra.harness.manifest import content_digest

            if content_digest(document) != row["payload_digest"]:
                issues.append(
                    f"entry {index} ({row['kind']} {row['entry_id']}) payload changed"
                )
        prev_hash = row["entry_hash"]

    recorded = ledger.chain_counts()
    for kind, count in ledger.record_counts().items():
        chained = recorded.get(kind, 0)
        if chained != count:
            issues.append(
                f"{kind}: {count} records but {chained} chain entries"
            )
    return ChainReport(entries=len(rows), issues=tuple(issues))


__all__ = [
    "GENESIS",
    "KEY_ENV",
    "ChainError",
    "ChainReport",
    "entry_digest",
    "key_path",
    "load_or_create_key",
    "seal",
    "verify",
]
