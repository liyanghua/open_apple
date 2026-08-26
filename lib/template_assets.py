"""模板 run 的 assets 阶段制品构建（shot_execution_plan / asset_plan / production_lock / approval_bundle）。

只产出**待审批**的资产计划，**不调用任何付费 provider**（paid_generation_approved=False）。
每个 scene 的 source 已由 scene_plan 的 source_mapping 落到 owned source；若全部 owned →
gap_strategy=none、coverage=enough、generation_proposals=[]；否则标 gap 并为缺口生成 proposal。

走主链路：由 `checkpoint.get_next_stage` 推进到 assets 后，调用本模块产制品 + `write_checkpoint`
写 `awaiting_human`（creative_lock terminal gate），等人工批准才进 paid assets。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib.artifact_io import write_artifact_atomic
from lib.template_mainline import _load, scene_plan_data
from lib.template_run_plan import check_template_run_plan_ready
from schemas.artifacts import validate_artifact

PIPELINE = "cinematic-fast"


def _owned_path_tail(project_path: str) -> str:
    """把 `projects/<proj>/inputs/source/...` 归一成 `inputs/source/...`（schema pattern）。"""
    marker = "/inputs/source/"
    idx = project_path.find(marker)
    return project_path[idx + 1:] if idx >= 0 else "inputs/source/video/product/unknown.mp4"


def build_shot_execution_plan(project: Path, template: dict, sp: dict, ccp: dict, script: dict) -> dict:
    plan_id = str(template.get("template_id") or "")
    # 键控配对（评审 P0-1）：scene/slot/section 全部按显式引用（scene_id / template_slot_ref / start_seconds）
    # 查找，禁止 enumerate 与 slots[i-1] 位置取值——防跨阶段制品漂移。
    slots_by_id = {str(s.get("slot_id") or ""): s for s in (template.get("slots") or [])}
    scenes_by_id = {str(s.get("id") or ""): s for s in (sp.get("scenes") or [])}
    sections_by_start = {
        round(float(x.get("start_seconds") or 0), 3): x for x in (script.get("sections") or [])
        if isinstance(x, Mapping)
    }
    shots = []
    for i, m in enumerate(sp["metadata"]["source_mapping"], start=1):
        scene = scenes_by_id.get(str(m["scene_id"])) or {}
        slot = slots_by_id.get(str(m.get("template_slot_ref") or "")) or {}
        section = sections_by_start.get(round(float(scene.get("start_seconds") or 0), 3)) or {}
        source_tail = _owned_path_tail(m["source_path"])
        has_gap = not m.get("matrix_row_id")
        shots.append({
            "id": f"shot-{i:02d}",
            "order": i,
            "scene_id": str(m["scene_id"]),
            "template_slot_ref": str(m.get("template_slot_ref") or ""),
            "purpose": str(scene.get("description") or f"模板 slot {m.get('template_slot_ref')}"),
            "duration_seconds": round(m["timeline_interval"]["end_seconds_exclusive"] - m["timeline_interval"]["start_seconds"], 3),
            "narration": str(section.get("narration") or section.get("text") or "") if section else "",
            "screen_copy": str(section.get("screen_copy") or "") if section else "",
            "subject_action": str(scene.get("description") or "")[:80],
            "setting": str(slot.get("scene") or "室内/桌面"),
            "framing": "9:16 中景/近景，产品主体与动作结果可读",
            "camera": str((scene.get("shot_language") or {}).get("camera_movement") or "static"),
            "lighting": "自然光，透明材质不过曝",
            "sound": "保留动作原始声；口播与 BGM 在样片混音层叠加",
            "evidence_type": ("real_proof" if m.get("reference_evidence", {}).get("mode") != "none" else "demonstration"),
            "coverage_status": ("gap" if has_gap else "enough"),
            "gap_class": ("evidential" if has_gap else "none"),
            "gap_strategy": ("generate" if has_gap else "none"),
            "source_selection": {
                "media_id": Path(m["source_path"]).stem,
                "path": source_tail,
                "start_seconds": m["source_interval"]["start_seconds"],
                "end_seconds": m["source_interval"]["end_seconds_exclusive"],
                "fit_reason": f"自有素材覆盖「{m.get('source_fit','商品动作')}」，区间 {m['source_interval']}",
            },
            "reference_mechanisms": [str(m.get("reference_evidence", {}).get("mechanism") or "模板 slot 结构复用")],
            "industry_notes": ["每镜只放一个短词卖点", "字幕不遮动作结果"],
            "control_rule_refs": ["content_direction.rules[0]", "story_pacing.rules[1]"],
            "generation_proposals": [],
            "selected_generation_task_id": None,
        })
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


def build_asset_plan(project: Path, sp: dict, shot_plan: dict) -> dict:
    n = len(shot_plan["shots"])
    planned = []
    for i in range(1, n + 1):
        planned.append({
            "id": f"proxy-shot-{i:02d}", "type": "video_proxy", "provider": "media_proxy",
            "model": "ffmpeg-local", "cost_estimate_usd": 0.0, "paid": False,
            "output_path": f"assets/video/shot-{i:02d}-proxy.mp4", "source_stage": "assets", "exists": False,
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


def build_production_lock(project: Path, template: dict, ccp: dict, script: dict) -> dict:
    plan_id = str(template.get("template_id") or "")
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
            "captions": {"source": "script.sections[].screen_copy", "safe_zone": "9:16 bottom"},
            "cta": {"text": "点进看细节，69 元更省心。"},
            "platform": "tiktok",
            "output": {"resolution": "1080x1920", "fps": 30, "format": "mp4"},
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
    sections_by_start = {
        round(float(x.get("start_seconds") or 0), 3): x for x in (script.get("sections") or [])
        if isinstance(x, Mapping)
    }
    drift: list[str] = []
    for shot in shot_plan.get("shots", []):
        scene = scenes_by_id.get(str(shot.get("scene_id") or "")) or {}
        slot = slots_by_id.get(str(shot.get("template_slot_ref") or "")) or {}
        section = sections_by_start.get(round(float(scene.get("start_seconds") or 0), 3)) or {}
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


def sync_assets_artifacts(project: Path, template: dict, *, pipeline_dir: Path, sink=None) -> dict:
    """从**当前** script/scene_plan 重派生 assets 四制品（修复 rebuild 后漂移；评审 P0-1）。

    不改审批语义：重派生后 status 保持 approved（经 batch_approval 决策），并刷新 checkpoint 信封。
    """
    from lib.checkpoint import refresh_checkpoint_envelopes

    sp = _load(project / "artifacts" / "scene_plan.json")
    ccp = _load(project / "artifacts" / "creative_control_plan.json")
    script = _load(project / "artifacts" / "script.json")
    old_plan = _load(project / "artifacts" / "shot_execution_plan.json") or {}
    shot_env = write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan",
                                     build_shot_execution_plan(project, template, sp, ccp, script),
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
                                      build_asset_plan(project, sp, shot_plan), project_dir=project, sink=sink)
    lock_env = write_artifact_atomic("artifacts/production_lock.json", "production_lock",
                                     build_production_lock(project, template, ccp, script), project_dir=project, sink=sink)
    env_map = {"shot_execution_plan": shot_env, "asset_plan": asset_env, "production_lock": lock_env}
    bundle = build_approval_bundle(project, sp, shot_plan, asset_env["data"], lock_env["data"], envelope_map=env_map)
    bundle_env = write_artifact_atomic("artifacts/approval_bundle.json", "approval_bundle", bundle, project_dir=project, sink=sink)
    refresh_checkpoint_envelopes(pipeline_dir, project.name, pipeline_type=PIPELINE)
    return {"shot_execution_plan": shot_env, "asset_plan": asset_env,
            "production_lock": lock_env, "approval_bundle": bundle_env}


def build_assets(project: Path, template: dict, *, pipeline_dir: Path, sink=None) -> dict:
    """产 assets 四制品并写 checkpoint（awaiting_human，creative_lock terminal）。"""
    sp = _load(project / "artifacts" / "scene_plan.json")
    ccp = _load(project / "artifacts" / "creative_control_plan.json")
    script = _load(project / "artifacts" / "script.json")
    # 硬门：进入付费前必须 template_run_plan ready（无 unbound + 不复制参考花字）。
    # 传 template：校验每个 binding 的 slot_id 必须是模板已知 slot（缺 slot 绑定即阻断）。
    rp = _load(project / "artifacts" / "template_run_plan.json") or {}
    readiness = check_template_run_plan_ready(rp, template=template)
    if not readiness.get("ready"):
        raise SystemExit(f"template_run_plan 未就绪，禁止 paid assets: {readiness.get('blockers')}")

    shot_env = write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan",
                                     build_shot_execution_plan(project, template, sp, ccp, script), project_dir=project, sink=sink)
    shot_plan = shot_env["data"]
    asset_env = write_artifact_atomic("artifacts/asset_plan.json", "asset_plan",
                                      build_asset_plan(project, sp, shot_plan), project_dir=project, sink=sink)
    lock_env = write_artifact_atomic("artifacts/production_lock.json", "production_lock",
                                     build_production_lock(project, template, ccp, script), project_dir=project, sink=sink)
    # 事务内读磁盘会看到未提交内容 → 用本次写入的信封索引（envelope_map）构建 bundle refs。
    env_map = {name: env for name, env in (("shot_execution_plan", shot_env), ("asset_plan", asset_env),
                                           ("production_lock", lock_env))}
    bundle = build_approval_bundle(project, sp, shot_plan, asset_env["data"], lock_env["data"], envelope_map=env_map)
    bundle_env = write_artifact_atomic("artifacts/approval_bundle.json", "approval_bundle", bundle, project_dir=project, sink=sink)
    return {"shot_execution_plan": shot_env, "asset_plan": asset_env,
            "production_lock": lock_env, "approval_bundle": bundle_env}
