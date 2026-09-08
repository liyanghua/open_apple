from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest


NINE_STAGES = [
    ("research", "了解任务"),
    ("proposal", "看创意方案"),
    ("script", "确认脚本"),
    ("scene_plan", "看分镜"),
    ("assets", "确认制作准备"),
    ("sample", "查看样片"),
    ("edit", "完成剪辑"),
    ("compose", "检查成片"),
    ("publish", "确认交付"),
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
        "current_stage": "查看样片",
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


def test_publish_stage_surfaces_delivery_package_while_compose_does_not() -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    board = _board_state()
    board["artifacts"]["publish_log"] = {
        "version": "1.0",
        "entries": [
            {
                "platform": "local",
                "status": "exported",
                "export_path": "renders/final.mp4",
                "timestamp": "2026-08-22T10:00:00Z",
                "metadata_used": {
                    "title": "透明桌垫：一条讲清楚日常保护",
                    "description": "15 秒实录证明。",
                    "hashtags": ["透明桌垫", "居家好物"],
                },
            }
        ],
        "metadata": {
            "hero_output": "renders/final.mp4",
            "distribution_notes": "仅本地打包，未上传任何平台。",
            "qa_evidence": ["artifacts/final_review.json"],
        },
    }
    state = project_operator_state(board)
    validate_operator_state(state)

    stages = {stage["id"]: stage for stage in state["stages"]}
    compose_data = stages["compose"]["editor"]["data"]
    publish_data = stages["publish"]["editor"]["data"]

    # Shared review workbench, but the delivery package only belongs to publish.
    assert compose_data["player"] == publish_data["player"]
    assert "delivery" not in compose_data
    assert publish_data["delivery"]["notes"] == "仅本地打包，未上传任何平台。"
    assert publish_data["delivery"]["hero_output"] == "renders/final.mp4"
    entry = publish_data["delivery"]["entries"][0]
    assert entry["platform_label"] == "本地交付"
    assert entry["status_label"] == "已导出"
    assert entry["title"] == "透明桌垫：一条讲清楚日常保护"
    assert entry["description"] == "15 秒实录证明。"
    assert entry["hashtags"] == ["透明桌垫", "居家好物"]
    assert entry["export_path"] == "renders/final.mp4"
    assert publish_data["delivery"]["package_path"] == "renders/final.mp4"
    assert publish_data["delivery"]["package_files"] == [{
        "relative_path": "renders/final.mp4",
        "label": "final.mp4",
        "kind": "video",
        "download_url": None,
    }]
    assert publish_data["delivery"]["qa_evidence"] == [{
        "relative_path": "artifacts/final_review.json",
        "label": "final_review.json",
        "download_url": "/media/table-mat/artifacts/final_review.json",
    }]


def test_publish_stage_without_publish_log_has_empty_delivery_entries() -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    state = project_operator_state(_board_state())
    validate_operator_state(state)
    stages = {stage["id"]: stage for stage in state["stages"]}
    publish_data = stages["publish"]["editor"]["data"]
    assert publish_data["delivery"]["entries"] == []
    assert publish_data["delivery"]["package_path"] == ""
    assert publish_data["delivery"]["package_files"] == []
    assert "delivery" not in stages["compose"]["editor"]["data"]


def test_publish_stage_lists_files_from_project_delivery_package(tmp_path: Path) -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    package = tmp_path / "exports" / "table-mat"
    package.mkdir(parents=True)
    (package / "video").mkdir()
    (package / "video" / "output.mp4").write_bytes(b"video")
    (package / "metadata").mkdir()
    (package / "metadata" / "metadata.json").write_text("{}", encoding="utf-8")
    board = _board_state()
    board["_project_dir"] = tmp_path
    board["artifacts"]["publish_log"] = {
        "version": "1.0",
        "entries": [{
            "platform": "local",
            "status": "exported",
            "export_path": "exports/table-mat",
            "timestamp": "2026-08-22T10:00:00Z",
        }],
        "metadata": {"distribution_notes": "本地交付"},
    }
    state = project_operator_state(board)
    validate_operator_state(state)
    delivery = next(stage for stage in state["stages"] if stage["id"] == "publish")["editor"]["data"]["delivery"]
    assert delivery["package_path"] == "exports/table-mat"
    assert [item["relative_path"] for item in delivery["package_files"]] == [
        "exports/table-mat/metadata/metadata.json",
        "exports/table-mat/video/output.mp4",
    ]
    assert delivery["package_files"][0]["download_url"] == "/media/table-mat/exports/table-mat/metadata/metadata.json"


def test_publish_stage_does_not_expose_reference_files_as_downloads(tmp_path: Path) -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    reference = tmp_path / "inputs" / "reference"
    reference.mkdir(parents=True)
    (reference / "reference.mp4").write_bytes(b"reference")
    board = _board_state()
    board["_project_dir"] = tmp_path
    board["artifacts"]["publish_log"] = {
        "version": "1.0",
        "entries": [{
            "platform": "local", "status": "exported",
            "export_path": "inputs/reference", "timestamp": "2026-08-22T10:00:00Z",
        }],
    }
    state = project_operator_state(board)
    validate_operator_state(state)
    files = next(stage for stage in state["stages"] if stage["id"] == "publish")["editor"]["data"]["delivery"]["package_files"]
    assert files[0]["download_url"] is None


def test_sample_editor_exposes_execution_trace_summary_and_shots() -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    board = _board_state()
    board["artifacts"]["sample_execution_trace"] = {
        "summary": {
            "planned_shot_count": 2,
            "included_shot_count": 1,
            "status_counts": {"executed": 1, "partial": 0, "added": 0, "not_in_sample": 1},
            "new_content_count": 0,
        },
        "shots": [{
            "shot_id": "shot-1",
            "status": "executed",
            "status_label": "已按方案执行",
            "planned_basis": {"purpose": "展示擦净结果", "reference_rules": ["动作与结果成对"]},
            "actual_execution": {"source_path": "inputs/source/oil.mp4", "timeline_start_seconds": 0, "timeline_end_seconds": 2},
            "deviation": None,
            "sample_window": {"included": True, "start_seconds": 0, "end_seconds": 2},
        }],
    }

    state = project_operator_state(board)
    sample = next(stage for stage in state["stages"] if stage["id"] == "sample")

    assert sample["editor"]["data"]["execution_trace"]["summary"]["included_shot_count"] == 1
    assert sample["editor"]["data"]["execution_trace"]["shots"][0]["status_label"] == "已按方案执行"
    assert state["active_job"] is None
    validate_operator_state(state)


def test_sample_editor_projects_narration_and_diff_artifacts() -> None:
    """Task 1.3：样片只读投影补齐逐镜口播、caption_diff 和 creative_rule_diff。"""
    from backlot.operator_state import project_operator_state, validate_operator_state

    board = _board_state()
    board["artifacts"]["shot_execution_plan"] = {
        "shots": [{"id": "shot-1", "purpose": "展示擦净结果", "narration": "计划口播"}],
    }
    board["artifacts"]["sample_execution_trace"] = {
        "summary": {
            "planned_shot_count": 1,
            "included_shot_count": 1,
            "status_counts": {"executed": 1, "partial": 0, "added": 0, "not_in_sample": 0},
            "new_content_count": 0,
        },
        "shots": [{
            "shot_id": "shot-1",
            "status": "executed",
            "status_label": "已按方案执行",
            "planned_basis": {"purpose": "展示擦净结果", "screen_copy": "计划字幕"},
            "actual_execution": {
                "source_path": "inputs/source/oil.mp4",
                "timeline_start_seconds": 0,
                "timeline_end_seconds": 2,
                "screen_copy": "实际字幕",
                "narration": "实际口播",
            },
            "deviation": None,
            "sample_window": {"included": True, "start_seconds": 0, "end_seconds": 2},
        }],
        "caption_diff": {
            "status": "executed",
            "summary": "字幕：计划 1 条意图 / 实际 1 条字幕；字幕按剧本意图进入样片",
            "plan": {"policy": "", "expected_copy_count": 1},
            "actual": {"caption_count": 1, "timing_drift_detected": False},
            "reason": "字幕按剧本意图进入样片",
        },
        "creative_rule_diff": {
            "status": "executed",
            "summary": "导演规则已绑定并进入样片",
            "rules": [{"section": "内容方向", "rule": "动作与结果成对", "status": "bound", "summary": "已绑定镜头并进入样片"}],
        },
    }

    state = project_operator_state(board)
    sample = next(stage for stage in state["stages"] if stage["id"] == "sample")
    data = sample["editor"]["data"]

    shot = data["execution_trace"]["shots"][0]
    assert shot["planned"]["narration"] == "计划口播"
    assert shot["actual"]["narration"] == "实际口播"
    assert data["caption_diff"]["status"] == "executed"
    assert data["creative_rule_diff"]["rules"][0]["status"] == "bound"
    validate_operator_state(state)


def test_sample_editor_builds_trace_for_legacy_sample_without_saved_trace() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["shot_execution_plan"] = {
        "shots": [{"id": "shot-1", "purpose": "展示擦净结果", "duration_seconds": 2,
                   "source_selection": {"path": "inputs/source/oil.mp4", "start_seconds": 1, "end_seconds": 3}}],
    }
    board["artifacts"]["final_props"] = {
        "fps": 30,
        "shots": [{"id": "shot-1", "start_seconds": 0, "end_seconds": 2,
                   "source_path": "inputs/source/oil.mp4", "source_in_seconds": 1, "source_out_seconds": 3}],
    }

    state = project_operator_state(board)
    sample = next(stage for stage in state["stages"] if stage["id"] == "sample")

    assert sample["editor"]["data"]["execution_trace"]["summary"]["included_shot_count"] == 1


def test_projection_includes_safe_material_concept_and_shot_details() -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    board = _board_state()
    board["artifacts"]["scene_plan"]["metadata"]["source_mapping"][0].update({
        "claim_ids": ["claim-visible-result"],
        "action_keys": ["wipe_surface"],
        "evidence_row_ids": ["evidence-001"],
        "subject_completeness": "complete",
        "crop_strategy": "center crop with protected subject bounds",
        "caption_safe_zone": "top",
    })
    board["artifacts"]["script"]["sections"][0].update({
        "scene_id": "shot-1",
        "narration": "真实擦拭动作口播",
        "screen_copy": "一擦即净",
    })
    state = project_operator_state(board)
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
    assert shot["narration"] == "真实擦拭动作口播"
    assert shot["screen_copy"] == "一擦即净"
    assert shot["claim_ids"] == ["claim-visible-result"]
    assert shot["action_keys"] == ["wipe_surface"]
    assert shot["evidence_row_ids"] == ["evidence-001"]
    assert shot["subject_completeness"] == "complete"
    assert shot["crop_strategy"] == "center crop with protected subject bounds"
    assert shot["caption_safe_zone"] == "top"
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


def test_execution_plan_uses_media_index_to_report_source_coverage() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["media_index"] = {
        "entries": [{
            "path": "projects/table-mat/inputs/source/source-0.mp4",
            "probe": {"duration_seconds": 3},
            "representative_frames": ["analysis/source-0/frame.jpg"],
        }],
    }
    board["artifacts"]["shot_execution_plan"] = {
        "plan_id": "execution-1",
        "plan_version": 1,
        "status": "draft",
        "shots": [{
            "id": "shot-1", "order": 1, "purpose": "展示真实擦拭结果",
            "duration_seconds": 2, "narration": "擦一擦就好打理。", "screen_copy": "易擦拭",
            "subject_action": "擦拭透明桌垫", "setting": "餐桌", "framing": "近景",
            "camera": "固定", "lighting": "自然光", "sound": "保留擦拭声",
            "evidence_type": "real_proof", "coverage_status": "enough", "gap_class": "none",
            "gap_strategy": "none", "reference_mechanisms": [], "industry_notes": [],
            "control_rule_refs": [], "generation_proposals": [], "selected_generation_task_id": None,
            "source_selection": {
                "media_id": "source-0", "path": "inputs/source/source-0.mp4",
                "start_seconds": 1, "end_seconds": 3, "fit_reason": "完整呈现擦拭结果",
            },
        }],
    }

    assets = next(stage for stage in project_operator_state(board)["stages"] if stage["id"] == "assets")
    execution_shot = assets["editor"]["data"]["execution_plan"]["shots"][0]

    assert execution_shot["source_coverage"] == "素材已覆盖"
    assert execution_shot["source_duration_seconds"] == 3

    board["artifacts"]["shot_execution_plan"]["shots"][0]["source_selection"]["end_seconds"] = 4
    assets = next(stage for stage in project_operator_state(board)["stages"] if stage["id"] == "assets")
    assert assets["editor"]["data"]["execution_plan"]["shots"][0]["source_coverage"] == "需要调整"

    del board["artifacts"]["media_index"]
    assets = next(stage for stage in project_operator_state(board)["stages"] if stage["id"] == "assets")
    assert assets["editor"]["data"]["execution_plan"]["shots"][0]["source_coverage"] == "等待核对"


def test_asset_editor_projects_formal_audio_plan_and_cost() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["asset_plan"] = {
        "paid_generation_approved": False,
        "planned_assets": [],
        "audio_plan": {
            "tts": {"provider": "doubao", "resource_id": "seed-tts-2.0", "voice": "voice-1"},
            "bgm": {"provider": "suno", "profile": "轻快节奏电商 BGM"},
            "mix": {"ducking_db": -6},
            "estimated_cost_usd": 0.08,
        },
    }
    board["artifacts"]["shot_execution_plan"] = {
        "status": "draft",
        "shots": [{"id": "shot-1", "screen_copy": "商品页参数标注双面毛圈"}],
    }

    assets = next(
        stage for stage in project_operator_state(board)["stages"]
        if stage["id"] == "assets"
    )["editor"]["data"]

    assert assets["narration_status"] == "方案已锁定，等待本门确认"
    assert assets["music_status"] == "方案已锁定，等待本门确认"
    assert assets["subtitle_status"] == "由脚本生成，随样片制作"
    assert assets["estimated_cost_usd"] == 0.08
    assert assets["audio_plan"] == {
        "tts": {"provider": "doubao", "resource_id": "seed-tts-2.0", "voice": "voice-1"},
        "bgm": {"provider": "suno", "profile": "轻快节奏电商 BGM"},
        "mix": {"ducking_db": -6},
    }


def test_asset_editor_explains_exact_source_copy_and_local_proxy_processing() -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    board = _board_state()
    board["artifacts"]["asset_plan"] = {
        "paid_generation_approved": False,
        "planned_assets": [{
            "id": "proxy-shot-01",
            "type": "video_proxy",
            "provider": "media_proxy",
            "model": "ffmpeg-local",
            "cost_estimate_usd": 0.0,
            "paid": False,
            "output_path": "assets/video/shot-01-proxy.mp4",
            "source_stage": "assets",
            "exists": False,
            "shot_id": "shot-01",
            "source_selection": {
                "media_id": "source-0",
                "path": "inputs/source/source-0.mp4",
                "start_seconds": 1.25,
                "end_seconds": 4.75,
                "fit_reason": "连续倒水动作与湿润结果都在同一段素材内",
            },
            "creative_binding": {
                "purpose": "展示连续倒水后的湿润范围",
                "subject_action": "一股水连续倒在毛巾表面",
                "narration": "一股水浇下，湿润范围清楚可见。",
                "screen_copy": "连续水流吸收演示",
                "claim_ids": ["claim-absorbency"],
                "action_keys": ["continuous_pour_water"],
                "evidence_row_ids": ["evidence-pour-01"],
                "product_fact_refs": ["product_facts.claims[0]"],
                "product_page_refs": ["product_page_capture.fact_candidates[12]"],
                "page_asset_ids": ["page-asset-selected-sku"],
                "page_evidence_ids": ["page-detail-sequence"],
            },
            "processing_plan": {
                "operation": "local_proxy_transcode",
                "tool": "media_proxy",
                "aspect_ratio": "3:4",
                "width": 540,
                "height": 720,
                "fit": "cover",
                "crop_strategy": "center_crop_subject_protected",
                "audio_policy": "proxy_muted_mix_added_at_sample",
            },
        }],
    }
    board["artifacts"]["asset_manifest"] = {"assets": []}
    board["artifacts"]["product_facts"] = {
        "product_name": "花花公子银离子纯棉毛巾",
        "sku": "6276962282892",
        "claims": [{
            "claim_id": "page-claim-absorb-dry",
            "statement": "吸水速干",
            "claim_class": "benefit",
            "status": "needs_evidence",
            "evidence_status": "page_claim",
            "risk_level": "high",
            "sku_scope": ["6276962282892"],
            "allowed_wording": ["一股水浇下，湿润范围清楚可见"],
            "prohibited_wording": ["水滴一沾上就被吸进去"],
            "provenance_refs": ["visible_absorb_detail"],
        }],
    }
    board["artifacts"]["product_page_capture"] = {
        "project_id": "maojin-yinlizi",
        "capture_evidence": {"screenshots": [{
            "evidence_id": "page-detail-sequence",
            "local_path": "analysis/product_page/detail-sequence.jpg",
            "sha256": "a" * 64,
        }]},
    }
    board["artifacts"]["product_asset_ledger"] = {
        "project_id": "maojin-yinlizi",
        "assets": [{
            "asset_id": "page-asset-selected-sku",
            "asset_role": "selected_sku",
            "usage_role": "identity_anchor",
            "local_path": "assets/product_page/raw/selected-sku.webp",
            "sha256": "b" * 64,
        }],
    }

    state = project_operator_state(board)
    data = next(
        stage for stage in state["stages"] if stage["id"] == "assets"
    )["editor"]["data"]
    item = data["items"][0]

    assert item["label"] == "镜头 01 · source-0"
    assert item["status"] == "待本地处理"
    assert item["stage_label"] == "本地素材处理（零付费）"
    assert item["shot_id"] == "shot-01"
    assert item["source_path"] == "inputs/source/source-0.mp4"
    assert item["source_range"] == "1.25–4.75 秒"
    assert item["preview_url"] == "/media/table-mat/inputs/source/source-0.mp4"
    assert item["poster_url"] == "/thumb/table-mat/inputs/source/source-0.mp4?w=640&t=3"
    assert item["shot_purpose"] == "展示连续倒水后的湿润范围"
    assert item["subject_action"] == "一股水连续倒在毛巾表面"
    assert item["narration"] == "一股水浇下，湿润范围清楚可见。"
    assert item["screen_copy"] == "连续水流吸收演示"
    assert item["action_keys"] == ["continuous_pour_water"]
    assert item["evidence_row_ids"] == ["evidence-pour-01"]
    assert item["product_fact_refs"] == ["product_facts.claims[0]"]
    assert item["product_page_refs"] == ["product_page_capture.fact_candidates[12]"]
    assert item["fact_bindings"] == [{
        "ref": "product_facts.claims[0]",
        "claim_id": "page-claim-absorb-dry",
        "statement": "吸水速干",
        "claim_class": "benefit",
        "status": "needs_evidence",
        "evidence_status": "page_claim",
        "risk_level": "high",
        "sku_scope": ["6276962282892"],
        "allowed_wording": ["一股水浇下，湿润范围清楚可见"],
        "prohibited_wording": ["水滴一沾上就被吸进去"],
        "provenance_refs": ["visible_absorb_detail"],
    }]
    assert item["fact_role"] == "selling_point"
    assert [evidence["id"] for evidence in item["page_evidence"]] == [
        "page-asset-selected-sku", "page-detail-sequence",
    ]
    assert item["page_evidence"][0]["preview_url"] == (
        "/media/table-mat/projects/maojin-yinlizi/assets/product_page/raw/selected-sku.webp"
    )
    assert item["page_evidence"][1]["preview_url"] == (
        "/media/table-mat/projects/maojin-yinlizi/analysis/product_page/detail-sequence.jpg"
    )
    assert item["alignment_status"] == "pass"
    assert item["processing_summary"] == "本地转为 3:4（540×720）审片代理，中心裁切并保护主体；样片阶段再加入口播和 BGM"
    assert item["output_path"] == "assets/video/shot-01-proxy.mp4"
    assert "零付费" in item["reason"]
    validate_operator_state(state)

    board["artifacts"]["product_facts"]["claims"][0]["claim_class"] = "identity"
    identity_state = project_operator_state(board)
    identity_item = next(
        stage for stage in identity_state["stages"] if stage["id"] == "assets"
    )["editor"]["data"]["items"][0]
    assert identity_item["fact_role"] == "identity_anchor"
    validate_operator_state(identity_state)


def test_asset_editor_explains_product_image_fallback_as_selling_point_coverage() -> None:
    from backlot.operator_state import project_operator_state, validate_operator_state

    board = _board_state()
    board["artifacts"]["product_facts"] = {
        "claims": [{
            "claim_id": "page-claim-ag",
            "statement": "商品页标注 10A 级抗菌与 AG+ 银离子",
            "claim_class": "benefit",
            "status": "needs_evidence",
            "evidence_status": "page_claim",
            "risk_level": "high",
            "sku_scope": ["6276962282892"],
            "allowed_wording": ["商品页标注 10A 级抗菌"],
            "prohibited_wording": ["实验证明杀菌"],
            "provenance_refs": ["page-shot-ag"],
        }],
    }
    board["artifacts"]["product_asset_ledger"] = {
        "project_id": "maojin-yinlizi",
        "assets": [
            {
                "asset_id": "page-asset-main-03",
                "asset_role": "main_image",
                "usage_role": "selling_point_reference",
                "local_path": "assets/product_page/raw/main-03.webp",
                "sha256": "a" * 64,
                "sku_scope": ["6276962282892"],
            },
            {
                "asset_id": "page-asset-main-03-clean-v1",
                "asset_role": "derived_clean_reference",
                "usage_role": "generation_reference",
                "local_path": "assets/product_page/derived/main-03-clean-v1.png",
                "sha256": "b" * 64,
                "parent_asset_id": "page-asset-main-03",
                "sku_scope": ["6276962282892"],
                "identity_check": {"status": "pass", "notes": []},
                "ocr_residual_text": [],
                "generation_eligibility": "eligible",
            },
        ],
    }
    board["artifacts"]["reference_source_matrix"] = {
        "rows": [{
            "matrix_row_id": "evidence-ag-01",
            "visual_route": "generated_from_product_image",
            "route_reason": "自有素材没有可核验的银离子表达，使用已审核纯产品图补拍",
            "owned_candidates": [{
                "media_id": "source-4",
                "source_path": "inputs/source/source-4.mp4",
                "source_hash": "c" * 64,
                "source_time_range": {"start_seconds": 2, "end_seconds_exclusive": 5},
                "evidence_frames": ["analysis/source-4.jpg"],
                "confidence": 0.72,
                "status": "rejected",
                "observed_actions": ["measure_towel"],
                "observed_results": ["gauge_reads_0_00"],
                "subject_complete_in_3_4": True,
                "rejection_reasons": ["missing required actions", "missing required visible results"],
            }],
        }],
    }
    reference = {
        "asset_id": "page-asset-main-03-clean-v1",
        "parent_asset_id": "page-asset-main-03",
        "local_path": "assets/product_page/derived/main-03-clean-v1.png",
        "sha256": "b" * 64,
        "sku_scope": ["6276962282892"],
    }
    requirement = {
        "visualizability": "non_observable",
        "required_subjects": ["target_product"],
        "required_actions": ["product_hero_display"],
        "required_results": ["product_identity_remains_visible"],
        "forbidden_substitutions": ["simulated_antibacterial_proof"],
        "risk_level": "high",
    }
    board["artifacts"]["asset_plan"] = {
        "paid_generation_approved": False,
        "planned_assets": [{
            "id": "generated-shot-05",
            "type": "generated_video",
            "provider": "grok",
            "model": "grok-imagine-video",
            "cost_estimate_usd": 1.21,
            "paid": True,
            "output_path": "assets/video/shot-05-generated.mp4",
            "source_stage": "assets",
            "exists": False,
            "shot_id": "shot-05",
            "visual_route": "generated_from_product_image",
            "generation_reference": reference,
            "provider_candidates": [{
                "tool": "grok_video", "provider": "grok", "model": "grok-imagine-video",
                "estimated_cost_usd": 0.202, "supports_local_reference": True,
                "supports_native_3_4": True,
            }],
            "evidence_role": "visual_expression_only",
            "creative_binding": {
                "purpose": "银离子卖点的产品英雄镜头",
                "subject_action": "product_hero_display",
                "narration": "商品页标注 10A 级抗菌，日常使用更安心。",
                "screen_copy": "商品页标注 · 10A 级抗菌",
                "claim_ids": ["page-claim-ag"],
                "action_keys": ["product_hero_display"],
                "evidence_row_ids": ["evidence-ag-01"],
                "product_fact_refs": ["product_facts.claims[0]"],
                "product_page_refs": ["product_page_capture.fact_candidates[0]"],
                "page_asset_ids": ["page-asset-main-03"],
                "page_evidence_ids": [],
                "visual_route": "generated_from_product_image",
                "claim_visual_requirements": requirement,
                "evidence_role": "visual_expression_only",
            },
            "generation_plan": {
                "operation": "image_to_video",
                "prompt": "保持商品身份，只做产品英雄展示",
                "duration_seconds": 4,
                "aspect_ratio": "3:4",
                "required_actions": ["product_hero_display"],
                "required_results": ["product_identity_remains_visible"],
                "prohibitions": ["不得模拟抗菌实验"],
                "retry_limit": 2,
                "provider_selection_status": "awaiting_human",
            },
            "processing_plan": {"operation": "image_to_video", "aspect_ratio": "3:4"},
        }],
    }
    board["artifacts"]["asset_manifest"] = {"assets": []}

    state = project_operator_state(board)
    item = next(
        stage for stage in state["stages"] if stage["id"] == "assets"
    )["editor"]["data"]["items"][0]

    assert item["label"] == "镜头 05 · 商品图补拍（图生视频）"
    assert item["route_label"] == "商品图补拍（图生视频）"
    assert item["route_reason"] == "自有素材没有可核验的银离子表达，使用已审核纯产品图补拍"
    assert item["evidence_role_label"] == "AI 视觉表达，不是商品事实证明"
    assert item["visual_requirement"]["required_actions"] == ["product_hero_display"]
    assert item["owned_candidates"][0]["rejection_reasons"] == [
        "missing required actions", "missing required visible results",
    ]
    assert item["generation_reference"]["preview_url"].endswith("main-03-clean-v1.png")
    assert item["generation_reference"]["original_preview_url"].endswith("main-03.webp")
    assert item["generation_reference"]["identity_status"] == "pass"
    assert item["generation_plan"]["aspect_ratio"] == "3:4"
    assert item["generation_plan"]["retry_limit"] == 2
    assert item["generation_options"][0]["service"] == "grok"
    assert item["generation_options"][0]["version"] == "grok-imagine-video"
    assert item["generation_options"][0]["selected"] is True
    assert item["alignment_status"] == "pass"
    validate_operator_state(state)


def test_approved_execution_plan_completes_assets_and_exposes_agent_handoff() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["stages"] = [_stage(name, "pending" if name == "assets" else status) for name, status in {
        "research": "completed", "proposal": "completed", "script": "completed",
        "scene_plan": "completed", "assets": "pending", "sample": "pending",
        "edit": "pending", "compose": "pending", "publish": "pending",
    }.items()]
    board["artifacts"]["shot_execution_plan"] = {"status": "approved", "plan_version": 2, "shots": []}

    state = project_operator_state(board)
    stages = {stage["id"]: stage for stage in state["stages"]}
    assets = stages["assets"]["editor"]["data"]

    assert stages["assets"]["status"] == "已完成"
    assert stages["sample"]["status"] == "未开始"
    assert assets["execution_plan"]["handoff_ready"] is True


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


def test_template_run_preview_uses_shared_source_project_for_linked_media(tmp_path) -> None:
    import json
    from backlot.operator_state import _source_preview_path

    source = tmp_path / "projects" / "source-run" / "inputs" / "source"
    source.mkdir(parents=True)
    (source / "clip.mp4").write_bytes(b"video")
    project = tmp_path / "projects" / "template-run"
    (project / "inputs").mkdir(parents=True)
    (project / "inputs" / "source").symlink_to(source, target_is_directory=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": "template-run",
        "template_run": {"source_research_project": "source-run"},
    }))

    assert _source_preview_path(
        {"_project_dir": project}, "inputs/source/clip.mp4"
    ) == "projects/source-run/inputs/source/clip.mp4"


