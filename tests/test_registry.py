from __future__ import annotations

from dataclasses import dataclass

import pytest

from chamber_orchestra.harness.manifest import HarnessManifest
from chamber_orchestra.harness.registry import (
    HarnessStore,
    PromotionRejected,
    RegistryError,
    UnknownHarnessError,
)


@dataclass
class StubDecision:
    decision_id: str
    candidate_id: str
    approved: bool
    evidence_digest: str
    baseline_id: str = ""


class StubAuthority:
    def __init__(self, approved: set[str]) -> None:
        self.approved = approved

    def is_approved(self, decision_id: str) -> bool:
        return decision_id in self.approved


@pytest.fixture
def store(tmp_path) -> HarnessStore:
    return HarnessStore(tmp_path / "store")


@pytest.fixture
def base() -> HarnessManifest:
    return HarnessManifest(scope="coding", components={"prompt": "baseline"})


def test_put_get_roundtrip(store, base):
    store.put(base)
    assert store.exists(base.id)
    assert store.get(base.id).id == base.id
    # storing again is a no-op
    assert store.put(base) == base.id


def test_unknown_harness_raises(store):
    with pytest.raises(UnknownHarnessError):
        store.get("0" * 64)


def test_initialize_is_once_per_scope(store, base):
    store.initialize(base)
    assert store.active_id("coding") == base.id
    with pytest.raises(RegistryError):
        store.initialize(base)


def test_promote_requires_approved_recorded_decision(store, base):
    store.initialize(base)
    candidate = HarnessManifest(
        scope="coding", components={"prompt": "candidate"}, parent=base.id
    )
    store.put(candidate)

    unrecorded = StubDecision("dec-1", candidate.id, True, "evidence")
    with pytest.raises(PromotionRejected, match="not recorded"):
        store.promote("coding", candidate.id, unrecorded, StubAuthority(set()))

    rejected = StubDecision("dec-2", candidate.id, False, "evidence")
    with pytest.raises(PromotionRejected, match="did not approve"):
        store.promote("coding", candidate.id, rejected, StubAuthority({"dec-2"}))

    wrong_candidate = StubDecision("dec-3", base.id, True, "evidence")
    with pytest.raises(PromotionRejected, match="refers to"):
        store.promote("coding", candidate.id, wrong_candidate, StubAuthority({"dec-3"}))

    approved = StubDecision(
        "dec-4", candidate.id, True, "evidence", baseline_id=base.id
    )
    assert store.promote("coding", candidate.id, approved, StubAuthority({"dec-4"})) == candidate.id
    assert store.active_id("coding") == candidate.id


def test_promote_rejects_cross_scope_candidate(store, base):
    store.initialize(base)
    other = HarnessManifest(scope="study", components={"prompt": "x"})
    store.put(other)
    decision = StubDecision("dec-1", other.id, True, "evidence")
    with pytest.raises(PromotionRejected, match="scope"):
        store.promote("coding", other.id, decision, StubAuthority({"dec-1"}))


def test_rollback_requires_a_previously_active_harness(store, base):
    store.initialize(base)
    never_active = HarnessManifest(
        scope="coding", components={"prompt": "never promoted"}, parent=base.id
    )
    store.put(never_active)

    with pytest.raises(PromotionRejected, match="never active"):
        store.rollback("coding", never_active.id, reason="skip the gate")

    assert store.active_id("coding") == base.id
    assert [entry["kind"] for entry in store.history("coding")] == ["initialize"]


def test_promote_rejects_a_decision_taken_against_another_baseline(store, base):
    store.initialize(base)
    older = HarnessManifest(scope="coding", components={"prompt": "older"})
    store.put(older)
    candidate = HarnessManifest(
        scope="coding", components={"prompt": "candidate"}, parent=base.id
    )
    store.put(candidate)
    stale = StubDecision(
        "dec-1", candidate.id, True, "evidence", baseline_id=older.id
    )

    with pytest.raises(PromotionRejected, match="active harness"):
        store.promote("coding", candidate.id, stale, StubAuthority({"dec-1"}))

    assert store.active_id("coding") == base.id


def test_promote_rejects_a_decision_overtaken_by_a_newer_promotion(store, base):
    store.initialize(base)
    first = HarnessManifest(
        scope="coding", components={"prompt": "first"}, parent=base.id
    )
    second = HarnessManifest(
        scope="coding", components={"prompt": "second"}, parent=base.id
    )
    store.put(first)
    store.put(second)

    store.promote(
        "coding",
        first.id,
        StubDecision("dec-1", first.id, True, "evidence", baseline_id=base.id),
        StubAuthority({"dec-1"}),
    )

    # decided against the baseline, but the pointer has moved since
    stale = StubDecision("dec-2", second.id, True, "evidence", baseline_id=base.id)
    with pytest.raises(PromotionRejected, match="active harness"):
        store.promote("coding", second.id, stale, StubAuthority({"dec-2"}))

    assert store.active_id("coding") == first.id


def test_rollback_moves_pointer_and_records_audit(store, base):
    store.initialize(base)
    candidate = HarnessManifest(
        scope="coding", components={"prompt": "candidate"}, parent=base.id
    )
    store.put(candidate)
    decision = StubDecision(
        "dec-1", candidate.id, True, "evidence", baseline_id=base.id
    )
    store.promote("coding", candidate.id, decision, StubAuthority({"dec-1"}))

    store.rollback("coding", base.id, reason="regression found in production")
    assert store.active_id("coding") == base.id

    entries = store.history("coding")
    assert [entry["kind"] for entry in entries] == ["initialize", "promote", "rollback"]
    assert entries[-1]["reason"] == "regression found in production"
