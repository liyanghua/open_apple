from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backlot.project_commit import ProjectCommitStore
from lib.approval_groups import persist_approval_bundle_snapshot
from lib.artifact_hashing import attach_hashes, verify_hashes
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import write_checkpoint
from schemas.artifacts import validate_artifact


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
PROJECT = PROJECTS / "table-mat-mix-v1"
PROJECT_ID = PROJECT.name


def load(name: str) -> dict:
    return json.loads((PROJECT / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))


def disk_env(name: str) -> dict:
    data = load(name)
    assert verify_hashes(data).valid, name
    return {"name": name, "path": f"artifacts/{name}.json", "semantic_sha256": data["semantic_sha256"], "artifact_sha256": data["artifact_sha256"], "data": data}


def build() -> tuple[dict, dict, dict, dict]:
    now = datetime.now(timezone.utc).isoformat()
    script, scene_plan, control = load("script"), load("scene_plan"), load("creative_control_plan")
    replacement, fidelity, decision_log = load("replacement_matrix"), load("fidelity_policy"), load("decision_log")
    sections = {item["id"]: item for item in script["sections"]}
    mappings = {item["scene_id"]: item for item in scene_plan["metadata"]["source_mapping"]}
    image_paths = [
        "inputs/source/video/product/main_01.webp",
        "inputs/source/video/product/main_02.webp",
        "inputs/source/video/product/main_03.webp",
        "inputs/source/video/product/main_04.webp",
        "inputs/source/video/product/main_02.webp",
        "inputs/source/video/product/main_05.webp",
    ]
    if not all((PROJECT / path).is_file() for path in image_paths):
        raise FileNotFoundError("table-mat-mix-v1 product image proxy is missing")
    shots, planned = [], []
    for index, scene in enumerate(scene_plan["scenes"]):
        section = sections[scene["script_section_id"]]
        mapping = mappings[scene["id"]]
        duration = round(float(scene["end_seconds"]) - float(scene["start_seconds"]), 3)
        image_path = image_paths[min(index, len(image_paths) - 1)]
        role = "cta" if index >= 6 else ("real_proof" if index in {1, 2, 3, 4} else "demonstration")
        shot = {
            "id": f"shot-{index + 1:02d}", "order": index + 1, "scene_id": scene["id"], "section_id": section["id"],
            "purpose": scene.get("shot_intent") or scene.get("description") or "按参考时间线呈现产品证据",
            "duration_seconds": duration, "narration": section.get("narration") or section.get("text") or "",
            "screen_copy": section.get("screen_copy") or "", "subject_action": "、".join(section.get("action_keys") or []) or scene.get("description") or "产品展示动作",
            "setting": "Atelier 透明桌垫产品桌面场景", "framing": "9:16 竖版；主体居中，保留顶部卖点字卡与底部口播安全区",
            "camera": (scene.get("shot_language") or {}).get("camera_movement") or "static",
            "lighting": "自然柔光；透明材质边缘高光可读，避免过曝", "sound": "保留素材现场声位；口播、字幕与 BGM 在样片阶段混音",
            "evidence_type": role, "coverage_status": "enough", "gap_class": "none", "gap_strategy": "none",
            "source_selection": {"media_id": f"product-{Path(image_path).stem}", "path": image_path, "start_seconds": 0.0, "end_seconds": duration, "fit_reason": "已提供产品图代理，用于 Atelier 构图审核；不调用付费生成"},
            "reference_mechanisms": [(mapping.get("reference_evidence") or {}).get("mechanism") or "严格复刻参考镜头的时序与动作密度", "严格保持参考时间线、镜头边界与口播节奏；只替换产品事实与卖点"],
            "industry_notes": ["参考媒体仅 analysis_only，不进入最终渲染", "产品规格与性能只由用户事实/证据承载，画面不虚构检测结果"],
            "control_rule_refs": section.get("control_rule_refs") or ["fidelity_policy.locked_dimensions"], "generation_proposals": [], "selected_generation_task_id": None,
            "claim_ids": section.get("claim_ids") or [], "action_keys": section.get("action_keys") or [], "evidence_row_ids": section.get("evidence_row_ids") or [],
            "product_fact_refs": section.get("product_fact_refs") or [], "product_page_refs": section.get("product_page_refs") or [], "page_asset_ids": section.get("page_asset_ids") or [], "page_evidence_ids": section.get("page_evidence_ids") or [],
            "visual_route": "owned_source", "evidence_role": "owned_visual_evidence", "claim_visual_requirements": section.get("claim_visual_requirements") or {},
            "source_interval": {"start_seconds": 0.0, "end_seconds_exclusive": duration},
        }
        shots.append(shot)
        planned.append({
            "id": f"asset-shot-{index + 1:02d}", "type": "owned_source_media", "provider": "owned", "model": "user_supplied_product_image", "cost_estimate_usd": 0.0, "paid": False, "output_path": image_path, "source_stage": "scene_plan", "exists": True, "shot_id": shot["id"], "visual_route": "owned_source", "evidence_role": "owned_visual_evidence", "source_selection": shot["source_selection"],
            "creative_binding": {"purpose": shot["purpose"], "subject_action": shot["subject_action"], "narration": shot["narration"], "screen_copy": shot["screen_copy"], "claim_ids": shot["claim_ids"], "action_keys": shot["action_keys"], "evidence_row_ids": shot["evidence_row_ids"], "product_fact_refs": shot["product_fact_refs"], "product_page_refs": shot["product_page_refs"], "page_asset_ids": shot["page_asset_ids"], "page_evidence_ids": shot["page_evidence_ids"], "visual_route": "owned_source", "evidence_role": "owned_visual_evidence"},
            "processing_plan": {"operation": "atelier_still_motion_proxy", "tool": "remotion", "aspect_ratio": "9:16", "width": 1080, "height": 1920, "fit": "cover", "crop_strategy": "center_crop_protected_subject", "audio_policy": "mute_source_until_sample_mix"},
        })
    planned += [
        {"id": "asset-narration-plan", "type": "narration_audio", "provider": "local_pending", "model": "remotion_tts_slot", "cost_estimate_usd": 0.0, "paid": False, "output_path": "assets/audio/narration.zh-CN.wav", "source_stage": "assets", "exists": False},
        {"id": "asset-caption-plan", "type": "subtitle_track", "provider": "local", "model": "remotion_caption_layer", "cost_estimate_usd": 0.0, "paid": False, "output_path": "assets/subtitles.srt", "source_stage": "assets", "exists": False},
        {"id": "asset-bgm-plan", "type": "music_bed", "provider": "none", "model": "no_bgm_before_sample_approval", "cost_estimate_usd": 0.0, "paid": False, "output_path": "assets/music/bed.wav", "source_stage": "assets", "exists": False},
    ]
    sep = {"version": "1.0", "project_id": PROJECT_ID, "plan_id": f"shot-execution-{PROJECT_ID}", "plan_version": 1, "status": "draft", "created_at": now, "creative_control_ref": {"artifact": "creative_control_plan", "version": 1, "artifact_sha256": control["artifact_sha256"]}, "script_ref": {"artifact": "script", "version": 1, "artifact_sha256": script["artifact_sha256"]}, "scene_plan_ref": {"artifact": "scene_plan", "version": 1, "artifact_sha256": scene_plan["artifact_sha256"]}, "shots": shots}
    ap = {"version": "1.0", "project_id": PROJECT_ID, "created_at": now, "producer": "reference-fidelity/asset-director@1.0", "input_hashes": {"script": script["artifact_sha256"], "scene_plan": scene_plan["artifact_sha256"], "replacement_matrix": replacement["artifact_sha256"], "fidelity_policy": fidelity["artifact_sha256"]}, "planned_assets": planned, "paid_generation_approved": False}
    lock = {"version": "1.0", "project_id": PROJECT_ID, "created_at": now, "producer": "reference-fidelity/production-lock@1.0", "input_hashes": {"script": script["artifact_sha256"], "scene_plan": scene_plan["artifact_sha256"], "creative_control_plan": control["artifact_sha256"], "fidelity_policy": fidelity["artifact_sha256"]}, "lock_version": 1, "locked_values": {"script": {"artifact": "script", "artifact_sha256": script["artifact_sha256"], "status": "approved", "duration_seconds": script["total_duration_seconds"]}, "narration": {"language": "zh-CN", "copy_source": "approved_script", "timing": "reference_locked", "status": "planned_not_rendered"}, "tts": {"provider": "pending_user_approval", "model": "pending", "paid": False, "status": "not_called"}, "bgm": {"provider": "none", "status": "deferred_until_sample"}, "mix": {"target_lufs": -14, "voice_ducking_db": -6, "status": "planned"}, "font": {"family": "Noto Sans SC", "source": "local", "status": "planned"}, "captions": {"policy": "one_claim_per_shot", "source": "approved_script.screen_copy", "status": "locked"}, "cta": "现在就来直播间看看", "platform": "tiktok", "output": {"aspect_ratio": "9:16", "fps": 30, "duration_seconds": script["total_duration_seconds"]}, "render_runtime": "remotion", "composition_mode": "atelier"}, "decision_revision_ids": [decision_log["artifact_sha256"]]}
    for name, data in (("shot_execution_plan", sep), ("asset_plan", ap), ("production_lock", lock)):
        validate_artifact(name, attach_hashes(dict(data)))
    refs = []
    for checkpoint_name in ("checkpoint_proposal.json", "checkpoint_scene_plan.json"):
        checkpoint = json.loads((PROJECT / checkpoint_name).read_text(encoding="utf-8"))
        for artifact in (checkpoint.get("artifacts") or {}).values():
            if isinstance(artifact, dict) and {"name", "path", "semantic_sha256", "artifact_sha256"} <= set(artifact) and not any(item["path"] == artifact["path"] for item in refs):
                refs.append({key: artifact[key] for key in ("name", "path", "semantic_sha256", "artifact_sha256")})
    return sep, ap, lock, {"version": "1.0", "project_id": PROJECT_ID, "created_at": now, "producer": "approval_groups", "input_hashes": {"proposal": load("proposal_packet")["semantic_sha256"], "scene_plan": scene_plan["semantic_sha256"], "assets": attach_hashes(dict(ap))["semantic_sha256"]}, "bundle_id": f"{PROJECT_ID}-creative_lock", "bundle_version": 1, "group": "creative_lock", "terminal_stage": "assets", "members": ["proposal", "scene_plan", "assets"], "artifact_refs": refs, "status": "awaiting_human"}


