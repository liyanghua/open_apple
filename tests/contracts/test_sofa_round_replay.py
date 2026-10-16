"""Replay historical observations through the gate, without claiming to watch media."""
import hashlib
import json
from pathlib import Path

import pytest

from lib.shot_source_contracts import validate_source_record
from tests.contracts.test_shot_source_contract import source_fixture

CASES = json.loads((Path(__file__).parents[1] / "fixtures/shot_sources/sofa_round_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_historical_improvement_does_not_waive_other_failure(tmp_path, case):
    plan, evaluation, record, path, put = source_fixture(tmp_path)
    evidence = evaluation["source_review"]["observations"][0]["evidence"]
    plan["requirements"].append({"id": "scale", "required": True, "method": "frame_sampling", "description": "Natural scale"})
    plan["uses"][0]["required_requirement_ids"].append("scale")
    evaluation["source_review"]["observations"].append({"id": "scale", "status": "pass", "method": "frame_sampling", "observed": "Recorded case", "evidence": evidence})
    for observation in evaluation["source_review"]["observations"]:
        observation["status"] = case["observations"].get(observation["id"], "not_run")
        observation["observed"] = case["note"]
        if observation["status"] == "not_run":
            observation["evidence"] = []
    # Rebind synthetic inputs/receipt through the helper, never change a real historical approval.
    record["plan_ref"] = put(record["plan_ref"]["path"], plan)
    evaluation["source_review"]["plan_sha256"] = record["plan_ref"]["sha256"]
    inputs = json.loads((tmp_path / record["generation_inputs_ref"]["path"]).read_text())
    inputs["plan_ref"] = record["plan_ref"]
    record["generation_inputs_ref"] = put(record["generation_inputs_ref"]["path"], inputs)
    receipt = json.loads((tmp_path / record["generation_receipt_ref"]["path"]).read_text())
    receipt["data"]["source_inputs_fingerprint"] = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    record["generation_receipt_ref"] = put(record["generation_receipt_ref"]["path"], receipt)
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    put(path, record)
    assert validate_source_record(tmp_path, record)["original_purpose_status"] == case["expected_original"]
