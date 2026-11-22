"""Export an experiment with the evidence needed to explain its outcome.

An export is self-describing: the pre-registration, the state transitions, the
reports, the per-attempt provenance, the decision, the promotions and the chain
entries that commit to all of it. It is meant to be stored outside the working
directory as an audit checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from chamber_orchestra.ledger.store import Ledger, LedgerError

EXPORT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ExperimentExport:
    document: dict[str, Any]

    def to_json(self) -> str:
        import json

        return json.dumps(self.document, indent=2, sort_keys=True) + "\n"


def export_experiment(ledger: Ledger, experiment_id: str) -> ExperimentExport:
    record = ledger.get_experiment(experiment_id)
    if record is None:
        raise LedgerError(f"unknown experiment: {experiment_id}")

    events = ledger.experiment_events(experiment_id)
    reports = ledger.reports_for_experiment(experiment_id)
    provenance = ledger.provenance(experiment_id=experiment_id)
    contexts = ledger.contexts(experiment_id=experiment_id)
    decisions = ledger.decisions(experiment_id=experiment_id)
    decision_ids = {item["decision_id"] for item in decisions}
    promotions = [
        item
        for item in ledger.promotions(scope=record["scope"])
        if item["decision_id"] in decision_ids
    ]

    wanted: set[tuple[str, str]] = {("experiment", experiment_id)}
    wanted.update(("experiment_event", item["event_id"]) for item in events)
    wanted.update(("report", item["report_id"]) for item in reports)
    wanted.update(("provenance", item["run_id"]) for item in provenance)
    wanted.update(("context", item["context_id"]) for item in contexts)
    wanted.update(("decision", item["decision_id"]) for item in decisions)
    wanted.update(("promotion", item["promotion_id"]) for item in promotions)

    chain = [
        {
            "seq": row["seq"],
            "kind": row["kind"],
            "entry_id": row["entry_id"],
            "payload_digest": row["payload_digest"],
            "prev_hash": row["prev_hash"],
            "entry_hash": row["entry_hash"],
            "mac": row["mac"],
        }
        for row in ledger.chain_rows()
        if (row["kind"], row["entry_id"]) in wanted
    ]

    verification = ledger.verify().document()
    document = {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "experiment": {
            "experiment_id": record["experiment_id"],
            "kind": record["kind"],
            "scope": record["scope"],
            "state": record["state"],
            "digest": record["digest"],
            "created_at": record["created_at"],
            "document": record["document"],
        },
        "events": events,
        "reports": reports,
        "provenance": provenance,
        "contexts": contexts,
        "decisions": decisions,
        "promotions": promotions,
        "chain": chain,
        "verification": verification,
    }
    return ExperimentExport(document=document)


__all__ = ["EXPORT_VERSION", "ExperimentExport", "export_experiment"]
