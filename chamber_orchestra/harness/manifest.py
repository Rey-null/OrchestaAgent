"""Versioned, content-addressed harness manifests.

A harness is everything around the model: prompt, skills, memory, tool
guidance, subagents and scripts. Only that surface is versionable and editable
by the optimizer. Safety-critical configuration (guardrails, permissions and
the evaluation suite) lives *outside* the manifest, so no patch can reach it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

EDITABLE_COMPONENTS: tuple[str, ...] = (
    "prompt",
    "skills",
    "memory",
    "tool_guidance",
    "subagents",
    "scripts",
)

PROTECTED_COMPONENTS: tuple[str, ...] = (
    "guardrails",
    "permissions",
    "evaluation",
)


class HarnessError(ValueError):
    """Base class for harness definition errors."""


class ProtectedComponentError(HarnessError):
    """Raised when a patch or manifest tries to touch safety-critical surface."""


class ManifestIntegrityError(HarnessError):
    """Raised when a stored manifest does not match its own content address."""


def canonical_json(value: Any) -> str:
    """Stable JSON encoding used for every content address in the system."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HarnessManifest:
    """Immutable snapshot of the editable harness surface for one scope."""

    scope: str
    components: Mapping[str, Any] = field(default_factory=dict)
    parent: str | None = None
    provenance: tuple[str, ...] = ()

    _digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        scope = self.scope.strip() if isinstance(self.scope, str) else ""
        if not scope:
            raise HarnessError("scope must be a non-empty string")
        if "/" in scope or "\\" in scope or scope in {".", ".."}:
            raise HarnessError(f"invalid scope name: {scope!r}")

        components = dict(self.components)
        for name in components:
            if name in PROTECTED_COMPONENTS:
                raise ProtectedComponentError(
                    f"{name!r} is protected: it cannot be part of an editable harness"
                )
            if name not in EDITABLE_COMPONENTS:
                raise HarnessError(f"unknown harness component: {name!r}")

        provenance = tuple(str(item) for item in self.provenance)
        payload = self._payload(scope, components, self.parent, provenance)
        try:
            canonical_json(payload)
        except TypeError as exc:  # non JSON-serializable component values
            raise HarnessError(f"harness components must be JSON-serializable: {exc}") from exc

        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "components", MappingProxyType(components))
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "_digest", content_digest(payload))

    @staticmethod
    def _payload(
        scope: str,
        components: Mapping[str, Any],
        parent: str | None,
        provenance: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "scope": scope,
            "components": dict(components),
            "parent": parent,
            "provenance": list(provenance),
        }

    @property
    def id(self) -> str:
        return self._digest

    def document(self) -> dict[str, Any]:
        payload = self._payload(
            self.scope, dict(self.components), self.parent, self.provenance
        )
        payload["id"] = self.id
        return payload

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "HarnessManifest":
        manifest = cls(
            scope=document["scope"],
            components=document.get("components", {}),
            parent=document.get("parent"),
            provenance=tuple(document.get("provenance", ())),
        )
        declared = document.get("id")
        if declared is not None and declared != manifest.id:
            raise ManifestIntegrityError(
                f"manifest id mismatch: declared {declared}, recomputed {manifest.id}"
            )
        return manifest

    def replace_components(
        self, components: Mapping[str, Any], *, provenance: tuple[str, ...] | None = None
    ) -> "HarnessManifest":
        return HarnessManifest(
            scope=self.scope,
            components=components,
            parent=self.id,
            provenance=provenance if provenance is not None else self.provenance,
        )

    def declared_behaviors(self) -> tuple[str, ...]:
        """Behaviors the harness claims to enforce, in stable order."""
        guidance = self.components.get("tool_guidance", {})
        if not isinstance(guidance, Mapping):
            return ()
        raw = guidance.get("behaviors", ())
        if not isinstance(raw, (list, tuple)):
            return ()
        return tuple(sorted({str(item) for item in raw}))
