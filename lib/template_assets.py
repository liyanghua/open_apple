"""模板 run 的 assets 阶段制品构建（shot_execution_plan / asset_plan / production_lock / approval_bundle）。

只产出**待审批**的资产计划，**不调用任何付费 provider**（paid_generation_approved=False）。
每个 scene 的 source 已由 scene_plan 的 source_mapping 落到 owned source；若全部 owned →
gap_strategy=none、coverage=enough、generation_proposals=[]；否则标 gap 并为缺口生成 proposal。

走主链路：由 `checkpoint.get_next_stage` 推进到 assets 后，调用本模块产制品 + `write_checkpoint`
写 `awaiting_human`（creative_lock terminal gate），等人工批准才进 paid assets。
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib.artifact_io import write_artifact_atomic
from lib.template_mainline import _load, scene_plan_data
from lib.template_run_plan import check_template_run_plan_ready
from lib.template_batch import resolve_run_batch_differentiation_ref
from schemas.artifacts import validate_artifact

PIPELINE = "cinematic-fast"


def _content_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _discover_i2v_provider_candidates(
    *, duration_seconds: float, reference_path: str
) -> list[dict[str, Any]]:
    """Return currently available native/local 3:4 image-to-video choices.

    Discovery and cost estimation are read-only.  This is a shortlist for the
    Assets gate, not a provider selection and never a generation call.
    """
    from tools.tool_registry import registry

    registry.discover()
    duration = max(4, min(15, int(math.ceil(duration_seconds))))
    candidates: list[dict[str, Any]] = []
    for tool in registry.get_by_capability("video_generation"):
        info = tool.get_info()
        supports = info.get("supports") or {}
        supports_i2v = (
            supports.get("image_to_video") is True
            if isinstance(supports, Mapping)
            else "image_to_video" in supports
        )
        if info.get("status") != "available" or not supports_i2v:
            continue
        input_schema = info.get("input_schema") or {}
        properties = input_schema.get("properties") or {}
        aspect_ratios = (properties.get("aspect_ratio") or {}).get("enum") or []
        supports_three_four = "3:4" in aspect_ratios
        supports_local = (
            "image_path" in properties
            or "reference_image_paths" in properties
            or (isinstance(supports, Mapping) and supports.get("local_image_data_uri") is True)
        )
        if not supports_three_four or not supports_local:
            continue
        model_spec = properties.get("model_variant") or properties.get("model") or {}
        model = str(model_spec.get("default") or "provider_default")
        estimate_inputs = {
            "prompt": "product identity preserving image-to-video shot",
            "operation": "image_to_video",
            "duration": duration,
            "aspect_ratio": "3:4",
            "resolution": "1080p",
            "image_path": reference_path,
        }
        try:
            estimated_cost = float(tool.estimate_cost(estimate_inputs))
        except (TypeError, ValueError, RuntimeError):
            estimated_cost = None
        candidates.append({
            "tool": str(info.get("name") or getattr(tool, "name", "")),
            "provider": str(info.get("provider") or "unknown"),
            "model": model,
            "estimated_cost_usd": estimated_cost,
            "supports_local_reference": supports_local,
            "supports_native_3_4": supports_three_four,
        })
    candidates.sort(key=lambda item: (
        item["estimated_cost_usd"] is None,
        item["estimated_cost_usd"] if item["estimated_cost_usd"] is not None else 0,
        item["tool"],
    ))
    return candidates


def _owned_path_tail(project_path: str) -> str:
    """把 `projects/<proj>/inputs/source/...` 归一成 `inputs/source/...`（schema pattern）。"""
    normalized = str(project_path).replace("\\", "/")
    if normalized.startswith("inputs/source/"):
        return normalized
    marker = "/inputs/source/"
    idx = normalized.find(marker)
    return normalized[idx + 1:] if idx >= 0 else "inputs/source/video/product/unknown.mp4"


def _project_target_platform(project: Path) -> str:
    marker = _load(project / "project.json") or {}
    product_input = marker.get("product_input") or {}
    configured = str(product_input.get("target_platform") or "").strip().lower()
    if configured:
        return configured
    product_url = str(product_input.get("product_url") or "").lower()
    if "tmall.com" in product_url or "taobao.com" in product_url:
        return "taobao"

    proposal = _load(project / "artifacts" / "proposal_packet.json") or {}
    selected_id = str((proposal.get("selected_concept") or {}).get("concept_id") or "")
    selected = next(
        (item for item in (proposal.get("concept_options") or [])
         if str(item.get("id") or "") == selected_id),
        {},
    )
    return str(selected.get("target_platform") or "tiktok").strip().lower()


def _resolved_output_profile(project: Path, requested: str | None) -> str:
    if requested:
        return requested
    if _project_target_platform(project) == "taobao":
        return "social_vertical_3_4_2160p30"
    return "social_vertical_1080p30"


def _selected_cta(project: Path, platform: str) -> str:
    marker = _load(project / "project.json") or {}
    configured = str((marker.get("product_input") or {}).get("cta") or "").strip()
    if configured:
        return configured

    proposal = _load(project / "artifacts" / "proposal_packet.json") or {}
    selected_id = str((proposal.get("selected_concept") or {}).get("concept_id") or "")
    selected = next(
        (item for item in (proposal.get("concept_options") or [])
         if str(item.get("id") or "") == selected_id),
        {},
    )
    selected_cta = str(selected.get("cta") or "").strip()
    if selected_cta:
        return selected_cta
    return "查看商品详情" if platform == "taobao" else "查看详情"


def build_shot_execution_plan(
    project: Path,
    template: dict,
    sp: dict,
    ccp: dict,
    script: dict,
    *,
    output_profile: str | None = None,
    provider_candidates: list[dict[str, Any]] | None = None,
) -> dict:
    plan_id = str(template.get("template_id") or "")
    resolved_profile = _resolved_output_profile(project, output_profile)
    framing = (
        "3:4 中景/近景，中心裁切并保护产品主体与动作结果"
        if "3_4" in resolved_profile
        else "9:16 中景/近景，产品主体与动作结果可读"
    )
    # 键控配对（评审 P0-1）：scene/slot/section 全部按显式引用。
    slots_by_id = {str(s.get("slot_id") or ""): s for s in (template.get("slots") or [])}
    scenes_by_id = {str(s.get("id") or ""): s for s in (sp.get("scenes") or [])}
    sections_by_scene = {
        str(x.get("scene_id") or ""): x for x in (script.get("sections") or [])
        if isinstance(x, Mapping) and x.get("scene_id")
    }
    shots = []
    for i, m in enumerate(sp["metadata"]["source_mapping"], start=1):
        scene = scenes_by_id.get(str(m["scene_id"])) or {}
        slot = slots_by_id.get(str(m.get("template_slot_ref") or "")) or {}
        section = sections_by_scene.get(str(scene.get("id") or "")) or {}
        visual_route = str(m.get("visual_route") or "owned_source")
        is_generated = visual_route == "generated_from_product_image"
        source_tail = _owned_path_tail(m["source_path"]) if not is_generated else ""
        has_gap = is_generated or not m.get("matrix_row_id")
        evidence_fields = {
            "claim_ids": list(section.get("claim_ids") or m.get("claim_ids") or []),
            "action_keys": list(section.get("action_keys") or m.get("action_keys") or []),
            "evidence_row_ids": list(section.get("evidence_row_ids") or m.get("evidence_row_ids") or []),
            "product_fact_refs": list(section.get("product_fact_refs") or m.get("product_fact_refs") or []),
            "product_page_refs": list(section.get("product_page_refs") or m.get("product_page_refs") or []),
            "page_asset_ids": list(section.get("page_asset_ids") or m.get("page_asset_ids") or []),
            "page_evidence_ids": list(section.get("page_evidence_ids") or m.get("page_evidence_ids") or []),
        }
        narration = str(section.get("narration") or section.get("text") or "") if section else ""
        screen_copy = str(section.get("screen_copy") or "") if section else ""
        source_interval = None if is_generated else {
            "start_seconds": m["source_interval"]["start_seconds"],
            "end_seconds_exclusive": m["source_interval"]["end_seconds_exclusive"],
        }
        source_hash = str(m.get("source_hash") or "")
        canonical_evidence = (
            all(evidence_fields[field] for field in ("claim_ids", "action_keys", "evidence_row_ids", "product_fact_refs"))
            and (
                is_generated
                or (
                    len(source_hash) == 64
                    and all(ch in "0123456789abcdef" for ch in source_hash)
                )
            )
        )
        generation_reference = (
            dict(m["generation_reference"])
            if isinstance(m.get("generation_reference"), Mapping)
            else None
        )
        generation_proposals: list[dict[str, Any]] = []
        if is_generated:
            generation_spec = m.get("generation_spec")
            requirement = m.get("claim_visual_requirements")
            if not isinstance(generation_reference, Mapping) or not isinstance(generation_spec, Mapping):
                raise ValueError("generated shot requires generation_reference and generation_spec")
            if not isinstance(requirement, Mapping):
                raise ValueError("generated shot requires claim_visual_requirements")
            candidates = deepcopy(provider_candidates) if provider_candidates is not None else _discover_i2v_provider_candidates(
                duration_seconds=(
                    m["timeline_interval"]["end_seconds_exclusive"]
                    - m["timeline_interval"]["start_seconds"]
                ),
                reference_path=str(generation_reference.get("local_path") or ""),
            )
            if not candidates:
                raise ValueError("generated shot has no configured 3:4 local-reference image-to-video provider")
            duration = max(4, min(15, int(math.ceil(
                m["timeline_interval"]["end_seconds_exclusive"]
                - m["timeline_interval"]["start_seconds"]
            ))))
            required_actions = list(generation_spec.get("required_actions") or [])
            required_results = list(generation_spec.get("required_results") or [])
            prohibitions = list(dict.fromkeys([
                *[str(value) for value in requirement.get("forbidden_substitutions") or []],
                "不得新增文字或错误品牌标识",
                "不得改变商品颜色、纹理、结构或 SKU 身份",
                "不得把生成画面表现成检测或功效证明",
                "不得超出 3:4 产品主体安全区",
            ]))
            prompt = (
                "严格保持参考图中的商品身份、颜色、纹理和结构。"
                f"只执行动作：{'、'.join(required_actions)}。"
                f"必须出现结果：{'、'.join(required_results)}。"
                "淘宝 3:4 竖版产品镜头，主体和动作结果始终位于中心安全区；"
                "画面不得生成任何文字、额外包装或虚构检测场景。"
            )
            approval_subject_hash = _content_hash({
                "shot_id": f"shot-{i:02d}",
                "reference_hash": generation_reference.get("sha256"),
                "prompt": prompt,
                "provider_candidates": candidates,
                "duration_seconds": duration,
                "aspect_ratio": "3:4",
                "narration": narration,
                "screen_copy": screen_copy,
            })
            known_costs = [
                float(item["estimated_cost_usd"])
                for item in candidates
                if isinstance(item.get("estimated_cost_usd"), (int, float))
            ]
            generation_proposals.append({
                "id": f"generate-shot-{i:02d}",
                "operation": "image_to_video",
                "prompt": prompt,
                "provider_capability": "video_generation",
                "provider_candidates": candidates,
                "provider_selection_status": "awaiting_human",
                "duration_seconds": duration,
                "aspect_ratio": "3:4",
                "reference_paths": [str(generation_reference["local_path"])],
                "reference_asset_id": str(generation_reference["asset_id"]),
                "reference_hash": str(generation_reference["sha256"]),
                "required_actions": required_actions,
                "required_results": required_results,
                "consistency_requirements": [
                    "保持商品颜色、纹理、结构、品牌和 SKU 身份",
                    "主体与动作结果在 3:4 中心安全区完整可见",
                ],
                "prohibitions": prohibitions,
                "estimated_fast_cost_usd": min(known_costs) if known_costs else 0.0,
                "estimated_standard_cost_usd": max(known_costs) if known_costs else 0.0,
                "retry_limit": 2,
                "approval_subject_hash": approval_subject_hash,
                "evidence_risk": str(requirement.get("risk_level") or "medium"),
                "evidence_role": "visual_expression_only",
            })
        shot = {
            "id": f"shot-{i:02d}",
            "order": i,
            "scene_id": str(m["scene_id"]),
            "section_id": str(section.get("id") or ""),
            "template_slot_ref": str(m.get("template_slot_ref") or ""),
            "purpose": str(scene.get("description") or f"模板 slot {m.get('template_slot_ref')}"),
            "duration_seconds": round(m["timeline_interval"]["end_seconds_exclusive"] - m["timeline_interval"]["start_seconds"], 3),
            "narration": narration,
            "screen_copy": screen_copy,
            "subject_action": (
                "、".join(str(value) for value in (m.get("action_keys") or []))
                if is_generated else str(scene.get("description") or "")[:80]
            ),
            "setting": str(slot.get("scene") or "室内/桌面"),
            "framing": framing,
            "camera": str((scene.get("shot_language") or {}).get("camera_movement") or "static"),
            "lighting": "自然光，透明材质不过曝",
            "sound": "保留动作原始声；口播与 BGM 在样片混音层叠加",
            "evidence_type": (
                "demonstration"
                if is_generated
                else ("real_proof" if m.get("reference_evidence", {}).get("mode") != "none" else "demonstration")
            ),
            "coverage_status": ("gap" if has_gap else "enough"),
            "gap_class": ("expressive" if is_generated else ("evidential" if has_gap else "none")),
            "gap_strategy": ("generate_from_product_image" if is_generated else ("generate" if has_gap else "none")),
            "source_selection": None if is_generated else {
                "media_id": Path(m["source_path"]).stem,
                "path": source_tail,
                "start_seconds": m["source_interval"]["start_seconds"],
                "end_seconds": m["source_interval"]["end_seconds_exclusive"],
                "fit_reason": f"自有素材覆盖「{m.get('source_fit','商品动作')}」，区间 {m['source_interval']}",
            },
            "reference_mechanisms": [str(m.get("reference_evidence", {}).get("mechanism") or "模板 slot 结构复用")],
            "industry_notes": ["每镜只放一个短词卖点", "字幕不遮动作结果"],
            "control_rule_refs": ["content_direction.rules[0]", "story_pacing.rules[1]"],
            "generation_proposals": generation_proposals,
            "selected_generation_task_id": None,
            "narration_hash": _content_hash({"section_id": section.get("id"), "text": narration}),
            "screen_copy_hash": _content_hash({"section_id": section.get("id"), "text": screen_copy}),
            "tts_asset_hash": None,
            "tts_measured_duration": None,
            "caption_timeline_hash": _content_hash({
                "section_id": section.get("id"),
                "screen_copy": screen_copy,
                "start_seconds": section.get("start_seconds"),
                "end_seconds": section.get("end_seconds"),
            }),
            **(evidence_fields if canonical_evidence else {}),
            **({
                "visual_route": visual_route,
                "claim_visual_requirements": dict(m.get("claim_visual_requirements") or {}),
                "generation_reference": generation_reference,
                "evidence_role": "visual_expression_only" if is_generated else "owned_visual_evidence",
            } if m.get("visual_route") else {}),
            **({"source_hash": source_hash, "source_interval": source_interval} if not is_generated and canonical_evidence else {}),
        }
        shots.append(shot)
    refs = {
        "creative_control_ref": {"artifact": "creative_control_plan", "version": int(ccp.get("plan_version") or 1),
                                 "artifact_sha256": str(ccp.get("artifact_sha256") or "a" * 64)},
        "script_ref": {"artifact": "script", "version": 1, "artifact_sha256": str(script.get("artifact_sha256") or "a" * 64)},
        "scene_plan_ref": {"artifact": "scene_plan", "version": 1, "artifact_sha256": str(sp.get("artifact_sha256") or "a" * 64)},
    }
    return {
        "version": "1.0",
        "project_id": project.name,
        "plan_id": plan_id,
        "plan_version": 1,
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
        **refs,
        "shots": shots,
    }


def bind_tts_assets(
    project: Path,
    bindings: Mapping[str, tuple[Path, float]],
    *,
    sink=None,
) -> dict[str, Any]:
    """Bind generated narration files and measured durations into the shot plan.

    The section id is the stable join key.  Rewriting through artifact I/O
    refreshes both canonical hashes so downstream render/evaluation inputs
    cannot keep referring to the pre-TTS plan.
    """
    plan = _load(project / "artifacts" / "shot_execution_plan.json")
    if not isinstance(plan, dict):
        raise ValueError("shot_execution_plan is required before TTS binding")
    seen: set[str] = set()
    shots = []
    for raw in plan.get("shots") or []:
        shot = dict(raw)
        section_id = str(shot.get("section_id") or "")
        binding = bindings.get(section_id)
        if binding is not None:
            audio_path, measured_duration = binding
            if not audio_path.is_file():
                raise FileNotFoundError(f"TTS asset not found for {section_id}: {audio_path}")
            duration = float(measured_duration)
            if duration <= 0:
                raise ValueError(f"TTS measured duration must be positive for {section_id}")
            section_duration = float(shot.get("duration_seconds") or 0)
            if duration > section_duration + 1e-6:
                raise ValueError(f"TTS measured duration exceeds shot duration for {section_id}")
            shot["tts_asset_hash"] = hashlib.sha256(audio_path.read_bytes()).hexdigest()
            shot["tts_measured_duration"] = round(duration, 3)
            seen.add(section_id)
        shots.append(shot)
    missing = sorted(set(bindings) - seen)
    if missing:
        raise ValueError(f"TTS bindings reference unknown sections: {', '.join(missing)}")
    updated = dict(plan)
    updated["shots"] = shots
    return write_artifact_atomic(
        "artifacts/shot_execution_plan.json", "shot_execution_plan",
        updated, project_dir=project, sink=sink,
    )


def build_asset_plan(
    project: Path,
    sp: dict,
    shot_plan: dict,
    *,
    output_profile: str | None = None,
) -> dict:
    resolved_profile = _resolved_output_profile(project, output_profile)
    is_three_four = "3_4" in resolved_profile
    proxy_width, proxy_height = (540, 720) if is_three_four else (540, 960)
    aspect_ratio = "3:4" if is_three_four else "9:16"
    planned = []
    included_references: set[str] = set()
    for i, shot in enumerate(shot_plan["shots"], start=1):
        visual_route = str(shot.get("visual_route") or "owned_source")
        creative_binding = {
            "purpose": str(shot.get("purpose") or ""),
            "subject_action": str(shot.get("subject_action") or ""),
            "narration": str(shot.get("narration") or ""),
            "screen_copy": str(shot.get("screen_copy") or ""),
            "claim_ids": [str(value) for value in shot.get("claim_ids") or []],
            "action_keys": [str(value) for value in shot.get("action_keys") or []],
            "evidence_row_ids": [str(value) for value in shot.get("evidence_row_ids") or []],
            "product_fact_refs": [str(value) for value in shot.get("product_fact_refs") or []],
            "product_page_refs": [str(value) for value in shot.get("product_page_refs") or []],
            "page_asset_ids": [str(value) for value in shot.get("page_asset_ids") or []],
            "page_evidence_ids": [str(value) for value in shot.get("page_evidence_ids") or []],
        }
        if shot.get("visual_route"):
            creative_binding.update({
                "visual_route": visual_route,
                "claim_visual_requirements": dict(
                    shot.get("claim_visual_requirements") or {}
                ),
                "evidence_role": str(shot.get("evidence_role") or ""),
            })
        if visual_route == "generated_from_product_image":
            proposals = shot.get("generation_proposals") or []
            if len(proposals) != 1 or not isinstance(proposals[0], Mapping):
                raise ValueError("generated shot requires exactly one generation proposal")
            proposal = dict(proposals[0])
            generation_reference = shot.get("generation_reference")
            if not isinstance(generation_reference, Mapping):
                raise ValueError("generated shot requires generation_reference")
            reference = dict(generation_reference)
            reference_id = str(reference.get("asset_id") or "")
            if reference_id not in included_references:
                planned.append({
                    "id": f"clean-reference-{reference_id}",
                    "type": "clean_product_reference",
                    "provider": "product_asset_ledger",
                    "model": "reviewed-derived-reference",
                    "cost_estimate_usd": 0.0,
                    "paid": False,
                    "output_path": str(reference.get("local_path") or ""),
                    "source_stage": "research",
                    "exists": True,
                    "shot_id": str(shot.get("id") or f"shot-{i:02d}"),
                    "visual_route": visual_route,
                    "generation_reference": reference,
                    "evidence_role": "visual_expression_reference_only",
                    "creative_binding": dict(creative_binding),
                    "processing_plan": {
                        "operation": "use_reviewed_clean_product_reference",
                        "tool": "product_asset_ledger",
                        "aspect_ratio": aspect_ratio,
                        "fit": "contain",
                        "crop_strategy": "identity_preserving",
                        "audio_policy": "not_applicable",
                    },
                })
                included_references.add(reference_id)
            known_costs = [
                float(item["estimated_cost_usd"])
                for item in proposal.get("provider_candidates") or []
                if isinstance(item, Mapping)
                and isinstance(item.get("estimated_cost_usd"), (int, float))
            ]
            planned.append({
                "id": f"generated-shot-{i:02d}",
                "type": "generated_video",
                "provider": "selection_pending",
                "model": "selection_pending",
                "cost_estimate_usd": max(known_costs) if known_costs else 0.0,
                "paid": True,
                "output_path": f"assets/video/shot-{i:02d}-generated.mp4",
                "source_stage": "assets",
                "exists": False,
                "shot_id": str(shot.get("id") or f"shot-{i:02d}"),
                "visual_route": visual_route,
                "generation_reference": reference,
                "provider_candidates": deepcopy(proposal.get("provider_candidates") or []),
                "evidence_role": "visual_expression_only",
                "approval_subject_hash": str(proposal.get("approval_subject_hash") or ""),
                "creative_binding": creative_binding,
                "generation_plan": {
                    key: deepcopy(proposal[key])
                    for key in (
                        "operation", "prompt", "duration_seconds", "aspect_ratio",
                        "required_actions", "required_results", "consistency_requirements",
                        "prohibitions", "retry_limit", "approval_subject_hash",
                        "provider_selection_status",
                    )
                },
                "processing_plan": {
                    "operation": "image_to_video",
                    "tool": "video_selector",
                    "aspect_ratio": aspect_ratio,
                    "width": proxy_width,
                    "height": proxy_height,
                    "fit": "cover",
                    "crop_strategy": "generate_subject_protected_3_4",
                    "audio_policy": "generated_clip_muted_mix_added_at_sample",
                },
            })
            continue
        source_selection = dict(shot.get("source_selection") or {})
        planned.append({
            "id": f"proxy-shot-{i:02d}", "type": "video_proxy", "provider": "media_proxy",
            "model": "ffmpeg-local", "cost_estimate_usd": 0.0, "paid": False,
            "output_path": f"assets/video/shot-{i:02d}-proxy.mp4", "source_stage": "assets", "exists": False,
            "shot_id": str(shot.get("id") or f"shot-{i:02d}"),
            "source_selection": source_selection,
            "creative_binding": creative_binding,
            "processing_plan": {
                "operation": "local_proxy_transcode",
                "tool": "media_proxy",
                "aspect_ratio": aspect_ratio,
                "width": proxy_width,
                "height": proxy_height,
                "fit": "cover",
                "crop_strategy": "center_crop_subject_protected",
                "audio_policy": "proxy_muted_mix_added_at_sample",
            },
        })
    audio = {
        "tts": {"provider": "doubao", "resource_id": "seed-tts-2.0", "voice": "zh_female_vv_uranus_bigtts"},
        "bgm": {"provider": "suno", "profile": "轻快节奏电商 BGM"},
        "mix": {"narration": "doubao", "music": "suno", "ducking_db": -6},
        "estimated_cost_usd": 0.08,
    }
    return {
        "version": "1.0",
        "project_id": project.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-asset-director@1.0",
        "input_hashes": {"scene_plan": str(sp.get("artifact_sha256") or "a" * 64)},
        "planned_assets": planned,
        "paid_generation_approved": False,
        "audio_plan": audio,
    }


def build_production_lock(project: Path, template: dict, ccp: dict, script: dict, *,
                          output_profile: str | None = None) -> dict:
    plan_id = str(template.get("template_id") or "")
    from lib.media_profiles import get_profile
    output_profile = _resolved_output_profile(project, output_profile)
    profile = get_profile(output_profile)
    platform = _project_target_platform(project)
    safe_zone = "taobao_detail_3_4" if "3_4" in output_profile else "9:16 bottom"
    return {
        "version": "1.0",
        "project_id": project.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-asset-director@1.0",
        "input_hashes": {"script": str(script.get("artifact_sha256") or "a" * 64)},
        "lock_version": 1,
        "locked_values": {
            "script": {"ref": "artifacts/script.json", "total_duration_seconds": script.get("total_duration_seconds")},
            "narration": {"source": "script.sections[].narration", "voice": "doubao-zh_female"},
            "tts": {"provider": "doubao", "resource_id": "seed-tts-2.0", "voice": "zh_female_vv_uranus_bigtts"},
            "bgm": {"provider": "suno", "profile": "轻快节奏电商 BGM"},
            "mix": {"narration": "doubao", "music": "suno", "ducking_db": -6},
            "font": {"family": "MaShanZheng", "stroke": 0, "fill": "#FFFFFF"},
            "captions": {"source": "script.sections[].screen_copy", "safe_zone": safe_zone},
            "cta": {"text": _selected_cta(project, platform)},
            "platform": platform,
            "output": {"resolution": f"{profile.width}x{profile.height}", "fps": profile.fps, "format": "mp4", "profile": output_profile},
            "render_runtime": "remotion",
            "composition_mode": "templated",
        },
        "decision_revision_ids": [],
    }


def build_approval_bundle(project: Path, sp: dict, shot_plan: dict, asset_plan: dict, prod_lock: dict,
                          *, envelope_map: dict[str, dict] | None = None) -> dict:
    """按 name → artifact 文件名的信封索引（envelope_map）取 hash；缺省读磁盘。"""
    def ref(name):
        d = {
            "creative_control_plan": "creative_control_plan",
            "proposal_packet": "proposal_packet", "scene_plan": "scene_plan", "asset_plan": "asset_plan",
            "production_lock": "production_lock", "shot_execution_plan": "shot_execution_plan",
        }
        path = f"artifacts/{d[name]}.json"
        env = (envelope_map or {}).get(d[name])
        if env is None:
            data = _load(project / path)
            if data is None:
                raise ValueError(f"approval_bundle ref {name} artifact not found: {path}")
        else:
            data = env.get("data") or env
        return {"name": name, "path": path, "semantic_sha256": str(data.get("semantic_sha256") or "a" * 64),
                "artifact_sha256": str(data.get("artifact_sha256") or "a" * 64)}
    members = ["proposal", "scene_plan", "assets"]
    return {
        "version": "1.0",
        "project_id": project.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-asset-director@1.0",
        "input_hashes": {"scene_plan": str(sp.get("artifact_sha256") or "a" * 64)},
        "bundle_id": f"{project.name}-creative_lock",
        "bundle_version": 1,
        "group": "creative_lock",
        "terminal_stage": "assets",
        "members": members,
        "artifact_refs": [ref(n) for n in ("proposal_packet", "creative_control_plan", "scene_plan", "asset_plan", "production_lock", "shot_execution_plan")],
        "status": "awaiting_human",
    }


def shot_plan_drift(project: Path, template: dict, sp: dict, script: dict, shot_plan: dict) -> list[str]:
    """shot_execution_plan 与当前 script/scene_plan 的键控一致性检查（评审 P0-1）。

    返回漂移描述列表（空 = 一致）。任何一镜的 narration/screen_copy/duration/setting
    与当前制品不一致都算漂移——下游（渲染/发布）必须经 sync 后使用。
    """
    slots_by_id = {str(s.get("slot_id") or ""): s for s in (template.get("slots") or [])}
    scenes_by_id = {str(s.get("id") or ""): s for s in (sp.get("scenes") or [])}
    sections_by_id = {
        str(x.get("id") or ""): x for x in (script.get("sections") or [])
        if isinstance(x, Mapping) and x.get("id")
    }
    from lib.template_alignment import shot_execution_plan_errors

    drift: list[str] = shot_execution_plan_errors(
        shot_plan, script, sp, audio_dir=project / "assets" / "audio"
    )
    for shot in shot_plan.get("shots", []):
        scene = scenes_by_id.get(str(shot.get("scene_id") or "")) or {}
        slot = slots_by_id.get(str(shot.get("template_slot_ref") or "")) or {}
        section = sections_by_id.get(str(shot.get("section_id") or "")) or {}
        if not section:
            # Read-only compatibility for pre-section_id artifacts.  New
            # renders are guarded by lib.template_alignment and require the
            # explicit field; this fallback only lets sync report old drift.
            section = next((x for x in (script.get("sections") or [])
                            if isinstance(x, Mapping)
                            and round(float(x.get("start_seconds") or 0), 3)
                            == round(float(scene.get("start_seconds") or 0), 3)), {})
            if not section:
                drift.append(f"{shot.get('id')}.section_id: missing or unknown")
        expected = {
            "narration": str(section.get("narration") or section.get("text") or "") if section else "",
            "screen_copy": str(section.get("screen_copy") or "") if section else "",
            "setting": str(slot.get("scene") or "室内/桌面"),
            "purpose": str(scene.get("description") or f"模板 slot {shot.get('template_slot_ref')}"),
        }
        for key, want in expected.items():
            if str(shot.get(key) or "") != str(want or ""):
                drift.append(f"{shot.get('id')}.{key}: 存={str(shot.get(key))[:20]!r} 期望={want[:20]!r}")
    return drift


def sync_assets_artifacts(project: Path, template: dict, *, pipeline_dir: Path, sink=None,
                          output_profile: str | None = None) -> dict:
    """从**当前** script/scene_plan 重派生 assets 四制品（修复 rebuild 后漂移；评审 P0-1）。

    不改审批语义：重派生后 status 保持 approved（经 batch_approval 决策），并刷新 checkpoint 信封。
    """
    from lib.checkpoint import refresh_checkpoint_envelopes

    sp = _load(project / "artifacts" / "scene_plan.json")
    ccp = _load(project / "artifacts" / "creative_control_plan.json")
    script = _load(project / "artifacts" / "script.json")
    old_plan = _load(project / "artifacts" / "shot_execution_plan.json") or {}
    shot_env = write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan",
                                     build_shot_execution_plan(
                                         project, template, sp, ccp, script,
                                         output_profile=output_profile,
                                     ),
                                     project_dir=project, sink=sink)
    shot_plan = shot_env["data"]
    # 保持已批准状态（重派生不至于让已批门失效）
    shot_plan["status"] = str(old_plan.get("status") or "draft")
    if shot_plan["status"] == "approved":
        shot_plan["approval"] = old_plan.get("approval") or {"approved_by": "batch-operator",
                                                             "approved_at": datetime.now(timezone.utc).isoformat()}
    shot_env = write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan",
                                     shot_plan, project_dir=project, sink=sink)
    asset_env = write_artifact_atomic("artifacts/asset_plan.json", "asset_plan",
                                      build_asset_plan(project, sp, shot_plan, output_profile=output_profile),
                                      project_dir=project, sink=sink)
    lock_env = write_artifact_atomic("artifacts/production_lock.json", "production_lock",
                                     build_production_lock(project, template, ccp, script,
                                                            output_profile=output_profile), project_dir=project, sink=sink)
    env_map = {"shot_execution_plan": shot_env, "asset_plan": asset_env, "production_lock": lock_env}
    bundle = build_approval_bundle(project, sp, shot_plan, asset_env["data"], lock_env["data"], envelope_map=env_map)
    bundle_env = write_artifact_atomic("artifacts/approval_bundle.json", "approval_bundle", bundle, project_dir=project, sink=sink)
    refresh_checkpoint_envelopes(pipeline_dir, project.name, pipeline_type=PIPELINE)
    return {"shot_execution_plan": shot_env, "asset_plan": asset_env,
            "production_lock": lock_env, "approval_bundle": bundle_env}


def build_assets(project: Path, template: dict, *, pipeline_dir: Path, sink=None,
                 output_profile: str | None = None) -> dict:
    """产 assets 四制品并写 checkpoint（awaiting_human，creative_lock terminal）。"""
    sp = _load(project / "artifacts" / "scene_plan.json")
    ccp = _load(project / "artifacts" / "creative_control_plan.json")
    script = _load(project / "artifacts" / "script.json")
    # 硬门：进入付费前必须 template_run_plan ready（无 unbound + 不复制参考花字）。
    # 传 template：校验每个 binding 的 slot_id 必须是模板已知 slot（缺 slot 绑定即阻断）。
    rp = _load(project / "artifacts" / "template_run_plan.json") or {}
    try:
        input_mode, authoritative_ref = resolve_run_batch_differentiation_ref(project, pipeline_dir)
    except ValueError as exc:
        raise SystemExit(f"differentiation owner 无法验证，禁止 paid assets: {exc}") from exc
    readiness = check_template_run_plan_ready(
        rp, template=template, input_mode=input_mode,
        authoritative_differentiation_plan_ref=authoritative_ref,
    )
    if not readiness.get("ready"):
        raise SystemExit(f"template_run_plan 未就绪，禁止 paid assets: {readiness.get('blockers')}")

    shot_env = write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan",
                                     build_shot_execution_plan(
                                         project, template, sp, ccp, script,
                                         output_profile=output_profile,
                                     ), project_dir=project, sink=sink)
    shot_plan = shot_env["data"]
    asset_env = write_artifact_atomic("artifacts/asset_plan.json", "asset_plan",
                                      build_asset_plan(project, sp, shot_plan, output_profile=output_profile),
                                      project_dir=project, sink=sink)
    lock_env = write_artifact_atomic("artifacts/production_lock.json", "production_lock",
                                     build_production_lock(project, template, ccp, script,
                                                            output_profile=output_profile), project_dir=project, sink=sink)
    # 事务内读磁盘会看到未提交内容 → 用本次写入的信封索引（envelope_map）构建 bundle refs。
    env_map = {name: env for name, env in (("shot_execution_plan", shot_env), ("asset_plan", asset_env),
                                           ("production_lock", lock_env))}
    bundle = build_approval_bundle(project, sp, shot_plan, asset_env["data"], lock_env["data"], envelope_map=env_map)
    bundle_env = write_artifact_atomic("artifacts/approval_bundle.json", "approval_bundle", bundle, project_dir=project, sink=sink)
    return {"shot_execution_plan": shot_env, "asset_plan": asset_env,
            "production_lock": lock_env, "approval_bundle": bundle_env}
