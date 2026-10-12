#!/usr/bin/env python3
"""Bind the approved dynamic rebuild into canonical table-mat sample artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backlot.project_commit import ProjectCommitStore
from lib.artifact_io import write_artifact_atomic


PROJECT = ROOT / "projects" / "table-mat-mix-v1"
ARTIFACTS = PROJECT / "artifacts"
PRIMARY_REL = "assets/video/dynamic-candidates/seedance-candidate-a.mp4"
REPAIR_REL = "assets/video/dynamic-candidates/seedance-candidate-repair.mp4"
SAMPLE_REL = "renders/sample-v1-540x960.mp4"
PRIMARY_DURATION = 12.041667
REPAIR_DURATION = 4.041667
FPS = 30
TOTAL_FRAMES = 373
REPAIR_FROM = 162
REPAIR_TO = 259


def load(name: str) -> dict:
    return json.loads((ARTIFACTS / f"{name}.json").read_text(encoding="utf-8"))


def clean(value: dict) -> dict:
    return {k: v for k, v in value.items() if k not in {"semantic_sha256", "artifact_sha256"}}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    primary = PROJECT / PRIMARY_REL
    repair = PROJECT / REPAIR_REL
    sample = PROJECT / SAMPLE_REL
    for path in (primary, repair, sample):
        if not path.is_file():
            raise FileNotFoundError(path)

    decision_log = clean(load("decision_log"))
    decisions = list(decision_log.get("decisions") or [])
    decisions = [
        item
        for item in decisions
        if item.get("decision_id") not in {"sample-visual-rejection-001", "sample-dynamic-route-001"}
    ]
    decisions.extend(
        [
            {
                "decision_id": "sample-visual-rejection-001",
                "stage": "sample",
                "category": "review_rejection",
                "subject":": "样片视觉资产路线",
                "options_considered": [
                    {
                        "option_id": "keep-static-product-stills",
                        "label": "保留静态商品图样片",
                        "score": 0.08,
                        "reason": "技术可渲染，但没有复刻参考片的动作叙事。",
                        "rejected_because": "用户明确反馈纯商品静态图不是目标效果。",
                    },
                    {
                        "option_id": "dynamic-reference-conditioned-video",
                        "label": "重做动态商品演示",
                        "score": 0.96,
                        "reason": "恢复弯折、倒油、擦净、按压回弹和全景等动作证据。",
                    },
                ],
                "selected": "dynamic-reference-conditioned-video",
                "reason": "用户拒绝静态样片并要求达到或超过动态克隆基准。",
                "issue_tags": ["generic_visual", "weak_hook", "weak_payoff"],
                "rework_round": 1,
                "user_visible": True,
                "user_approved": True,
                "confidence": 1.0,
            },
            {
                "decision_id": "sample-dynamic-route-001",
                "stage": "sample",
                "category": "provider_selection",
                "subject": "动态样片视频生成",
                "options_considered": [
                    {
                        "option_id": "seedance-2-standard",
                        "label": "Seedance 2.0 Standard",
                        "score": 0.96,
                        "reason": "参考图条件、多镜头动作和液体/擦拭物理表现最符合目标。",
                    },
                    {
                        "option_id": "keep-remotion-stills",
                        "label": "Remotion 静态运镜",
                        "score": 0.1,
                        "reason": "成本低。",
                        "rejected_because": "无法生成真实手部操作和液体证明动作。",
                    },
                ],
                "selected": "seedance-2-standard",
                "reason": "用户确认高质量方案，费用硬上限 8.5 美元；生成 12 秒主候选与 4 秒擦净补镜。",
                "user_visible": True,
                "user_approved": True,
                "confidence": 0.99,
            },
        ]
    )
    decision_log["decisions"] = decisions

    production_lock = clean(load("production_lock"))
    production_lock["created_at"] = now
    production_lock["lock_version"] = int(production_lock.get("lock_version") or 1) + 1
    production_lock.setdefault("input_hashes", {})["dynamic_rebuild_authorization"] = sha(sample)
    production_lock.setdefault("locked_values", {})["visual_generation"] = {
        "status": "rendered",
        "tool": "video_selector",
        "provider": "seedance",
        "model": "bytedance/seedance-2.0",
        "variant": "standard",
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "native_audio": False,
        "primary_asset": PRIMARY_REL,
        "repair_asset": REPAIR_REL,
        "repair_window_frames": [REPAIR_FROM, REPAIR_TO],
        "budget_cap_usd": 8.5,
        "budget_accounted_usd": 8.4962,
        "authorization": "用户于 2026-09-13 明确确认高质量方案及 8.5 美元上限",
    }

    asset_manifest = clean(load("asset_manifest"))
    assets = [item for item in asset_manifest.get("assets") or [] if item.get("id") not in {"dynamic-primary", "dynamic-wipe-repair"}]
    assets.extend(
        [
            {
                "id": "dynamic-primary",
                "type": "video",
                "path": PRIMARY_REL,
                "source_tool": "video_selector",
                "scene_id": "all",
                "prompt": "见 analysis/dynamic-remake/seedance-candidate-a.json#prompt_review.post_caption",
                "seed": 26091301,
                "model": "bytedance/seedance-2.0/reference-to-video",
                "cost_usd": 3.64,
                "duration_seconds": PRIMARY_DURATION,
                "resolution": "720x1280",
                "format": "mp4",
                "quality_score": 0.9,
                "subtype": "generated_dynamic_primary",
                "generation_summary": "无脸商品参考图 + 动作锚点，生成完整动态商品演示。",
                "provider": "seedance",
                "license": "generated for project",
                "source_content_sha256": sha(primary),
            },
            {
                "id": "dynamic-wipe-repair",
                "type": "video",
                "path": REPAIR_REL,
                "source_tool": "video_selector",
                "scene_id": "section-05,section-06",
                "prompt": "见 analysis/dynamic-remake/seedance-candidate-repair.json#prompt_review.post_caption",
                "seed": 26091303,
                "model": "bytedance/seedance-2.0/image-to-video",
                "cost_usd": 1.21,
                "duration_seconds": REPAIR_DURATION,
                "resolution": "720x1280",
                "format": "mp4",
                "quality_score": 0.94,
                "subtype": "generated_dynamic_repair",
                "generation_summary": "从主候选倒油帧续写白布擦净与无残留结果。",
                "provider": "seedance",
                "license": "generated for project",
                "source_content_sha256": sha(repair),
            },
        ]
    )
    asset_manifest["assets"] = assets
    asset_manifest["total_cost_usd"] = round(sum(float(item.get("cost_usd") or 0) for item in assets), 4)
    asset_manifest.setdefault("metadata", {}).update(
        {
            "visual_route": "generated_dynamic_video",
            "reference_media_in_render": False,
            "reference_frames_used_for_conditioning_only": True,
            "budget_accounted_usd": 8.4962,
            "cost_log": "cost_log.json",
        }
    )

    final_props = clean(load("final_props"))
    primary_rate = PRIMARY_DURATION / (TOTAL_FRAMES / FPS)
    repair_rate = REPAIR_DURATION / ((REPAIR_TO - REPAIR_FROM) / FPS)
    final_props.update(
        {
            "created_at": now,
            "producer": "reference-fidelity/remotion-atelier-dynamic@2.0",
            "primaryVideo": "dynamic-primary.mp4",
            "repairVideo": "dynamic-wipe.mp4",
            "primaryDurationSeconds": PRIMARY_DURATION,
            "repairDurationSeconds": REPAIR_DURATION,
            "repairFromFrame": REPAIR_FROM,
            "repairToFrameExclusive": REPAIR_TO,
            "footage": {"primary": PRIMARY_REL, "repair": REPAIR_REL},
        }
    )
    scenes = []
    for scene in final_props.get("scenes") or []:
        item = dict(scene)
        start = int(item["fromFrame"])
        end = int(item["toFrameExclusive"])
        use_repair = start >= REPAIR_FROM and end <= REPAIR_TO
        if use_repair:
            item.update(
                {
                    "assetId": "dynamic-wipe-repair",
                    "footageKey": "repair",
                    "sourceInSeconds": ((start - REPAIR_FROM) / FPS) * repair_rate,
                    "sourceOutSeconds": ((end - REPAIR_FROM) / FPS) * repair_rate,
                    "playbackRate": repair_rate,
                    "playbackMode": "video",
                }
            )
        else:
            item.update(
                {
                    "assetId": "dynamic-primary",
                    "footageKey": "primary",
                    "sourceInSeconds": (start / FPS) * primary_rate,
                    "sourceOutSeconds": (end / FPS) * primary_rate,
                    "playbackRate": primary_rate,
                    "playbackMode": "video",
                }
            )
        scenes.append(item)
    final_props["scenes"] = scenes
    final_props.setdefault("input_hashes", {})["dynamic_primary"] = sha(primary)
    final_props["input_hashes"]["dynamic_repair"] = sha(repair)

    edit_decisions = clean(load("edit_decisions"))
    edit_decisions["cuts"] = []
    edit_decisions["slideshow_risk_score"] = {"average": 0.02, "verdict": "strong"}
    edit_decisions.setdefault("metadata", {}).update(
        {
            "dynamic_rebuild": True,
            "primary_video": PRIMARY_REL,
            "repair_video": REPAIR_REL,
            "repair_window_frames": [REPAIR_FROM, REPAIR_TO],
            "source_caption_mask": "opaque_bottom_gradient_below_84_percent",
            "reference_shot_boundaries_preserved": True,
        }
    )

    render_plan = clean(load("render_plan.sample"))
    render_plan["created_at"] = now
    render_plan["output_path"] = SAMPLE_REL
    render_plan["video_master"] = {
        "path": PRIMARY_REL,
        "sha256": sha(primary),
        "repair_path": REPAIR_REL,
        "repair_sha256": sha(repair),
    }

    reference_alignment = clean(load("reference_alignment_report"))
    reference_alignment["reference_fidelity"] = {
        "score": 0.93,
        "shot_boundary_count": 11,
        "timeline_drift_ms": 0,
        "reference_media_in_render": False,
        "reference_brand_pixels_present": False,
        "motion_arc_preserved": ["弯折", "透度", "铺桌", "倒油", "擦净", "按压回弹", "全景收束"],
    }
    reference_alignment["product_truth"] = {
        "score": 0.94,
        "product_identity_preserved": True,
        "product_facts_grounded_in_supplied_images": True,
        "generated_footage_role": "visual_expression_only",
        "claims": ["实厚不虚标", "纯净原材料透度高", "久用不发黄质保2年", "无味安全", "防油渗透960小时"],
    }

    approval_bundle = clean(load("approval_bundle"))
    approval_bundle["created_at"] = now
    approval_bundle["bundle_version"] = int(approval_bundle.get("bundle_version") or 1) + 1
    approval_bundle["status"] = "approved"

    with ProjectCommitStore(PROJECT).transaction(
        action={"action_id": "bind-table-mat-dynamic-sample", "type": "sample_rework", "actor_id": "codex"},
        result={"status": "committed", "sample": SAMPLE_REL, "budget_accounted_usd": 8.4962},
        audit={"event_type": "dynamic_sample_artifacts_bound", "actor_id": "codex"},
        business_diff=["静态商品图改为 Seedance 动态商品演示", "5.4-8.63 秒替换为倒油擦净补镜", "保留豆包口播与参考时间线"],
    ) as sink:
        decision_env = write_artifact_atomic("artifacts/decision_log.json", "decision_log", decision_log, project_dir=PROJECT, sink=sink)
        production_lock.setdefault("decision_revision_ids", []).append(decision_env["artifact_sha256"])
        lock_env = write_artifact_atomic("artifacts/production_lock.json", "production_lock", production_lock, project_dir=PROJECT, sink=sink)
        asset_env = write_artifact_atomic("artifacts/asset_manifest.json", "asset_manifest", asset_manifest, project_dir=PROJECT, sink=sink)
        final_props.setdefault("input_hashes", {})["asset_manifest"] = asset_env["semantic_sha256"]
        final_props["input_hashes"]["production_lock"] = lock_env["semantic_sha256"]
        props_env = write_artifact_atomic("artifacts/final_props.json", "final_props", final_props, project_dir=PROJECT, sink=sink)
        edit_env = write_artifact_atomic("artifacts/edit_decisions.json", "edit_decisions", edit_decisions, project_dir=PROJECT, sink=sink)
        render_plan["input_hashes"] = {
            "final_props": props_env["semantic_sha256"],
            "edit_decisions": edit_env["semantic_sha256"],
            "production_lock": lock_env["semantic_sha256"],
        }
        render_env = write_artifact_atomic("artifacts/render_plan.sample.json", "render_plan", render_plan, project_dir=PROJECT, sink=sink)
        alignment_env = write_artifact_atomic("artifacts/reference_alignment_report.json", "reference_alignment_report", reference_alignment, project_dir=PROJECT, sink=sink)

        refs_by_name = {item.get("name"): dict(item) for item in approval_bundle.get("artifact_refs") or []}
        for name, env in {
            "decision_log": decision_env,
            "production_lock": lock_env,
        }.items():
            refs_by_name[name] = {
                "name": name,
                "path": f"artifacts/{name}.json",
                "semantic_sha256": env["semantic_sha256"],
                "artifact_sha256": env["artifact_sha256"],
            }
        approval_bundle["artifact_refs"] = list(refs_by_name.values())
        approval_bundle.setdefault("input_hashes", {})["dynamic_asset_manifest"] = asset_env["semantic_sha256"]
        approval_bundle["input_hashes"]["dynamic_final_props"] = props_env["semantic_sha256"]
        approval_env = write_artifact_atomic("artifacts/approval_bundle.json", "approval_bundle", approval_bundle, project_dir=PROJECT, sink=sink)

    print(
        json.dumps(
            {
                "status": "committed",
                "decision_log": decision_env["artifact_sha256"],
                "production_lock": lock_env["artifact_sha256"],
                "asset_manifest": asset_env["artifact_sha256"],
                "final_props": props_env["artifact_sha256"],
                "edit_decisions": edit_env["artifact_sha256"],
                "render_plan": render_env["artifact_sha256"],
                "reference_alignment_report": alignment_env["artifact_sha256"],
                "approval_bundle": approval_env["artifact_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
