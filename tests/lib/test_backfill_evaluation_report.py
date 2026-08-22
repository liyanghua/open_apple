"""Backfill script contract tests (评审 #11 幂等/原子 + #12 subject_hash 回填)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.backfill_evaluation_report import (
    _append_decision,
    _repair_report_subject_hash,
    _valid_subject_hash,
)


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def _project(tmp_path: Path) -> Path:
    p = tmp_path / "legacy"
    _write(p / "project.json", {"project_id": "legacy", "title": "Legacy"})
    _write(
        p / "artifacts" / "decision_log.json",
        {"version": "1.0", "project_id": "legacy", "decisions": []},
    )
    _write(
        p / "artifacts" / "sample_report.json",
        {"version": "1.0", "semantic_sha256": "a" * 64, "probe": {"duration_seconds": 10}},
    )
    _write(
        p / "artifacts" / "final_review.json",
        {"version": "2.0", "semantic_sha256": "b" * 64},
    )
    return p


def _report(scope: str) -> dict:
    return {
        "version": "1.0", "project_id": "legacy", "scope": scope,
        "created_at": "2026-08-22T00:00:00+00:00",
        "judge_version": "technical_validator-0.1.0", "rubric_version": "l1a-v1.0",
        "subject_ref": {"name": "final_review", "path": "artifacts/final_review.json"},
        "subject_version": "2.0", "subject_hash": "",
        "hard_gate": {"pass": False, "checks": []},
        "creative_advisory": {"scored": False, "dimensions": [], "summary": "未运行"},
        "repair_targets": [], "status": "revise", "recommended_action": "repair",
    }


def test_valid_subject_hash_shape():
    assert _valid_subject_hash("a" * 64)
    assert not _valid_subject_hash("")
    assert not _valid_subject_hash("abc")
    assert not _valid_subject_hash(None)


def test_repair_fills_missing_subject_hash(tmp_path):
    p = _project(tmp_path)
    _write(p / "artifacts" / "evaluation_report.final.json", _report("final"))
    assert _repair_report_subject_hash(p, "artifacts/evaluation_report.final.json", "final") is True
    repaired = json.loads((p / "artifacts" / "evaluation_report.final.json").read_text())
    assert repaired["subject_hash"] == "b" * 64
    assert repaired["status"] == "revise"  # 其余字段不动
    assert repaired["semantic_sha256"] and repaired["artifact_sha256"]
    # 幂等：已修复的文件不再改写
    assert _repair_report_subject_hash(p, "artifacts/evaluation_report.final.json", "final") is False


def test_repair_handles_legacy_unscoped_sample_report(tmp_path):
    p = _project(tmp_path)
    _write(p / "artifacts" / "evaluation_report.json", _report("sample"))
    assert _repair_report_subject_hash(p, "artifacts/evaluation_report.json", "sample") is True
    repaired = json.loads((p / "artifacts" / "evaluation_report.json").read_text())
    assert repaired["subject_hash"] == "a" * 64


def test_append_decision_is_idempotent_and_atomic(tmp_path):
    p = _project(tmp_path)
    _append_decision(p, "legacy", {"sample": "ok", "final": "ok"})
    _append_decision(p, "legacy", {"sample": "ok", "final": "ok"})
    log = json.loads((p / "artifacts" / "decision_log.json").read_text())
    backfill = [d for d in log["decisions"] if d["decision_id"] == "backfill-evaluation-report-001"]
    assert len(backfill) == 1
    assert log["semantic_sha256"] and log["artifact_sha256"]
