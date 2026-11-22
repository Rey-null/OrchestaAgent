"""Patch model: the only way the optimizer can produce a new harness version.

A patch is data, never code. It is validated against the editable component
allow-list before it can be applied, and it is bound to the exact base version
it was derived from so a stale proposal cannot silently overwrite newer work.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from chamber_orchestra.harness.manifest import (
    EDITABLE_COMPONENTS,
    PROTECTED_COMPONENTS,
    HarnessError,
    HarnessManifest,
    ProtectedComponentError,
    canonical_json,
)

PatchTarget = str
OpName = Literal["set", "delete"]

_MAX_SEGMENT = 64
_MAX_TARGET = 200


@dataclass(frozen=True, slots=True)
class PatchOp:
    op: OpName
    target: PatchTarget
    value: Any = None

    def document(self) -> dict[str, Any]:
        return {"op": self.op, "target": self.target, "value": self.value}


@dataclass(frozen=True, slots=True)
class HarnessPatch:
    proposal_id: str
    base: str
    rationale: str
    ops: tuple[PatchOp, ...] = field(default_factory=tuple)

    def document(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "base": self.base,
            "rationale": self.rationale,
            "ops": [op.document() for op in self.ops],
        }


def _segments(target: str) -> list[str]:
    if not isinstance(target, str) or not target:
        raise HarnessError("patch target must be a non-empty string")
    if len(target) > _MAX_TARGET:
        raise HarnessError(f"patch target too long: {len(target)} chars")
    if "\\" in target:
        raise HarnessError(f"patch target must use '/' separators: {target!r}")
    parts = target.split("/")
    for part in parts:
        if not part:
            raise HarnessError(f"patch target has an empty segment: {target!r}")
        if part in {".", ".."}:
            raise HarnessError(f"patch target may not traverse: {target!r}")
        if len(part) > _MAX_SEGMENT:
            raise HarnessError(f"patch target segment too long: {part!r}")
    return parts


def validate_patch(patch: HarnessPatch) -> None:
    if not patch.ops:
        raise HarnessError("a patch must contain at least one operation")
    if not patch.proposal_id:
        raise HarnessError("a patch must carry a proposal id")
    for op in patch.ops:
        if op.op not in ("set", "delete"):
            raise HarnessError(f"unsupported patch operation: {op.op!r}")
        parts = _segments(op.target)
        head = parts[0]
        if head in PROTECTED_COMPONENTS:
            raise ProtectedComponentError(
                f"patch targets protected component {head!r}; it is outside the editable surface"
            )
        if head not in EDITABLE_COMPONENTS:
            raise HarnessError(f"unknown harness component in patch target: {head!r}")
        if op.op == "delete" and op.value is not None:
            raise HarnessError(f"delete operation may not carry a value: {op.target!r}")
        if op.op == "set":
            try:
                canonical_json(op.value)
            except TypeError as exc:
                raise HarnessError(
                    f"patch value for {op.target!r} is not JSON-serializable: {exc}"
                ) from exc


def _apply_op(components: dict[str, Any], op: PatchOp) -> None:
    parts = _segments(op.target)
    head, rest = parts[0], parts[1:]
    if not rest:
        if op.op == "delete":
            if head not in components:
                raise HarnessError(f"cannot delete missing component {head!r}")
            del components[head]
        else:
            components[head] = copy.deepcopy(op.value)
        return

    if op.op == "delete" and not isinstance(components.get(head), dict):
        raise HarnessError(f"cannot delete missing path {op.target!r}")

    node = components.setdefault(head, {}) if op.op == "set" else components.get(head)
    if not isinstance(node, dict):
        raise HarnessError(
            f"cannot traverse {head!r}: expected an object, found {type(node).__name__}"
        )
    for part in rest[:-1]:
        if op.op == "set":
            child = node.setdefault(part, {})
        else:
            child = node.get(part)
        if op.op == "delete" and not isinstance(child, dict):
            raise HarnessError(f"cannot delete missing path {op.target!r}")
        if not isinstance(child, dict):
            raise HarnessError(f"cannot traverse {part!r}: expected an object")
        node = child

    leaf = rest[-1]
    if op.op == "delete":
        if leaf not in node:
            raise HarnessError(f"cannot delete missing path {op.target!r}")
        del node[leaf]
    else:
        node[leaf] = copy.deepcopy(op.value)


def apply_patch(manifest: HarnessManifest, patch: HarnessPatch) -> HarnessManifest:
    """Return the candidate manifest produced by ``patch`` on top of ``manifest``."""
    validate_patch(patch)
    if patch.base != manifest.id:
        raise HarnessError(
            f"stale patch: derived from {patch.base}, applied to {manifest.id}"
        )

    components = json.loads(json.dumps(dict(manifest.components)))
    for op in patch.ops:
        _apply_op(components, op)

    return HarnessManifest(
        scope=manifest.scope,
        components=components,
        parent=manifest.id,
        provenance=(patch.proposal_id,),
    )
