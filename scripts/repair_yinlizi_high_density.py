"""Repair the approved high-density towel run without changing providers.

The fourth beat's approved wording is valid, but its 2.0s slot is shorter than
the measured Doubao narration. Extend only that slot to 2.4s, rebuild the
dependent canonical artifacts, and leave the run on the normal cinematic-fast
mainline for media prep/render/QA.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from lib.artifact_io import write_artifact_atomic
from lib.artifact_hashing import attach_hashes
from lib.template_mainline import build_script, scene_plan_data
from lib.template_assets import sync_assets_artifacts
from backlot.project_commit import ProjectCommitStore

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
RUN = "yinlizi-script-variants-20260908-v3-high_density"


def load(project: Path, name: str) -> dict:
    return json.loads((project / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))


def main() -> None:
    project = PROJECTS / RUN
    pack = load(project, "template_pack")
    template_id = str(load(project, "template_run_plan").get("template_id") or "")
    template = next(item for item in pack.get("templates", []) if item.get("template_id") == template_id)
    target = next(slot for slot in template.get("slots", []) if slot.get("slot_id", "").endswith("slot-004"))
    old_duration = float(target.get("duration_s") or 0.0)
    rp = load(project, "template_run_plan")
    ccp = load(project, "creative_control_plan")
    facts = load(project, "product_facts")
    scene_plan = scene_plan_data(project, template, rp, ccp, facts)
    scenes = list(scene_plan.get("scenes") or [])
    target_scene = next(scene for scene in scenes if scene.get("template_slot_ref", "").endswith("slot-004"))
    extension = max(0.0, 2.4 - (float(target_scene["end_seconds"]) - float(target_scene["start_seconds"])))
    passed_target = False
    for scene in scenes:
        if scene is target_scene:
            scene["end_seconds"] = round(float(scene["end_seconds"]) + extension, 3)
            passed_target = True
        elif passed_target:
            scene["start_seconds"] = round(float(scene["start_seconds"]) + extension, 3)
            scene["end_seconds"] = round(float(scene["end_seconds"]) + extension, 3)
    for mapping in (scene_plan.get("metadata") or {}).get("source_mapping") or []:
        timeline = mapping.get("timeline_interval") or {}
        scene = next(item for item in scenes if item.get("id") == mapping.get("scene_id"))
        timeline["start_seconds"] = float(scene["start_seconds"])
        timeline["end_seconds_exclusive"] = float(scene["end_seconds"])
        mapping["timeline_interval"] = timeline
    with ProjectCommitStore(project).transaction(action={"action_id": f"repair-high-density-slot-004-{RUN}"}) as sink:
        scene_env = write_artifact_atomic("artifacts/scene_plan.json", "scene_plan", scene_plan, project_dir=project, sink=sink)
        script_env = build_script(project, template, scene_plan, ccp, facts, approved=True, sink=sink)
        log = load(project, "decision_log")
        log.setdefault("decisions", []).append({
            "decision_id": f"{RUN}-timing-repair-001",
            "stage": "edit",
            "category": "rework_cause",
            "subject": "high_density 第4镜口播时间轴",
            "options_considered": [
                {"option_id": "extend_shot", "label": "延长第4镜至2.4秒", "score": 0.95,
                 "reason": "保留已批准文案与自然语速，实测2.265秒可完整落入镜头"},
                {"option_id": "silent_speedup_or_trim", "label": "静默加速或截断", "score": 0.0,
                 "reason": "会破坏口播自然度或事实完整性", "rejected_because": "违反 voice-timeline-fit 契约"},
            ],
            "selected": "extend_shot",
            "reason": "第4镜实测口播2.265秒超过原2.0秒槽位；仅延长该镜，不切换 provider、不改商品事实。",
            "issue_tags": ["timing"],
            "rework_round": 1,
            "confidence": 0.98,
            "user_visible": True,
        })
        log = attach_hashes(log)
        log_env = write_artifact_atomic("artifacts/decision_log.json", "decision_log", log, project_dir=project, sink=sink)
    with ProjectCommitStore(project).transaction(action={"action_id": f"sync-high-density-slot-004-{RUN}"}) as sink:
        sync_env = sync_assets_artifacts(project, template, pipeline_dir=PROJECTS, sink=sink,
                                         output_profile="social_vertical_3_4_2160p30")
    print(json.dumps({
        "run": RUN,
        "old_slot_004_seconds": old_duration,
        "new_slot_004_seconds": 2.4,
        "scene_plan": scene_env["artifact_sha256"][:12],
        "script": script_env["artifact_sha256"][:12],
        "sync": {k: v["artifact_sha256"][:12] for k, v in sync_env.items()},
        "decision_log": log_env["artifact_sha256"][:12],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
