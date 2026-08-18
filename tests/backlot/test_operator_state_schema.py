from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas" / "backlot" / "operator_state.schema.json"


def _editor(editor_type: str) -> dict:
    data_by_type = {
        "research_review": {
            "reference_summary": "参考视频前 3 秒用真实测试建立冲突",
            "source_count": 6,
            "usable_count": 5,
            "risks": ["一条素材轻微抖动"],
            "sources": [],
            "reference": {
                "title": "爆款透明桌垫",
                "summary": "真实动作测试型短视频",
                "duration_seconds": 14.8,
                "hook": "首秒动作",
                "beat_order": ["刮擦冲突", "擦净恢复"],
                "proof_method": "真实动作与即时结果成对",
                "avg_evidence_seconds": 2.1,
                "camera_method": "固定近景",
                "caption_method": "功能短词",
                "typography": "粗描边",
                "transitions": ["硬切"],
                "replicate": ["动作与结果成对"],
                "differentiate": ["改用横排字幕"],
                "preview_url": "/media/table-mat/inputs/reference/hit.mp4",
                "poster_url": "/thumb/table-mat/artifacts/reference.jpg?w=640",
                "scenes": [{
                    "id": "reference-1", "description": "刮擦冲突", "screen_copy": "防刮",
                    "energy": "peak", "start_seconds": 0, "end_seconds": 2.1,
                    "poster_url": "/thumb/table-mat/artifacts/reference.jpg?w=640",
                }],
            },
        },
        "proposal_choice": {
            "concepts": [{
                "id": "concept-a",
                "title": "强测试证明型",
                "hook": "餐桌最怕什么",
                "duration_seconds": 30,
                "core_message": "真实测试证明保护效果",
                "target_audience": "家庭用户",
                "tone": "利落可信",
                "visual_approach": "真实测试配合短字幕",
                "why_this_works": "冲突和结果形成闭环",
                "key_points": ["防刮", "防污"],
                "cta": "点击查看",
                "narrative_structure": "problem_solution",
                "target_platform": "tiktok",
            }],
            "selected_id": "concept-a",
            "estimated_cost_usd": 0.05,
        },
        "script_editor": {
            "duration_seconds": 30,
            "sections": [{
                "id": "hook",
                "label": "开场",
                "text": "一张餐桌每天要扛住多少考验",
                "start_seconds": 0,
                "end_seconds": 2,
            }],
        },
        "shot_mapping": {
            "duration_seconds": 30,
            "reference_basis": {
                "summary": "真实动作测试型短视频",
                "beat_order": ["刮擦冲突", "擦净恢复"],
                "proof_method": "真实动作与即时结果成对",
                "avg_evidence_seconds": 2.1,
            },
            "shots": [{
                "id": "shot-1",
                "beat": "油污冲突",
                "screen_copy": "油污一擦就净",
                "source_label": "防油易擦拭",
                "in_seconds": 1,
                "out_seconds": 3,
                "timeline_in_seconds": 0,
                "timeline_out_seconds": 2,
                "source_in_seconds": 1,
                "source_out_seconds": 3,
                "preview_url": "/media/table-mat/inputs/source/oil.mp4",
                "poster_url": "/thumb/table-mat/inputs/source/oil.mp4?w=640&t=2",
                "intent": "展示擦净结果",
                "framing": "近景",
                "movement": "static",
                "narrative_role": "evidence",
                "source_summary": "餐叉反复刮擦垫面",
                "source_usable_for": ["防刮测试"],
                "mapping_reason": "参考机制要求动作与结果成对；素材可承担防刮测试。",
                "reference_evidence": {
                    "mode": "direct_segment",
                    "reference_scene_id": "reference-1",
                    "description": "刮擦冲突",
                    "mechanism": "动作与结果成对",
                    "rationale": "对应冲突钩子",
                    "start_seconds": 0,
                    "end_seconds": 2.1,
                    "preview_url": "/media/table-mat/inputs/reference/hit.mp4",
                    "poster_url": "/thumb/table-mat/artifacts/reference.jpg?w=640",
                },
            }],
        },
        "asset_review": {
            "narration_status": "已准备",
            "subtitle_status": "已准备",
            "music_status": "已准备",
            "estimated_cost_usd": 0.06,
        },
        "sample_review": {
            "duration_seconds": 12,
            "preview_url": "/media/table-mat/renders/sample.mp4",
            "qa_status": "检查通过",
            "review_summary": "等待确认样片效果",
        },
        "edit_review": {
            "change_scope": "保留画面，仅更新声音",
            "reasons": ["背景音乐音量调整"],
            "affected_shot_count": 0,
        },
        "delivery_review": {
            "duration_seconds": 30,
            "qa_status": "检查通过",
            "download_url": "/media/table-mat/renders/final.mp4",
            "format_label": "竖屏 1080x1920",
        },
        "unavailable": {"message": "该步骤暂无结构化内容"},
    }
    return {"type": editor_type, "data": data_by_type[editor_type]}


