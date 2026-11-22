from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from chamber_orchestra.harness.manifest import (
    HarnessError,
    HarnessManifest,
    ManifestIntegrityError,
    ProtectedComponentError,
)


def test_id_is_content_addressed_and_order_independent():
    first = HarnessManifest(
        scope="coding",
        components={"prompt": "p", "skills": {"a": "x", "b": "y"}},
    )
    second = HarnessManifest(
        scope="coding",
        components={"skills": {"b": "y", "a": "x"}, "prompt": "p"},
    )
    assert first.id == second.id
    assert len(first.id) == 64


def test_id_changes_with_content_and_parent():
    base = HarnessManifest(scope="coding", components={"prompt": "p"})
    changed = HarnessManifest(scope="coding", components={"prompt": "p2"})
    child = HarnessManifest(scope="coding", components={"prompt": "p"}, parent=base.id)

    assert base.id != changed.id
    assert base.id != child.id


def test_guardrails_cannot_enter_the_editable_surface():
    with pytest.raises(ProtectedComponentError):
        HarnessManifest(scope="coding", components={"guardrails": {"allow": "*"}})
    with pytest.raises(ProtectedComponentError):
        HarnessManifest(scope="coding", components={"permissions": {"admin": True}})


def test_unknown_component_is_rejected():
    with pytest.raises(HarnessError):
        HarnessManifest(scope="coding", components={"plugins": ["x"]})


def test_non_serializable_component_is_rejected():
    with pytest.raises(HarnessError):
        HarnessManifest(scope="coding", components={"prompt": {"set": {1, 2}}})


def test_invalid_scope_is_rejected():
    with pytest.raises(HarnessError):
        HarnessManifest(scope="../escape", components={})


def test_document_roundtrip_and_integrity():
    manifest = HarnessManifest(scope="coding", components={"prompt": "p"})
    document = manifest.document()
    assert HarnessManifest.from_document(document).id == manifest.id

    document["components"]["prompt"] = "tampered"
    with pytest.raises(ManifestIntegrityError):
        HarnessManifest.from_document(document)


def test_manifest_is_immutable():
    manifest = HarnessManifest(scope="coding", components={"skills": {"a": "x"}})
    with pytest.raises(TypeError):
        manifest.components["skills"] = {}  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        manifest.scope = "other"  # type: ignore[misc]


def test_declared_behaviors_are_sorted_and_filtered():
    manifest = HarnessManifest(
        scope="coding",
        components={"tool_guidance": {"behaviors": ["runs_tests", "checks_requirements"]}},
    )
    assert manifest.declared_behaviors() == ("checks_requirements", "runs_tests")

    empty = HarnessManifest(scope="coding", components={"tool_guidance": {}})
    assert empty.declared_behaviors() == ()