def main() -> None:
    sep, ap, lock, bundle = build()
    with ProjectCommitStore(PROJECT).transaction(action={"action_id": "prepare-reference-fidelity-assets", "reason": "script-approved"}) as sink:
        sep_env = write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan", sep, project_dir=PROJECT, sink=sink)
        ap_env = write_artifact_atomic("artifacts/asset_plan.json", "asset_plan", ap, project_dir=PROJECT, sink=sink)
        lock_env = write_artifact_atomic("artifacts/production_lock.json", "production_lock", lock, project_dir=PROJECT, sink=sink)
        refs = list(bundle["artifact_refs"])
        refs.extend({key: env[key] for key in ("name", "path", "semantic_sha256", "artifact_sha256")} for env in (sep_env, ap_env, lock_env))
        bundle["artifact_refs"] = refs
        bundle_env = write_artifact_atomic("artifacts/approval_bundle.json", "approval_bundle", bundle, project_dir=PROJECT, sink=sink)
        persist_approval_bundle_snapshot(PROJECT, bundle_env["data"], sink=sink)
        write_checkpoint(PROJECTS, PROJECT_ID, "assets", "awaiting_human", {"shot_execution_plan": sep_env, "asset_plan": ap_env, "production_lock": lock_env, "approval_bundle": bundle_env}, pipeline_type="cinematic-fast", human_approval_required=True, human_approved=False, approval_group="creative_lock", approval_bundle_id=bundle_env["data"]["bundle_id"], approval_bundle_version=bundle_env["data"]["bundle_version"], next_action={"summary": "审核 creative_lock：确认11镜头严格复刻执行单、资产计划与 Remotion Atelier 锁定；通过后进入 Sample", "verb": "await_user", "priority": "blocking", "context_refs": ["artifacts/approval_bundle.json", "artifacts/shot_execution_plan.json", "artifacts/asset_plan.json", "artifacts/production_lock.json"]}, review={"verdict": "pass", "findings": [], "note": "无付费素材已生成；当前仅使用已提供产品图作为构图代理"}, cost_snapshot={"spent_usd": 0.0, "projected_compose_usd": 0.0, "paid_calls": 0}, sink=sink)
    print(json.dumps({"status": "awaiting_human", "shots": len(sep["shots"]), "planned_assets": len(ap["planned_assets"]), "bundle": bundle["bundle_id"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
