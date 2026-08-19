from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest


NINE_STAGES = [
    ("research", "参考解析与素材体检"),
    ("proposal", "创意方案"),
    ("script", "口播与字幕"),
    ("scene_plan", "分镜"),
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
            "video_analysis_brief": {
                "source": {
                    "title": "爆款透明桌垫", "duration_seconds": 14.8,
                    "local_path": "projects/table-mat/inputs/reference/hit.mp4",
                },
                "content_analysis": {
                    "summary": "依次用真实动作证明贴合、防刮、防污和回弹。",
                    "hook_technique": "首秒直接展开商品",
                },
                "structure_analysis": {
                    "total_scenes": 2,
                    "pacing_profile": {"avg_scene_duration_seconds": 2.1, "cuts_per_minute": 28.4},
                    "scenes": [{
                        "scene_index": 0, "start_time": 0, "end_time": 2.1,
                        "description": "工具刮擦制造冲突", "on_screen_text": "防刮耐磨",
                        "energy_level": "peak",
                    }],
                },
                "style_profile": {
                    "typography_observed": "粗描边功能短词",
                    "transition_types": ["硬切"],
                },
                "replication_guidance": {
                    "key_elements_to_replicate": ["首秒动作", "动作与结果成对"],
                    "creative_differentiation_seeds": ["改用明亮原木和横排字幕"],
                },
                "keyframes": [{
                    "scene_index": 0, "timestamp": 1.2,
                    "path": "projects/table-mat/artifacts/research_media/reference/frame-1.jpg",
                }],
            },
            "reference_fingerprint": {"abstract_structure": {
                "beat_order": ["刮擦冲突", "擦净恢复"],
                "proof_method": "真实动作与即时结果成对",
                "avg_evidence_unit_seconds": 2.1,
                "camera_method": "固定近景，首尾全景",
                "caption_method": "粗描边功能短词",
            }},
            "source_media_review": {
                "summary": "6 条真实产品素材",
                "files": [
                    {
                        "media_id": f"source-{index}",
                        "path": f"projects/table-mat/inputs/source/source-{index}.mp4",
                        "media_type": "video",
                        "content_summary": f"素材 {index} 内容",
                        "reviewed": True,
                        "usable_for": ["产品展示"],
                        "quality_risks": ["需要代理"],
                        "best_ranges": [{"start_seconds": 1, "end_seconds": 4}],
                        "representative_frames": [
                            f"projects/table-mat/artifacts/research_media/source-{index}.jpg"
                        ],
                        "technical_probe": {
                            "duration_seconds": 8.5, "resolution": "3840x2160", "fps": 59.94,
                        },
                    }
                    for index in range(6)
                ],
            },
            "proposal_packet": {
                "concept_options": [{
                    "id": "concept-a",
                    "title": "强测试证明型",
                    "hook": "餐桌最怕什么",
                    "target_duration_seconds": 30,
                    "core_message": "真实动作证明保护效果",
                    "target_audience": "家庭用户",
                    "tone": "利落可信",
                    "visual_approach": "真实测试配合短字幕",
                    "why_this_works": "冲突和结果形成闭环",
                    "key_points": ["防刮", "防污"],
                    "cta": "点击查看",
                    "narrative_structure": "problem_solution",
                    "target_platform": "tiktok",
                }],
                "selected_concept": {"concept_id": "concept-a"},
                "cost_estimate": {"total_estimated_usd": 0.05},
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
                    "shot_intent": "展示擦净动作",
                    "overlay_notes": "油污一擦就净",
                    "start_seconds": 0,
                    "end_seconds": 2,
                    "required_assets": [{
                        "description": "/Users/example/透明桌垫-防油易擦拭.MP4",
                    }],
                }],
                "metadata": {"source_mapping": [{
                    "scene_id": "shot-1",
                    "reference_evidence": {
                        "mode": "direct_segment",
                        "reference_scene_id": "reference-1",
                        "reference_interval": {
                            "start_seconds": 0,
                            "end_seconds_exclusive": 2.1,
                        },
                        "mechanism": "动作与结果成对",
                        "rationale": "对应开场冲突钩子",
                    },
                    "source_path": "projects/table-mat/inputs/source/source-0.mp4",
                    "source_interval": {"start_seconds": 1, "end_seconds_exclusive": 3},
                    "timeline_interval": {"start_seconds": 0, "end_seconds_exclusive": 2},
                }]},
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


