"""Per-attempt provenance: what was evaluated, and under which configuration.

An attempt is only evidence if it can be explained later: which rendered
prompt, which executor, which suite and harness, and which model or seed if
any. A value the run cannot produce is recorded with an explicit status
instead of a plausible default, so "we do not know" never reads as
"unspecified option".
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping

from chamber_orchestra.harness.manifest import (
    HarnessManifest,
    canonical_json,
    content_digest,
)

FieldStatus = Literal["available", "unsupported", "unknown"]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ProvenanceError(ValueError):
    """Raised when provenance is malformed or claims a value it cannot prove."""


@dataclass(frozen=True, slots=True)
class Field:
    """One provenance value, or an explicit statement that it is unavailable.

    ``status`` is ``"available"`` when ``value`` was captured, ``"unsupported"``
    when the executor or model cannot produce it at all (a seed for a
    deterministic simulator, for instance), and ``"unknown"`` when it should
    have been captured but was not. Non-available fields carry a ``detail``
    explaining why, and never a value: nothing is invented and nothing is
    silently omitted.
    """

    status: FieldStatus
    value: Any = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ("available", "unsupported", "unknown"):
            raise ProvenanceError(f"unknown provenance status: {self.status!r}")
        if self.status == "available":
            if self.value is None:
                raise ProvenanceError("an available field needs a value")
            try:
                canonical_json(self.value)
            except TypeError as exc:
                raise ProvenanceError(
                    f"provenance value must be JSON-serializable: {exc}"
                ) from exc
        elif self.value is not None:
            raise ProvenanceError(
                f"a {self.status} field must not carry a value; explain it with detail="
            )
        if self.status != "available" and not self.detail:
            raise ProvenanceError(f"a {self.status} field needs detail= explaining why")

    def document(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status, "value": self.value}
        if self.detail:
            payload["detail"] = self.detail
        return payload

    @classmethod
    def available(cls, value: Any) -> "Field":
        return cls("available", value)

    @classmethod
    def unsupported(cls, detail: str) -> "Field":
        return cls("unsupported", None, detail)

    @classmethod
    def unknown(cls, detail: str) -> "Field":
        return cls("unknown", None, detail)


def render_prompt(task_prompt: str, harness: HarnessManifest) -> str:
    """The prompt an attempt actually saw: harness prompt, then the task."""
    template = harness.components.get("prompt")
    if isinstance(template, str) and template.strip():
        return f"{template.strip()}\n\n{task_prompt.strip()}"
    return task_prompt.strip()


def prompt_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def describe_executor(executor: Any, version: str | None = None) -> Field:
    """Content-address the executor that produced an attempt."""
    name = type(executor).__name__
    reported = version or getattr(executor, "version", None)
    document: dict[str, Any] = {"name": name}
    if reported:
        document["version"] = str(reported)
    document["digest"] = content_digest(document)
    if reported:
        return Field.available(document)
    return Field("available", document, "the executor does not report a version")


def executor_value_fields(executor: Any) -> tuple[Field, Field]:
    """Model and seed provenance for an executor that does not report them."""
    from chamber_orchestra.execution.executor import SimulatedExecutor

    if isinstance(executor, SimulatedExecutor):
        return (
            Field.unsupported("the deterministic simulator never calls a model"),
            Field.unsupported(
                "the deterministic simulator derives its draws from task, harness "
                "and attempt, so no seed is configurable"
            ),
        )
    return (
        Field.unknown("the executor did not report model provenance"),
        Field.unknown("the executor did not report a seed"),
    )


def write_trace_artifact(
    directory: Path | str | None,
    run_id: str,
    *,
    task: Mapping[str, Any],
    attempt: Mapping[str, Any],
) -> Field:
    """Persist the trace of one attempt and return its hash and location."""
    if directory is None:
        return Field.unknown("no artifact directory was configured for this run")
    payload = canonical_json({"task": dict(task), "attempt": dict(attempt)}) + "\n"
    path = Path(directory) / f"{run_id}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    except OSError as exc:
        return Field.unknown(f"the tool log could not be written: {exc}")
    return Field.available(
        {
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "uri": str(path),
        }
    )


@dataclass(frozen=True, slots=True)
class AttemptProvenance:
    """Provenance for one attempt, bound to the run and the experiment."""

    experiment_id: str
    split: str
    harness_id: str
    suite_digest: str
    prompt_sha256: str
    executor: Field
    model: Field
    seed: Field
    tool_log: Field
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("experiment_id", "split", "harness_id", "suite_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ProvenanceError(f"{name} must be a non-empty string")
        if not _HEX64.match(self.prompt_sha256):
            raise ProvenanceError("prompt_sha256 must be a lowercase sha256 hex digest")
        if self.executor.status != "available":
            raise ProvenanceError("executor provenance must be available")
        config = dict(self.config)
        try:
            canonical_json(config)
        except TypeError as exc:
            raise ProvenanceError(
                f"attempt config must be JSON-serializable: {exc}"
            ) from exc
        object.__setattr__(self, "config", config)

    def document(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "split": self.split,
            "harness_id": self.harness_id,
            "suite_digest": self.suite_digest,
            "prompt_sha256": self.prompt_sha256,
            "executor": self.executor.document(),
            "model": self.model.document(),
            "seed": self.seed.document(),
            "tool_log": self.tool_log.document(),
            "config": dict(self.config),
        }

    def digest(self) -> str:
        return content_digest(self.document())


__all__ = [
    "AttemptProvenance",
    "Field",
    "ProvenanceError",
    "describe_executor",
    "executor_value_fields",
    "prompt_digest",
    "render_prompt",
    "write_trace_artifact",
]
