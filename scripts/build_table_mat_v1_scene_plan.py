from __future__ import annotations

import json
from pathlib import Path

from lib.artifact_io import write_artifact_atomic
from backlot.project_commit import ProjectCommitStore
from schemas.artifacts import validate_artifact


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "table-mat-mix-v1"
ARTIFACTS = PROJECT / "artifacts"


def load(name: str) -> dict:
    return json.loads((ARTIFACTS / name).read_text(encoding="utf-8"))


def build() -> dict:
    script = load("script.json")
    matrix = {row["matrix_row_id"]: row for row in load("reference_source_matrix.json")["rows"]}
    source_review = load("source_media_review.json")
    sources = {item["media_id"]: item for item in source_review["files"]}
    reference_timeline = load("reference_timeline.json")["shots"]
    creative = load("creative_control_plan.json")
    creative_sha = creative["artifact_sha256"]

    source_by_row = {
        "matrix-01": ("0757a4784647644c", 0.0, 3.9, "direction-proof-chain"),
        "matrix-02": ("aa1712278fe76e69", 1.2, 5.75, "direction-proof-chain"),
        "matrix-03": ("ad38ded3aa91a164", 1.3, 6.7, "direction-proof-chain"),
        "matrix-04": ("6c9a821063ba05af", 3.2, 10.8, "direction-proof-chain"),
        "matrix-05": ("aa1712278fe76e69", 2.4, 6.8, "direction-proof-chain"),
        "matrix-06": ("114ffcd6f7c246bd", 0.0, 7.51, "direction-proof-chain"),
        # CTA has no accepted source row; the owned restaurant shot is only a
        # visual bed for an original Atelier end card.
        "matrix-07": ("114ffcd6f7c246bd", 4.7, 6.6, "direction-life-table"),
    }
    shot_roles = [
        ("hook", "introduce_subject", "铺开动作首帧就交代透明桌垫与桌面关系", "hook", "action_match"),
        ("reveal", "evidence", "用桌角近景证明贴合与透度，不让字幕盖住边缘", "reveal", "action_match"),
        ("evidence", "evidence", "让硬物刮擦和透明垫面结果在同一时间槽内可读", "proof", "proof"),
        ("evidence", "build_tension", "先保留油污落点，再把擦拭结果交给下一镜完成", "proof", "proof"),
        ("evidence", "evidence", "用按压不变形承接久用不发黄与质保2年的可信表达", "proof", "action_match"),
        ("payoff", "resolution", "回到真实餐桌，让透明、无味、安全的结果有生活场景", "label", "soft"),
        ("cta", "call_to_action", "在生活画面上叠加原创行动提示，不复制参考身份信息", "label", "soft"),
        ("cta", "call_to_action", "用原创品牌短句完成一次短停留，维持参考收尾密度", "label", "soft"),
        ("cta", "call_to_action", "用证据回顾短句收束，不引入参考片原文案", "label", "soft"),
        ("cta", "call_to_action", "保持最后两拍的搜索型节奏，但视觉完全 Atelier 重写", "label", "soft"),
        ("cta", "call_to_action", "最后一帧停在透明桌垫与原创 CTA，给口播完整落点", "label", "soft"),
    ]
    descriptions = [
        "透明桌垫自动铺开，木纹与产品边缘同时进入画面。",
        "桌角对齐并按压边缘，透明材质和贴合状态被压到近景。",
        "硬物在透明垫面上刮擦，接触点与无明显损伤结果清楚。",
        "油污落在垫面并形成可见边界，画面为下一拍擦拭结果蓄力。",
        "手部按压垫面，释放后保持平整，以柔韧不变形替代无证据回弹。",
        "明亮家庭餐桌、餐具、木纹和透明垫面同框，作为生活化 payoff。",
        "餐桌画面上出现原创 CTA：请到直播间看看，避开产品动作安全区。",
        "原创短句‘透明桌垫，保护每一餐’短停留，背景继续保留餐桌实景。",
        "原创短句‘实拍证明，细节可见’与产品高光同步出现。",
        "原创短句‘现在就来直播间看看’完成行动提示，不使用参考账号或搜索词。",
        "最终定格‘透明桌垫，给桌面多一层保护’，留出完整口播尾音。",
    ]
    source_fit = {
        "matrix-01": "自有自动铺开素材能在首帧给出产品、桌面和动作结果。",
        "matrix-02": "自有桌角对齐素材含按压与边缘贴合证据。",
        "matrix-03": "自有防刮素材含硬物接触动作和透明垫面结果。",
        "matrix-04": "自有防油素材同时覆盖落液、擦拭和清洁后结果。",
        "matrix-05": "自有桌角素材可证明按压后不变形，不能夸大为回弹。",
        "matrix-06": "自有餐桌素材能让木纹、餐具和透明垫面共同可见。",
        "matrix-07": "自有餐桌素材仅作原创 CTA 背景，不承担参考品牌身份。",
    }

    scenes: list[dict] = []
    mappings: list[dict] = []
    for index, section in enumerate(script["sections"]):
        ref = reference_timeline[index]
        section_id = section["id"]
        row_id = section["evidence_row_ids"][0]
        media_id, source_start, source_end, direction = source_by_row[row_id]
        source = sources[media_id]
        role, narrative, intent, caption_intent, transition_intent = shot_roles[index]
        is_cta = index >= 6
        direct = index < 9
        duration_drift_ms = round((section["end_seconds"] - section["start_seconds"] - (ref["end_seconds_exclusive"] - ref["start_seconds"])) * 1000)
        caption_id = f"source-caption-{index + 1:02d}-none-visible"
        overlay_id = f"overlay-{index + 1:02d}"
        scene = {
            "id": f"reference-shot-{index + 1}",
            "type": "broll" if not is_cta else "text_card",
            "description": descriptions[index],
            "start_seconds": section["start_seconds"],
            "end_seconds": section["end_seconds"],
            "script_section_id": section_id,
            "claim_ids": section["claim_ids"],
            "action_keys": section["action_keys"],
            "evidence_row_ids": section["evidence_row_ids"],
            "product_fact_refs": section.get("product_fact_refs", []),
            "visual_route": "owned_source",
            "claim_visual_requirements": section["claim_visual_requirements"],
            "framing": "9:16 vertical crop; protect the action/result area and reserve the upper safe zone for original overlay text.",
            "movement": "source playback at 1.0x; hard action cut" if not is_cta else "subtle Atelier push-in over owned restaurant footage",
            "transition_in": "hard_start" if index == 0 else ("action_match" if not is_cta else "soft_cut"),
            "transition_out": "action_cut" if index < 6 else "soft_cut",
            "transition_recipe_intent": transition_intent,
            "caption_recipe_intent": caption_intent,
            "caption_treatment": "animated" if not is_cta else "static",
            "caption_intent_derived_from": "shot_intent",
            "caption_fallback_used": False,
            "overlay_notes": f"原创 overlay {section['screen_copy']}，避开主体动作和结果；禁止参考字幕、品牌、水印和账号信息。",
            "shot_language": {
                "shot_size": ["wide", "close_up", "extreme_close_up", "close_up", "close_up", "wide", "medium", "medium", "close_up", "medium", "medium"][index],
                "camera_movement": ["steadicam", "static", "static", "static", "tracking_right", "dolly_out", "static", "dolly_in", "rack_focus", "dolly_in", "static"][index],
                "lens_mm": [35, 50, 50, 50, 50, 35, 50, 50, 85, 50, 50][index],
                "lighting_key": "natural" if not is_cta else "overcast_soft",
                "depth_of_field": "medium" if index < 6 else "shallow",
                "color_temperature": "warm" if index < 6 else "neutral",
            },
            "shot_intent": intent,
            "narrative_role": narrative,
            "information_role": section["screen_copy"],
            "hero_moment": index in {0, 2, 3, 4},
            "texture_keywords": ["transparent edge highlight", "real product proof", "warm wood", "atelier typography"],
            "required_assets": [{
                "type": "video",
                "description": f"{source['path']} [{source_start},{source_end})；参考视频仅用于分析",
                "source": "source",
            }],
            "caption_policy_version": "1.0",
            "caption_inventory_refs": [caption_id],
            "caption_treatments": [{
                "caption_id": caption_id,
                "action": "replace",
                "review": "approved",
                "interval": {"start_seconds": section["start_seconds"], "end_seconds": section["end_seconds"]},
                "reason": "自有源片未登记可保留字幕；使用本片原创卖点字卡，绝不带入参考字幕。",
                "replacement_overlay_id": overlay_id,
            }],
            "overlay_layers": [{
                "overlay_id": overlay_id,
                "text": section["screen_copy"],
                "source": "generated_overlay",
                "start_seconds": section["start_seconds"],
                "end_seconds": section["end_seconds"],
                "review": "approved",
            }],
        }
        scenes.append(scene)

        if direct:
            reference_evidence = {
                "mode": "direct_segment",
                "reference_scene_id": f"reference-{index + 1}",
                "reference_interval": {"start_seconds": ref["start_seconds"], "end_seconds_exclusive": ref["end_seconds_exclusive"]},
                "mechanism": "保留参考片动作先行、短节奏、动作结果成对的组织机制。",
                "rationale": f"该机制服务于‘{intent}’，但画面主体、文案、字幕和素材均替换为自有产品。",
            }
        else:
            reference_evidence = {
                "mode": "structural_only",
                "mechanism": "借鉴参考片 CTA 的短停留与连续口播节奏，不复制品牌身份视觉。",
                "rationale": "参考后段没有可直接解析的独立镜头证据；只迁移收束节奏，视觉完全原创。",
            }
        mappings.append({
            "scene_id": scene["id"],
            "reference_shot_id": ref["reference_shot_id"],
            "script_section_id": section_id,
            "claim_ids": section["claim_ids"],
            "action_keys": section["action_keys"],
            "evidence_row_ids": section["evidence_row_ids"],
            "product_fact_refs": section.get("product_fact_refs", []),
            "visual_route": "owned_source",
            "claim_visual_requirements": section["claim_visual_requirements"],
            "reference_evidence": reference_evidence,
            "source_path": source["path"],
            "source_interval": {"start_seconds": source_start, "end_seconds_exclusive": source_end},
            "timeline_interval": {"start_seconds": section["start_seconds"], "end_seconds_exclusive": section["end_seconds"]},
            "duration_drift_ms": duration_drift_ms,
            "reference_basis": "动作先行、连续证明、生活化收束；CTA 仅保留节奏机制。",
            "source_fit": source_fit[row_id],
            "mapping_reason": f"用已审核的自有素材支撑‘{intent}’，并把‘{section['screen_copy']}’限定在本镜。",
            "originality_note": "参考视频只用于分析；成片不含参考路径、画面、字幕、品牌、水印、账号或音乐。",
            "matrix_row_id": row_id,
            "matrix_resolution_id": matrix[row_id]["resolution"],
            "replacement_matrix_row_id": row_id,
            "research_direction_ref": direction,
            "subject_completeness": "complete",
            "crop_strategy": "center crop with protected subject bounds",
            "caption_safe_zone": "top safe zone; bottom reserved for narration captions",
        })

    plan = {
        "version": "1.0",
        "creative_control_ref": {"plan_id": creative["plan_id"], "plan_version": creative["plan_version"], "artifact_sha256": creative_sha},
        "caption_policy_version": "1.0",
        "style_playbook": "atelier-transparent-proof-chain",
        "scenes": scenes,
        "metadata": {
            "project_id": "table-mat-mix-v1",
            "input_mode": "reference_fidelity",
            "reference_media_usage": "analysis_only",
            "render_runtime": "remotion",
            "composition_mode": "atelier",
            "reference_alignment": {"fps": 30.0, "target_duration_seconds": 12.445918, "max_duration_drift_ms": 0, "timing_policy": "copy reference half-open intervals; narration follows approved script slots"},
            "hero_frames": ["reference-shot-1", "reference-shot-3", "reference-shot-4", "reference-shot-11"],
            "transition_rules": "仅使用 hard_start、action_match、soft_cut；不使用装饰性转场。",
            "aspect_ratio_rules": "9:16；动作区域和底部口播字幕均保持安全区。",
            "originality_boundary": "参考媒体仅分析；所有可渲染 source_path 均来自 reviewed owned source；CTA 身份和文字原创。",
            "source_mapping": mappings,
        },
    }
    validate_artifact("scene_plan", plan)
    return plan


if __name__ == "__main__":
    payload = build()
    with ProjectCommitStore(PROJECT).transaction(
        action={"action_id": "build-table-mat-v1-scene-plan"},
        business_diff=["生成 table-mat-mix-v1 严格复刻 scene_plan"],
    ) as sink:
        envelope = write_artifact_atomic(
            "artifacts/scene_plan.json",
            "scene_plan",
            payload,
            project_dir=PROJECT,
            sink=sink,
        )
    print(json.dumps({"artifact_sha256": envelope["artifact_sha256"], "scene_count": len(payload["scenes"]), "duration": payload["scenes"][-1]["end_seconds"]}, ensure_ascii=False))
