from copy import deepcopy
import json
import math

import pytest

from lib.artifact_io import canonical_artifact_path, write_artifact_atomic
from lib.checkpoint import CheckpointValidationError, validate_checkpoint
from lib.cinematic_fast_validation import validate_scene_mapping


def _source_review() -> dict:
    return {
        "version": "1.0",
        "files": [
            {
                "path": "projects/demo/inputs/source/owned.mp4",
                "media_type": "video",
                "reviewed": True,
                "technical_probe": {"duration_seconds": 3},
            }
        ],
        "summary": "已检查一条自有产品视频。",
        "planning_implications": ["使用防刮动作与结果作为首镜证据。"],
    }


def _scene_plan() -> dict:
    return {
        "version": "1.0",
        "scenes": [{
            "id": "sc01",
            "type": "broll",
            "description": "防刮测试动作与结果",
            "shot_intent": "用可见结果建立产品可信度",
            "start_seconds": 0,
            "end_seconds": 2,
        }],
        "metadata": {
            "reference_media_usage": "analysis_only",
            "source_mapping": [{
                "scene_id": "sc01",
                "source_path": "projects/demo/inputs/source/owned.mp4",
                "source_interval": {
                    "start_seconds": 1,
                    "end_seconds_exclusive": 3,
                },
                "timeline_interval": {
                    "start_seconds": 0,
                    "end_seconds_exclusive": 2,
                },
                "reference_basis": "参考片用动作与结果成对证明卖点",
                "source_fit": "自有素材完整拍到防刮动作和结果",
                "mapping_reason": "用冲突钩子完成首镜的证明意图",
                "originality_note": "仅复用证明节奏，画面和文案均来自本项目",
            }],
        },
    }


def test_validate_scene_mapping_accepts_complete_owned_source_evidence() -> None:
    validate_scene_mapping(_scene_plan(), _source_review())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda plan: plan["metadata"].update(reference_media_usage="copy_allowed"), "analysis_only"),
        (lambda plan: plan["metadata"]["source_mapping"][0].update(reference_basis=""), "reference_basis"),
        (lambda plan: plan["metadata"]["source_mapping"][0].update(source_path="inputs/reference/hit.mp4"), "owned source"),
        (lambda plan: plan["metadata"]["source_mapping"][0]["source_interval"].update(end_seconds_exclusive=1), "source_interval"),
        (lambda plan: plan["metadata"]["source_mapping"][0]["source_interval"].update(start_seconds=100, end_seconds_exclusive=102), "duration"),
        (lambda plan: plan["metadata"]["source_mapping"][0]["timeline_interval"].update(start_seconds=50, end_seconds_exclusive=52), "scene timing"),
        (lambda plan: plan["metadata"]["source_mapping"][0]["source_interval"].update(start_seconds=math.nan), "finite"),
        (lambda plan: plan["scenes"][0].update(shot_intent=""), "shot_intent"),
        (lambda plan: plan["metadata"].update(source_mapping=[]), "one mapping per scene"),
    ],
)
def test_validate_scene_mapping_rejects_untraceable_mapping(mutation, message) -> None:
    plan = deepcopy(_scene_plan())
    mutation(plan)

    with pytest.raises(ValueError, match=message):
        validate_scene_mapping(plan, _source_review())


def _checkpoint(project_dir, scene_plan: dict) -> dict:
    source_envelope = write_artifact_atomic(
        canonical_artifact_path(project_dir, "source_media_review"),
        "source_media_review",
        _source_review(),
        project_dir=project_dir,
    )
    (project_dir / "checkpoint_research.json").write_text(
        json.dumps({"artifacts": {"source_media_review": source_envelope}}),
        encoding="utf-8",
    )
    scene_envelope = write_artifact_atomic(
        canonical_artifact_path(project_dir, "scene_plan"),
        "scene_plan",
        scene_plan,
        project_dir=project_dir,
    )
    return {
        "version": "1.0",
        "project_id": "demo",
        "pipeline_type": "cinematic-fast",
        "stage": "scene_plan",
        "status": "completed",
        "timestamp": "2026-08-18T00:00:00Z",
        "artifacts": {"scene_plan": scene_envelope},
    }


def test_validate_checkpoint_accepts_grounded_cinematic_fast_scene_plan(tmp_path) -> None:
    project_dir = tmp_path / "demo"
    (project_dir / "artifacts").mkdir(parents=True)
    validate_checkpoint(_checkpoint(project_dir, _scene_plan()), project_dir=project_dir)


def test_validate_checkpoint_rejects_cinematic_fast_scene_plan_without_evidence(tmp_path) -> None:
    project_dir = tmp_path / "demo"
    (project_dir / "artifacts").mkdir(parents=True)
    invalid_plan = _scene_plan()
    invalid_plan["metadata"]["source_mapping"][0]["mapping_reason"] = ""

    with pytest.raises(CheckpointValidationError, match="mapping_reason"):
        validate_checkpoint(_checkpoint(project_dir, invalid_plan), project_dir=project_dir)
