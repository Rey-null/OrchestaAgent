from __future__ import annotations

import json

from chamber_orchestra.ledger.export import export_experiment
from tests.test_experiment_flow import _run


def test_export_explains_the_outcome(tmp_path):
    ledger, _, _, _, prereg, outcome = _run(tmp_path)

    export = export_experiment(ledger, prereg.experiment_id)
    document = export.document

    assert document["export_version"] == 1
    assert document["experiment"]["experiment_id"] == prereg.experiment_id
    assert document["experiment"]["state"] == "completed"
    assert document["experiment"]["document"]["digest"] == prereg.digest()
    assert document["verification"]["ok"] is True
    assert [item["state"] for item in document["events"]][-1] == "completed"
    assert len(document["reports"]) == 2
    assert len(document["provenance"]) == 36
    assert document["decisions"][0]["decision_id"] == outcome.decision_id
    assert document["chain"]
    assert all(
        len(item["entry_hash"]) == 64 and len(item["mac"]) == 64
        for item in document["chain"]
    )


def test_export_serializes_to_readable_json(tmp_path):
    ledger, _, _, _, prereg, _ = _run(tmp_path)

    body = export_experiment(ledger, prereg.experiment_id).to_json()

    assert json.loads(body)["experiment"]["experiment_id"] == prereg.experiment_id
    assert body.endswith("\n")
