from __future__ import annotations

import pytest

from chamber_orchestra.harness.manifest import (
    HarnessError,
    HarnessManifest,
    ProtectedComponentError,
)
from chamber_orchestra.harness.patch import HarnessPatch, PatchOp, apply_patch, validate_patch


def _base() -> HarnessManifest:
    return HarnessManifest(
        scope="coding",
        components={"prompt": "p", "tool_guidance": {"behaviors": ["reports_evidence"]}},
    )


def test_patch_produces_child_with_provenance():
    base = _base()
    patch = HarnessPatch(
        proposal_id="prop-1",
        base=base.id,
        rationale="add tests",
        ops=(
            PatchOp(op="set", target="tool_guidance/behaviors", value=["reports_evidence", "runs_tests"]),
            PatchOp(op="set", target="skills/verify", value="run tests"),
        ),
    )
    candidate = apply_patch(base, patch)

    assert candidate.parent == base.id
    assert candidate.provenance == ("prop-1",)
    assert candidate.id != base.id
    assert candidate.declared_behaviors() == ("reports_evidence", "runs_tests")
    assert candidate.components["skills"]["verify"] == "run tests"
    # base is untouched
    assert base.declared_behaviors() == ("reports_evidence",)


def test_stale_patch_is_rejected():
    base = _base()
    patch = HarnessPatch(
        proposal_id="prop-1",
        base="deadbeef",
        rationale="stale",
        ops=(PatchOp(op="set", target="prompt", value="new"),),
    )
    with pytest.raises(HarnessError, match="stale patch"):
        apply_patch(base, patch)


@pytest.mark.parametrize(
    "target",
    ["guardrails/policy", "permissions/allow_write", "evaluation/suite"],
)
def test_protected_targets_are_rejected(target):
    patch = HarnessPatch(
        proposal_id="prop-1",
        base="x",
        rationale="escape attempt",
        ops=(PatchOp(op="set", target=target, value="anything"),),
    )
    with pytest.raises(ProtectedComponentError):
        validate_patch(patch)


@pytest.mark.parametrize("target", ["plugins/x", "../prompt", "prompt/", "unknown"])
def test_invalid_targets_are_rejected(target):
    patch = HarnessPatch(
        proposal_id="prop-1",
        base="x",
        rationale="bad target",
        ops=(PatchOp(op="set", target=target, value="v"),),
    )
    with pytest.raises(HarnessError):
        validate_patch(patch)


def test_empty_patch_is_rejected():
    with pytest.raises(HarnessError):
        validate_patch(HarnessPatch(proposal_id="p", base="x", rationale="", ops=()))


def test_delete_missing_path_is_rejected():
    base = _base()
    patch = HarnessPatch(
        proposal_id="prop-1",
        base=base.id,
        rationale="remove",
        ops=(PatchOp(op="delete", target="skills/missing"),),
    )
    with pytest.raises(HarnessError, match="missing"):
        apply_patch(base, patch)


def test_delete_value_must_be_none():
    patch = HarnessPatch(
        proposal_id="prop-1",
        base="x",
        rationale="remove",
        ops=(PatchOp(op="delete", target="skills/x", value="oops"),),
    )
    with pytest.raises(HarnessError):
        validate_patch(patch)


def test_patch_cannot_smuggle_non_json_values():
    patch = HarnessPatch(
        proposal_id="prop-1",
        base="x",
        rationale="bad value",
        ops=(PatchOp(op="set", target="prompt", value=object()),),
    )
    with pytest.raises(HarnessError):
        validate_patch(patch)
