"""Immutable pre-registration of a comparison.

The criteria are fixed before any task runs: baseline, candidate, suite,
inclusion rules, primary metric and threshold, statistical policy and the
limits of the experiment. The document is canonical, so the same criteria
always produce the same content address, and the ledger keeps both the
document and its hash. Editing a criterion afterwards changes the hash and the
decision can no longer be taken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from chamber_orchestra.promotion.policy import PromotionPolicy

STATES = ("registered", "running", "completed", "rejected", "invalid", "failed")

PRIMARY_METRIC = "paired_success_delta"

DEFAULT_INCLUSION_CRITERIA = (
    "every task in the evaluation split is included once per repetition",
    "no task content may appear in both the context and the evaluation split",
    "the baseline must be the harness active at decision time",
)


class PreRegistrationError(ValueError):
    """Raised for malformed pre-registrations or changed criteria."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PreRegistrationError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ExperimentLimits:
    """What the experiment is allowed to spend."""

    repetitions: int = 2
    max_attempts: int = 400
    max_cost_usd: float = 5.0

    def __post_init__(self) -> None:
        if self.repetitions < 1:
            raise PreRegistrationError("repetitions must be at least 1")
        if self.max_attempts < 1:
            raise PreRegistrationError("max_attempts must be at least 1")
        if self.max_cost_usd <= 0:
            raise PreRegistrationError("max_cost_usd must be positive")

    def document(self) -> dict[str, Any]:
        return {
            "repetitions": self.repetitions,
            "max_attempts": self.max_attempts,
            "max_cost_usd": self.max_cost_usd,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "ExperimentLimits":
        return cls(
            repetitions=int(document.get("repetitions", 2)),
            max_attempts=int(document.get("max_attempts", 400)),
            max_cost_usd=float(document.get("max_cost_usd", 5.0)),
        )


@dataclass(frozen=True, slots=True)
class PreRegistration:
    """The criteria of one comparison, fixed before it runs."""

    scope: str
    baseline_id: str
    candidate_id: str
    suite_name: str
    suite_digest: str
    evaluation_split: str = "heldout"
    context_split: str = "dev"
    inclusion_criteria: tuple[str, ...] = DEFAULT_INCLUSION_CRITERIA
    primary_metric: str = PRIMARY_METRIC
    policy: PromotionPolicy = field(default_factory=PromotionPolicy)
    limits: ExperimentLimits = field(default_factory=ExperimentLimits)
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in (
            "scope",
            "baseline_id",
            "candidate_id",
            "suite_name",
            "suite_digest",
            "evaluation_split",
            "context_split",
        ):
            _text(getattr(self, name), name)
        if self.baseline_id == self.candidate_id:
            raise PreRegistrationError(
                "baseline and candidate must be different harness versions"
            )
        for split_name in ("evaluation_split", "context_split"):
            if getattr(self, split_name) not in ("dev", "heldout"):
                raise PreRegistrationError(
                    f"{split_name} must be 'dev' or 'heldout'"
                )
        if self.evaluation_split == self.context_split:
            raise PreRegistrationError(
                "the context split and the evaluation split must differ"
            )
        if self.primary_metric != PRIMARY_METRIC:
            raise PreRegistrationError(
                f"unsupported primary metric {self.primary_metric!r}; "
                f"the evaluator computes {PRIMARY_METRIC!r}"
            )
        criteria = tuple(self.inclusion_criteria)
        if not criteria or any(not str(item).strip() for item in criteria):
            raise PreRegistrationError("inclusion criteria must be non-empty strings")
        if not isinstance(self.policy, PromotionPolicy):
            raise PreRegistrationError("policy must be a PromotionPolicy")
        if not isinstance(self.limits, ExperimentLimits):
            raise PreRegistrationError("limits must be ExperimentLimits")
        object.__setattr__(self, "inclusion_criteria", tuple(str(c) for c in criteria))
        object.__setattr__(self, "created_at", str(self.created_at))

    # -- identity ------------------------------------------------------
    def identity(self) -> dict[str, Any]:
        """Everything the content address is derived from.

        ``created_at`` is metadata: two registrations of the same criteria are
        the same experiment, so re-registering is idempotent rather than
        producing a second experiment that silently differs.
        """
        return {
            "scope": self.scope,
            "baseline_id": self.baseline_id,
            "candidate_id": self.candidate_id,
            "suite": {"name": self.suite_name, "digest": self.suite_digest},
            "splits": {
                "evaluation": self.evaluation_split,
                "context": self.context_split,
            },
            "inclusion_criteria": list(self.inclusion_criteria),
            "primary_metric": self.primary_metric,
            "threshold": self.policy.min_effect,
            "policy": self.policy.document(),
            "limits": self.limits.document(),
        }

    @property
    def experiment_id(self) -> str:
        from chamber_orchestra.harness.manifest import content_digest

        return "exp-" + content_digest(self.identity())[:20]

    def digest(self) -> str:
        from chamber_orchestra.harness.manifest import content_digest

        return content_digest(self.identity())

    def document(self) -> dict[str, Any]:
        payload = self.identity()
        payload["experiment_id"] = self.experiment_id
        payload["created_at"] = self.created_at
        payload["digest"] = self.digest()
        return payload

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "PreRegistration":
        policy_document = document.get("policy")
        if not isinstance(policy_document, Mapping):
            raise PreRegistrationError("pre-registration is missing its policy")
        suite = document.get("suite")
        splits = document.get("splits")
        if not isinstance(suite, Mapping) or not isinstance(splits, Mapping):
            raise PreRegistrationError("pre-registration is missing suite or splits")
        prereg = cls(
            scope=document["scope"],
            baseline_id=document["baseline_id"],
            candidate_id=document["candidate_id"],
            suite_name=suite["name"],
            suite_digest=suite["digest"],
            evaluation_split=splits.get("evaluation", "heldout"),
            context_split=splits.get("context", "dev"),
            inclusion_criteria=tuple(document.get("inclusion_criteria", ())),
            primary_metric=document.get("primary_metric", PRIMARY_METRIC),
            policy=PromotionPolicy(**{k: v for k, v in policy_document.items()}),
            limits=ExperimentLimits.from_document(document.get("limits", {})),
            created_at=document.get("created_at", _now()),
        )
        declared = document.get("digest")
        if declared is not None and declared != prereg.digest():
            raise PreRegistrationError(
                "pre-registration digest mismatch: declared "
                f"{declared}, recomputed {prereg.digest()}"
            )
        threshold = document.get("threshold")
        if threshold is not None and float(threshold) != prereg.policy.min_effect:
            raise PreRegistrationError(
                "the declared threshold differs from the registered policy"
            )
        declared_id = document.get("experiment_id")
        if declared_id is not None and declared_id != prereg.experiment_id:
            raise PreRegistrationError(
                f"experiment id mismatch: declared {declared_id}, "
                f"recomputed {prereg.experiment_id}"
            )
        return prereg


__all__ = [
    "DEFAULT_INCLUSION_CRITERIA",
    "PRIMARY_METRIC",
    "STATES",
    "ExperimentLimits",
    "PreRegistration",
    "PreRegistrationError",
]
