from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest


NINE_STAGES = [
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


def _stage(name: str, status: str, *, versions: int = 1) -> dict:
    return {
        "name": name,
        "status": status,
        "versions": versions,
        "timestamp": "2026-08-15T10:00:00Z" if status != "pending" else None,
        "error": None,
        "gated": name in {"assets", "sample"},
        "human_approved": status == "completed" and name == "assets",
        "warnings": [],
    }


def _board_state() -> dict:
    statuses = {
        "research": "completed",
        "proposal": "completed",
        "script": "completed",
        "scene_plan": "completed",
        "assets": "completed",
        "sample": "awaiting_human",
        "edit": "pending",
        "compose": "pending",
        "publish": "pending",
    }
    return {
        "project_id": "table-mat",
        "title": "透明桌垫竖屏产品混剪",
        "pipeline": {
            "pipeline_type": "cinematic-fast",
            "known": True,
            "stages": [{"name": name} for name, _ in NINE_STAGES],
        },
        "stages": [_stage(name, statuses[name]) for name, _ in NINE_STAGES],
        "artifacts": {
            "research_brief": {"topic": "透明桌垫", "summary": "参考视频用测试证明卖点"},
            "source_media_review": {
                "summary": "6 条真实产品素材",
                "files": [
                    {"path": f"/Users/example/source-{index}.mp4", "usable_for": ["产品展示"]}
                    for index in range(6)
                ],
            },
            "proposal_packet": {
                "concept_options": [{
                    "id": "concept-a",
                    "title": "强测试证明型",
                    "hook": "餐桌最怕什么",
                    "target_duration_seconds": 30,
                }],
                "selected_concept": {"concept_id": "concept-a"},
            },
            "script": {
                "total_duration_seconds": 30,
                "sections": [{
                    "id": "hook",
                    "label": "开场",
                    "text": "一张餐桌每天要扛住多少考验",
                    "start_seconds": 0,
                    "end_seconds": 2,
                }],
            },
            "scene_plan": {
                "scenes": [{
                    "id": "shot-1",
                    "description": "油污擦拭测试",
                    "overlay_notes": "油污一擦就净",
                    "start_seconds": 0,
                    "end_seconds": 2,
                    "required_assets": [{
                        "description": "/Users/example/透明桌垫-防油易擦拭.MP4",
                    }],
                }],
            },
            "sample_report": {
                "window": {"startFrame": 0, "endFrameExclusive": 360},
                "output_path": "/Users/example/renders/sample.mp4",
                "status": "pass",
                "qa": {"summary": "quick QA pass"},
            },
        },
        "storyboard": {"total_duration_seconds": 30, "scenes": []},
        "media": {
            "renders": [{"path": "renders/sample.mp4", "duration_seconds": 12}],
            "snapshots": [],
            "music": [],
        },
        "events": [{"event": "cache_hit", "path": "/private/tmp/cache-item"}],
        "cost": {"total_spent_usd": 0.06},
        "last_activity": 1786796000,
        "live": True,
        "fastline": {
            "gate": "sample",
            "current_task": "样片已准备好，等待确认效果",
            "eta": {"seconds": 420, "confidence": "high", "operation": "video_compose"},
            "blocker": "等待确认样片效果",
            "next_action": "请回到任务中确认样片效果",
            "render": {"mode": "sample", "business_label": "生成样片"},
            "bundle": {
                "status": "approved",
                "artifact_refs": [{"path": "/Users/example/artifacts/script.json"}],
            },
        },
    }


def _walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_fastline_project_projects_business_state() -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    state = project_operator_state(_board_state())

    assert state["summary"] == {
        "current_stage": "样片确认",
        "current_task": "样片已准备好，等待确认效果",
        "progress_percent": 56,
        "next_action": "请回到任务中确认样片效果",
        "estimated_seconds": 420,
        "estimate_confidence": "high",
        "spent_usd": 0.06,
    }
    assert [(stage["id"], stage["label"]) for stage in state["stages"]] == NINE_STAGES
    assert state["stages"][5]["status"] == "等待确认"
    assert state["stages"][7]["editor"]["type"] == "delivery_review"
    assert state["stages"][8]["editor"]["type"] == "delivery_review"
    assert state["workspace"]["stage_id"] == "sample"
    assert state["workspace"]["editor"]["type"] == "sample_review"
    assert state["pending_review"]["kind"] == "sample"
    assert state["permissions"] == ["view"]
    assert state["active_job"] is None
    validate_operator_state(state)


def test_projection_never_leaks_machine_fields_or_paths() -> None:
    from backlot.operator_state import project_operator_state

    state = project_operator_state(_board_state())
    forbidden_keys = {
        "semantic_sha256", "artifact_sha256", "input_hashes", "artifact_refs",
        "path", "stack", "traceback", "artifacts", "events",
    }
    for key, child in _walk(state):
        assert key not in forbidden_keys
        if isinstance(child, str):
            assert "/Users/" not in child
            assert "/private/" not in child
            assert ".json" not in child


def test_legacy_project_is_read_only_without_invented_fastline_data() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["pipeline"] = {
        "pipeline_type": "cinematic",
        "known": True,
        "stages": [{"name": "proposal"}, {"name": "script"}, {"name": "compose"}],
    }
    board["stages"] = [
        _stage("proposal", "completed"),
        _stage("script", "awaiting_human"),
        _stage("compose", "pending"),
    ]
    board["fastline"] = None
    board["cost"] = None
    board["events"] = []

    state = project_operator_state(board)

    assert state["legacy"] == {
        "read_only": True,
        "source_pipeline": "cinematic",
        "upgrade_available": True,
        "message": "该项目创建于快线升级前，可查看内容；编辑前需创建快线运营副本",
    }
    assert state["summary"]["estimated_seconds"] is None
    assert state["summary"]["spent_usd"] is None
    assert state["workspace"]["read_only"] is True
    assert state["workspace"]["upgrade_action"] == "创建快线运营副本"


@pytest.mark.parametrize("pipeline_type", ["unknown", "character-animation"])
def test_other_pipeline_uses_safe_unavailable_editor(pipeline_type: str) -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    board = _board_state()
    board["pipeline"] = {
        "pipeline_type": pipeline_type,
        "known": pipeline_type != "unknown",
        "stages": [{"name": "character_design"}],
    }
    board["stages"] = [_stage("character_design", "in_progress")]
    board["artifacts"] = {"character_design": {"raw": "/tmp/secret.json"}}
    board["fastline"] = None

    state = project_operator_state(board)

    assert state["stages"][0]["label"] == "其他步骤"
    assert state["stages"][0]["editor"] == {
        "type": "unavailable",
        "data": {"message": "该步骤暂无可展示的结构化内容"},
    }
    validate_operator_state(state)


def test_corrupt_project_artifact_degrades_without_error_details(tmp_path: Path) -> None:
    from backlot.operator_state import load_operator_state, validate_operator_state

    project = tmp_path / "broken"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": "broken",
        "title": "损坏内容测试",
        "pipeline_type": "cinematic-fast",
    }), encoding="utf-8")
    (project / "artifacts" / "script.json").write_text("{bad", encoding="utf-8")

    state = load_operator_state(project)

    assert state["title"] == "损坏内容测试"
    assert state["workspace"]["read_only"] is True
    assert "JSONDecodeError" not in json.dumps(state, ensure_ascii=False)
    assert str(tmp_path) not in json.dumps(state, ensure_ascii=False)
    validate_operator_state(state)


def test_revision_is_stable_for_noise_and_changes_for_business_content() -> None:
    from backlot.operator_state import project_operator_state

    base = _board_state()
    first = project_operator_state(base)
    assert project_operator_state(copy.deepcopy(base))["revision"] == first["revision"]

    noisy = copy.deepcopy(base)
    noisy["last_activity"] += 100
    noisy["live"] = False
    noisy["events"] = list(reversed(noisy["events"])) + [{"event": "heartbeat"}]
    assert project_operator_state(noisy)["revision"] == first["revision"]

    changed = copy.deepcopy(base)
    changed["artifacts"]["script"]["sections"][0]["text"] = "新的口播内容"
    assert project_operator_state(changed)["revision"] != first["revision"]


def test_revision_value_is_not_part_of_its_own_hash() -> None:
    from backlot.operator_state import operator_revision, project_operator_state

    state = project_operator_state(_board_state())
    expected = state["revision"]
    state["revision"] = "f" * 64

    assert operator_revision(state) == expected