def test_projection_includes_safe_material_concept_and_shot_details() -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    state = project_operator_state(_board_state())
    editors = {stage["id"]: stage["editor"]["data"] for stage in state["stages"]}

    research = editors["research"]
    assert research["source_count"] == research["usable_count"] == 6
    assert research["risks"] == ["需要代理"]
    assert research["reference"]["summary"] == "依次用真实动作证明贴合、防刮、防污和回弹。"
    assert research["reference"]["beat_order"] == ["刮擦冲突", "擦净恢复"]
    assert research["reference"]["scenes"][0]["poster_url"] == "/thumb/table-mat/artifacts/research_media/reference/frame-1.jpg?w=640"
    assert len(research["sources"]) == 6
    assert research["sources"][0] == {
        "id": "source-0",
        "label": "source-0",
        "media_type": "video",
        "summary": "素材 0 内容",
        "reviewed": True,
        "usable_for": ["产品展示"],
        "risks": ["需要代理"],
        "duration_seconds": 8.5,
        "resolution": "3840x2160",
        "fps": 59.94,
        "best_in_seconds": 1,
        "best_out_seconds": 4,
        "preview_url": "/media/table-mat/inputs/source/source-0.mp4",
        "poster_url": "/thumb/table-mat/artifacts/research_media/source-0.jpg?w=640",
    }

    proposal = editors["proposal"]
    assert proposal["estimated_cost_usd"] == 0.05
    assert proposal["concepts"][0]["visual_approach"] == "真实测试配合短字幕"
    assert proposal["concepts"][0]["key_points"] == ["防刮", "防污"]

    assets = editors["assets"]
    assert assets["planned_count"] == 0
    assert assets["prepared_count"] == 0
    assert assets["items"] == []

    shot = editors["scene_plan"]["shots"][0]
    assert editors["scene_plan"]["reference_basis"]["proof_method"] == "真实动作与即时结果成对"
    assert shot["timeline_in_seconds"] == 0
    assert shot["timeline_out_seconds"] == 2
    assert shot["source_in_seconds"] == 1
    assert shot["source_out_seconds"] == 3
    assert shot["preview_url"] == "/media/table-mat/inputs/source/source-0.mp4"
    assert shot["poster_url"] == "/thumb/table-mat/inputs/source/source-0.mp4?w=640&t=2"
    assert shot["source_summary"] == "素材 0 内容"
    assert shot["source_usable_for"] == ["产品展示"]
    assert "镜头意图" in shot["mapping_reason"]
    assert shot["reference_evidence"] == {
        "mode": "direct_segment",
        "reference_scene_id": "reference-1",
        "description": "工具刮擦制造冲突",
        "mechanism": "动作与结果成对",
        "rationale": "对应开场冲突钩子",
        "start_seconds": 0,
        "end_seconds": 2.1,
        "preview_url": "/media/table-mat/inputs/reference/hit.mp4",
        "poster_url": "/thumb/table-mat/artifacts/research_media/reference/frame-1.jpg?w=640",
    }
    validate_operator_state(state)


def test_legacy_shot_mapping_uses_structural_reference_without_fake_clip() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    del board["artifacts"]["scene_plan"]["metadata"]["source_mapping"][0]["reference_evidence"]

    state = project_operator_state(board)
    editors = {stage["id"]: stage["editor"]["data"] for stage in state["stages"]}
    shot = editors["scene_plan"]["shots"][0]

    assert shot["reference_evidence"]["mode"] == "structural_only"
    assert shot["reference_evidence"]["mechanism"] == "真实动作与即时结果成对"
    assert shot["reference_evidence"]["preview_url"] is None
    assert shot["reference_evidence"]["start_seconds"] is None


def test_script_projection_prefers_edited_narration_over_original_text() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["script"]["sections"][0]["narration"] = "修改后的口播和字幕"

    script = next(stage for stage in project_operator_state(board)["stages"] if stage["id"] == "script")

    assert script["editor"]["data"]["sections"][0]["text"] == "修改后的口播和字幕"


