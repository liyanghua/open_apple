from __future__ import annotations

import json

import pytest
from jsonschema import ValidationError

from schemas.artifacts import validate_artifact


HASH = "a" * 64


def production_script(*, status: str = "approved") -> dict:
    return {
        "version": "1.0",
        "script_id": "script-table-mat-v1",
        "script_version": 1,
        "status": status,
        "creative_control_ref": {
            "plan_id": "control-table-mat",
            "plan_version": 1,
            "artifact_sha256": HASH,
        },
        "title": "透明桌垫制作剧本",
        "total_duration_seconds": 6,
        "sections": [
            {
                "id": "section-1",
                "label": "先证明耐刮",
                "text": "桌面每天磨，不如先垫住。",
                "narration": "桌面每天磨，不如先垫住。",
                "screen_copy": "日常耐刮演示",
                "start_seconds": 0,
                "end_seconds": 6,
                "section_goal": "让用户先相信这是日常保护，不是夸张承诺",
                "pacing": "前两秒快速钩住，证据动作至少停留三秒",
                "visual_intent": "真实桌垫上完成一次可看清的刮擦动作",
                "evidence_requirements": ["刮擦动作必须使用自有真实素材"],
                "control_rule_refs": ["fact_continuity.rule-1"],
                "review": "approved",
                "feedback": "",
            }
        ],
        "approval": {
            "approved_by": "operator-1",
            "approved_at": "2026-08-21T10:00:00Z",
        },
    }


def shot_execution_plan(*, status: str = "approved") -> dict:
    return {
        "version": "1.0",
        "project_id": "table-mat-mix-v7",
        "plan_id": "shots-table-mat-v1",
        "plan_version": 1,
        "status": status,
        "created_at": "2026-08-21T10:00:00Z",
        "creative_control_ref": {
            "artifact": "creative_control_plan",
            "version": 1,
            "artifact_sha256": HASH,
        },
        "script_ref": {
            "artifact": "script",
            "version": 1,
            "artifact_sha256": HASH,
        },
        "scene_plan_ref": {
            "artifact": "scene_plan",
            "version": 1,
            "artifact_sha256": HASH,
        },
        "shots": [
            {
                "id": "shot-1",
                "order": 1,
                "purpose": "证明桌垫覆盖常用工作区",
                "duration_seconds": 5,
                "narration": "桌面每天磨，不如先垫住。",
                "screen_copy": "日常耐刮演示",
                "subject_action": "手持钥匙在透明桌垫表面划过一次",
                "setting": "明亮家庭书桌",
                "framing": "俯拍近景",
                "camera": "固定机位",
                "lighting": "柔和自然光，反光不过曝",
                "sound": "保留一次清晰摩擦声",
                "evidence_type": "real_proof",
                "coverage_status": "gap",
                "gap_class": "evidential",
                "gap_strategy": "generate",
                "source_selection": None,
                "reference_mechanisms": ["先动作后结论"],
                "industry_notes": ["证据动作至少完整呈现三秒"],
                "control_rule_refs": ["fact_continuity.rule-1"],
                "generation_proposals": [
                    {
                        "id": "proposal-shot-1-fast",
                        "operation": "image_to_video",
                        "prompt": "Single shot product demonstration, fixed overhead camera.",
                        "model_family": "seedance",
                        "duration_seconds": 5,
                        "aspect_ratio": "9:16",
                        "reference_paths": ["inputs/source/images/table-mat.png"],
                        "consistency_requirements": ["保持桌垫透明度、边缘形状和颜色一致"],
                        "prohibitions": ["不生成可读规格文字或 Logo"],
                        "estimated_fast_cost_usd": 1.21,
                        "estimated_standard_cost_usd": 1.52,
                        "evidence_risk": "生成画面只能作为生成演示，不能单独证明耐刮结果",
                    }
                ],
                "selected_generation_task_id": None,
            }
        ],
        "approval": {
            "approved_by": "operator-1",
            "approved_at": "2026-08-21T10:05:00Z",
        },
    }


def test_production_script_and_shot_execution_plan_are_canonical_artifacts() -> None:
    validate_artifact("script", production_script())
    validate_artifact("shot_execution_plan", shot_execution_plan())


def test_shot_execution_plan_rejects_reference_media_as_generation_input() -> None:
    value = shot_execution_plan()
    value["shots"][0]["generation_proposals"][0]["reference_paths"] = [
        "inputs/reference/viral.mp4"
    ]

    with pytest.raises(ValidationError, match="does not match"):
        validate_artifact("shot_execution_plan", value)


def test_approved_production_contracts_require_approval_metadata() -> None:
    for name, value in (
        ("script", production_script()),
        ("shot_execution_plan", shot_execution_plan()),
    ):
        value.pop("approval")
        with pytest.raises(ValidationError):
            validate_artifact(name, value)
