"""Re-open the Tiansi source-led runs at the script gate with story-shaped copy.

The previous scripts were fact-aligned but list-shaped.  This migration keeps
the accepted source/evidence bindings and timings, while changing only the
narrative role, consumer-facing narration and short screen copy.  No paid
asset is generated here; downstream checkpoints are invalidated and the
script_lock review is reopened.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
RUNS = (
    "tiansi-script-variants-20260911-result_first",
    "tiansi-script-variants-20260911-texture_first",
    "tiansi-script-variants-20260911-daily_seed",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _matrix_by_id(project: Path) -> dict[str, dict[str, Any]]:
    matrix = _load(project / "artifacts" / "reference_source_matrix.json")
    return {
        str(row["matrix_row_id"]): row
        for row in matrix.get("rows", [])
        if isinstance(row, dict) and row.get("matrix_row_id")
    }


def _copy_for(action: str, row: dict[str, Any], role: str) -> tuple[str, str]:
    """Return natural viewer-facing copy; page/source labels stay metadata-only."""
    allowed = str((row.get("allowed_wording") or [""])[0])
    if action == "连续水流接触毛巾":
        narration = f"先看结果：连续倒水后，湿润范围清楚可见；{allowed}。"
        screen = f"连续倒水 · 湿润范围清楚可见（{allowed}）"
    elif action == "纹理特写":
        narration = f"再看细节：细密竖条毛圈清楚可见；{allowed}。"
        screen = f"细密竖条毛圈 · {allowed}"
    elif action == "轻抚脸颊":
        narration = f"手指轻抚毛圈，纹理变化清楚可见；{allowed}。"
        screen = f"轻抚 · {allowed}"
    elif action == "擦拭面部":
        narration = f"真正用起来，擦拭面部更顺手；{allowed}。"
        screen = f"日常擦拭 · {allowed}"
    elif action == "叠放展示":
        narration = f"把毛巾展开，双面毛圈与边缘结构清楚可见；{allowed}。"
        screen = f"双面毛圈 · {allowed}"
    elif action == "包裹颈部":
        narration = f"贴肤使用这一刻，轻轻包裹颈部；{allowed}。"
        screen = f"贴肤使用 · {allowed}"
    elif action == "挂起毛巾":
        narration = f"用完顺手挂回去，日常取用更自然；{allowed}。"
        screen = f"用完顺手挂回 · {allowed}"
    elif action == "悬挂展示":
        narration = f"颜色看得见：海天蓝单条展示；{allowed}。"
        screen = f"海天蓝单条展示 · {allowed}"
    elif action == "纹理展示":
        narration = f"最后看清楚，{allowed}。"
        screen = allowed
    else:
        allowed = list(row.get("allowed_wording") or [])
        narration = allowed[0] if allowed else ""
        screen = allowed[0] if allowed else ""
    # Keep the story connector short and never introduce a new product claim.
    if role == "cta" and action != "纹理展示":
        narration = narration.rstrip("。") + "，现在就去看看。"
    return narration, screen


ROLE_MAP = {
    "result_first": ("hook", "problem", "escalation", "reveal", "proof", "proof", "payoff", "payoff", "cta"),
    "texture_first": ("hook", "problem", "reveal", "proof", "escalation", "proof", "payoff", "payoff", "cta"),
    "daily_seed": ("hook", "problem", "escalation", "reveal", "proof", "proof", "escalation", "payoff", "cta"),
}


def _action_for(mapping: dict[str, Any]) -> str:
    actions = [str(value) for value in mapping.get("action_keys") or [] if str(value).strip()]
    # The evidence contract has one primary visual action; keep secondary
    # result wording in metadata rather than making the narration ambiguous.
    return actions[0] if actions else ""


def _build_story_script(project: Path) -> dict[str, Any]:
    old = _load(project / "artifacts" / "script.json")
    # Idempotent refresh after the first migration has already invalidated the
    # old scene plan: only the beat-map metadata needs correcting.
    if not (project / "artifacts" / "scene_plan.json").exists():
        refreshed = dict(old)
        refreshed["metadata"] = {
            **dict(old.get("metadata") or {}),
            "beat_map": [str(section.get("beat_role") or "proof") for section in old.get("sections") or []],
        }
        return refreshed
    scene_plan = _load(project / "artifacts" / "scene_plan.json")
    matrix = _matrix_by_id(project)
    variant = str((_load(project / "project.json").get("variant") or {}).get("id") or "")
    roles = ROLE_MAP.get(variant)
    if not roles:
        raise ValueError(f"unsupported Tiansi variant: {variant}")
    mappings = {
        str(item.get("scene_id")): item
        for item in (scene_plan.get("metadata") or {}).get("source_mapping") or []
        if isinstance(item, dict) and item.get("scene_id")
    }
    sections = []
    for index, scene in enumerate(scene_plan.get("scenes") or []):
        scene_id = str(scene.get("id") or "")
        mapping = mappings.get(scene_id)
        if not mapping:
            raise ValueError(f"{project.name}: missing source mapping for {scene_id}")
        row_ids = [str(value) for value in mapping.get("evidence_row_ids") or []]
        if len(row_ids) != 1 or row_ids[0] not in matrix:
            raise ValueError(f"{project.name}: expected one accepted evidence row for {scene_id}")
        row = matrix[row_ids[0]]
        action = _action_for(mapping)
        role = roles[index] if index < len(roles) else "proof"
        narration, screen_copy = _copy_for(action, row, role)
        section = {
            "id": str(scene.get("script_section_id") or f"sec-{index + 1:03d}"),
            "label": f"story-beat-{index + 1}",
            "text": narration,
            "narration": narration,
            "scene_id": scene_id,
            "screen_copy": screen_copy,
            "section_goal": {
                "hook": "先给结果或日常瞬间，建立观看动机",
                "problem": "把使用选择转成具体疑问",
                "escalation": "把疑问推进到材质或使用证据",
                "reveal": "揭示画面中可见的产品细节",
                "proof": "用单一动作兑现当前叙事承诺",
                "payoff": "让产品回到真实日常使用",
                "cta": "收束到商品身份与查看详情",
            }.get(role, "推进故事"),
            "beat_role": role,
            "viewer_state": {
                "hook": "无感→好奇", "problem": "好奇→疑问", "escalation": "疑问→期待",
                "reveal": "期待→被解答", "proof": "被解答→信服", "payoff": "信服→想用",
                "cta": "想用→行动",
            }.get(role, "继续观看"),
            "start_seconds": scene["start_seconds"],
            "end_seconds": scene["end_seconds"],
            "visual_intent": str(scene.get("shot_intent") or ""),
            "evidence_requirements": list(dict.fromkeys(
                str(value) for value in (mapping.get("claim_visual_requirements") or {}).get("required_actions") or []
            )),
            "pacing": "先动作后解释；一镜只推进一个故事动作",
            "control_rule_refs": [
                "creative_control_plan.content_direction",
                "creative_control_plan.story_pacing",
                "creative_control_plan.fact_continuity",
                "reference_source_matrix.allowed_wording",
            ],
            "review": "pending",
            "feedback": "",
            "source_ref": "product_facts",
            "narration_action_key": action,
            "bound_material_action": action,
            "narration_material_aligned": True,
            "claim_ids": list(mapping.get("claim_ids") or []),
            "action_keys": list(mapping.get("action_keys") or []),
            "evidence_row_ids": row_ids,
            "product_fact_refs": list(mapping.get("product_fact_refs") or []),
            "product_page_refs": list(mapping.get("product_page_refs") or []),
            "page_asset_ids": list(mapping.get("page_asset_ids") or []),
            "page_evidence_ids": list(mapping.get("page_evidence_ids") or []),
            "visual_route": str(mapping.get("visual_route") or "owned_source"),
            "claim_visual_requirements": dict(mapping.get("claim_visual_requirements") or {}),
            "generation_reference": mapping.get("generation_reference"),
        }
        sections.append(section)
    updated = dict(old)
    updated.update({
        "version": "1.0",
        # Keep the migration idempotent when a validation-only rerun refreshes
        # the same story draft.
        "script_version": max(2, int(old.get("script_version") or 1)),
        "status": "draft",
        "sections": sections,
        "voice_performance": {
            **dict(old.get("voice_performance") or {}),
            "performance_intent": "有情境转折、清晰克制的淘宝种草口播",
            "pacing_profile": "conversational",
            "energy_curve": "先制造疑问，再用动作证据落地",
            "pause_policy": "hook 后短停；每个 beat 独立停连",
            "sample_section_id": sections[0]["id"],
        },
        "metadata": {
            **dict(old.get("metadata") or {}),
            "beat_map": [section["beat_role"] for section in sections],
            "narrative_structure": "hook_problem_escalation_reveal_proof_payoff_cta",
            "story_variant": variant,
            "story_migration": {
                "supersedes_script_version": max(1, int(old.get("script_version") or 1) - 1),
                "reason": "样片审核通过后发现脚本卖点平铺，改为故事结构；下游口播/字幕需重建",
            },
        },
    })
    updated.pop("approval", None)
    return updated


def main() -> None:
    from backlot.operator_reviews import ReviewService
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_io import write_artifact_atomic
    from lib.checkpoint import write_checkpoint

    for run in RUNS:
        project = PROJECTS / run
        story = _build_story_script(project)
        store = ProjectCommitStore(project)
        with store.transaction(action={"action_id": f"story-script-migration-{run}"}) as sink:
            env = write_artifact_atomic("artifacts/script.json", "script", story, project_dir=project, sink=sink)
            for stage in ("scene_plan", "assets", "sample", "edit", "compose", "publish"):
                sink.stage_delete(f"checkpoint_{stage}.json")
            sink.stage_delete("artifacts/scene_plan.json")
            write_checkpoint(
                PROJECTS, run, "script", "awaiting_human", {"script": env},
                pipeline_type="cinematic-fast", human_approved=False,
                next_action={
                    "summary": "故事化脚本已重建，等待人工确认后重新生成分镜、口播与字幕",
                    "verb": "await_user",
                    "context_refs": ["artifacts/script.json", "artifacts/creative_control_plan.json", "artifacts/reference_source_matrix.json"],
                }, sink=sink,
            )
            reviews = ReviewService(project, store=store)
            reviews.stage_supersede_pending(
                sink, kinds={"creative_lock", "sample"},
                decided_by="cinematic-fast-story-script",
                reason="上游故事脚本重建，下游样片/创意锁定失效",
            )
            reviews.stage_create(
                sink, kind="script_lock", subject_id="script-story-v2",
                subject_version=int(story.get("script_version") or 2),
                subject_hash=str(env["semantic_sha256"]),
                submitted_by="cinematic-fast-story-script",
            )
        print(f"{run}: story script v{story.get('script_version')} awaiting_human")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