def test_script_projection_prefers_edited_narration_over_original_text() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["script"]["sections"][0]["narration"] = "修改后的口播和字幕"

    script = next(stage for stage in project_operator_state(board)["stages"] if stage["id"] == "script")

    assert script["editor"]["data"]["sections"][0]["text"] == "修改后的口播和字幕"


def test_script_projection_resolves_director_rules_for_operator_display() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["creative_control_plan"] = {
        "sections": {
            "content_direction": {"rules": ["主信息只讲透明保护，不遮住木纹。"]},
            "story_pacing": {"rules": ["前两秒先出现清楚的产品动作。"]},
        },
    }
    board["artifacts"]["script"]["sections"][0]["control_rule_refs"] = [
        "content_direction.rules[0]", "story_pacing.rules[0]",
    ]

    script = next(stage for stage in project_operator_state(board)["stages"] if stage["id"] == "script")

    assert script["editor"]["data"]["sections"][0]["director_rules"] == [
        "内容方向：主信息只讲透明保护，不遮住木纹。",
        "故事和节奏：前两秒先出现清楚的产品动作。",
    ]


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


def test_research_projection_has_fixed_substages_and_disabled_reference_state() -> None:
    from backlot.operator_state import project_operator_state

    state = project_operator_state(_board_state())
    research = next(stage for stage in state["stages"] if stage["id"] == "research")["editor"]["data"]
    assert [item["id"] for item in research["substages"]] == [
        "reference", "sources", "matching", "direction", "quality",
    ]
    assert research["substages"][0]["state"] == "completed"

    without_reference = copy.deepcopy(_board_state())
    without_reference["artifacts"].pop("video_analysis_brief")
    without_reference["artifacts"].pop("reference_fingerprint")
    if isinstance(without_reference["artifacts"].get("research_breakdown"), dict):
        without_reference["artifacts"]["research_breakdown"].pop("reference_shots", None)
    state_without_reference = project_operator_state(without_reference)
    research_without_reference = next(stage for stage in state_without_reference["stages"] if stage["id"] == "research")["editor"]["data"]
    reference_substage = research_without_reference["substages"][0]
    assert reference_substage["state"] == "not_needed"
    assert reference_substage["message"] == "本项目没有参考片，这一步不需要处理"


