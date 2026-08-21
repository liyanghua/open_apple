from __future__ import annotations

import pytest

from backlot.operator_errors import OperatorError


def test_script_section_confirmation_requires_every_section_before_lock() -> None:
    from backlot.operator_adapters import get_adapter

    adapter = get_adapter("script")
    draft = {
        "status": "draft",
        "sections": [
            {"id": "s1", "review": "pending"},
            {"id": "s2", "review": "pending"},
        ],
    }
    one_confirmed = adapter.apply(
        draft,
        [{"op": "review_script_section", "section_id": "s1", "decision": "approved", "feedback": ""}],
    )
    with pytest.raises(OperatorError, match="每一段"):
        adapter.apply(one_confirmed, [{"op": "approve_production_script"}])

    approved = adapter.apply(
        one_confirmed,
        [
            {"op": "review_script_section", "section_id": "s2", "decision": "approved", "feedback": ""},
            {"op": "approve_production_script"},
        ],
    )
    assert approved["status"] == "approved"


def test_asset_adapter_cannot_lock_execution_plan_with_unresolved_shots() -> None:
    from backlot.operator_adapters import get_adapter

    adapter = get_adapter("assets")
    snapshot = {
        "status": "draft",
        "shots": [{"id": "q1", "coverage_status": "gap", "gap_strategy": "none"}],
    }
    with pytest.raises(OperatorError, match="素材缺口"):
        adapter.apply(snapshot, [{"op": "approve_shot_execution_plan"}])


def test_operator_projection_uses_production_language_and_shot_execution_cards() -> None:
    from backlot.operator_state import _asset_editor, _script_editor

    board = {
        "project_id": "demo",
        "artifacts": {
            "script": {
                "status": "draft",
                "total_duration_seconds": 6,
                "sections": [{
                    "id": "s1", "label": "先证明", "narration": "先看动作", "screen_copy": "真实演示",
                    "start_seconds": 0, "end_seconds": 6, "section_goal": "让用户相信",
                    "pacing": "先快后停", "visual_intent": "完整动作", "evidence_requirements": ["真实素材"],
                    "control_rule_refs": ["fact-1"], "review": "pending", "feedback": "",
                }],
            },
            "shot_execution_plan": {
                "plan_id": "shots-1", "plan_version": 1, "status": "draft",
                "shots": [{
                    "id": "q1", "order": 1, "purpose": "展示使用动作", "duration_seconds": 5,
                    "narration": "先看动作", "screen_copy": "真实演示", "subject_action": "铺开桌垫",
                    "setting": "书桌", "framing": "俯拍", "camera": "固定", "lighting": "自然光", "sound": "环境声",
                    "evidence_type": "demonstration", "coverage_status": "gap", "gap_class": "expressive",
                    "gap_strategy": "generate", "source_selection": None, "reference_mechanisms": [],
                    "industry_notes": [], "control_rule_refs": [], "generation_proposals": [{
                        "id": "g1", "operation": "text_to_video", "model_family": "seedance", "duration_seconds": 5,
                        "aspect_ratio": "9:16", "estimated_fast_cost_usd": 1.21,
                        "estimated_standard_cost_usd": 1.52, "evidence_risk": "生成演示",
                    }], "selected_generation_task_id": None,
                }],
            },
        },
        "cost": {"total_spent_usd": 0},
    }
    script = _script_editor(board)["data"]
    assets = _asset_editor(board)["data"]
    assert script["status"] == "draft"
    assert script["sections"][0]["section_goal"] == "让用户相信"
    assert assets["execution_plan"]["shots"][0]["generation_proposals"][0]["evidence_risk"] == "生成演示"
