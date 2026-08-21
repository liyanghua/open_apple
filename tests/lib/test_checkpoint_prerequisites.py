import json

import pytest
from tests.contracts.test_fastline_artifact_contracts import valid_artifact
from tests.contracts.test_phase0_contracts import sample_artifact

from lib.checkpoint import (
    CheckpointValidationError,
    _enforce_approved_creative_control_plan,
    init_project,
    validate_checkpoint,
    write_checkpoint,
)


def _script_artifact() -> dict:
    return {
        "version": "1.0",
        "title": "Smoke",
        "total_duration_seconds": 1,
        "sections": [
            {
                "id": "s1",
                "text": "One second.",
                "start_seconds": 0,
                "end_seconds": 1,
            }
        ],
    }


def _checkpoint(stage, artifacts, pipeline_type, *, version="1.0") -> dict:
    return {
        "version": version,
        "project_id": "run",
        "pipeline_type": pipeline_type,
        "stage": stage,
        "status": "completed",
        "timestamp": "2026-08-14T10:00:00Z",
        "artifacts": artifacts,
    }


def test_legacy_manifest_requires_only_canonical_artifact() -> None:
    validate_checkpoint(
        _checkpoint(
            "proposal",
            {"proposal_packet": sample_artifact("proposal_packet")},
            "animated-explainer",
        )
    )


def test_legacy_noncanonical_stage_can_complete_without_artifact() -> None:
    validate_checkpoint(
        _checkpoint("character_design", {}, "character-animation")
    )


def test_legacy_manifest_allows_raw_fastline_artifact(monkeypatch) -> None:
    manifest = {
        "name": "mock-legacy",
        "version": "1.0",
        "stages": [{"name": "research", "produces": ["media_index"]}],
    }
    monkeypatch.setattr(
        "lib.pipeline_loader.load_pipeline_readonly", lambda name: manifest
    )

    validate_checkpoint(
        _checkpoint(
            "research",
            {
                "research_brief": sample_artifact("research_brief"),
                "media_index": valid_artifact("media_index"),
            },
            "mock-legacy",
        )
    )


def test_contract_v2_requires_all_declared_produces(monkeypatch) -> None:
    manifest = {
        "name": "mock-fastline",
        "version": "1.0",
        "artifact_contract_version": 2,
        "stages": [{"name": "sample", "produces": ["final_props", "sample_report"]}],
    }
    monkeypatch.setattr(
        "lib.pipeline_loader.load_pipeline_readonly", lambda name: manifest
    )

    with pytest.raises(CheckpointValidationError, match="manifest artifacts.*final_props"):
        validate_checkpoint(
            _checkpoint("sample", {}, "mock-fastline", version="2.0")
        )


def test_later_stage_cannot_skip_a_missing_predecessor(tmp_path) -> None:
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )

    with pytest.raises(CheckpointValidationError, match="PREREQUISITE VIOLATION"):
        write_checkpoint(
            tmp_path,
            "run",
            "script",
            "completed",
            {"script": _script_artifact()},
            pipeline_type="framework-smoke",
            human_approved=True,
        )


def test_later_stage_rejects_unapproved_gated_predecessor(tmp_path) -> None:
    project_dir = init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    predecessor_path = write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {"research_brief": sample_artifact("research_brief")},
        next_action={"summary": "测试恢复指令", "verb": "run_stage", "context_refs": ["artifacts/x.json"]},
        pipeline_type="framework-smoke",
    )
    predecessor = json.loads(predecessor_path.read_text(encoding="utf-8"))
    predecessor["status"] = "completed"
    predecessor["human_approved"] = False
    predecessor_path.write_text(json.dumps(predecessor), encoding="utf-8")

    with pytest.raises(CheckpointValidationError, match="completed without required approval"):
        write_checkpoint(
            tmp_path,
            "run",
            "script",
            "completed",
            {"script": _script_artifact()},
            pipeline_type="framework-smoke",
            human_approved=True,
        )


def test_malformed_predecessor_cannot_forge_completion(tmp_path) -> None:
    project_dir = init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    (project_dir / "checkpoint_research.json").write_text(
        json.dumps({"status": "completed", "human_approved": True}),
        encoding="utf-8",
    )

    with pytest.raises(CheckpointValidationError, match="incomplete or missing"):
        write_checkpoint(
            tmp_path,
            "run",
            "script",
            "completed",
            {"script": _script_artifact()},
            pipeline_type="framework-smoke",
            human_approved=True,
        )


def test_in_progress_heartbeat_is_not_blocked_by_prerequisites(tmp_path) -> None:
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )

    path = write_checkpoint(
        tmp_path,
        "run",
        "script",
        "in_progress",
        {},
        next_action={"summary": "测试恢复指令", "verb": "run_stage", "context_refs": ["artifacts/x.json"]},
        pipeline_type="framework-smoke",
    )

    assert path.exists()


@pytest.mark.parametrize("stage", ["script", "scene_plan", "assets"])
def test_fastline_production_stages_require_an_approved_director_control_plan(
    tmp_path, stage
) -> None:
    project_dir = tmp_path / "run"
    (project_dir / "artifacts").mkdir(parents=True)
    plan_path = project_dir / "artifacts" / "creative_control_plan.json"

    with pytest.raises(CheckpointValidationError, match="导演总控单.*已锁定"):
        _enforce_approved_creative_control_plan(
            project_dir, "cinematic-fast", stage, "completed"
        )

    plan_path.write_text(json.dumps({"status": "draft"}), encoding="utf-8")
    with pytest.raises(CheckpointValidationError, match="导演总控单.*已锁定"):
        _enforce_approved_creative_control_plan(
            project_dir, "cinematic-fast", stage, "awaiting_human"
        )

    plan_path.write_text(json.dumps({"status": "approved"}), encoding="utf-8")
    _enforce_approved_creative_control_plan(
        project_dir, "cinematic-fast", stage, "completed"
    )


def test_fastline_director_control_plan_does_not_block_a_heartbeat(tmp_path) -> None:
    _enforce_approved_creative_control_plan(
        tmp_path / "run", "cinematic-fast", "script", "in_progress"
    )


def test_unknown_style_playbook_fails_before_project_creation(tmp_path) -> None:
    with pytest.raises(CheckpointValidationError, match="style_playbook"):
        init_project(
            "run",
            title="Run",
            pipeline_type="framework-smoke",
            pipeline_dir=tmp_path,
            style_playbook="does-not-exist",
        )

    assert not (tmp_path / "run").exists()


def test_marker_derived_unknown_playbook_blocks_later_writes(tmp_path) -> None:
    project_dir = tmp_path / "run"
    project_dir.mkdir()
    (project_dir / "project.json").write_text(
        json.dumps({
            "version": "1.0",
            "project_id": "run",
            "pipeline_type": "framework-smoke",
            "style_playbook": "does-not-exist",
        }),
        encoding="utf-8",
    )

    with pytest.raises(CheckpointValidationError, match="style_playbook"):
        write_checkpoint(tmp_path, "run", "research", "in_progress", {})