def test_research_projection_groups_only_blocking_decisions_and_exposes_proposal_handoff() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"].update({
        "reference_source_matrix": {"rows": [
            {"matrix_row_id": "rebound", "reference_intent": "展示回弹", "resolution": "bridge", "unmatched_gap": "现有素材没有回弹释放瞬间"},
            {"matrix_row_id": "cta", "reference_intent": "结尾行动引导", "resolution": "rewrite", "unmatched_gap": "现有素材没有原创 CTA 画面"},
            {"matrix_row_id": "scratch", "reference_intent": "耐刮证明", "resolution": "accept", "source_media_id": "source-3"},
        ]},
        "research_synthesis": {"differentiation_directions": [
            {"direction_id": "proof", "title": "四段证据一条讲清楚", "promise": "用动作证明产品"},
        ]},
        "research_scorecard": {"status": "pass", "score": 10, "max_score": 10, "checks": []},
    })

    research = project_operator_state(board)["stages"][0]["editor"]["data"]
    assert [item["id"] for item in research["decision_inbox"]] == ["matrix-rebound", "matrix-cta", "direction"]
    assert research["proposal_handoff"]["state"] == "needs_decision"
    assert research["proposal_handoff"]["message"] == "还有 3 项需要你确认，确认后即可进入创意方案"
    assert research["substages"][-1]["state"] == "awaiting_human"

    board["artifacts"]["research_annotations"] = {
        "matrix_resolutions": {
            "rebound": {"resolution": "rewrite", "source_media_id": None, "note": "改成柔韧不易变形"},
            "cta": {"resolution": "rewrite", "source_media_id": None, "note": "使用原创 CTA"},
        },
        "direction_preferences": {"proof": {"preference": "prefer", "rationale": "优先展示动作证据"}},
    }
    decided = project_operator_state(board)["stages"][0]["editor"]["data"]
    assert decided["decision_inbox"] == []
    assert decided["proposal_handoff"]["state"] == "ready"
    assert decided["proposal_handoff"]["selected_direction_ids"] == ["proof"]


