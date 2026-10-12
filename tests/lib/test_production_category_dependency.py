"""Category policy changes invalidate media approval dependencies."""

import hashlib
import json
from pathlib import Path

import pytest

from lib.category_profile import bundled_towel_profile_ref
from lib.production_dependency_graph import dependency_closure
from lib.production_evidence import build_production_subject, quality_summary, verify_production_subject


def test_bundled_category_profile_is_in_dependency_closure(tmp_path):
    ref = bundled_towel_profile_ref()
    closure = dependency_closure(tmp_path, document={"category_profile_ref": ref})
    dependency = closure[f"category_profile:{ref['path']}"]
    source = Path(__file__).resolve().parents[2] / ref["path"]
    assert dependency["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    bad_ref = {**ref, "artifact_sha256": "0" * 64}
    with pytest.raises(ValueError):
        dependency_closure(tmp_path, document={"category_profile_ref": bad_ref})


def test_category_file_change_stales_approved_subject(tmp_path):
    original_ref = bundled_towel_profile_ref()
    source = Path(__file__).resolve().parents[2] / original_ref["path"]
    category_path = tmp_path / "artifacts/category.json"
    category_path.parent.mkdir()
    category_path.write_bytes(source.read_bytes())
    ref = {**original_ref, "path": "artifacts/category.json"}
    render = tmp_path / "render.mp4"
    render.write_bytes(b"approved sample")
    record = {"version": "1.0", "content_slot_id": "slot-1",
              "render": {"path": "render.mp4", "sha256": hashlib.sha256(render.read_bytes()).hexdigest()},
              "category_profile_ref": ref}
    (tmp_path / "record.json").write_text(json.dumps(record), encoding="utf-8")
    subject = build_production_subject(tmp_path, "record.json")
    assert verify_production_subject(tmp_path, subject)
    category_path.write_bytes(category_path.read_bytes() + b"\n")
    assert not verify_production_subject(tmp_path, subject)


def test_new_record_requires_category_qa_evidence(tmp_path):
    ref = bundled_towel_profile_ref()
    record = {"version": "1.1", "render": {"path": "absent.mp4", "sha256": "0" * 64},
              "category_profile_ref": ref}
    summary = quality_summary(tmp_path, record)
    assert "action_completion" in summary["blocking_checks"]
    changed = {**record, "category_profile_ref": {**ref, "artifact_sha256": "0" * 64}}
    assert "category_profile" in quality_summary(tmp_path, changed)["blocking_checks"]


def test_new_record_approval_pins_fact_and_brand_files(tmp_path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "renders").mkdir()
    for name in ("brand.json", "fact.json", "quality.json"):
        (tmp_path / "artifacts" / name).write_text("{}", encoding="utf-8")
    render = tmp_path / "renders/final.mp4"
    render.write_bytes(b"approved film")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    record = {
        "version": "1.1", "provenance": "canonical", "content_slot_id": "slot-1",
        "run_id": "run-1", "work_id": "work-1", "sku": "sku-1",
        "campaign_role": "pilot", "production_route": "ai_assisted",
        "content_version_id": "slot-1-v1", "fact_version": "fact-v1",
        "brand_version": "brand-v1", "timing": {}, "costs": {},
        "render": {"path": "renders/final.mp4", "sha256": digest(render)},
        "canonical_artifacts": {}, "quality_report_ref": "artifacts/quality.json",
        "category_profile_ref": bundled_towel_profile_ref(),
        "brand_profile_ref": {"path": "artifacts/brand.json", "sha256": digest(tmp_path / "artifacts/brand.json")},
        "fact_snapshot_ref": {"path": "artifacts/fact.json", "sha256": digest(tmp_path / "artifacts/fact.json")},
    }
    (tmp_path / "record.json").write_text(json.dumps(record), encoding="utf-8")
    subject = build_production_subject(tmp_path, "record.json")
    assert verify_production_subject(tmp_path, subject)
    brand = tmp_path / "artifacts/brand.json"
    brand.write_text('{"changed":true}', encoding="utf-8")
    assert not verify_production_subject(tmp_path, subject)
    brand.write_text("{}", encoding="utf-8")
    fact = tmp_path / "artifacts/fact.json"
    fact.write_text('{"changed":true}', encoding="utf-8")
    assert not verify_production_subject(tmp_path, subject)