def minimal_operator_state(editor_type: str = "research_review") -> dict:
    editor = _editor(editor_type)
    return {
        "schema_version": "1.0",
        "project_id": "table-mat",
        "title": "透明桌垫竖屏产品混剪",
        "pipeline": "cinematic-fast",
        "skill": None,
        "summary": {
            "current_stage": "参考解析与素材体检",
            "current_task": "正在检查参考视频和自有素材",
            "progress_percent": 10,
            "next_action": "等待素材检查完成",
            "estimated_seconds": None,
            "estimate_confidence": None,
            "spent_usd": None,
        },
        "stages": [{
            "id": "research",
            "label": "参考解析与素材体检",
            "status": "制作中",
            "version": 1,
            "updated_at": None,
            "updated_by": None,
            "editable": False,
            "summary": "正在检查素材",
            "warnings": [],
            "editor": editor,
        }],
        "workspace": {
            "stage_id": "research",
            "editor": copy.deepcopy(editor),
            "read_only": True,
            "upgrade_action": None,
        },
        "pending_review": None,
        "permissions": ["view"],
        "active_job": None,
        "revision": "a" * 64,
        "legacy": {
            "read_only": False,
            "source_pipeline": "cinematic-fast",
            "upgrade_available": False,
            "message": "",
        },
    }


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_operator_state_schema_is_valid_and_accepts_each_editor() -> None:
    schema = _schema()
    jsonschema.Draft202012Validator.check_schema(schema)

    for editor_type in (
        "research_review",
        "proposal_choice",
        "script_editor",
        "shot_mapping",
        "asset_review",
        "sample_review",
        "edit_review",
        "delivery_review",
        "unavailable",
    ):
        jsonschema.validate(minimal_operator_state(editor_type), schema)


def test_operator_state_schema_requires_summary_next_action() -> None:
    state = minimal_operator_state()
    del state["summary"]["next_action"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(state, _schema())


def test_operator_state_schema_rejects_unknown_editor_type() -> None:
    state = minimal_operator_state()
    state["stages"][0]["editor"]["type"] = "raw_json"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(state, _schema())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state.update({"raw": {}}),
        lambda state: state["summary"].update({"artifact_path": "/tmp/a.json"}),
        lambda state: state["stages"][0].update({"semantic_sha256": "b" * 64}),
        lambda state: state["stages"][0]["editor"].update({"debug": True}),
        lambda state: state["workspace"].update({"events": []}),
        lambda state: state["legacy"].update({"stack": "trace"}),
    ],
)
def test_operator_state_schema_rejects_unknown_fields_recursively(mutate) -> None:
    state = minimal_operator_state()
    mutate(state)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(state, _schema())


def test_operator_state_schema_rejects_empty_editor_data() -> None:
    state = minimal_operator_state("shot_mapping")
    state["stages"][0]["editor"]["data"] = {}

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(state, _schema())


def test_operator_language_uses_the_canonical_nine_stage_vocabulary() -> None:
    from backlot.operator_language import STAGE_LABELS, STATUS_LABELS

    assert list(STAGE_LABELS.items()) == [
        ("research", "参考解析与素材体检"),
        ("proposal", "创意方案"),
        ("script", "口播与字幕"),
        ("scene_plan", "镜头映射"),
        ("assets", "制作准备"),
        ("sample", "样片确认"),
        ("edit", "修改与精剪"),
        ("compose", "成片生成"),
        ("publish", "交付下载"),
    ]
    assert STATUS_LABELS["awaiting_human"] == "等待确认"