def test_research_projection_exposes_complete_product_fact_capture() -> None:
    """商品页完整采集结果必须在研究工作台可见，而不是只留在后端 gate。"""
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["product_page_capture"] = {
        "acquisition_status": "complete",
        "page_identity": {
            "platform": "tmall",
            "selected_sku_id": "6276962282892",
            "selected_sku_text": "柔胭粉",
        },
        "capture_scope": {
            "required_surfaces": ["identity", "selected_sku", "parameter_table", "main_gallery", "detail_content"],
            "captured_surfaces": ["identity", "selected_sku", "parameter_table", "main_gallery", "detail_content"],
            "surface_evidence": {"identity": ["capture_evidence.screenshots[0]"]},
            "fact_candidate_count": 3,
            "excluded_volatile_count": 1,
        },
    }
    board["artifacts"]["product_facts"] = {
        "product_name": "花花公子银离子毛巾",
        "sku": "6276962282892",
        "claims": [
            {
                "claim_id": "absorb",
                "statement": "商品页主打吸水速干",
                "claim_class": "benefit",
                "status": "needs_evidence",
                "evidence_status": "page_claim",
                "risk_level": "medium",
                "sku_scope": ["6276962282892"],
                "allowed_wording": ["商品页主打吸水速干"],
                "prohibited_wording": ["一滴水瞬间吸干"],
            },
            {
                "claim_id": "report-needed",
                "statement": "检测报告正文尚未核验",
                "claim_class": "evidence",
                "status": "forbidden",
                "evidence_status": "restricted",
                "risk_level": "high",
                "sku_scope": ["6276962282892"],
                "allowed_wording": ["商品图展示报告缩略图"],
                "prohibited_wording": ["权威报告已证明"],
            },
        ],
    }

    product = project_operator_state(board)["stages"][0]["editor"]["data"]["product_facts"]

    assert product["product_name"] == "花花公子银离子毛巾"
    assert product["selected_sku"] == "柔胭粉（6276962282892）"
    assert product["capture"]["candidate_count"] == 3
    assert product["capture"]["volatile_excluded_count"] == 1
    assert [item["id"] for item in product["capture"]["surfaces"]] == [
        "identity", "selected_sku", "parameter_table", "main_gallery", "detail_content",
    ]
    assert all(item["captured"] for item in product["capture"]["surfaces"])
    assert product["counts"] == {
        "total": 2,
        "page_claim": 1,
        "visually_observed": 0,
        "needs_human_confirmation": 0,
        "restricted": 1,
    }
    assert product["facts"][0]["allowed_wording"] == ["商品页主打吸水速干"]
    assert product["facts"][1]["prohibited_wording"] == ["权威报告已证明"]


