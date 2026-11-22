"""Evaluation data model.

Every report is content-addressed and carries the suite digest it was produced
against, so a decision can prove which tasks and which harness versions it
compared. Reports are self-describing: they can be persisted and re-loaded
without the runner.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from chamber_orchestra.harness.manifest import canonical_json, content_digest


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    split: str
    prompt: str
    kind: str = "coding"
    required_behaviors: tuple[str, ...] = ()
    difficulty: float = 0.5

    def document(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "split": self.split,
            "prompt": self.prompt,
            "kind": self.kind,
            "required_behaviors": list(self.required_behaviors),
            "difficulty": self.difficulty,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "Task":
        return cls(
            id=document["id"],
            split=document["split"],
            prompt=document["prompt"],
            kind=document.get("kind", "coding"),
            required_behaviors=tuple(document.get("required_behaviors", ())),
            difficulty=float(document.get("difficulty", 0.5)),
        )


@dataclass(frozen=True, slots=True)
class CaseAttempt:
    task_id: str
    harness_id: str
    attempt: int
    success: bool
    behaviors: tuple[str, ...] = ()
    missing_behaviors: tuple[str, ...] = ()
    cost_usd: float = 0.0
    latency_ms: int = 0
    iterations: int = 0
    interventions: int = 0
    detail: Mapping[str, Any] = field(default_factory=dict)

    def document(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "harness_id": self.harness_id,
            "attempt": self.attempt,
            "success": self.success,
            "behaviors": list(self.behaviors),
            "missing_behaviors": list(self.missing_behaviors),
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "iterations": self.iterations,
            "interventions": self.interventions,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "CaseAttempt":
        return cls(
            task_id=document["task_id"],
            harness_id=document["harness_id"],
            attempt=int(document["attempt"]),
            success=bool(document["success"]),
            behaviors=tuple(document.get("behaviors", ())),
            missing_behaviors=tuple(document.get("missing_behaviors", ())),
            cost_usd=float(document.get("cost_usd", 0.0)),
            latency_ms=int(document.get("latency_ms", 0)),
            iterations=int(document.get("iterations", 0)),
            interventions=int(document.get("interventions", 0)),
            detail=document.get("detail", {}),
        )


@dataclass(frozen=True, slots=True)
class EvalReport:
    report_id: str
    harness_id: str
    suite_name: str
    suite_digest: str
    split: str
    repetitions: int
    attempts: tuple[CaseAttempt, ...]
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )

    # -- aggregates ----------------------------------------------------
    def per_task_success(self) -> dict[str, float]:
        buckets: dict[str, list[bool]] = {}
        for attempt in self.attempts:
            buckets.setdefault(attempt.task_id, []).append(attempt.success)
        return {
            task_id: sum(values) / len(values)
            for task_id, values in sorted(buckets.items())
        }

    @property
    def success_rate(self) -> float:
        if not self.attempts:
            return 0.0
        return sum(1 for a in self.attempts if a.success) / len(self.attempts)

    def behavior_rate(self) -> float:
        required = observed = 0
        for attempt in self.attempts:
            required += len(attempt.missing_behaviors) + len(attempt.behaviors)
            observed += len(attempt.behaviors)
        return 1.0 if required == 0 else observed / required

    @property
    def total_cost_usd(self) -> float:
        return round(sum(a.cost_usd for a in self.attempts), 6)

    @property
    def cost_per_task(self) -> float:
        tasks = {a.task_id for a in self.attempts}
        return 0.0 if not tasks else self.total_cost_usd / len(tasks)

    def latency_p95_ms(self) -> int:
        if not self.attempts:
            return 0
        ordered = sorted(a.latency_ms for a in self.attempts)
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[index]

    def metrics(self) -> dict[str, float]:
        return {
            "success_rate": round(self.success_rate, 6),
            "behavior_rate": round(self.behavior_rate(), 6),
            "cost_usd": self.total_cost_usd,
            "cost_per_task_usd": round(self.cost_per_task, 6),
            "latency_p95_ms": float(self.latency_p95_ms()),
            "tasks": float(len(self.per_task_success())),
            "attempts": float(len(self.attempts)),
        }

    # -- serialization -------------------------------------------------
    def document(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "harness_id": self.harness_id,
            "suite_name": self.suite_name,
            "suite_digest": self.suite_digest,
            "split": self.split,
            "repetitions": self.repetitions,
            "created_at": self.created_at,
            "attempts": [attempt.document() for attempt in self.attempts],
        }

    def digest(self) -> str:
        return content_digest(self.document())

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "EvalReport":
        return cls(
            report_id=document["report_id"],
            harness_id=document["harness_id"],
            suite_name=document["suite_name"],
            suite_digest=document["suite_digest"],
            split=document["split"],
            repetitions=int(document["repetitions"]),
            attempts=tuple(
                CaseAttempt.from_document(item) for item in document.get("attempts", ())
            ),
            created_at=document.get("created_at", ""),
        )

    def to_json(self) -> str:
        return json.dumps(self.document(), sort_keys=True, indent=2)


def new_report_id() -> str:
    return uuid.uuid4().hex


def _short(digest: str, length: int = 12) -> str:
    return hashlib.sha256(digest.encode("utf-8")).hexdigest()[:length]


__all__ = [
    "CaseAttempt",
    "EvalReport",
    "Task",
    "new_report_id",
    "canonical_json",
]
