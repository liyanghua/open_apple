"""Source approvals are purpose-bound and cannot advance film checkpoints."""
import json
import subprocess
from pathlib import Path

import pytest

from backlot.operator_errors import OperatorError
from backlot.operator_reviews import ReviewService
from tests.contracts.test_shot_source_contract import source_fixture


def setup_source(tmp_path, shot="sofa"):
    root = tmp_path / "test"
    root.mkdir(exist_ok=True)
    (root / "project.json").write_text(json.dumps({"project_id": "test"}))
    fixture = source_fixture(root, shot_id=shot)
    return root, fixture


def approve(service, review):
    return service.decide(review_id=review["review_id"], decision="approved", actor_id="human",
                          reason="同意本用途", expected_version=review["subject_version"],
                          expected_hash=review["subject_hash"])


def test_source_approval_does_not_advance_script_or_film(tmp_path):
    root, (_, _, _, path, _) = setup_source(tmp_path)
    checkpoint = root / "checkpoint_script.json"
    checkpoint.write_text('{"status":"in_progress"}')
    service = ReviewService(root)
    review = service.create_source_clip_review(record_path=path, purpose_id="local-touch", submitted_by="producer")
    assert review["kind"] == "source_clip"
    assert approve(service, review)["status"] == "approved"
    assert checkpoint.read_text() == '{"status":"in_progress"}'
    assert not (root / "operator/current-delivery.json").exists()
    assert service.create_source_clip_review(record_path=path, purpose_id="local-touch", submitted_by="producer")["review_id"] == review["review_id"]


def test_source_purposes_and_shots_are_independent(tmp_path):
    root, (_, _, _, a, _) = setup_source(tmp_path)
    _, _, _, b, _ = source_fixture(root, shot_id="other")
    service = ReviewService(root)
    ra = service.create_source_clip_review(record_path=a, purpose_id="local-touch", submitted_by="producer")
    rb = service.create_source_clip_review(record_path=b, purpose_id="local-touch", submitted_by="producer")
    rc = service.create_source_clip_review(record_path=a, purpose_id="whole-sofa", submitted_by="producer")
    approve(service, ra)
    assert service.review_state(rb["review_id"])["status"] == "awaiting_human"
    assert service.review_state(rc["review_id"])["status"] == "awaiting_human"


@pytest.mark.parametrize("changed", ["assets/sofa.mp4", "artifacts/sofa-fact_snapshot.json", "artifacts/shot_sources/sofa/v6/plan.json"])
def test_source_changed_dependency_invalidates_even_approved_replay(tmp_path, changed):
    root, (_, _, _, path, _) = setup_source(tmp_path)
    service = ReviewService(root)
    review = service.create_source_clip_review(record_path=path, purpose_id="local-touch", submitted_by="producer")
    approve(service, review)
    (root / changed).write_bytes(b"changed")
    with pytest.raises(OperatorError) as exc:
        approve(service, review)
    assert exc.value.code == "review_stale"


def test_failed_original_purpose_is_not_approved_as_final(tmp_path):
    root, (_, evaluation, record, path, put) = setup_source(tmp_path)
    evaluation["source_review"]["observations"][0].update(status="fail", observed="Missing right arm")
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    put(path, record)
    service = ReviewService(root)
    with pytest.raises(OperatorError):
        service.create_source_clip_review(record_path=path, purpose_id="whole-sofa", submitted_by="producer")
    review = service.create_source_clip_review(record_path=path, purpose_id="local-touch", submitted_by="producer")
    assert approve(service, review)["source_subject"]["summary"]["original_use_eligible"] is False
    with pytest.raises(OperatorError):
        service.create_production_review(record_path=path, submitted_by="producer")


def test_source_workbench_projects_each_use_without_counting_a_film(tmp_path):
    from backlot.source_clip_review_items import source_clip_review_items
    root, (_, evaluation, record, path, put) = setup_source(tmp_path)
    evaluation["source_review"]["observations"][0].update(status="fail", observed="Missing right arm")
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    put(path, record)
    items = source_clip_review_items(root, [])
    assert len(items) == 2
    original = next(i for i in items if i["purpose_id"] == "whole-sofa")
    candidate = next(i for i in items if i["purpose_id"] == "local-touch")
    assert original["review_allowed"] is False
    assert candidate["review_allowed"] is True
    assert all(i["review_kind"] == "source_clip" and not i["counts_as_film"] for i in items)
    service = ReviewService(root)
    approve(service, service.create_source_clip_review(record_path=path, purpose_id="local-touch", submitted_by="producer"))
    assert next(i for i in source_clip_review_items(root, []) if i["purpose_id"] == "local-touch")["review_status"] == "该用途已通过"


def test_frontend_source_only_never_reports_accepted_film():
    module = (Path(__file__).resolve().parents[2] / "backlot/ui/operator/approval_model.js").as_uri()
    state = {"stages": [{"id": "compose", "status": "in_progress", "editor": {"data": {
        "production_reviews": [{"id": "A:v1:local", "review_kind": "source_clip", "review_status": "该用途已通过"}]
    }}}]}
    script = f"import {{buildApprovalStages}} from {json.dumps(module)}; console.log(JSON.stringify(buildApprovalStages({json.dumps(state)}).find(s=>s.stageId==='compose')));"
    model = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", script], text=True))
    assert model["status"] == "源片可审"
    assert "1 条源片用途" in model["summary"]
    assert "0 条成片" in model["summary"]


def test_sources_can_be_reviewed_during_asset_stage(tmp_path):
    from backlot.operator_state import _asset_editor
    root, _ = setup_source(tmp_path)
    editor = _asset_editor({"_project_dir": str(root), "artifacts": {}})
    assert len(editor["data"]["source_reviews"]) == 2
    assert all(item["review_kind"] == "source_clip" for item in editor["data"]["source_reviews"])
