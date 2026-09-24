import json
import hashlib
from pathlib import Path

import pytest

from backlot.campaign_production import campaign_production_panorama
from backlot.operator_reviews import ReviewService
from backlot.operator_state import load_operator_state
from lib.campaign_panorama import normalize_original_campaign_plan
from tests.production_evidence_fixture import create_bound_quality

ROOT = Path(__file__).resolve().parents[2]


def setup_campaign(root):
    (root / "artifacts").mkdir()
    (root / "project.json").write_text(json.dumps({"project_id": root.name, "pipeline_type": "cinematic-fast"}))
    source = ROOT / "花花公子毛巾_300条_V2/300条周度实验排期.json"
    plan = normalize_original_campaign_plan(json.loads(source.read_text()))
    (root / "artifacts/campaign_300_plan.json").write_text(json.dumps(plan))
    index = {"plan_ref": "artifacts/campaign_300_plan.json", "production_record_refs": [], "release_context_ref": "artifacts/release.json"}
    (root / "artifacts/production_campaign_index.json").write_text(json.dumps(index))
    return index


def test_panorama_read_is_nonmutating_and_preserves_original_quotas(tmp_path):
    setup_campaign(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    state = load_operator_state(tmp_path)
    compose = next(s for s in state["stages"] if s["id"] == "compose")
    panorama = compose["editor"]["data"]["production_panorama"]
    assert panorama["summary"]["planned"] == 300
    assert panorama["summary"]["approved_unique"] == 0
    assert {k: v["planned"] for k, v in panorama["by_sku"].items()} == {"S01": 100, "S08": 120, "S04": 80}
    assert all(not row["release"]["ready"] for row in panorama["slots"])
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_unapproved_release_context_cannot_enable_generation(tmp_path):
    index = setup_campaign(tmp_path)
    (tmp_path / "artifacts/release.json").write_text(json.dumps({
        "fact_versions": {"S01": "fake", "S08": "fake", "S04": "fake"}, "brand_version": "fake",
        "production_budget": {"approved": True, "cap_cny": 99999, "approval_ref": "fake"},
        "approved_weeks": [1, 2, 3, 4], "recipe_first_articles": {f"P{i}": "fake" for i in range(1, 7)}}))
    assert all(not row["release"]["ready"] for row in campaign_production_panorama(tmp_path, index)["slots"])


def approved_campaign_record(root, index):
    (root / "film.mp4").write_bytes(b"test film")
    record = {"content_slot_id": "W1-001", "run_id": "run-1", "content_version_id": "v1",
        "sku": "S01", "production_route": "ai_assisted", "work_id": "work-1", "status": "approved",
        "render": {"path": "film.mp4", "sha256": hashlib.sha256(b"test film").hexdigest()},
        "quality_report_ref": "qa.json"}
    report = create_bound_quality(root, record)
    (root / "qa.json").write_text(json.dumps(report))
    (root / "record.json").write_text(json.dumps(record))
    index["production_record_refs"] = ["record.json"]
    # Neither a record's status nor complete machine evidence grants approval.
    assert campaign_production_panorama(root, index)["summary"]["approved_unique"] == 0
    service = ReviewService(root)
    review = service.create_final_review(record_path="record.json", submitted_by="pipeline")
    service.decide(review_id=review["review_id"], decision="approved", actor_id="reviewer",
        reason="Reviewed exact production", expected_version=review["subject_version"], expected_hash=review["subject_hash"])
    assert campaign_production_panorama(root, index)["summary"]["approved_unique"] == 1
    return record, report


@pytest.mark.parametrize("changed", ["media", "source", "slot"])
def test_panorama_counts_only_current_approved_media_sources_and_identity(tmp_path, changed):
    index = setup_campaign(tmp_path)
    record, report = approved_campaign_record(tmp_path, index)
    if changed == "media":
        (tmp_path / "film.mp4").write_bytes(b"another film")
    elif changed == "source":
        (tmp_path / report["source_refs"]["technical"]).write_text("{}")
    else:
        record.update(content_slot_id="W4-001", production_route="manual")
        (tmp_path / "record.json").write_text(json.dumps(record))
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert campaign_production_panorama(tmp_path, index)["summary"]["approved_unique"] == 0
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
