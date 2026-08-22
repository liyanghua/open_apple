"""Contract tests for the evaluation_report artifact (Design_Review P0-0)."""

from __future__ import annotations

import jsonschema
import pytest

from schemas.artifacts import ARTIFACT_NAMES, load_schema, validate_artifact


def _base_report(**overrides):
    report = {
        "version": "1.0",
        "project_id": "p-test",
        "scope": "final",
        "created_at": "2026-08-22T00:00:00+00:00",
        "judge_version": "technical_validator-0.1.0",
        "rubric_version": "l1a-v1.0",
        "subject_ref": {"name": "final_review", "path": "artifacts/final_review.json"},
        "subject_version": "1.0",
        "subject_hash": "a" * 64,
        "execution_diff_ref": None,
        "hard_gate": {
            "pass": True,
            "checks": [
                {
                    "id": "l1a_sku",
                    "name": "SKU 正确",
                    "status": "skip",
                    "severity": "info",
                    "message": "未提供期望 SKU，无法比对",
                    "evidence": {},
                    "affected_shots": [],
                    "fixable": False,
                }
            ],
        },
        "creative_advisory": {"scored": False, "dimensions": [], "summary": "未运行 VLM 评审"},
        "repair_targets": [],
        "status": "pass",
        "recommended_action": "proceed",
    }
    report.update(overrides)
    return report


def test_evaluation_report_is_registered():
    assert "evaluation_report" in ARTIFACT_NAMES
    schema = load_schema("evaluation_report")
    assert schema["$id"] == "openmontage/artifacts/evaluation_report"


def test_minimal_pass_report_validates():
    validate_artifact("evaluation_report", _base_report())


def test_pass_requires_hard_gate_pass():
    report = _base_report(hard_gate={"pass": False, "checks": []})
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("evaluation_report", report)


def test_hard_gate_cannot_pass_with_fatal_failure():
    report = _base_report(
        hard_gate={
            "pass": True,
            "checks": [
                {
                    "id": "l1a_sku",
                    "name": "SKU 正确",
                    "status": "fail",
                    "severity": "fatal",
                    "message": "SKU 不一致",
                    "evidence": {},
                    "affected_shots": [],
                    "fixable": False,
                }
            ],
        }
    )
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("evaluation_report", report)


def test_fail_requires_fatal_failure():
    report = _base_report(status="fail", recommended_action="reject")
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("evaluation_report", report)


def test_recommended_action_must_match_status():
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("evaluation_report", _base_report(recommended_action="repair"))


def test_revise_with_fixable_failure_validates():
    report = _base_report(
        hard_gate={
            "pass": False,
            "checks": [
                {
                    "id": "l1a_duration",
                    "name": "时长符合预期",
                    "status": "fail",
                    "severity": "warning",
                    "message": "时长超出预期",
                    "evidence": {"measured_duration_seconds": 17.0},
                    "affected_shots": ["shot-01"],
                    "fixable": True,
                    "fix_suggestion": "修剪或补齐时间轴",
                }
            ],
        },
        repair_targets=[
            {"check_id": "l1a_duration", "action": "shorten_shot", "affected_shots": ["shot-01"], "note": "时长超出预期"}
        ],
        status="revise",
        recommended_action="repair",
    )
    validate_artifact("evaluation_report", report)


def test_unknown_repair_action_rejected():
    report = _base_report(
        repair_targets=[{"check_id": "x", "action": "rotate_shot", "affected_shots": []}]
    )
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("evaluation_report", report)


def test_empty_subject_hash_rejected():
    """评审 #12：subject_hash 必须是非空 64 位 sha256。"""
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("evaluation_report", _base_report(subject_hash=""))
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("evaluation_report", _base_report(subject_hash="abc"))
