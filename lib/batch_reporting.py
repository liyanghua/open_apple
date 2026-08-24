"""Deterministic batch run/quality report builders (read-only, no generation).

Both builders are pure functions of persisted facts: candidate index, candidate
events/cost/checkpoint/evaluation artifacts, and operator reviews. They never
call TTS/music/VLM/render tools and never mutate candidate state. Semantic
idempotency is guaranteed by canonical source hashing (input_hashes); rebuilding
the same inputs yields byte-identical content.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib.artifact_hashing import semantic_sha256
from lib.candidate_diversity import compare_candidate_pair


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _count_events(events_path: Path) -> int:
    if not events_path.exists():
        return 0
    try:
        return sum(1 for _ in events_path.open(encoding="utf-8"))
    except OSError:
        return 0


def _read_events(events_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    except OSError:
        pass
    return rows


def _cost_path(child_dir: Path) -> Path:
    root_path = child_dir / "cost_log.json"
    return root_path if root_path.exists() else child_dir / "artifacts" / "cost_log.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _batch_dir(batch_dir: str | Path) -> Path:
    return Path(batch_dir)


def _candidates(batch_dir: Path) -> list[dict[str, Any]]:
    index = _read_json(batch_dir / "artifacts" / "candidate_batch.json")
    if not isinstance(index, Mapping):
        return []
    return [c for c in (index.get("candidates") or []) if isinstance(c, Mapping)]


def _child_dir(batch_dir: Path, candidate: Mapping[str, Any]) -> Path:
    project_id = str(candidate.get("project_id") or candidate.get("candidate_id") or "")
    root = batch_dir.parent.resolve()
    try:
        child = (root / project_id).resolve()
        child.relative_to(root)
        return child
    except (ValueError, OSError):
        return root / "__invalid_candidate__"


def _scoped_eval(child_dir: Path) -> dict[str, Any] | None:
    """Return the final-scope evaluation report, but merge in the sample-scope
    VLM creative_advisory when the final report itself has none (the final
    technical_validator does not run video_judge).

    The merge is provenance-gated: it only happens when the sample report is
    genuinely ``scope == "sample"`` and carries a valid ``subject_hash``, and
    the merged summary is explicitly tagged as sample-scope (never presented as
    a final quality conclusion). A provenance mismatch leaves the final report
    unscored, which surfaces as an honest ``vlm_not_scored``."""
    final = None
    for name in ("evaluation_report.final.json", "evaluation_report.json", "evaluation_report.sample.json"):
        data = _read_json(child_dir / "artifacts" / name)
        if isinstance(data, dict) and final is None:
            final = data
    if final is None:
        return None
    advisory = final.get("creative_advisory") if isinstance(final.get("creative_advisory"), Mapping) else {}
    if not (isinstance(advisory, Mapping) and advisory and advisory.get("scored")):
        for name in ("evaluation_report.json", "evaluation_report.sample.json"):
            sample = _read_json(child_dir / "artifacts" / name)
            if not isinstance(sample, dict):
                continue
            sample_advisory = sample.get("creative_advisory")
            if not (isinstance(sample_advisory, Mapping) and sample_advisory and sample_advisory.get("scored")):
                continue
            # provenance：sample 作用域 + 有效 subject_hash，才允许派生展示
            scope = str(sample.get("scope") or "sample")
            subject_hash = sample.get("subject_hash")
            if scope != "sample" or not (isinstance(subject_hash, str) and re.fullmatch(r"[a-fA-F0-9]{64}", subject_hash)):
                continue
            merged = dict(final)
            merged_advisory = dict(sample_advisory)
            merged_advisory["summary"] = f"【样片作用域 VLM，非成片】{sample_advisory.get('summary') or ''}"
            merged["creative_advisory"] = merged_advisory
            return merged
    return final


def _collect_source_refs(batch_dir: Path, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect source refs + input hashes for deterministic idempotency."""
    refs: list[dict[str, Any]] = []
    input_parts: dict[str, Any] = {}

    index_path = batch_dir / "artifacts" / "candidate_batch.json"
    if index_path.exists():
        refs.append({"kind": "candidate_batch", "path": index_path.name,
                     "sha256": _sha256_file(index_path), "record_count": len(candidates)})
        input_parts["candidate_batch"] = _sha256_file(index_path)

    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        child_dir = _child_dir(batch_dir, candidate)
        events_path = child_dir / "events.jsonl"
        events_count = _count_events(events_path)
        if events_path.exists():
            refs.append({"kind": "events", "path": f"{child_dir.name}/events.jsonl",
                         "sha256": _sha256_file(events_path), "record_count": events_count})
            input_parts[f"events:{candidate_id}"] = _sha256_file(events_path)
        eval_data = _scoped_eval(child_dir)
        if isinstance(eval_data, dict):
            input_parts[f"evaluation:{candidate_id}"] = semantic_sha256(eval_data)
        cost_path = _cost_path(child_dir)
        if cost_path.exists():
            refs.append({"kind": "cost_log", "path": str(cost_path.relative_to(batch_dir.parent)),
                         "sha256": _sha256_file(cost_path), "record_count": 1})
            input_parts[f"cost:{candidate_id}"] = _sha256_file(cost_path)
        plan_path = child_dir / "artifacts" / "candidate_variant_plan.json"
        if plan_path.exists():
            input_parts[f"variant_plan:{candidate_id}"] = _sha256_file(plan_path)
    return refs, input_parts


