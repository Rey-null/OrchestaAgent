from __future__ import annotations

import pytest

from chamber_orchestra.experiment.provenance import (
    AttemptProvenance,
    Field,
    ProvenanceError,
    describe_executor,
    executor_value_fields,
    prompt_digest,
    render_prompt,
    write_trace_artifact,
)
from chamber_orchestra.execution.executor import SimulatedExecutor
from chamber_orchestra.harness.manifest import HarnessManifest

HARNESS = HarnessManifest(
    scope="coding", components={"prompt": "You are a coding agent."}
)


def _provenance() -> AttemptProvenance:
    return AttemptProvenance(
        experiment_id="exp-1",
        split="heldout",
        harness_id="h" * 64,
        suite_digest="suite-digest",
        prompt_sha256=prompt_digest("prompt"),
        executor=Field.available({"name": "SimulatedExecutor", "version": "v1"}),
        model=Field.unsupported("the simulator never calls a model"),
        seed=Field.unsupported("the simulator derives its draws itself"),
        tool_log=Field.unknown("the artifact could not be written"),
        config={"attempt": 0},
    )


def test_unavailable_values_are_explicit_not_omitted():
    document = _provenance().document()

    assert document["model"] == {
        "status": "unsupported",
        "value": None,
        "detail": "the simulator never calls a model",
    }
    assert document["seed"]["status"] == "unsupported"
    assert document["seed"]["value"] is None
    assert document["tool_log"]["status"] == "unknown"
    # nothing disappears from the document, so "absent" never means "unknown"
    for key in ("executor", "model", "seed", "tool_log"):
        assert key in document


def test_available_field_requires_a_value():
    with pytest.raises(ProvenanceError):
        Field("available")


def test_unavailable_field_may_not_carry_a_value():
    with pytest.raises(ProvenanceError):
        Field("unsupported", "0")
    with pytest.raises(ProvenanceError):
        Field("unsupported")


def test_provenance_digest_is_stable_and_content_bound():
    first = _provenance()
    assert first.digest() == _provenance().digest()

    different = AttemptProvenance(
        experiment_id="exp-1",
        split="heldout",
        harness_id="h" * 64,
        suite_digest="suite-digest",
        prompt_sha256=prompt_digest("another prompt"),
        executor=Field.available({"name": "SimulatedExecutor"}),
        model=Field.unsupported("none"),
        seed=Field.unsupported("none"),
        tool_log=Field.unknown("none"),
    )
    assert different.digest() != first.digest()


def test_provenance_requires_a_prompt_hash():
    with pytest.raises(ProvenanceError):
        AttemptProvenance(
            experiment_id="exp-1",
            split="heldout",
            harness_id="h",
            suite_digest="s",
            prompt_sha256="not-a-digest",
            executor=Field.available({"name": "x"}),
            model=Field.unsupported("none"),
            seed=Field.unsupported("none"),
            tool_log=Field.unknown("none"),
        )


def test_simulator_provenance_does_not_invent_a_seed():
    model, seed = executor_value_fields(SimulatedExecutor())

    assert model.status == "unsupported"
    assert seed.status == "unsupported"
    assert "seed" in seed.detail


def test_executor_digest_changes_with_version():
    old = describe_executor(SimulatedExecutor(), version="simulator-1")
    new = describe_executor(SimulatedExecutor(), version="simulator-2")

    assert old.value["digest"] != new.value["digest"]
    assert old.status == new.status == "available"


def test_rendered_prompt_hash_covers_harness_and_task():
    rendered = render_prompt("Fix the bug", HARNESS)
    assert rendered == "You are a coding agent.\n\nFix the bug"
    assert prompt_digest(render_prompt("a", HARNESS)) != prompt_digest(
        render_prompt("b", HARNESS)
    )


def test_trace_artifact_is_hashed_and_located(tmp_path):
    field = write_trace_artifact(
        tmp_path / "artifacts",
        "run-1",
        task={"id": "held-1"},
        attempt={"success": True},
    )

    assert field.status == "available"
    assert field.value["uri"].endswith("run-1.json")
    assert len(field.value["sha256"]) == 64
    assert (tmp_path / "artifacts" / "run-1.json").is_file()


def test_missing_artifact_directory_is_reported_as_unknown():
    field = write_trace_artifact(None, "run-1", task={}, attempt={})

    assert field.status == "unknown"
    assert "artifact directory" in field.detail
