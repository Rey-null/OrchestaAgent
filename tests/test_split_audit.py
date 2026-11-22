from __future__ import annotations

import pytest

from chamber_orchestra.evaluation.models import Task
from chamber_orchestra.evaluation.suite import (
    ContextLeakError,
    SplitOverlapError,
    TaskSuite,
    assert_context_excludes_heldout,
    audit_suite,
    normalize_task_content,
    task_content_digest,
)


def _task(task_id: str, split: str, prompt: str) -> Task:
    return Task(id=task_id, split=split, prompt=prompt, kind="coding")


def test_normalization_ignores_case_punctuation_and_whitespace():
    assert normalize_task_content("  Fix   the BUG! ") == normalize_task_content(
        "fix the bug"
    )


def test_exact_duplicate_content_across_splits_is_rejected():
    tasks = (
        _task("dev-1", "dev", "Answer the scoped research question."),
        _task("held-1", "heldout", "Answer the scoped research question."),
    )

    with pytest.raises(SplitOverlapError, match="dev-1"):
        TaskSuite(name="overlap", tasks=tasks)


def test_normalized_variant_across_splits_is_rejected():
    tasks = (
        _task("dev-1", "dev", "Summarize the notes and cite sources."),
        _task("held-1", "heldout", "  summarize the NOTES, and cite sources!  "),
    )

    with pytest.raises(SplitOverlapError):
        TaskSuite(name="variant", tasks=tasks)


def test_same_split_repetition_is_allowed():
    tasks = (
        _task("dev-1", "dev", "Run the tests before reporting."),
        _task("dev-2", "dev", "Run the tests before reporting."),
        _task("held-1", "heldout", "Answer a new question within the constraints."),
    )

    suite = TaskSuite(name="fine", tasks=tasks)

    assert suite.split("dev") and suite.split("heldout")


def test_task_content_digest_ignores_the_id():
    first = _task("dev-1", "dev", "Same content here")
    second = _task("held-1", "heldout", "same content, here!")

    assert task_content_digest(first) == task_content_digest(second)


def test_audit_describes_counts_and_content():
    suite = TaskSuite(
        name="audited",
        tasks=(
            _task("dev-1", "dev", "First dev task content"),
            _task("held-1", "heldout", "First held-out task content"),
        ),
    )

    audit = audit_suite(suite).document()

    assert audit["counts"] == {"dev": 1, "heldout": 1}
    assert len(audit["tasks"]) == 2
    assert audit["overlaps"] == []


def test_context_naming_a_heldout_task_is_refused():
    suite = TaskSuite(
        name="leak",
        tasks=(
            _task("dev-1", "dev", "First dev task content"),
            _task("held-1", "heldout", "First held-out task content"),
        ),
    )

    with pytest.raises(ContextLeakError, match="held-1"):
        assert_context_excludes_heldout(
            {"failed_tasks": ["dev-1", "held-1"]}, suite
        )


def test_context_quoting_heldout_content_is_refused():
    suite = TaskSuite(
        name="leak",
        tasks=(
            _task("dev-1", "dev", "First dev task content"),
            _task("held-1", "heldout", "Deliver the retry policy with its tests"),
        ),
    )

    with pytest.raises(ContextLeakError, match="quotes"):
        assert_context_excludes_heldout(
            {"notes": "Deliver the retry policy, with its tests"}, suite
        )


def test_clean_context_passes():
    suite = TaskSuite(
        name="clean",
        tasks=(
            _task("dev-1", "dev", "First dev task content"),
            _task("held-1", "heldout", "Deliver the retry policy with its tests"),
        ),
    )

    assert_context_excludes_heldout({"failed_tasks": ["dev-1"]}, suite)
