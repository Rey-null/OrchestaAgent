"""The evaluation suite: protected, versioned, split into dev and held-out.

The optimizer may see dev results. Promotion decisions are made on held-out
tasks, which the proposer never observes. The suite lives outside the harness
store and this module refuses to treat a path inside that store as a suite, so
"edit the tests" is not a growth strategy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from chamber_orchestra.evaluation.models import Task
from chamber_orchestra.harness.manifest import canonical_json, content_digest

SPLITS = ("dev", "heldout")

_SPACES = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^0-9a-z\s]+")


class SuiteError(ValueError):
    """Raised for malformed suites or suites placed on the editable surface."""


class SplitOverlapError(SuiteError):
    """Raised when the same task content appears in more than one split."""


class ContextLeakError(SuiteError):
    """Raised when proposer context carries held-out task content."""


def normalize_task_content(text: str) -> str:
    """Case, punctuation and whitespace insensitive task content."""
    folded = _NON_WORD.sub(" ", text.casefold())
    return _SPACES.sub(" ", folded).strip()


def task_content_digest(task: Task) -> str:
    """Content address of a task, independent of its id."""
    return content_digest(
        {
            "content": normalize_task_content(task.prompt),
            "kind": task.kind,
            "required_behaviors": sorted(task.required_behaviors),
        }
    )


def _cross_split_duplicates(tasks: tuple[Task, ...]) -> dict[str, list[Task]]:
    grouped: dict[str, list[Task]] = {}
    for task in tasks:
        grouped.setdefault(task_content_digest(task), []).append(task)
    return {
        digest: members
        for digest, members in grouped.items()
        if len({member.split for member in members}) > 1
    }


def _assert_splits_do_not_overlap(tasks: tuple[Task, ...]) -> None:
    duplicates = _cross_split_duplicates(tasks)
    if duplicates:
        members = next(iter(duplicates.values()))
        described = ", ".join(f"{item.id} ({item.split})" for item in members)
        raise SplitOverlapError(
            "the same task content appears in more than one split: " + described
        )


@dataclass(frozen=True, slots=True)
class SplitAudit:
    """What the suite looked like when the split was checked."""

    suite_name: str
    suite_digest: str
    counts: Mapping[str, int]
    content: Mapping[str, tuple[str, ...]]

    def document(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "suite_digest": self.suite_digest,
            "counts": dict(self.counts),
            "tasks": {
                digest: list(ids) for digest, ids in sorted(self.content.items())
            },
            "overlaps": [],
        }


def audit_suite(suite: "TaskSuite") -> SplitAudit:
    """Check that no task content is shared between splits, and describe it."""
    _assert_splits_do_not_overlap(suite.tasks)
    counts: dict[str, int] = {split: 0 for split in SPLITS}
    content: dict[str, tuple[str, ...]] = {}
    for task in suite.tasks:
        counts[task.split] = counts.get(task.split, 0) + 1
        digest = task_content_digest(task)
        content[digest] = tuple(
            sorted(set(content.get(digest, ())) | {task.id})
        )
    return SplitAudit(
        suite_name=suite.name,
        suite_digest=suite.digest,
        counts=counts,
        content=content,
    )


def assert_context_excludes_heldout(
    document: Mapping[str, Any], suite: "TaskSuite", *, split: str = "heldout"
) -> None:
    """Refuse a proposer context that names or quotes a held-out task."""
    text = canonical_json(document)
    folded = normalize_task_content(text)
    for task in suite.split(split):
        if task.id in text:
            raise ContextLeakError(
                f"proposer context mentions held-out task {task.id!r}"
            )
        content = normalize_task_content(task.prompt)
        if len(content) >= 24 and content in folded:
            raise ContextLeakError(
                f"proposer context quotes held-out task {task.id!r}"
            )

@dataclass(frozen=True, slots=True)
class TaskSuite:
    name: str
    tasks: tuple[Task, ...]

    digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise SuiteError("suite name must be non-empty")
        tasks = tuple(self.tasks)
        if not tasks:
            raise SuiteError("suite must contain at least one task")
        seen: set[str] = set()
        for task in tasks:
            if task.split not in SPLITS:
                raise SuiteError(f"task {task.id!r} has unknown split {task.split!r}")
            if task.id in seen:
                raise SuiteError(f"duplicate task id: {task.id!r}")
            seen.add(task.id)
        _assert_splits_do_not_overlap(tasks)
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "digest", content_digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tasks": [
                task.document() for task in sorted(self.tasks, key=lambda item: item.id)
            ],
        }

    def document(self) -> dict[str, Any]:
        payload = self._payload()
        payload["digest"] = self.digest
        return payload

    def split(self, split: str) -> tuple[Task, ...]:
        if split not in SPLITS:
            raise SuiteError(f"unknown split: {split!r}")
        return tuple(task for task in self.tasks if task.split == split)

    def required_behaviors(self) -> tuple[str, ...]:
        return tuple(
            sorted({b for task in self.tasks for b in task.required_behaviors})
        )


def load_suite(path: str | Path) -> TaskSuite:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    suite = TaskSuite(
        name=document["name"],
        tasks=tuple(Task.from_document(item) for item in document["tasks"]),
    )
    declared = document.get("digest")
    if declared is not None and declared != suite.digest:
        raise SuiteError(
            f"suite digest mismatch: declared {declared}, recomputed {suite.digest}"
        )
    return suite


def dump_suite(suite: TaskSuite, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(suite.document(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def assert_suite_is_protected(suite_path: str | Path, editable_root: str | Path) -> None:
    """Refuse to evaluate with a suite that sits on the editable surface."""
    suite_resolved = Path(suite_path).resolve()
    root_resolved = Path(editable_root).resolve()
    if suite_resolved == root_resolved or root_resolved in suite_resolved.parents:
        raise SuiteError(
            f"suite {suite_resolved} lives inside the editable store {root_resolved}"
        )


def _task(
    task_id: str,
    split: str,
    kind: str,
    behaviors: tuple[str, ...],
    difficulty: float,
    prompt: str,
) -> Task:
    return Task(
        id=task_id,
        split=split,
        prompt=prompt,
        kind=kind,
        required_behaviors=behaviors,
        difficulty=difficulty,
    )


def default_suite() -> TaskSuite:
    """Small, recurring-task suite used to exercise the improvement loop.

    Dev tasks expose the failures the proposer is allowed to learn from.
    Held-out tasks test whether the resulting procedure generalizes beyond the
    cases that motivated it.
    """
    tasks: list[Task] = []

    for index in range(1, 9):
        tasks.append(
            _task(
                f"dev-code-{index:02d}",
                "dev",
                "coding",
                ("runs_tests",),
                0.3,
                "Implement a small function and prove it works with the test suite.",
            )
        )
    for index in range(9, 13):
        tasks.append(
            _task(
                f"dev-code-{index:02d}",
                "dev",
                "coding",
                ("runs_tests", "checks_requirements"),
                0.5,
                "Fix a reported bug without breaking the rest of the project.",
            )
        )
    for index in range(1, 4):
        tasks.append(
            _task(
                f"dev-research-{index:02d}",
                "dev",
                "research",
                ("checks_requirements",),
                0.4,
                "Contrast two sources and answer a scoped research question.",
            )
        )
    tasks.append(
        _task(
            "dev-research-04",
            "dev",
            "research",
            ("reports_evidence",),
            0.4,
            "Summarize the notes and cite what each claim rests on.",
        )
    )
    for index in range(1, 3):
        tasks.append(
            _task(
                f"dev-study-{index:02d}",
                "dev",
                "study",
                ("reports_evidence",),
                0.3,
                "Turn the material into study notes with explicit sources.",
            )
        )

    for index in range(1, 6):
        tasks.append(
            _task(
                f"held-code-{index:02d}",
                "heldout",
                "coding",
                ("runs_tests", "checks_requirements"),
                0.5,
                "Deliver a change that satisfies the acceptance criteria and its tests.",
            )
        )
    for index in range(1, 4):
        tasks.append(
            _task(
                f"held-research-{index:02d}",
                "heldout",
                "research",
                ("checks_requirements",),
                0.45,
                "Answer a new research question against the stated constraints.",
            )
        )

    return TaskSuite(name="recurring-v1", tasks=tuple(tasks))


__all__ = [
    "SPLITS",
    "ContextLeakError",
    "SplitAudit",
    "SplitOverlapError",
    "SuiteError",
    "TaskSuite",
    "assert_context_excludes_heldout",
    "assert_suite_is_protected",
    "audit_suite",
    "default_suite",
    "dump_suite",
    "load_suite",
    "normalize_task_content",
    "task_content_digest",
]
