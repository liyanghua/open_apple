"""Batch run/quality report contract tests (schema).

Task 5 will add the deterministic builder tests. These first tests freeze the
batch_run_report and batch_quality_report artifact contracts.
"""
from __future__ import annotations

import pytest
from jsonschema import ValidationError

from schemas.artifacts import validate_artifact


def _provenance() -> dict:
    return {
        "version": "1.0",
        "batch_id": "b1",
        "run_id": "run-1",
        "generated_at": "2026-08-23T00:00:00+00:00",
        "input_hashes": {"events": "a" * 64},
        "rubric_version": "1.0",
        "source_refs": [{"kind": "events", "path": "p", "sha256": "b" * 64, "record_count": 10}],
        "data_quality": {"status": "complete"},
    }


def _run_report() -> dict:
    return {
        **_provenance(),
        "timing": {"queue_seconds": 1.0, "active_seconds": 2.0, "human_wait_seconds": 0.5},
        "stages": [{"stage_id": "sample", "wall_seconds": 10, "active_seconds": 8, "attempts": 1}],
        "provider_calls": [{"provider": "doubao", "model": "tts", "count": 1, "cost_usd": 0.1}],
        "cache": {"hits": 1, "misses": 2, "rate": 0.33},
        "concurrency": {"max_parallel": 3, "peak_active": 2},
        "throughput": {"candidates_per_hour": 5.0},
        "cost": {"total_usd": 0.5, "per_candidate_usd": 0.1},
        "candidate_cycles": [{"candidate_id": "c1", "attempts": 1, "status": "evaluated"}],
        "milestones": {"start_to_sample": 60, "sample_to_selectable": None, "select_to_delivery": None},
    }


def _quality_report() -> dict:
    return {
        **_provenance(),
        "candidates": [
            {
                "candidate_id": "c1", "status": "revise", "score": 7.5,
                "vlm_dimensions": {"hook": 6.0, "opening_alignment": 7.0, "proof": 8.0,
                                  "pacing": 7.0, "readability": 8.5, "diversity": 6.0},
                "confirmations": None, "blocking_items": ["l1a_coverage"],
                "rework": {"tags": ["coverage"], "rounds": 1},
                "next_action": "repair",
            }
        ],
        "pairwise_diversity": [
            {"candidate_a": "c1", "candidate_b": "c2", "changed_dimensions": 3,
             "structural_shot_count": 3, "visual_risk": "low", "passes": True, "evidence_refs": []}
        ],
        "human_review": {"selected_candidate_ids": [], "reason": ""},
        "recommendations": [{"candidate_id": "c1", "action": "repair", "reason": "coverage"}],
    }


def test_valid_run_report_passes() -> None:
    validate_artifact("batch_run_report", _run_report())


def test_valid_quality_report_passes() -> None:
    validate_artifact("batch_quality_report", _quality_report())


def test_run_report_missing_section_rejected() -> None:
    report = _run_report()
    del report["milestones"]
    with pytest.raises(ValidationError):
        validate_artifact("batch_run_report", report)


def test_quality_report_bad_status_rejected() -> None:
    report = _quality_report()
    report["candidates"][0]["status"] = "bogus"
    with pytest.raises(ValidationError):
        validate_artifact("batch_quality_report", report)


def test_report_bad_source_sha_rejected() -> None:
    report = _run_report()
    report["source_refs"][0]["sha256"] = "x"
    with pytest.raises(ValidationError):
        validate_artifact("batch_run_report", report)


# ---------------------------------------------------------------------------
# Task 5: deterministic report builders
# ---------------------------------------------------------------------------
import json
import tempfile
from pathlib import Path

from lib.batch_reporting import build_batch_run_report, build_batch_quality_report
from lib.artifact_hashing import semantic_sha256


def _fixture() -> Path:
    tmp = Path(tempfile.mkdtemp())
    batch = tmp / "batch-b1"
    (batch / "artifacts").mkdir(parents=True)
    index = {
        "version": "1.0", "batch_id": "b1", "project_id": "batch-b1",
        "created_at": "2026-08-23T00:00:00+00:00",
        "shared_research": {"refs": [{"name": "x", "path": "p"}]},
        "concurrency": {"max_candidates": 5, "max_parallel": 3},
        "differentiation_axes": {},
        "candidates": [
            {"candidate_id": "cand-01", "label": "c1", "direction": {"hook": "h1"},
             "project_id": "cand-01", "status": "evaluated", "cost_usd": 0.5, "attempts": 1},
            {"candidate_id": "cand-02", "label": "c2", "direction": {"hook": "h2"},
             "project_id": "cand-02", "status": "failed", "cost_usd": 0.2, "attempts": 2},
        ],
        "selection": {"selected_candidate_ids": [], "reason": ""},
    }
    (batch / "artifacts" / "candidate_batch.json").write_text(json.dumps(index), encoding="utf-8")
    # cand-01 has an evaluation_report + events; cand-02 has nothing (failed/missing)
    child = tmp / "cand-01"
    (child / "artifacts").mkdir(parents=True, exist_ok=True)
    (child / "artifacts" / "evaluation_report.final.json").write_text(
        json.dumps({"version": "1.0", "status": "revise",
                    "hard_gate": {"pass": False, "checks": [{"status": "fail", "id": "l1a_coverage"}]},
                    "recommended_action": "repair"}), encoding="utf-8")
    (child / "events.jsonl").write_text('{"a":1}\n{"a":2}\n', encoding="utf-8")
    return batch


def test_run_report_is_schema_valid_and_deterministic() -> None:
    batch = _fixture()
    rr1 = build_batch_run_report(batch)
    rr2 = build_batch_run_report(batch)
    validate_artifact("batch_run_report", {k: v for k, v in rr1.items()
                                           if k not in ("semantic_sha256", "artifact_sha256")})
    assert semantic_sha256(rr1) == semantic_sha256(rr2)  # generated_at excluded
    assert rr1["cost"]["total_usd"] == 0.7
    assert rr1["candidate_cycles"][0]["attempts"] == 1


def test_quality_report_marks_missing_and_revise() -> None:
    batch = _fixture()
    qr = build_batch_quality_report(batch)
    validate_artifact("batch_quality_report", {k: v for k, v in qr.items()
                                               if k not in ("semantic_sha256", "artifact_sha256")})
    statuses = {c["candidate_id"]: c["status"] for c in qr["candidates"]}
    assert statuses["cand-01"] == "revise"
    assert statuses["cand-02"] == "missing"
    assert any(w["code"] == "missing_evaluation" for w in qr["data_quality"].get("warnings", []))
    assert any(r["candidate_id"] == "cand-01" and r["action"] == "repair" for r in qr["recommendations"])


def test_quality_report_rebuild_is_idempotent() -> None:
    batch = _fixture()
    qr1 = build_batch_quality_report(batch)
    qr2 = build_batch_quality_report(batch)
    assert semantic_sha256(qr1) == semantic_sha256(qr2)
