"""Write-once harness store with a per-scope active pointer.

Invariants enforced here, not by convention:

* a stored manifest is immutable and addressed by its content hash;
* exactly one harness is active per scope at a time;
* promotion requires a recorded, approving decision from the gate;
* every pointer move is appended to an audit log, so rollback is auditable.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from chamber_orchestra.harness.manifest import (
    HarnessManifest,
    ManifestIntegrityError,
    canonical_json,
)


class RegistryError(RuntimeError):
    """Base class for registry failures."""


class UnknownHarnessError(RegistryError):
    """Raised when a harness id is not present in the store."""


class PromotionRejected(RegistryError):
    """Raised when a promotion attempt lacks recorded evidence or approval."""


class DecisionAuthority(Protocol):
    """Source of truth for whether a promotion decision was recorded and approved."""

    def is_approved(self, decision_id: str) -> bool: ...


class DecisionLike(Protocol):
    decision_id: str
    candidate_id: str
    baseline_id: str
    approved: bool
    evidence_digest: str


def _atomic_write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class HarnessStore:
    """Filesystem-backed, content-addressed harness registry."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        (self.root / "harnesses").mkdir(parents=True, exist_ok=True)
        (self.root / "scopes").mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------
    def _harness_path(self, harness_id: str) -> Path:
        if not harness_id or "/" in harness_id or "\\" in harness_id:
            raise RegistryError(f"invalid harness id: {harness_id!r}")
        return self.root / "harnesses" / f"{harness_id}.json"

    def _scope_dir(self, scope: str) -> Path:
        if not scope or "/" in scope or "\\" in scope or scope in {".", ".."}:
            raise RegistryError(f"invalid scope: {scope!r}")
        return self.root / "scopes" / scope

    # -- manifests -----------------------------------------------------
    def put(self, manifest: HarnessManifest) -> str:
        """Store a manifest. Re-storing identical content is a no-op."""
        path = self._harness_path(manifest.id)
        body = canonical_json(manifest.document()) + "\n"
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if path.read_text(encoding="utf-8") != body:
                raise RegistryError(
                    f"content address {manifest.id} already holds different content"
                ) from None
        return manifest.id

    def exists(self, harness_id: str) -> bool:
        return self._harness_path(harness_id).is_file()

    def get(self, harness_id: str) -> HarnessManifest:
        path = self._harness_path(harness_id)
        if not path.is_file():
            raise UnknownHarnessError(f"unknown harness: {harness_id}")
        document = json.loads(path.read_text(encoding="utf-8"))
        try:
            return HarnessManifest.from_document(document)
        except ManifestIntegrityError as exc:
            raise RegistryError(str(exc)) from exc

    # -- active pointer ------------------------------------------------
    def _pointer(self, scope: str) -> Path:
        return self._scope_dir(scope) / "active.json"

    def active_id(self, scope: str) -> str | None:
        pointer = self._pointer(scope)
        if not pointer.is_file():
            return None
        return json.loads(pointer.read_text(encoding="utf-8"))["harness_id"]

    def active(self, scope: str) -> HarnessManifest | None:
        harness_id = self.active_id(scope)
        return self.get(harness_id) if harness_id else None

    def initialize(self, manifest: HarnessManifest) -> str:
        """Set the first active harness for a scope. Fails if already initialized."""
        self.put(manifest)
        pointer = self._pointer(manifest.scope)
        if pointer.is_file():
            raise RegistryError(f"scope {manifest.scope!r} is already initialized")
        _atomic_write(pointer, canonical_json({"harness_id": manifest.id}) + "\n")
        self._audit(
            manifest.scope,
            {"kind": "initialize", "from": None, "to": manifest.id},
        )
        return manifest.id

    def promote(
        self,
        scope: str,
        candidate_id: str,
        decision: DecisionLike,
        authority: DecisionAuthority,
    ) -> str:
        """Move the active pointer to ``candidate_id`` after checking the decision."""
        if not decision.approved:
            raise PromotionRejected(
                f"decision {decision.decision_id} did not approve a promotion"
            )
        if decision.candidate_id != candidate_id:
            raise PromotionRejected(
                f"decision {decision.decision_id} refers to {decision.candidate_id}, "
                f"not {candidate_id}"
            )
        if not decision.evidence_digest:
            raise PromotionRejected("decision carries no evidence digest")
        if not authority.is_approved(decision.decision_id):
            raise PromotionRejected(
                f"decision {decision.decision_id} is not recorded as approved evidence"
            )

        candidate = self.get(candidate_id)
        if candidate.scope != scope:
            raise PromotionRejected(
                f"candidate belongs to scope {candidate.scope!r}, not {scope!r}"
            )
        current = self.active_id(scope)
        if current is None:
            raise RegistryError(f"scope {scope!r} is not initialized")
        # The comparison only means something against the harness it was run
        # against. If the pointer moved since, the evidence is about a version
        # that is no longer deployed and cannot authorize this promotion.
        if decision.baseline_id != current:
            raise PromotionRejected(
                f"decision {decision.decision_id} was taken against "
                f"{decision.baseline_id}, but the active harness is {current}; "
                "a promotion must be decided against what is deployed"
            )
        if current == candidate_id:
            return current

        _atomic_write(
            self._pointer(scope),
            canonical_json({"harness_id": candidate_id}) + "\n",
        )
        self._audit(
            scope,
            {
                "kind": "promote",
                "from": current,
                "to": candidate_id,
                "decision_id": decision.decision_id,
                "evidence_digest": decision.evidence_digest,
            },
        )
        return candidate_id

    def _was_active(self, scope: str, harness_id: str) -> bool:
        """Whether ``harness_id`` was ever the active harness in ``scope``."""
        return any(entry.get("to") == harness_id for entry in self.history(scope))

    def rollback(self, scope: str, target_id: str, *, reason: str) -> str:
        """Move the active pointer back to a previously active harness."""
        target = self.get(target_id)
        if target.scope != scope:
            raise PromotionRejected(
                f"rollback target belongs to scope {target.scope!r}, not {scope!r}"
            )
        current = self.active_id(scope)
        if current is None:
            raise RegistryError(f"scope {scope!r} is not initialized")
        if not self._was_active(scope, target_id):
            raise PromotionRejected(
                f"rollback target {target_id} was never active in scope {scope!r}; "
                "only a previously active harness can be restored"
            )
        _atomic_write(
            self._pointer(scope),
            canonical_json({"harness_id": target_id}) + "\n",
        )
        self._audit(
            scope,
            {
                "kind": "rollback",
                "from": current,
                "to": target_id,
                "reason": reason,
            },
        )
        return target_id

    def history(self, scope: str) -> list[dict]:
        path = self._scope_dir(scope) / "audit.jsonl"
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _audit(self, scope: str, entry: dict) -> None:
        path = self._scope_dir(scope) / "audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(canonical_json(entry) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