def test_research_scorecard_uses_production_language_for_fixed_checks() -> None:
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["research_scorecard"] = {
        "score": 10,
        "max_score": 10,
        "status": "pass",
        "checks": [
            {"id": check_id, "label": check_id, "status": "pass", "message": "Confirmed"}
            for check_id in (
                "input_coverage",
                "evidence_traceability",
                "source_matching",
                "production_readiness",
                "execution_discipline",
            )
        ],
    }

    quality = project_operator_state(board)["stages"][0]["editor"]["data"]["quality"]

    assert [item["label"] for item in quality["checks"]] == [
        "输入素材检查",
        "结论依据",
        "素材匹配",
        "制作可行性",
        "执行完整性",
    ]
    assert {item["message"] for item in quality["checks"]} == {"已检查，未发现问题"}


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


def test_compose_and_publish_degrade_honestly_when_render_missing() -> None:
    """Task 4.1：成片/交付缺少渲染结果时只读降级，不伪造通过或交付。"""
    from backlot.operator_state import project_operator_state

    state = project_operator_state(_board_state())
    compose = next(stage for stage in state["stages"] if stage["id"] == "compose")
    publish = next(stage for stage in state["stages"] if stage["id"] == "publish")
    compose_data = compose["editor"]["data"]
    publish_data = publish["editor"]["data"]
    assert compose_data["qa_status"] == "等待成片检查"
    assert compose_data["download_url"] is None
    assert publish_data["delivery"]["entries"] == []
    assert publish_data["delivery"]["package_files"] == []


