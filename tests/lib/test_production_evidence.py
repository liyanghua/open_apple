import hashlib
import json

import pytest

from lib.production_evidence import (
    MACHINE_CHECKS, REQUIRED_CHECKS, build_production_subject,
    production_subject_hash, quality_summary, verify_production_subject,
)
from tests.production_evidence_fixture import create_bound_quality


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def fixture_record(root):
    (root / "video.mp4").write_bytes(b"actual video")
    sha = hashlib.sha256(b"actual video").hexdigest()
    put(root, "props.json", {"captions": ["hello"]})
    record = {"content_slot_id": "S01-001", "render": {"path": "video.mp4", "sha256": sha},
              "canonical_artifacts": {"final_props": "props.json"}, "quality_report_ref": "quality.json"}
    report = create_bound_quality(root, record)
    put(root, "quality.json", report)
    put(root, "record.json", record)
    return record, report


def test_subject_tracks_actual_dependencies_and_rejects_changed_render(tmp_path):
    fixture_record(tmp_path)
    subject = build_production_subject(tmp_path, "record.json")
    assert verify_production_subject(tmp_path, subject)
    old = production_subject_hash(subject)
    put(tmp_path, "props.json", {"captions": ["changed"]})
    assert not verify_production_subject(tmp_path, subject)
    assert production_subject_hash(build_production_subject(tmp_path, "record.json")) != old
    (tmp_path / "video.mp4").write_bytes(b"changed video")
    with pytest.raises(ValueError, match="render"):
        build_production_subject(tmp_path, "record.json")


@pytest.mark.parametrize("name", ["../outside.json", "/tmp/outside.json"])
def test_subject_rejects_unsafe_paths(tmp_path, name):
    with pytest.raises(ValueError):
        build_production_subject(tmp_path, name)


def test_missing_checks_and_invalid_judge_never_become_full_pass(tmp_path):
    record, report = fixture_record(tmp_path)
    report["checks"] = [{"id": "video_judge", "status": "error", "evidence_refs": []}]
    put(tmp_path, "quality.json", report)
    summary = quality_summary(tmp_path, record)
    assert not summary["eligible"]
    assert "narration_content" in summary["blocking_checks"]
    assert summary["checks"]["video_judge"]["machine_status"] == "error"


def test_manual_substitution_keeps_machine_not_run_and_binds_report(tmp_path):
    record, report = fixture_record(tmp_path)
    next(c for c in report["checks"] if c["id"] == "narration_content")["status"] = "not_run"
    path = put(tmp_path, "quality.json", report)
    record["manual_verifications_ref"] = "manual.json"
    put(tmp_path, "manual.json", {"items": [{"check_id": "narration_content", "decision": "pass",
        "reviewer_id": "reviewer-a", "verified_at": "2026-09-24T00:00:00Z",
        "render_sha256": record["render"]["sha256"], "qa_report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "evidence_refs": ["props.json"]}]})
    summary = quality_summary(tmp_path, record)
    assert summary["eligible"]
    assert summary["checks"]["narration_content"]["machine_status"] == "not_run"
    assert summary["checks"]["narration_content"]["effective_status"] == "manual_verified"
    report["changed"] = True
    put(tmp_path, "quality.json", report)
    assert not quality_summary(tmp_path, record)["eligible"]


def test_machine_checks_cannot_be_replaced_by_manual_approval(tmp_path):
    record, report = fixture_record(tmp_path)
    check = next(c for c in report["checks"] if c["id"] in MACHINE_CHECKS)
    check["status"] = "not_run"
    path = put(tmp_path, "quality.json", report)
    record["manual_verifications_ref"] = "manual.json"
    put(tmp_path, "manual.json", {"items": [{"check_id": check["id"], "decision": "pass", "reviewer_id": "a",
        "verified_at": "2026-09-24T00:00:00Z", "render_sha256": record["render"]["sha256"],
        "qa_report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "evidence_refs": ["props.json"]}]})
    assert not quality_summary(tmp_path, record)["eligible"]


def test_unbound_or_missing_evidence_does_not_certify_checks(tmp_path):
    record, report = fixture_record(tmp_path)
    report["render_sha256"] = "0" * 64
    put(tmp_path, "quality.json", report)
    assert not quality_summary(tmp_path, record)["eligible"]


def test_named_dependencies_cannot_override_production_record_binding(tmp_path):
    record, _ = fixture_record(tmp_path)
    record["canonical_artifacts"]["production_record"] = "props.json"
    record["review_dependencies"] = {"final_props": "quality.json"}
    put(tmp_path, "record.json", record)
    subject = build_production_subject(tmp_path, "record.json")
    assert subject["dependencies"]["production_record"]["path"] == "record.json"
    record["production_route"] = "manual"
    put(tmp_path, "record.json", record)
    assert not verify_production_subject(tmp_path, subject)


def test_existing_arbitrary_file_is_not_machine_measurement_evidence(tmp_path):
    record, report = fixture_record(tmp_path)
    report.pop("source_refs")
    for item in report["checks"]:
        item.update(status="pass", method="invented", evidence_refs=["props.json"])
    put(tmp_path, "quality.json", report)
    assert not quality_summary(tmp_path, record)["eligible"]


def test_raw_pass_cannot_override_failed_or_changed_source_measurement(tmp_path):
    record, report = fixture_record(tmp_path)
    technical = json.loads((tmp_path / report["source_refs"]["technical"]).read_text())
    technical["checks"]["media_integrity"]["decode_ok"] = False
    put(tmp_path, report["source_refs"]["technical"], technical)
    summary = quality_summary(tmp_path, record)
    assert summary["checks"]["decode"]["effective_status"] == "unverified"
    assert not summary["eligible"]


def test_source_evidence_reference_order_is_not_an_extra_quality_gate(tmp_path):
    record, _ = fixture_record(tmp_path)
    put(tmp_path, "script.json", {"copy": "approved words"})
    record["canonical_artifacts"]["script"] = "script.json"
    report = create_bound_quality(tmp_path, record)
    next(c for c in report["checks"] if c["id"] == "dependency_integrity")["evidence_refs"].reverse()
    put(tmp_path, "quality.json", report)
    assert quality_summary(tmp_path, record)["eligible"]


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_required_check_is_error_not_last_value_wins(tmp_path, reverse):
    record, report = fixture_record(tmp_path)
    report["checks"].append({"id": "decode", "status": "error", "evidence_refs": ["props.json"]})
    if reverse:
        report["checks"].reverse()
    put(tmp_path, "quality.json", report)
    summary = quality_summary(tmp_path, record)
    assert not summary["eligible"]
    assert summary["checks"]["decode"]["machine_status"] == "error"
    report["render_sha256"] = record["render"]["sha256"]
    report["checks"][0]["evidence_refs"] = ["missing.json"]
    put(tmp_path, "quality.json", report)
    assert not quality_summary(tmp_path, record)["eligible"]
