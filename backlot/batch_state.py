"""批级聚合状态（Batch_Workbench_Aggregate_State_Event_Contract v1.0）。

只读派生投影：candidate_batch 是批级索引/成员/预算/选择的事实来源；候选项目
的 checkpoint、stage rail、pending review、evaluation 与 sample trace 是候选
状态的事实来源。批动作必须先写事实来源再重算投影，绝不直接编辑投影字段。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backlot.state import load_board_state
from lib.artifact_hashing import semantic_sha256

BATCH_RAIL_PHASES = ("building", "sampling", "scoring", "selection", "editing", "publishing")
RAIL_LABELS = {
    "building": "建批",
    "sampling": "首轮样片",
    "scoring": "评分",
    "selection": "人工选择",
    "editing": "精剪",
    "publishing": "发布",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_child_dir(child_root: Path, project_id: str) -> Path | None:
    """Resolve a candidate path without allowing traversal outside projects."""
    try:
        candidate = (child_root / project_id).resolve()
        candidate.relative_to(child_root.resolve())
        return candidate
    except (ValueError, OSError):
        return None


def _child_revision_inputs(project_dir: Path, child_dir: Path) -> dict[str, Any] | None:
    """子项目 revision 输入：不存在 → None；project.json 缺失/损坏 → 抛异常。"""
    if not child_dir.is_dir():
        return None
    marker = child_dir / "project.json"
    if not marker.is_file():
        raise ValueError(f"candidate project marker missing: {child_dir.name}")
    marker_data = json.loads(marker.read_text(encoding="utf-8"))  # 损坏 → 抛异常
    if not isinstance(marker_data, dict) or not marker_data.get("project_id"):
        raise ValueError(f"candidate project marker invalid: {child_dir.name}")
    stages = {}
    for path in sorted(child_dir.glob("checkpoint_*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict) and raw.get("stage"):
            stages[str(raw["stage"])] = {
                "status": str(raw.get("status") or "unknown"),
                "version": max(0, int(raw.get("versions") or 0)),
                "updated_at": raw.get("timestamp"),
            }
    artifact_hashes = {}
    for name in ("evaluation_report.sample", "evaluation_report.final", "sample_execution_trace"):
        path = child_dir / "artifacts" / f"{name}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("semantic_sha256"):
                artifact_hashes[name] = data["semantic_sha256"]
    return {"stages": stages, "artifact_hashes": artifact_hashes}


def _planned_audio_tracks(child_dir: Path) -> list[dict[str, Any]]:
    """素材创意锁阶段的口播/BGM 计划轨（样片未生成时的三轨占位）。"""
    try:
        asset_plan = json.loads((child_dir / "artifacts" / "asset_plan.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    planned = {item.get("type"): True for item in asset_plan.get("planned_assets", [])}

    def track(kind: str, label: str, is_planned: bool) -> dict[str, Any]:
        return {
            "kind": kind,
            "label": label,
            "planned": is_planned,
            "present": False,
            "state": "planned" if is_planned else "not_planned",
        }

    return [
        track("narration", "口播", bool(planned.get("narration") or planned.get("narration_tts"))),
        track("bgm", "BGM", bool(planned.get("music"))),
        track("original", "原声", False),
    ]


def _gate_material(child_dir: Path, awaiting_stage: str) -> dict[str, Any] | None:
    """门复核材料：批页候选展开卡的内容来源（只读派生，无写入）。"""
    def artifact(name: str) -> dict[str, Any]:
        try:
            data = json.loads((child_dir / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    if awaiting_stage == "script":
        script = artifact("script")
        return {
            "kind": "script",
            "title": script.get("title") or "",
            "duration_seconds": script.get("total_duration_seconds"),
            "sections": [
                {"id": s.get("id"), "label": s.get("label"), "screen_copy": s.get("screen_copy")}
                for s in script.get("sections", [])
            ],
        }
    if awaiting_stage == "assets":
        script = artifact("script")
        scene_plan = artifact("scene_plan")
        asset_plan = artifact("asset_plan")
        lock = artifact("production_lock")
        locked = lock.get("locked_values") if isinstance(lock.get("locked_values"), dict) else {}
        tts = locked.get("tts") if isinstance(locked.get("tts"), dict) else {}
        bgm = locked.get("bgm") if isinstance(locked.get("bgm"), dict) else {}
        audio_plan = (script.get("metadata") or {}).get("audio_plan", {}) if isinstance(script.get("metadata"), Mapping) else {}
        narration = audio_plan.get("narration", {}) if isinstance(audio_plan, Mapping) else {}
        music = audio_plan.get("music", {}) if isinstance(audio_plan, Mapping) else {}
        planned = asset_plan.get("planned_assets", [])
        aspect = ""
        for scene in scene_plan.get("scenes", []):
            match = re.search(r"\d+:\d+", str(scene.get("framing", "")))
            if match:
                aspect = match.group(0)
                break
        return {
            "kind": "assets",
            "title": script.get("title") or "",
            "shots": [
                {"id": s.get("id"), "screen_copy": (s.get("overlay_layers") or [{}])[0].get("text") if s.get("overlay_layers") else ""}
                for s in scene_plan.get("scenes", [])
            ],
            "narration": {
                "provider": narration.get("provider") or tts.get("provider") or "doubao",
                "model": narration.get("resource_id") or tts.get("resource_id") or tts.get("model") or "seed-tts-2.0",
                "voice": narration.get("voice") or tts.get("voice") or "",
            },
            "bgm": {
                "provider": bgm.get("provider") or music.get("provider") or "",
                "profile": bgm.get("profile") or music.get("profile") or "",
            },
            "plan_summary": {
                "proxy_shots": sum(1 for item in planned if str(item.get("type", "")) in {"video_proxy", "video"}),
                "narration_segments": sum(1 for item in planned if str(item.get("type", "")) in {"narration", "narration_tts"}),
                "music_tracks": sum(1 for item in planned if str(item.get("type", "")) == "music"),
                "paid_estimate_usd": round(sum(float(item.get("cost_estimate_usd", 0)) for item in planned), 4),
            },
            "lock": {
                "platform": locked.get("platform") or "",
                "engine": locked.get("render_runtime") or "",
                "output": locked.get("output") or {},
                "aspect": aspect,
                "duration_seconds": script.get("total_duration_seconds"),
            },
        }
    if awaiting_stage == "sample":
        report = artifact("sample_report")
        probe = report.get("probe") if isinstance(report.get("probe"), Mapping) else {}
        return {
            "kind": "sample",
            "output_path": report.get("output_path") or "",
            "probe": probe,
            "qa": report.get("qa") or {},
        }
    return None


def child_snapshot(project_dir: Path, child_dir: Path) -> dict[str, Any]:
    """读取一个候选子项目的快照（stages/reviews/评价/音轨/样片链接/revision）。"""
    snapshot: dict[str, Any] = {
        "exists": False,
        "corrupt": False,
        "child_revision": None,
        "stage_states": [],
        "pending_reviews": [],
        "preview_url": None,
        "evaluation": None,
        "audio_tracks": [],
        "gate_material": None,
    }
    inputs = None
    try:
        inputs = _child_revision_inputs(project_dir, child_dir)
    except Exception:
        snapshot["corrupt"] = True
    if inputs is None:
        return snapshot
    snapshot["exists"] = True
    snapshot["child_revision"] = _sha256(_canonical(inputs))
    for stage_id, state in sorted(inputs["stages"].items()):
        snapshot["stage_states"].append({
            "stage_id": stage_id,
            "status": state["status"],
            "version": state["version"],
            "updated_at": state["updated_at"],
        })
    try:
        board = load_board_state(child_dir)
    except Exception:
        snapshot["corrupt"] = True
        return snapshot
    renders = (board.get("media") or {}).get("renders") if isinstance(board.get("media"), Mapping) else []
    render = next(
        (item for item in renders if isinstance(item, Mapping) and "sample" in str(item.get("path", "")).lower()),
        None,
    )
    if render:
        from backlot.operator_state import _media_url

        snapshot["preview_url"] = _media_url(child_dir.name, render.get("path"))
    artifacts = board.get("artifacts") if isinstance(board.get("artifacts"), Mapping) else {}
    eval_report = artifacts.get("evaluation_report.sample") or artifacts.get("evaluation_report")
    if isinstance(eval_report, Mapping) and eval_report.get("scope") == "sample":
        from backlot.operator_state import _evaluation_summary

        snapshot["evaluation"] = _evaluation_summary(eval_report)
    from backlot.operator_state import _audio_tracks

    trace = artifacts.get("sample_execution_trace")
    snapshot["audio_tracks"] = _audio_tracks(trace) if isinstance(trace, Mapping) else _planned_audio_tracks(child_dir)
    awaiting_stage = next(
        (item["stage_id"] for item in snapshot["stage_states"] if item["status"] == "awaiting_human"),
        None,
    )
    if awaiting_stage in {"script", "assets", "sample"}:
        # 只读投影：不在此创建 review（那是写路径 batch_actions/reviews 的职责）。
        # Gallery 只读入口可直接复用，避免在读取时产生写副作用。
        snapshot["gate_material"] = _gate_material(child_dir, awaiting_stage)
    reviews_dir = child_dir / "operator" / "reviews"
    if reviews_dir.is_dir():
        for path in sorted(reviews_dir.glob("*.json")):
            try:
                review = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(review, dict) or review.get("status") != "awaiting_human":
                continue
            snapshot["pending_reviews"].append({
                "review_id": review.get("review_id"),
                "kind": review.get("kind"),
                "subject_version": review.get("subject_version"),
                "subject_hash": review.get("subject_hash"),
                "actions": ["批准", "拒绝"],
            })
    # schema 1.1 业务字段（纯派生；reviews 只读）
    from backlot.operator_reviews import ReviewService

    _svc = ReviewService(child_dir)
    _by_kind: dict[str, list[dict]] = {}
    for _r in _svc.list():
        _by_kind.setdefault(str(_r.get("kind") or ""), []).append(_r)
    _eval = None
    try:
        _eval = __import__("json").loads(
            (child_dir / "artifacts" / "evaluation_report.json").read_text(encoding="utf-8"))
    except Exception:
        _eval = None
    snapshot.update(derive_candidate_business(
        snapshot, reviews_by_kind=_by_kind, evaluate=_eval,
        media_ready=bool((snapshot.get("media") or {}).get("sample_url"))))

    return snapshot


def candidate_phase_for(status: str, snapshot: dict[str, Any]) -> str:
    """候选相位机器值（契约 §2.2）；status 保留 candidate_batch 原始值。"""
    if snapshot.get("corrupt"):
        return "corrupt"
    if not snapshot.get("exists"):
        return "missing"
    stage_statuses = {item["stage_id"]: item["status"] for item in snapshot["stage_states"]}
    if stage_statuses.get("publish") == "completed":
        return "published"
    if stage_statuses.get("compose") == "completed":
        return "composed"
    if status == "selected_for_edit":
        return "selected"
    if stage_statuses.get("edit") == "completed":
        return "editing"
    if status == "evaluated":
        return "evaluated"
    if stage_statuses.get("sample") == "completed" or status == "sampled":
        return "sampled"
    if status == "failed":
        return "failed"
    if status == "in_progress":
        return "sampling"
    return "planned"


def compute_phase(
    views: list[dict[str, Any]],
    selected_ids: list[str],
    blocked_reasons: list[str],
) -> tuple[str, str]:
    """相位归约（契约 §3）+ 人读理由。失败/缺失候选不阻塞相位推进。"""
    alive = [view for view in views if view["candidate_phase"] not in {"failed", "missing", "corrupt"}]
    if not alive:
        return "blocked", "没有可选候选：" + ("；".join(blocked_reasons[:2]) or "全部失败/缺失")
    if "over_budget" in blocked_reasons:
        return "blocked", "预算超限，阻止继续推进"
    phases = {view["candidate_phase"] for view in alive}
    if not selected_ids:
        if phases <= {"evaluated"}:
            return "selection", "全部存活候选已评分，等待人工选择"
        if phases <= {"sampled", "evaluated", "failed"} and "sampled" in phases:
            return "scoring", "候选已有样片，等待评分"
        # P1-4: 乱序成片（无选择即已完成 compose/publish）不再回退 sampling。
        if phases <= {"published"}:
            return "completed", "全部存活候选已发布"
        if phases <= {"composed", "published", "evaluated"} and "composed" in phases:
            return "selection", "候选已全部成片，等待人工选择（精剪/发布对象）"
        return "sampling", "至少一个候选尚未完成样片"
    selected = [view for view in views if view["candidate_id"] in selected_ids]
    if all(view["candidate_phase"] == "published" for view in selected):
        return "completed", "全部选中候选已发布"
    if all(view["candidate_phase"] in {"composed", "published"} for view in selected):
        return "publishing", "选中候选已完成成片，等待发布"
    return "editing", "选中候选进入精剪"


def aggregate_revision(
    batch_generation_id: str,
    candidates_summary: list[dict[str, Any]],
    selection: Mapping[str, Any],
    budget_summary: Mapping[str, Any],
    facts: Mapping[str, Any] | None = None,
) -> str:
    return _sha256(_canonical({
        "batch_generation_id": batch_generation_id,
        "candidates": candidates_summary,
        "selection": selection,
        "budget_summary": budget_summary,
        "facts": dict(facts or {}),
    }))


def build_batch_review_data(board: Mapping[str, Any], batch: Mapping[str, Any]) -> dict[str, Any]:
    """按契约 §2 组装 batch_review 载荷。"""
    project_dir = board.get("_project_dir") if isinstance(board.get("_project_dir"), Path) else Path.cwd()
    batch_id = str(batch.get("batch_id") or board.get("project_id") or "batch")
    candidates = [
        candidate for candidate in (batch.get("candidates") or [])
        if isinstance(candidate, Mapping)
    ]
    child_root = project_dir.parent
    warnings: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    read_inputs: dict[str, Any] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        project_id = str(candidate.get("project_id") or candidate_id)
        child_dir = _safe_child_dir(child_root, project_id)
        if child_dir is None:
            child_dir = child_root / "__invalid_candidate__"
            warnings.append({
                "code": "candidate_path_invalid",
                "candidate_id": candidate_id,
                "description": f"候选项目路径越界：{project_id}",
                "suggested_action": "修正 candidate_batch.project_id",
            })
        snapshot = child_snapshot(project_dir, child_dir)
        read_inputs[candidate_id] = snapshot.get("child_revision")
        phase = candidate_phase_for(str(candidate.get("status") or "planned"), snapshot)
        if phase == "missing":
            warnings.append({
                "code": "candidate_missing",
                "candidate_id": candidate_id,
                "description": f"候选项目 {project_id} 缺失",
                "suggested_action": "重新分叉该候选或从批中移除",
            })
        elif phase == "corrupt":
            warnings.append({
                "code": "candidate_corrupt",
                "candidate_id": candidate_id,
                "description": f"候选项目 {project_id} 制品损坏或不可读",
                "suggested_action": "检查候选项目 artifacts/checkpoint 后重试",
            })
        views.append({
            "candidate_id": candidate_id,
            "project_id": project_id,
            "label": str(candidate.get("label") or candidate_id),
            "direction": dict(candidate.get("direction") or {}),
            "status": str(candidate.get("status") or "planned"),
            "candidate_phase": phase,
            "child_revision": snapshot.get("child_revision"),
            "stage_states": snapshot.get("stage_states") or [],
            "pending_reviews": snapshot.get("pending_reviews") or [],
            "gate_material": snapshot.get("gate_material"),
            "score": {
                "dimension_scores": candidate.get("dimension_scores"),
                "weighted_total": candidate.get("weighted_total"),
                "evaluation": snapshot.get("evaluation"),
            },
            "media": {
                "sample_url": snapshot.get("preview_url"),
                "audio_tracks": snapshot.get("audio_tracks") or [],
            },
            "cost": {
                "cost_usd": float(candidate.get("cost_usd") or 0),
                "attempts": int(candidate.get("attempts") or 0),
            },
            "links": {"project_page": f"/p/{project_id}"},
            "failure": {
                "failure": candidate.get("failure"),
                "technical": bool(candidate.get("failure")) and str(candidate.get("status")) == "failed",
            },
        })

    # 一致性：候选 revision 二次读取复核（unstable）；缺失/损坏/预算不一致（degraded）。
    consistency = "stable"
    for candidate_id, first_revision in read_inputs.items():
        project_id = next(
            (str(c.get("project_id") or c.get("candidate_id")) for c in candidates
             if str(c.get("candidate_id") or "") == candidate_id),
            candidate_id,
        )
        try:
            safe_dir = _safe_child_dir(child_root, project_id)
            second = child_snapshot(project_dir, safe_dir).get("child_revision") if safe_dir else None
        except Exception:
            second = first_revision
        if second != first_revision:
            consistency = "unstable"
            break

    cost = board.get("cost") if isinstance(board.get("cost"), Mapping) else {}
    tracker_spent = cost.get("total_spent_usd")
    index_spent = sum(float(candidate.get("cost_usd") or 0) for candidate in candidates)
    budget = batch.get("budget") if isinstance(batch.get("budget"), Mapping) else {}
    max_cost = budget.get("max_cost_usd")
    source = "cost_tracker" if isinstance(tracker_spent, (int, float)) else "candidate_batch"
    spent = float(tracker_spent) if isinstance(tracker_spent, (int, float)) else index_spent
    # 缺失/损坏候选本身即降级（契约 §4/§6：不可静默删除候选）。
    if any(w["code"] in {"candidate_missing", "candidate_corrupt"} for w in warnings):
        if consistency != "unstable":
            consistency = "degraded"
    if isinstance(tracker_spent, (int, float)) and abs(float(tracker_spent) - index_spent) > 0.005:
        if consistency != "unstable":
            consistency = "degraded"
        warnings.append({
            "code": "budget_mismatch",
            "candidate_id": None,
            "description": f"cost_tracker（{tracker_spent}）与候选索引合计（{index_spent}）不一致",
            "suggested_action": "以 cost_tracker 为准，检查候选成本回写",
        })
    over_budget = isinstance(max_cost, (int, float)) and spent > float(max_cost)
    if over_budget:
        if consistency == "stable":
            consistency = "degraded"
        warnings.append({
            "code": "over_budget",
            "candidate_id": None,
            "description": f"已花费 {spent} 超过预算 {max_cost}",
            "suggested_action": "停止新付费调用或提高预算",
        })

    selection = batch.get("selection") if isinstance(batch.get("selection"), Mapping) else {}
    selected_ids = [str(item) for item in (selection.get("selected_candidate_ids") or [])]
    # Keep the UI's selectable set aligned with the API's hard quality gate.
    # Import lazily to avoid the batch_actions -> batch_state import cycle.
    from backlot.batch_actions import selection_quality_failures

    for view, candidate in zip(views, candidates):
        candidate_dir = _safe_child_dir(child_root, view["project_id"]) or (child_root / "__invalid_candidate__")
        view["selection_quality_failures"] = selection_quality_failures(
            batch, candidate, candidate_dir
        )
    # 差异度矩阵：从每个候选的 candidate_variant_plan 计算 pairwise 差异（eligible 集由此派生）。
    from lib.candidate_diversity import compare_candidate_pair
    variant_plans: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        candidate_dir = _safe_child_dir(child_root, str(candidate.get("project_id") or candidate_id))
        if candidate_dir is None:
            continue
        plan_path = candidate_dir / "artifacts" / "candidate_variant_plan.json"
        if plan_path.exists():
            try:
                variant_plans[candidate_id] = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
    pairwise = []
    ids = sorted(variant_plans)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            pairwise.append(compare_candidate_pair(variant_plans[ids[i]], variant_plans[ids[j]]))
    diversity = {
        "mode": batch.get("diversity_mode") or "legacy_read_only",
        "plans_present": len(variant_plans),
        "plans_missing": [str(c.get("candidate_id")) for c in candidates if str(c.get("candidate_id")) not in variant_plans],
        "pairwise": pairwise,
    }
    pairwise_blocked_ids: set[str] = set()
    if str(batch.get("diversity_mode") or "legacy_read_only") == "hard_gate":
        for result in pairwise:
            if not result.get("passes"):
                pairwise_blocked_ids.update({str(result.get("candidate_a") or ""), str(result.get("candidate_b") or "")})
    # 报告投影：只读批根 artifacts 下的 batch_run_report / batch_quality_report。
    reports = {"run": None, "quality": None, "status": "missing", "warnings": []}
    run_path = project_dir / "artifacts" / "batch_run_report.json"
    if run_path.exists():
        try:
            rr = json.loads(run_path.read_text(encoding="utf-8"))
            stages = rr.get("stages") if isinstance(rr.get("stages"), list) else []
            slowest = max(
                (s for s in stages if isinstance(s, Mapping) and s.get("wall_seconds")),
                key=lambda s: float(s.get("wall_seconds") or 0.0),
                default=None,
            )
            reports["run"] = {
                "data_quality": rr.get("data_quality"),
                "cost": rr.get("cost"),
                "throughput": rr.get("throughput"),
                "milestones": rr.get("milestones"),
                "slowest_stage": {"stage_id": slowest.get("stage_id"), "wall_seconds": slowest.get("wall_seconds")} if isinstance(slowest, Mapping) else None,
                "rubric_version": rr.get("rubric_version"),
                "generated_at": rr.get("generated_at"),
            }
        except (OSError, json.JSONDecodeError):
            reports["warnings"].append("batch_run_report 不可读")
    quality_path = project_dir / "artifacts" / "batch_quality_report.json"
    if quality_path.exists():
        try:
            qr = json.loads(quality_path.read_text(encoding="utf-8"))
            reports["quality"] = {
                "data_quality": qr.get("data_quality"),
                "rubric_version": qr.get("rubric_version"),
                "recommendations": qr.get("recommendations"),
                "generated_at": qr.get("generated_at"),
            }
        except (OSError, json.JSONDecodeError):
            reports["warnings"].append("batch_quality_report 不可读")
    if reports["run"] is not None and reports["quality"] is not None:
        statuses = {
            (reports["run"].get("data_quality") or {}).get("status"),
            (reports["quality"].get("data_quality") or {}).get("status"),
        }
        reports["status"] = "degraded" if "degraded" in statuses else ("partial" if "partial" in statuses else "complete")
    elif reports["run"] is not None or reports["quality"] is not None:
        reports["status"] = "partial"
    # P2/Task7-4: 报告缺失/降级时给出恢复动作，禁止 UI 伪报“完成”。
    if reports["status"] == "missing":
        reports["recovery_action"] = "rebuild_reports"
        reports["disabled_actions"] = ["select", "publish"]
    elif reports["status"] in {"partial", "degraded"}:
        reports["recovery_action"] = "backfill_reports"
        reports["disabled_actions"] = ["select", "publish"]
    else:
        reports["recovery_action"] = None
        reports["disabled_actions"] = []
    blocked_reasons = [w["code"] for w in warnings if w["code"] == "over_budget"]
    phase, phase_reason = compute_phase(views, selected_ids, blocked_reasons)
    awaiting_assets = any(
        item.get("stage_id") == "assets" and item.get("status") == "awaiting_human"
        for view in views for item in view["stage_states"]
    )
    if phase == "sampling" and awaiting_assets:
        phase_reason = (
            "素材创意锁待批准：请展开下方候选复核口播/BGM/素材计划，"
            "然后点击「一键全部通过」。批准前不会生成样片，样片区域为空属正常。"
        )

    budget_summary = {"spent_usd": spent, "over_budget": over_budget, "source": source}
    generation_id = "none"
    try:
        from backlot.project_commit import ProjectCommitStore

        store = ProjectCommitStore(project_dir)
        pointer = store._read_pointer()
        if isinstance(pointer, dict) and pointer.get("generation_id"):
            generation_id = str(pointer["generation_id"])
    except Exception:
        pass
    revision = aggregate_revision(
        generation_id,
        [
            {
                "candidate_id": view["candidate_id"],
                "project_id": view["project_id"],
                "child_revision": view["child_revision"],
                "candidate_phase": view["candidate_phase"],
            }
            for view in views
        ],
        {"selected_candidate_ids": selected_ids, "reason": selection.get("reason")},
        budget_summary,
        {
            "diversity": diversity,
            "reports": reports,
        },
    )

    concurrency = batch.get("concurrency") if isinstance(batch.get("concurrency"), Mapping) else {}
    active = [
        view["candidate_id"] for view in views
        if view["candidate_phase"] in {"forking", "sampling", "evaluating", "editing"}
    ]
    rail = []
    current_index = BATCH_RAIL_PHASES.index(phase) if phase in BATCH_RAIL_PHASES else 0
    for index, rail_phase in enumerate(BATCH_RAIL_PHASES):
        rail.append({
            "phase": rail_phase,
            "label": RAIL_LABELS[rail_phase],
            "status": "completed" if index < current_index else ("current" if index == current_index else "pending"),
        })
    if phase in {"completed", "blocked"}:
        rail = [{**item, "status": "completed"} for item in rail]

    gates: list[dict[str, Any]] = []
    for gate, stage_id, review_kind, label in (
        ("script", "script", "script_lock", "剧本确认"),
        ("assets", "assets", "creative_lock", "素材创意确认"),
        ("sample", "sample", "sample", "样片效果确认"),
    ):
        gate_candidates = []
        for view in views:
            stage_awaiting = any(
                item.get("stage_id") == stage_id and item.get("status") == "awaiting_human"
                for item in view["stage_states"]
            )
            review_awaiting = any(
                item.get("kind") == review_kind for item in view["pending_reviews"]
            )
            if stage_awaiting or review_awaiting:
                gate_candidates.append({
                    "candidate_id": view["candidate_id"],
                    "project_id": view["project_id"],
                })
        gates.append({
            "gate": gate,
            "label": label,
            "stage": stage_id,
            "candidates": gate_candidates,
        })

    return {
        "schema_version": "1.0",
        "kind": "batch_review",
        "batch_id": batch_id,
        "aggregate_revision": revision,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "consistency": consistency,
        "phase": phase,
        "phase_reason": phase_reason,
        "rail": rail,
        "candidates": views,
        "budget": {
            "max_cost_usd": float(max_cost) if isinstance(max_cost, (int, float)) else None,
            "spent_usd": spent,
            "reserved_usd": 0.0,
            "remaining_usd": (
                float(max_cost) - spent if isinstance(max_cost, (int, float)) else None
            ),
            "over_budget": over_budget,
            "source": source,
        },
        "concurrency": {
            "max_parallel": int(concurrency.get("max_parallel", 3)),
            "active_count": len(active),
            "active_candidate_ids": active,
        },
        "selection": {
            "selected_candidate_ids": selected_ids,
            "selected_at": selection.get("selected_at"),
            "reason": str(selection.get("reason") or ""),
            "eligible_candidate_ids": [
                view["candidate_id"] for view in views
                if view["status"] == "evaluated"
                and view["candidate_phase"] not in {"missing", "corrupt"}
                and ((view.get("score") or {}).get("evaluation") or {}).get("status") != "fail"
                and not view.get("selection_quality_failures")
                and view["candidate_id"] not in pairwise_blocked_ids
            ],
        },
        "pending_gates": gates,
        "warnings": warnings,
        "diversity": diversity,
        "reports": reports,
    }


# ---------------------------------------------------------------------------
# 候选业务字段（schema 1.1，评审修正后定义；Selection 派生规则见 spec §5.1/§3.3）
# ---------------------------------------------------------------------------
GATE_KIND_BY_STAGE = {"script": "script_lock", "assets": "creative_lock", "sample": "sample"}
KIND_ORDER = ("script_lock", "creative_lock", "sample")


def derive_candidate_business(
    snapshot: dict,
    *,
    reviews_by_kind: dict[str, list[dict]],
    evaluate: dict | None = None,
    media_ready: bool = True,
) -> dict:
    """**纯派生**（无 fs/无写）：从已有快照+review 列表计算 schema 1.1 候选业务字段。

    workflow_revision：取「当前门」(script→assets→sample 顺序首个有 review 的门)
    的 subject_version（审批/内容版本，不是随产物变化的 child_revision）。
    selection_eligible：仅服务端派生——sample 门 approved 且评价报告存在（evaluate 非空）。
    """
    import re as _re

    awaiting = next((s.get("stage_id") for s in snapshot.get("stage_states", [])
                     if s.get("status") == "awaiting_human"), None)
    gate_kind = GATE_KIND_BY_STAGE.get(awaiting or "")
    chosen: dict | None = None
    chosen_kind: str | None = (gate_kind if gate_kind else None)
    if chosen_kind:
        items = [i for i in reviews_by_kind.get(chosen_kind, []) if i.get("status") == "awaiting_human"]
        chosen = items[-1] if items else None
    if chosen is None:
        # 无 pending：按门顺序取最近已决（approved/rejected，排除 status=superseded）
        for kind in KIND_ORDER:
            items = [i for i in reviews_by_kind.get(kind, [])
                     if i.get("status") in {"approved", "rejected"}]
            if not items:
                continue
            items.sort(key=lambda i: (str(i.get("decided_at") or ""), str(i.get("created_at") or ""),
                                      str(i.get("review_id") or "")))
            chosen = items[-1]
            chosen_kind = kind
            break
    subject_hash = chosen.get("subject_hash") if chosen else None
    workflow_revision = int(chosen.get("subject_version") or 0) if chosen else 0
    review_status = "not_ready"
    if chosen:
        review_status = {"awaiting_human": "awaiting_review", "approved": "approved",
                         "rejected": "needs_revision"}.get(chosen.get("status"), "awaiting_review")
    current_artifact = "none"
    if awaiting == "script":
        current_artifact = "script"
    elif awaiting == "assets":
        current_artifact = "production_plan"
    elif awaiting == "sample":
        current_artifact = "sample"
    elif snapshot.get("media"):
        current_artifact = "sample"
    eligible, block = False, None
    sample_review = [i for i in reviews_by_kind.get("sample", []) if i.get("status") == "approved"]
    if not sample_review:
        block = "尚未通过样片确认"
    elif not evaluate:
        block = "评分报告缺失或未生成"
    else:
        eligible = True
    return {
        "subject_hash": subject_hash,
        "workflow_revision": workflow_revision,
        "current_step": awaiting or str(snapshot.get("phase") or ""),
        "current_artifact": current_artifact,
        "review_status": review_status,
        "artifact_health": "ready" if media_ready else "missing",
        "preview_url": snapshot.get("preview_url"),
        "selection_eligible": eligible,
        "selection_block_reason": block,
    }