def test_delivery_review_projects_four_tracks_candidates_and_reference_isolation() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["stages"] = [
        _stage(name, "completed" if name != "publish" else "pending")
        for name, _ in NINE_STAGES
    ]
    board["artifacts"]["script"]["sections"] = [{
        "id": "sentence-1",
        "label": "开场",
        "text": "一张餐桌每天要扛住多少考验",
        "start_seconds": 0,
        "end_seconds": 4,
    }]
    board["artifacts"]["scene_plan"]["scenes"] = [
        {
            "id": "shot-1", "description": "刮擦冲突", "script_section_id": "sentence-1",
            "start_seconds": 0, "end_seconds": 2,
            "overlay_layers": [{"text": "先划一下", "start_seconds": 0, "end_seconds": 2}],
        },
        {
            "id": "shot-2", "description": "擦净结果", "script_section_id": "sentence-1",
            "start_seconds": 2, "end_seconds": 4,
            "overlay_layers": [{"text": "一擦就净", "start_seconds": 2, "end_seconds": 4}],
        },
    ]
    board["artifacts"]["edit_decisions"] = {
        "cuts": [
            {"id": "shot-1", "source": "projects/table-mat/inputs/source/scratch.mp4", "in_seconds": 1, "out_seconds": 3, "speed": 1},
            {"id": "shot-2", "source": "projects/table-mat/inputs/source/clean.mp4", "in_seconds": 2, "out_seconds": 4, "speed": 1},
        ],
        "audio": {
            "narration": {"segments": [{"asset_id": "voice-main", "start_seconds": 0, "end_seconds": 4}]},
            "music": {"asset_id": "music-main", "volume": 0.12, "fade_in_seconds": 0.3, "fade_out_seconds": 0.8, "ducking": {"enabled": True}},
            "sfx": [{"asset_id": "impact", "start_seconds": 0, "volume": 0.2}],
        },
    }
    board["artifacts"]["render_report"] = {
        "outputs": [{"path": "renders/final-v2.mp4", "duration_seconds": 4, "resolution": "1080x1920"}],
        "video_master_sha256": "a" * 64,
    }
    board["artifacts"]["final_review"] = {"status": "pass"}
    board["media"]["renders"] = [{"path": "renders/final-v2.mp4", "duration_seconds": 4}]

    state = project_operator_state(board)
    delivery = next(stage for stage in state["stages"] if stage["id"] == "compose")["editor"]["data"]

    assert delivery["player"] == {
        "video_url": "/media/table-mat/renders/final-v2.mp4",
        "poster_url": "/thumb/table-mat/renders/final-v2.mp4?w=640&t=1",
        "duration_seconds": 4,
    }
    assert [track["kind"] for track in delivery["timeline"]["tracks"]] == ["video", "narration", "copy", "audio"]
    video_segments = delivery["timeline"]["tracks"][0]["segments"]
    assert [segment["id"] for segment in video_segments] == ["shot-1", "shot-2"]
    copy_segments = delivery["timeline"]["tracks"][2]["segments"]
    assert copy_segments == [{
        "id": "sentence-1",
        "label": "一张餐桌每天要扛住多少考验",
        "start_seconds": 0,
        "end_seconds": 4,
        "shot_ids": ["shot-1", "shot-2"],
        "editable": True,
        "sync_narration": True,
    }]
    assert delivery["timeline"]["tracks"][3]["empty_message"] is None
    assert [group["kind"] for group in delivery["candidate_groups"]] == ["cover", "hook", "bgm", "ending"]
    assert delivery["candidate_groups"][0]["candidates"][0]["id"].startswith("cover-")
    assert delivery["candidate_groups"][2]["candidates"][0]["label"] == "当前背景音乐"
    assert delivery["versions"][0]["active"] is True
    assert delivery["pending_changes"] == []
    assert "inputs/reference" not in json.dumps(delivery, ensure_ascii=False)

    again = project_operator_state(board)
    delivery_again = next(stage for stage in again["stages"] if stage["id"] == "compose")["editor"]["data"]
    assert delivery_again["candidate_groups"] == delivery["candidate_groups"]


def test_research_projection_supports_image_and_audio_without_broken_posters() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["source_media_review"]["files"] = [
        {
            "media_id": "still", "media_type": "image",
            "path": "projects/table-mat/inputs/source/still.JPG", "reviewed": True,
        },
        {
            "media_id": "voice", "media_type": "audio",
            "path": "projects/table-mat/inputs/source/voice.MP3", "reviewed": True,
        },
    ]

    sources = project_operator_state(board)["stages"][0]["editor"]["data"]["sources"]

    assert sources[0]["preview_url"].endswith("/inputs/source/still.JPG")
    assert sources[0]["poster_url"].endswith("/inputs/source/still.JPG?w=640")
    assert sources[1]["preview_url"].endswith("/inputs/source/voice.MP3")
    assert sources[1]["poster_url"] is None


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

    assert [(stage["id"], stage["label"]) for stage in state["stages"]] == NINE_STAGES
    sample = next(stage for stage in state["stages"] if stage["id"] == "sample")
    assert sample["status"] == "状态未知"
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
