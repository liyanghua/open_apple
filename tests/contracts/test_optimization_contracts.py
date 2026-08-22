"""optimization_policy / optimization_run 契约测试（Autoresearch 设计 §3.1/§3.2）。"""

from __future__ import annotations

import jsonschema
import pytest

from lib.optimization_scoring import build_default_optimization_policy
from lib.optimization_run import create_optimization_run
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact


def _policy(**overrides):
    return build_default_optimization_policy("p-opt", overrides=overrides)


def _run(**overrides):
    policy = _policy(enabled=True)
    run = create_optimization_run(
        "autoresearch-mix-001",
        "p-opt",
        policy=policy,
        policy_ref={"name": "optimization_policy", "path": "artifacts/optimization_policy.json"},
    )
    for key, value in overrides.items():
        run[key] = value
    return run


def test_artifacts_registered():
    assert "optimization_policy" in ARTIFACT_NAMES
    assert "optimization_run" in ARTIFACT_NAMES


def test_default_policy_is_valid_and_human_review_first():
    policy = _policy()
    validate_artifact("optimization_policy", policy)
    assert policy["enabled"] is False
    assert policy["beam_width"] == 5
    assert policy["max_parallel"] == 3
    assert abs(sum(policy["weights"].values()) - 1.0) < 1e-9


def test_policy_weights_must_sum_to_one():
    policy = _policy()
    policy["weights"] = dict(policy["weights"])
    policy["weights"]["hook_clarity"] = 0.2
    with pytest.raises(jsonschema.ValidationError, match="sum to 1.0"):
        validate_artifact("optimization_policy", policy)


def test_policy_required_dimensions_need_weights():
    policy = _policy()
    policy["required_dimensions"] = ["hook_clarity", "made_up_dimension"]
    with pytest.raises(jsonschema.ValidationError, match="missing weights"):
        validate_artifact("optimization_policy", policy)


def test_policy_per_dimension_min_cannot_exceed_total_min():
    # builder 内部即校验（validate_artifact），非法阈值在构建时被拒绝
    with pytest.raises(jsonschema.ValidationError, match="must not exceed"):
        _policy(per_dimension_min=9.0, weighted_total_min=8.5)


def test_run_terminal_status_requires_stop_reason():
    run = _run(status="exhausted")
    with pytest.raises(jsonschema.ValidationError, match="requires stop_reason"):
        validate_artifact("optimization_run", run)


def test_run_stop_reason_only_on_terminal_status():
    run = _run(stop_reason="max_iterations")
    with pytest.raises(jsonschema.ValidationError, match="only allowed for terminal"):
        validate_artifact("optimization_run", run)


def test_run_passed_requires_confirmation_passed():
    run = _run(status="passed", stop_reason="confirmations_passed")
    with pytest.raises(jsonschema.ValidationError, match="requires confirmation.passed"):
        validate_artifact("optimization_run", run)


def test_run_schema_valid_roundtrip():
    policy = _policy(enabled=True)
    run = create_optimization_run(
        "autoresearch-mix-001",
        "p-opt",
        policy=policy,
        policy_ref={"name": "optimization_policy", "path": "artifacts/optimization_policy.json"},
    )
    validate_artifact("optimization_run", run)
    assert run["status"] == "planned"
    assert run["policy_snapshot"]["rubric_version"] == "ecommerce-remix-v1.0"


def test_evaluation_report_optimization_block_schema():
    from lib.artifact_hashing import attach_hashes

    report = {
        "version": "1.0", "project_id": "p-opt", "scope": "sample",
        "created_at": "2026-08-23T00:00:00+00:00",
        "judge_version": "technical_validator-0.1.0", "rubric_version": "l1a-v1.0",
        "subject_ref": {"name": "sample_report", "path": "artifacts/sample_report.json"},
        "subject_version": "1.0", "subject_hash": "a" * 64,
        "hard_gate": {"pass": True, "checks": []},
        "creative_advisory": {"scored": True, "dimensions": [], "summary": "ok"},
        "repair_targets": [], "status": "pass", "recommended_action": "proceed",
        "optimization": {
            "run_id": "autoresearch-mix-001", "candidate_id": "candidate-01",
            "iteration": 1, "parent_candidate_id": None,
            "dimension_scores": {"hook_clarity": 8.5},
            "weighted_total": 8.63,
            "thresholds": {"per_dimension_min": 8.0, "weighted_total_min": 8.5},
            "passed": True, "failure_dimensions": [], "confirmation_index": None,
        },
    }
    validate_artifact("evaluation_report", attach_hashes(report))

    bad = dict(report)
    bad["optimization"] = dict(report["optimization"])
    bad["optimization"]["dimension_scores"] = {"hook_clarity": 11.0}
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("evaluation_report", attach_hashes(bad))