def _load_variant_plans(batch_dir: Path, candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        plan = _read_json(_child_dir(batch_dir, candidate) / "artifacts" / "candidate_variant_plan.json")
        if isinstance(plan, dict):
            plans[candidate_id] = plan
    return plans


def build_batch_run_report(
    batch_dir: str | Path,
    *,
    run_id: str | None = None,
    rubric_version: str = "1.0",
) -> dict[str, Any]:
    """Build a deterministic batch_run_report from persisted facts."""
    batch_dir = _batch_dir(batch_dir)
    batch_id = batch_dir.name
    candidates = _candidates(batch_dir)
    refs, input_hashes = _collect_source_refs(batch_dir, candidates)

    warnings: list[dict[str, Any]] = []
    total_cost = 0.0
    cycles: list[dict[str, Any]] = []
    stage_rows: dict[str, dict[str, Any]] = defaultdict(lambda: {"wall": 0.0, "active": 0.0, "runs": set()})
    run_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    provider_rows: dict[tuple[str, str | None], dict[str, Any]] = defaultdict(lambda: {"count": 0, "cost": 0.0})
    cost_log_count = 0
    event_count = 0
    cache_hits = cache_misses = 0
    min_ts: float | None = None
    max_ts: float | None = None
    missing_ts = 0

    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        status = str(candidate.get("status") or "planned")
        attempts = int(candidate.get("attempts") or 0)
        index_cost = float(candidate.get("cost_usd") or 0.0)
        cycles.append({"candidate_id": candidate_id, "attempts": attempts, "status": status})
        child_dir = _child_dir(batch_dir, candidate)
        events = _read_events(child_dir / "events.jsonl")
        event_count += len(events)
        if not events:
            warnings.append({"code": "missing_events", "message": "候选无运行事件", "candidate_id": candidate_id})
        cost_log = _read_json(_cost_path(child_dir))
        log_cost = 0.0
        if isinstance(cost_log, Mapping):
            cost_log_count += 1
            log_cost = float(cost_log.get("total_cost_usd") or cost_log.get("budget_spent_usd") or 0.0)
            if abs(log_cost - index_cost) > 1e-6:
                warnings.append({"code": "cost_mismatch", "message": "cost_log 与 candidate_batch 不一致", "candidate_id": candidate_id})
        total_cost += log_cost if isinstance(cost_log, Mapping) else index_cost
        for event in events:
            ts_raw = event.get("ts")
            if isinstance(ts_raw, str):
                try:
                    ts_val = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
                    min_ts = ts_val if min_ts is None else min(min_ts, ts_val)
                    max_ts = ts_val if max_ts is None else max(max_ts, ts_val)
                except ValueError:
                    missing_ts += 1
            else:
                missing_ts += 1
            if event.get("event") == "cache_hit": cache_hits += 1
            elif event.get("event") == "cache_miss": cache_misses += 1
            if event.get("event") == "finish":
                key = (str(event.get("provider") or event.get("tool") or "unknown"), event.get("model"))
                provider_rows[key]["count"] += 1
                provider_rows[key]["cost"] += float(event.get("cost_usd") or 0.0)
            if event.get("schema_version") == "1.0" and event.get("run_id"):
                run_rows[str(event["run_id"])].append(event)

    for run_id_value, rows in run_rows.items():
        terminal = next((row for row in reversed(rows) if row.get("status") in {"succeeded", "failed", "cancelled"}), rows[-1])
        stage = str(terminal.get("stage") or "unknown")
        if stage == "unknown":
            stage = str(terminal.get("operation") or "unknown")
        machine_seconds = max(float(row.get("machine_ms") or 0) for row in rows) / 1000.0
        stage_rows[stage]["wall"] += machine_seconds
        stage_rows[stage]["active"] += machine_seconds
        stage_rows[stage]["runs"].add(run_id_value)

    # Some historical runs have no persisted CostTracker file, but their
    # terminal tool events still carry actual provider cost. Prefer that
    # observed spend over a misleading zero from the legacy candidate index.
    provider_cost_total = sum(row["cost"] for row in provider_rows.values())
    if cost_log_count == 0 and provider_cost_total > total_cost:
        total_cost = provider_cost_total

    if event_count == 0:
        warnings.append({"code": "missing_events", "message": "全批无运行事件"})
    if missing_ts:
        warnings.append({"code": "missing_timestamps", "message": f"{missing_ts} 条事件缺少/无法解析时间戳，wall_seconds 可能被低估"})

    data_quality = {"status": "complete", "warnings": []}
    if warnings:
        data_quality = {"status": "partial", "warnings": warnings}

    wall_seconds = max(0.0, (max_ts - min_ts)) if min_ts is not None and max_ts is not None else 0.0
    return {
        "version": "1.0",
        "batch_id": batch_id,
        "run_id": run_id or f"run-{batch_id}",
        "report_revision": 1,
        "generated_at": _now_iso(),
        "input_hashes": input_hashes,
        "rubric_version": rubric_version,
        "source_refs": refs,
        "data_quality": data_quality,
        "timing": {"queue_seconds": 0.0,
                   "active_seconds": round(sum(row["active"] for row in stage_rows.values()), 3),
                   "human_wait_seconds": round(sum(float(event.get("approval_wait_ms") or 0) / 1000 for rows in run_rows.values() for event in rows), 3),
                   "wall_seconds": round(wall_seconds, 3)},
        "stages": [{"stage_id": sid, "wall_seconds": round(row["wall"], 3), "active_seconds": round(row["active"], 3), "attempts": len(row["runs"])}
                   for sid, row in sorted(stage_rows.items())],
        "provider_calls": [{"provider": provider, "model": model, "count": row["count"], "cost_usd": round(row["cost"], 6)}
                            for (provider, model), row in sorted(provider_rows.items())],
        "cache": {"hits": cache_hits, "misses": cache_misses,
                  "rate": (cache_hits / (cache_hits + cache_misses)) if (cache_hits + cache_misses) else 0.0},
        "concurrency": {"max_parallel": int((_read_json(batch_dir / "artifacts" / "candidate_batch.json") or {}).get("concurrency", {}).get("max_parallel", 1))},
        # 吞吐口径统一：candidates / wall-clock（端到端墙钟），不是各阶段 machine_ms 求和
        "throughput": {"candidates_per_hour": round(len(candidates) / (wall_seconds / 3600), 3) if wall_seconds > 0 and candidates else 0.0},
        "cost": {"total_usd": total_cost,
                 "per_candidate_usd": (total_cost / len(candidates)) if candidates else None},
        "candidate_cycles": cycles,
        "milestones": {"start_to_sample": None, "sample_to_selectable": None, "select_to_delivery": None},
    }


def build_batch_quality_report(
    batch_dir: str | Path,
    *,
    run_id: str | None = None,
    rubric_version: str = "1.0",
) -> dict[str, Any]:
    """Build a deterministic batch_quality_report from persisted facts."""
    batch_dir = _batch_dir(batch_dir)
    batch_id = batch_dir.name
    candidates = _candidates(batch_dir)
    refs, input_hashes = _collect_source_refs(batch_dir, candidates)
    variant_plans = _load_variant_plans(batch_dir, candidates)

    warnings: list[dict[str, Any]] = []
    quality_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        eval_data = _scoped_eval(_child_dir(batch_dir, candidate))
        status = "missing"
        blocking: list[str] = []
        next_action = "review"
        if isinstance(eval_data, dict):
            status = str(eval_data.get("status") or "missing")
            if status not in {"pass", "revise", "fail", "missing"}:
                status = "revise"
            hard_gate = eval_data.get("hard_gate") if isinstance(eval_data.get("hard_gate"), Mapping) else {}
            for chk in hard_gate.get("checks", []):
                if isinstance(chk, Mapping) and chk.get("status") == "fail":
                    blocking.append(str(chk.get("id") or chk.get("message") or ""))
            next_action = {"pass": "proceed", "revise": "repair", "fail": "reject", "missing": "review"}.get(status, "review")
        else:
            blocking.append("缺少评价报告")
            warnings.append({"code": "missing_evaluation", "message": "候选缺少评价报告",
                             "candidate_id": candidate_id})
        advisory = eval_data.get("creative_advisory") if isinstance(eval_data, Mapping) and isinstance(eval_data.get("creative_advisory"), Mapping) else {}
        if isinstance(eval_data, Mapping) and isinstance(advisory, Mapping) and advisory and advisory.get("scored") is False:
            warnings.append({"code": "vlm_not_scored", "message": "候选尚未完成 VLM 创意评分", "candidate_id": candidate_id})
        name_map = {"hook_clarity": "hook", "opening_alignment": "opening_alignment", "product_presence": "proof", "rhythm": "pacing", "text_readability": "readability", "visual_hierarchy": "diversity"}
        dimensions: dict[str, float] = {}
        for dimension in advisory.get("dimensions", []) if isinstance(advisory.get("dimensions"), list) else []:
            if isinstance(dimension, Mapping) and str(dimension.get("id")) in name_map and isinstance(dimension.get("score"), (int, float)):
                dimensions[name_map[str(dimension["id"])]] = float(dimension["score"])
        review_dir = _child_dir(batch_dir, candidate) / "operator" / "reviews"
        confirmations = None
        if review_dir.is_dir():
            approved = [_read_json(path) for path in sorted(review_dir.glob("*.json"))]
            approved = [item for item in approved if isinstance(item, Mapping) and item.get("kind") == "sample" and item.get("status") == "approved"]
            if approved:
                confirmations = approved[-1].get("effect_confirmation")
        repair_targets = eval_data.get("repair_targets") if isinstance(eval_data, Mapping) else None
        rework = None
        if isinstance(eval_data, Mapping) and (repair_targets or eval_data.get("rework_round")):
            rework = {"tags": [str(item) for item in repair_targets] if isinstance(repair_targets, list) else [], "rounds": int(eval_data.get("rework_round") or 0)}
        quality_candidates.append({
            "candidate_id": candidate_id,
            "status": status,
            "score": round(sum(dimensions.values()) / len(dimensions), 2) if dimensions else None,
            "vlm_dimensions": dimensions,
            "confirmations": dict(confirmations) if isinstance(confirmations, Mapping) else None,
            "blocking_items": blocking,
            "rework": rework,
            "next_action": next_action,
        })

    pairwise = []
    ids = sorted(variant_plans)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            pairwise.append(compare_candidate_pair(variant_plans[ids[i]], variant_plans[ids[j]]))

    recommendations = []
    for qc in quality_candidates:
        if qc["status"] == "fail":
            recommendations.append({"candidate_id": qc["candidate_id"], "action": "reject", "reason": "致命 L1a"})
        elif qc["status"] == "revise":
            recommendations.append({"candidate_id": qc["candidate_id"], "action": "repair", "reason": "可修复项"})
        elif qc["status"] == "missing":
            recommendations.append({"candidate_id": qc["candidate_id"], "action": "review", "reason": "缺评价"})

    data_quality = {"status": "complete", "warnings": []}
    if warnings:
        data_quality = {"status": "partial", "warnings": warnings}

    return {
        "version": "1.0",
        "batch_id": batch_id,
        "run_id": run_id or f"run-{batch_id}",
        "report_revision": 1,
        "generated_at": _now_iso(),
        "input_hashes": input_hashes,
        "rubric_version": rubric_version,
        "source_refs": refs,
        "data_quality": data_quality,
        "candidates": quality_candidates,
        "pairwise_diversity": pairwise,
        "human_review": {
            "selected_candidate_ids": [str(item) for item in ((_read_json(batch_dir / "artifacts" / "candidate_batch.json") or {}).get("selection", {}).get("selected_candidate_ids", []) or [])],
            "reason": str(((_read_json(batch_dir / "artifacts" / "candidate_batch.json") or {}).get("selection", {}) or {}).get("reason") or ""),
        },
        "recommendations": recommendations,
    }