def test_real_operator_state_flows_through_approval_adapter(tmp_path: Path) -> None:
    """P1 联调回归：真实投影 + 真实任务注入 → 审批适配器不丢字段、不伪造事实。

    覆盖四个 P1：生成任务真实状态、样片计划/实际口播分离、参考片段证据保留、
    未选择创意方向时不默认取第一个方向。
    """
    import subprocess

    from backlot.operator_state import _inject_generation_tasks, project_operator_state

    repo_root = Path(__file__).resolve().parents[2]
    board = _board_state()
    # 1) 未选择创意方向（真实场景）
    board["artifacts"]["proposal_packet"]["selected_concept"] = None
    # 2) 真实生成任务目录（load_operator_state 的注入路径）
    tasks_dir = tmp_path / "operator" / "shot-generation" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "task-1.json").write_text(json.dumps({
        "task_id": "task-1", "shot_id": "shot-1", "proposal_id": "gp-1",
        "quality": "fast", "status": "completed",
        "output_path": "projects/table-mat/assets/gen/shot-1.mp4",
        "actual_cost_usd": 0.08, "error": None, "seed": 7,
    }), encoding="utf-8")
    board["artifacts"]["shot_execution_plan"] = {
        "plan_id": "ep-1", "plan_version": 2, "status": "approved",
        "shots": [{
            "id": "shot-1", "order": 1, "purpose": "展示擦净动作", "narration": "计划口播",
            "screen_copy": "计划字幕",
            "generation_proposals": [{
                "id": "gp-1", "operation": "generate", "model_family": "seedance",
                "duration_seconds": 2, "aspect_ratio": "9:16",
                "estimated_fast_cost_usd": 0.1, "estimated_standard_cost_usd": 0.2,
                "evidence_risk": "中",
            }],
            "selected_generation_task_id": "task-1",
        }],
    }
    board["artifacts"]["sample_execution_trace"] = {
        "summary": {"planned_shot_count": 1, "included_shot_count": 1,
                     "status_counts": {"executed": 1, "partial": 0, "added": 0, "not_in_sample": 0},
                     "new_content_count": 0},
        "shots": [{
            "shot_id": "shot-1", "status": "executed", "status_label": "已按方案执行",
            "planned_basis": {"purpose": "展示擦净动作", "screen_copy": "计划字幕",
                               "reference_rules": ["动作与结果成对"]},
            "actual_execution": {"source_path": "projects/table-mat/inputs/source/source-0.mp4",
                                  "screen_copy": "实际字幕",
                                  "timeline_start_seconds": 0, "timeline_end_seconds": 2,
                                  "source_in_seconds": 1, "source_out_seconds": 3, "narration": ""},
            "deviation": None,
            "sample_window": {"included": True, "start_seconds": 0, "end_seconds": 2},
        }],
        "caption_diff": {"status": "executed", "summary": "字幕按剧本意图进入样片"},
        "creative_rule_diff": {"status": "executed", "summary": "导演规则已绑定",
                                "rules": [{"section": "内容方向", "rule": "动作与结果成对",
                                           "status": "bound", "summary": "已绑定"}]},
        "audio_diff": {"plan": {"narration_planned": True, "music_planned": False},
                        "actual": {"narration_present": True, "music_present": False, "original_sound": True}},
    }
    board["artifacts"]["creative_control_plan"] = {
        "plan_id": "cp-1", "plan_version": 1,
        "sections": {"content_direction": {"summary": "方向摘要", "rules": ["动作与结果成对"]}},
    }
    board["artifacts"]["asset_plan"] = {
        "planned_assets": [{"id": "a1", "type": "image_generation", "provider": "flux",
                             "paid": True, "cost_estimate_usd": 0.02, "source_stage": "assets"}],
        "paid_generation_approved": False,
    }
    board["artifacts"]["asset_manifest"] = {"assets": []}
    board["artifacts"]["media_index"] = {"entries": []}

    state = project_operator_state(board)
    _inject_generation_tasks(state, tmp_path)

    stages_json = json.dumps(state["stages"], ensure_ascii=False)
    script = f"""
import {{ buildApprovalStages }} from './backlot/ui/operator/approval_model.js';
const stages = buildApprovalStages({{stages: {stages_json}}});
const proposal = stages.find((stage) => stage.stageId === 'proposal');
const assets = stages.find((stage) => stage.stageId === 'assets');
const sample = stages.find((stage) => stage.stageId === 'sample');
const scene = stages.find((stage) => stage.stageId === 'scene_plan');
const selected = proposal.artifacts.find((artifact) => artifact.id === 'selected_direction');
const tasks = assets.artifacts.find((artifact) => artifact.id === 'generation_tasks')?.payload?.tasks;
const captions = sample.artifacts.find((artifact) => artifact.id === 'captions_voice')?.payload?.shots?.[0];
const plan = scene.artifacts.find((artifact) => artifact.id === 'shot_plan')?.payload?.shots?.[0];
console.log(JSON.stringify({{
  selectedPayload: selected?.payload,
  selectedSummary: selected?.summary,
  taskStatus: tasks?.[0]?.status_label,
  taskOutput: tasks?.[0]?.output_url,
  taskCost: tasks?.[0]?.actual_cost_usd,
  taskSelected: tasks?.[0]?.selected,
  plannedNarration: captions?.planned_narration,
  actualNarration: captions?.actual_narration,
  referencePreview: plan?.reference_evidence?.preview_url,
  sourcePreview: plan?.preview_url,
  urlsDistinct: plan?.reference_evidence?.preview_url != null
    && plan?.reference_evidence?.preview_url !== plan?.preview_url,
}}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=repo_root, check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)
    assert result["selectedPayload"] is None
    assert result["selectedSummary"] == "尚未选定方向"
    assert result["taskStatus"] == "已完成"
    assert result["taskOutput"] == "/media/table-mat/assets/gen/shot-1.mp4"
    assert result["taskCost"] == 0.08
    assert result["taskSelected"] is True
    assert result["plannedNarration"] == "计划口播"
    assert result["actualNarration"] is None
    assert result["urlsDistinct"] is True


def test_sample_qa_status_merges_evaluation_failures() -> None:
    """P1-1 回归：文件检查 pass 但内容评价 revise/硬门失败时，qa_status 归约为需要调整。"""
    from backlot.operator_state import project_operator_state, validate_operator_state

    board = _board_state()
    board["artifacts"]["sample_report"]["status"] = "pass"
    board["artifacts"]["evaluation_report.sample"] = {
        "scope": "sample", "status": "revise", "recommended_action": "repair",
        "hard_gate": {"checks": [
            {"id": "c1", "name": "字幕可读性", "status": "fail", "severity": "fatal",
             "message": "字幕遮挡动作结果", "fixable": True},
        ]},
        "creative_advisory": {"scored": True, "summary": "需要修改字幕", "dimensions": []},
    }

    state = project_operator_state(board)
    sample = next(stage for stage in state["stages"] if stage["id"] == "sample")
    data = sample["editor"]["data"]
    assert data["qa_status"] == "需要调整"
    assert data["review_summary"] == "样片尚有需要调整的检查项"
    assert data["evaluation"]["hard_gate_fails"][0]["name"] == "字幕可读性"
    validate_operator_state(state)


def test_compose_qa_status_merges_final_evaluation_failures() -> None:
    """P1-1 回归：成片文件检查 pass 但 final 评价 fail 时，qa_status 归约为需要调整。"""
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["artifacts"]["render_report"] = {
        "outputs": [{"path": "projects/table-mat/renders/final.mp4", "duration_seconds": 16}],
    }
    board["artifacts"]["final_review"] = {"status": "pass"}
    board["artifacts"]["evaluation_report.final"] = {
        "scope": "final", "status": "fail", "recommended_action": "reject",
        "hard_gate": {"checks": [
            {"id": "c1", "name": "响度", "status": "fail", "severity": "fatal",
             "message": "响度超标", "fixable": False},
        ]},
        "creative_advisory": {"scored": True, "summary": "不可发布", "dimensions": []},
    }

    state = project_operator_state(board)
    compose = next(stage for stage in state["stages"] if stage["id"] == "compose")
    data = compose["editor"]["data"]
    assert data["qa_status"] == "需要调整"
    assert data["evaluation"]["recommended_action"] == "reject"


def test_original_sound_state_is_presence_based_not_planned() -> None:
    """P1-4 回归：原声状态独立于「是否计划」；缺失信号为 unknown，不默认成 True。"""
    from backlot.operator_state import _audio_tracks

    with_sound = _audio_tracks({"audio_diff": {
        "plan": {"narration_planned": True, "music_planned": True},
        "actual": {"narration_present": True, "music_present": True, "original_sound": True},
    }})
    original = next(track for track in with_sound if track["kind"] == "original")
    assert original["state"] == "present"

    without_signal = _audio_tracks({"audio_diff": {
        "plan": {"narration_planned": True, "music_planned": True},
        "actual": {"narration_present": True, "music_present": True},
    }})
    original = next(track for track in without_signal if track["kind"] == "original")
    assert original["state"] == "unknown"
    assert original["present"] is False


def test_source_label_prefers_file_name_over_media_id_hash() -> None:
    """P2-7 回归：素材名优先用原始文件名，media_id 哈希不进业务标题。"""
    from backlot.operator_state import project_operator_state

    board = _board_state()
    files = board["artifacts"]["source_media_review"]["files"]
    files[0]["media_id"] = "2f9213d9132ae3f7aabbccdd"
    files[0]["path"] = "projects/table-mat/inputs/source/防油擦拭-近景.mp4"

    state = project_operator_state(board)
    research = next(stage for stage in state["stages"] if stage["id"] == "research")
    sources = research["editor"]["data"]["sources"]
    assert sources[0]["label"] == "防油擦拭-近景"
    assert sources[0]["id"] == "2f9213d9132ae3f7aabbccdd"


def test_missing_render_file_never_reports_qa_pass(tmp_path: Path) -> None:
    """P1-4 回归：报告 pass 但样片/成片文件缺失时，qa 归约为需要调整且不提供预览。"""
    from backlot.operator_state import project_operator_state

    board = _board_state()
    board["_project_dir"] = tmp_path
    board["artifacts"]["sample_report"]["status"] = "pass"
    # renders/sample.mp4 并不存在于 tmp_path：必须归约为需要调整。
    state = project_operator_state(board)
    sample = next(stage for stage in state["stages"] if stage["id"] == "sample")
    data = sample["editor"]["data"]
    assert data["qa_status"] == "需要调整"
    assert data["preview_url"] is None

    # 成片：render_report 输出路径不存在 → 需要调整、无下载地址。
    board["artifacts"]["render_report"] = {
        "outputs": [{"path": "renders/final.mp4", "duration_seconds": 16}],
    }
    board["artifacts"]["final_review"] = {"status": "pass"}
    state = project_operator_state(board)
    compose = next(stage for stage in state["stages"] if stage["id"] == "compose")
    compose_data = compose["editor"]["data"]
    assert compose_data["qa_status"] == "需要调整"
    assert compose_data["download_url"] is None
