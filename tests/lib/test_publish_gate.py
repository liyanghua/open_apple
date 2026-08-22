"""Publish gate 三态语义测试（评审缺口 #3）。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lib.approval_groups import approve_bundle, build_approval_bundle
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import CheckpointValidationError, init_project
from lib.optimization_run import create_optimization_run
from lib.optimization_scoring import build_default_optimization_policy
from lib.pipeline_loader import load_pipeline
from tests.integration.test_cinematic_fast_end_to_end import (
    PIPELINE,
    PROJECT_ID,
    _artifact,
    _caption_policy_revision,
    _checkpoint,
    _envelopes,
)


def _drive_to_compose(tmp_path: Path, *, compose_overrides: dict | None = None) -> Path:
    project = init_project(PROJECT_ID, title="Publish Gate", pipeline_type=PIPELINE, pipeline_dir=tmp_path)
    manifest = load_pipeline(PIPELINE)

    _checkpoint(tmp_path, "research", "completed", _envelopes(project, [
        "research_brief", "video_analysis_brief", "source_media_review", "media_index",
        "reference_fingerprint", "research_breakdown", "reference_source_matrix",
        "research_synthesis", "research_scorecard", "caption_style_fingerprint",
    ]))
    _checkpoint(tmp_path, "proposal", "completed",
                _envelopes(project, ["proposal_packet", "creative_control_plan", "hook_plan", "decision_log"]))
    script_artifacts = _envelopes(project, ["script"])
    _checkpoint(tmp_path, "script", "awaiting_human", script_artifacts, approval_group="script_lock")
    _checkpoint(tmp_path, "script", "completed", script_artifacts, human_approved=True, approval_group="script_lock")
    _checkpoint(tmp_path, "scene_plan", "completed", _envelopes(project, ["scene_plan"]))

    asset_inputs = _envelopes(project, ["shot_execution_plan", "asset_plan", "production_lock"])
    _checkpoint(tmp_path, "assets", "in_progress", asset_inputs, approval_group="creative_lock")
    bundle = build_approval_bundle(project, manifest, "creative_lock")
    bundle_envelope = _envelopes(project, ["approval_bundle"], {"approval_bundle": bundle})["approval_bundle"]
    _checkpoint(tmp_path, "assets", "awaiting_human", {**asset_inputs, "approval_bundle": bundle_envelope},
                approval_group="creative_lock", approval_bundle_id=bundle["bundle_id"],
                approval_bundle_version=bundle["bundle_version"])
    approved_path = approve_bundle(project, bundle["bundle_id"], approved_by="tester")
    approved_bundle = json.loads(approved_path.read_text(encoding="utf-8"))
    approved_envelope = _envelopes(project, ["approval_bundle"], {"approval_bundle": approved_bundle})["approval_bundle"]
    _checkpoint(tmp_path, "assets", "completed", {**asset_inputs, "approval_bundle": approved_envelope},
                human_approved=True, approval_group="creative_lock",
                approval_bundle_id=bundle["bundle_id"], approval_bundle_version=bundle["bundle_version"])

    sample_artifacts = _envelopes(
        project,
        ["asset_manifest", "final_props", "render_plan", "sample_report",
         "sample_execution_trace"],
    )
    # 评审 #3：sample/final 各用 scoped 路径，避免同文件互踩导致信封漂移。
    sample_artifacts["evaluation_report"] = write_artifact_atomic(
        "artifacts/evaluation_report.sample.json",
        "evaluation_report",
        copy.deepcopy(_artifact("evaluation_report")),
        project_dir=project,
    )
    sample_artifacts["caption_policy_revision"] = write_artifact_atomic(
        "artifacts/caption_policy_revision.json",
        "caption_policy_revision",
        _caption_policy_revision(),
        project_dir=project,
    )
    _checkpoint(tmp_path, "sample", "awaiting_human", sample_artifacts)
    _checkpoint(tmp_path, "sample", "completed", sample_artifacts, human_approved=True)
    _checkpoint(tmp_path, "edit", "completed", _envelopes(project, ["edit_decisions", "change_impact"]))

    final_report = copy.deepcopy(
        (compose_overrides or {}).get("evaluation_report", _artifact("evaluation_report"))
    )
    if final_report.get("scope") != "final":
        final_report["scope"] = "final"
    compose_artifacts = _envelopes(project, ["render_report", "final_review"])
    compose_artifacts["evaluation_report"] = write_artifact_atomic(
        "artifacts/evaluation_report.final.json",
        "evaluation_report",
        final_report,
        project_dir=project,
    )
    _checkpoint(tmp_path, "compose", "completed", compose_artifacts)
    return project


def _fail_report() -> dict:
    report = copy.deepcopy(_artifact("evaluation_report"))
    report["scope"] = "final"
    report["status"] = "fail"
    report["recommended_action"] = "reject"
    report["hard_gate"] = {
        "pass": False,
        "checks": [
            {"id": "l1a_price", "name": "价格正确", "status": "fail", "severity": "fatal",
             "message": "画面价格与期望价格不一致", "evidence": {}, "affected_shots": [], "fixable": False},
        ],
    }
    return report


def _final_report_env(project: Path) -> dict:
    data = json.loads((project / "artifacts" / "evaluation_report.final.json").read_text(encoding="utf-8"))
    return {
        "name": "evaluation_report",
        "path": "artifacts/evaluation_report.final.json",
        "semantic_sha256": data["semantic_sha256"],
        "artifact_sha256": data["artifact_sha256"],
        "data": data,
    }


def _publish_artifacts(project: Path) -> dict:
    artifacts = _envelopes(project, ["publish_log"])
    artifacts["evaluation_report"] = _final_report_env(project)
    return artifacts


def test_fatal_l1a_blocks_publish_checkpoint(tmp_path: Path):
    project = _drive_to_compose(tmp_path, compose_overrides={"evaluation_report": _fail_report()})
    with pytest.raises(CheckpointValidationError, match="fatal L1a"):
        _checkpoint(tmp_path, "publish", "completed", _publish_artifacts(project))


def test_optimization_gate_blocks_publish_when_not_passed(tmp_path: Path):
    policy = build_default_optimization_policy(PROJECT_ID, overrides={"enabled": True})
    run = create_optimization_run(
        "autoresearch-mix-001", PROJECT_ID, policy=policy,
        policy_ref={"name": "optimization_policy", "path": "artifacts/optimization_policy.json"},
    )
    report = copy.deepcopy(_artifact("evaluation_report"))
    report["scope"] = "final"
    report["optimization"] = {
        "run_id": "autoresearch-mix-001", "candidate_id": "candidate-03", "iteration": 1,
        "parent_candidate_id": None, "dimension_scores": {"hook_clarity": 8.5},
        "weighted_total": 8.63, "thresholds": {"per_dimension_min": 8.0, "weighted_total_min": 8.5},
        "passed": False, "failure_dimensions": [], "confirmation_index": None,
    }
    project = _drive_to_compose(tmp_path, compose_overrides={"evaluation_report": report})

    policy_env = write_artifact_atomic("artifacts/optimization_policy.json", "optimization_policy",
                                       policy, project_dir=project)
    run_env = write_artifact_atomic("artifacts/optimization_run.json", "optimization_run",
                                    run, project_dir=project)
    publish_artifacts = _publish_artifacts(project)
    publish_artifacts["optimization_policy"] = policy_env
    publish_artifacts["optimization_run"] = run_env
    with pytest.raises(CheckpointValidationError, match="优化门禁未通过"):
        _checkpoint(tmp_path, "publish", "completed", publish_artifacts)


def test_publish_allowed_when_optimization_policy_disabled(tmp_path: Path):
    policy = build_default_optimization_policy(PROJECT_ID)  # enabled=False
    run = create_optimization_run(
        "autoresearch-mix-001", PROJECT_ID, policy=policy,
        policy_ref={"name": "optimization_policy", "path": "artifacts/optimization_policy.json"},
    )
    project = _drive_to_compose(tmp_path)
    policy_env = write_artifact_atomic("artifacts/optimization_policy.json", "optimization_policy",
                                       policy, project_dir=project)
    run_env = write_artifact_atomic("artifacts/optimization_run.json", "optimization_run",
                                    run, project_dir=project)
    publish_artifacts = _publish_artifacts(project)
    publish_artifacts["optimization_policy"] = policy_env
    publish_artifacts["optimization_run"] = run_env
    _checkpoint(tmp_path, "publish", "completed", publish_artifacts)  # 不抛


def test_plain_publish_without_policy_still_allowed(tmp_path: Path):
    project = _drive_to_compose(tmp_path)
    _checkpoint(tmp_path, "publish", "completed", _publish_artifacts(project))
