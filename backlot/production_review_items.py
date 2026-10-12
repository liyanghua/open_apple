"""Read-only projection of indexed, hash-bound production records for review."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _file(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    path = root / value
    try:
        path.resolve().relative_to(root.resolve())
        return path if path.is_file() else None
    except (ValueError, OSError):
        return None


def _json(root: Path, value: Any) -> dict:
    path = _file(root, value)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path else {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _review_checks(checks: dict) -> dict:
    """Small typed UI facts from the detailed canonical quality report."""
    projected = {}
    for name, check in checks.items():
        observations = []
        for observation in check.get("observations", []):
            if not isinstance(observation, dict):
                continue
            motion = observation.get("motion") or {}
            action = observation.get("actual_action") or {}
            observations.append({
                "shot_id": str(observation.get("shot_id") or ""),
                "method": str(observation.get("method") or ""),
                "reason": str(observation.get("reason") or ""),
                "motion": {"verb": str(motion.get("verb") or ""), "visible_result": str(motion.get("visible_result") or "")},
                "actual_action": {"source_interval_seconds": action.get("source_interval_seconds"),
                                  "output_interval_seconds": action.get("output_interval_seconds")},
            })
        projected[name] = {"machine_status": check.get("machine_status", "not_run"),
                           "effective_status": check.get("effective_status", "not_run"),
                           "observations": observations}
    return projected


def _bound_visual_confirmations(root: Path, record: dict) -> list[str]:
    """Show a user's scoped visual decision only beside its exact media version."""
    artifacts = record.get("canonical_artifacts") or {}
    review = _json(root, artifacts.get("human_color_review"))
    render = record.get("render") or {}
    if (review.get("decision") != "accept_gray_towel_visual_for_bound_variants"
            or (review.get("reviewer") or {}).get("kind") != "human"):
        return []
    media_list = review.get("media")
    if not isinstance(media_list, list):
        return []
    bound = any(
        isinstance(media, dict) and (media.get("render") or {}).get("path") == render.get("path")
        and (media.get("render") or {}).get("sha256") == render.get("sha256")
        and media.get("reviewed_interval_seconds") == [11.37, 16.1]
        for media in media_list
    )
    return ["11.37 秒后的灰色毛巾已由你确认可接受；仅限此成片版本，其他商品画面仍需核看。"] if bound else []


def production_review_items(project_dir: Path, index: dict, notes: list) -> list[dict]:
    """Never advance checkpoints or transfer approval from a different render."""
    root = Path(project_dir)
    from backlot.operator_reviews import ReviewService
    from lib.production_evidence import quality_summary, verify_production_subject

    reviews = [r for r in ReviewService(root).list() if r.get("kind") in {"final_review", "opening_preview"}]
    structure_inventory = _json(root, "artifacts/review-20261010/structure_inventory.v1.json")
    structure_by_slot = {row.get("content_slot_id"): row for row in structure_inventory.get("entries", [])
                         if isinstance(row, dict) and isinstance(row.get("content_slot_id"), str)}
    scoped_feedback = _json(root, "artifacts/review-20261010/human_feedback.v1.json")
    feedback_current = (scoped_feedback.get("decision") == "conditional_creative_acceptance_rework_required"
                        and (scoped_feedback.get("reviewer") or {}).get("kind") == "human")
    results = []
    entries = index.get("items")
    entries = entries if isinstance(entries, list) else []
    if len(entries) > 3000:
        raise ValueError("Production review index exceeds the explicit 3000-candidate read limit")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = _json(root, entry.get("record_path"))
        slot = str(record.get("content_slot_id") or "")
        if not slot or slot != entry.get("id"):
            continue
        render = record.get("render") or {}
        if not isinstance(render, dict):
            continue
        sha = str(render.get("sha256") or "")
        video = _file(root, render.get("path"))
        valid = False
        if video and video.suffix.lower() in {".mp4", ".webm", ".mov"} and re.fullmatch(r"[a-f0-9]{64}", sha):
            try:
                with video.open("rb") as handle:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                    valid = digest.hexdigest() == sha
            except OSError:
                pass
        checks = record.get("checks") if valid and isinstance(record.get("checks"), dict) else {}
        matches = [r for r in reviews if r.get("subject_id") == slot
                   and (r.get("production_subject") or {}).get("record_path") == entry.get("record_path")]
        from lib.opening_review_scope import opening_review_scope
        from jsonschema import ValidationError
        opening, scope_error = None, None
        try:
            opening = opening_review_scope(root, record)
        except (ValueError, OSError, KeyError, TypeError, ValidationError):
            scope_error = "开场登记或依赖已失效"
        kind = None if scope_error else "opening_preview" if opening and opening["scope"] == "preview" else "final_review"
        latest = max((r for r in matches if r.get("kind") == kind),
                     key=lambda r: (r.get("subject_version", 0), r.get("created_at", "")), default=None)
        historical_binding = latest or (max(matches, key=lambda r: (r.get("created_at", ""), r.get("subject_version", 0)), default=None) if scope_error else None)
        review_valid = bool(valid and latest
                            and verify_production_subject(root, latest.get("production_subject") or {}))
        binding_status = "current" if review_valid else "scope_changed" if kind and matches and not latest else "pending"
        if historical_binding and not review_valid:
            binding_status = "insufficient_history"
            subject = historical_binding.get("production_subject") or {}
            for ref in [subject.get("render") or {}, *(subject.get("dependencies") or {}).values()]:
                path = _file(root, ref.get("path")) if isinstance(ref, dict) else None
                from lib.production_evidence import file_sha256
                if not path or file_sha256(path) != ref.get("sha256"):
                    binding_status = "changed"
                    break
        human_status = latest.get("status") if review_valid else "pending"
        qa = quality_summary(root, record)
        if not valid:
            qa["eligible"] = False
        structure = structure_by_slot.get(slot)
        if not (valid and isinstance(structure, dict) and structure.get("record_path") == entry.get("record_path")
                and structure.get("render_sha256") == sha):
            structure = None
        review_scope = None
        if structure and feedback_current:
            rework = [row.get("id") for row in scoped_feedback.get("rework_items", [])
                      if isinstance(row, dict) and slot in row.get("content_slot_ids", [])]
            if "opening_impact" in rework:
                review_scope = "其他已看过的表现项获条件通过；前三秒钩子待加强"
                if "odor_visual" in rework:
                    review_scope += "；防臭画面待加强"
        review = ({key: latest[key] for key in ("review_id", "kind", "subject_version", "subject_hash", "status")}
                        if review_valid else None)
        version_ref = f"{slot}@{sha}"
        relative = video.relative_to(root).as_posix() if valid else None
        url = f"/media/{quote(root.name, safe='')}/{quote(relative, safe='/')}" if relative else None
        costs = record.get("costs") or {}
        ledger = _json(root, costs.get("shared_action_pool_ledger_ref"))
        shared_estimate = (ledger.get("catalog_estimate_by_currency") or {}).get("CNY")
        settled = (ledger.get("actual_spend_by_currency") or {}).get("CNY")
        paid_label = f"核实实付 ¥{settled:.3f}" if isinstance(settled, (int, float)) and not ledger.get("unknown_settlement_count") else "实付待核实"
        cost_label = (f"共用动作池目录估算 ¥{shared_estimate:.3f}，{paid_label}；尚未分摊到单条"
                      if isinstance(shared_estimate, (int, float)) else "单条完整费用待核实")
        results.append({
            "id": slot,
            "title": str(entry.get("title") or slot),
            "video_url": url,
            "duration_seconds": render.get("seconds") if isinstance(render.get("seconds"), (int, float)) else None,
            "version_ref": version_ref,
            "technical_label": "当前文件技术检查通过" if all(qa["checks"].get(name, {}).get("effective_status") == "pass"
                for name in ("decode", "video_profile", "duration", "audio_track")) else "当前文件技术证据待补齐",
            "alignment_label": "历史报告通过；不代表独立口播及全片核验完成" if checks.get("alignment") == "pass" else "尚未确认",
            "judge_label": "历史报告有评分；不代替本次完整认证" if checks.get("video_judge") == "scored"
                else "自动视觉评分未完成，原错误记录保留",
            "quality_label": "必要检查已完成" if qa["eligible"] else "检查证据待补齐，尚未获得完整生产认证",
            "blocking_checks": qa["blocking_checks"],
            "content_structure": ({key: structure[key] for key in ("structure_id", "structure_label", "planned_structure_relation", "fit")}
                                  if structure else None),
            "scoped_review_status": review_scope,
            "review_confirmations": _bound_visual_confirmations(root, record) if valid else [],
            "final_review": review if kind == "final_review" else None,
            "preview_review": review if kind == "opening_preview" else None,
            "review": review, "review_kind": kind,
            "opening_group": opening, "scope_error": scope_error,
            "checks": _review_checks(qa["checks"]), "applicability": qa.get("applicability", {}),
            "certification_eligible": qa["eligible"],
            "binding_status": binding_status,
            "review_history": [{key: r.get(key) for key in ("review_id", "kind", "subject_version", "status", "decided_by", "reason", "decided_at")}
                               for r in sorted(matches, key=lambda r: r.get("subject_version", 0), reverse=True)],
            "record_path": entry["record_path"],
            "cost_label": cost_label,
            "review_status": (("文件已变化，请重新提交审核" if not valid else None) or scope_error or {
                "changed": "制作文件或依赖已变化，请重新提交审核",
                "scope_changed": "审核范围已变化，请重新提交审核",
                "insufficient_history": "历史人工审核保留；旧绑定证据不足，请重新提交审核",
            }.get(binding_status) or ({"approved": "预览反馈已通过", "rejected": "预览需调整"}.get(human_status, "预览待反馈")
                if kind == "opening_preview" else {"approved": "已通过", "rejected": "需调整"}.get(human_status, "待审核"))),
            "notes": [{"note": str(n.get("note") or ""), "ts": str(n.get("ts") or "")}
                      for n in notes if isinstance(n, dict) and n.get("stage") == "compose"
                      and n.get("version_ref") == version_ref] if valid else [],
        })
    # The acyclic B0 preparation experiment precedes the approved freeze. Join
    # its actual record to a later registered experiment by canonical baseline
    # record path, never by the display label B0 or input ordering.
    groups = {}
    for item in results:
        group = item["opening_group"]
        if group and group["role"] == "variant":
            groups.setdefault(group["baseline_record_path"], []).append(group)
    for item in results:
        group = item["opening_group"]
        targets = groups.get(item["record_path"], [])
        unique = {g["id"]: g for g in targets}
        if group and group["role"] == "baseline" and len(unique) == 1:
            target = next(iter(unique.values()))
            item["opening_group"] = {**group, **{key: target[key] for key in ("id", "experiment_id", "experiment_ref", "baseline_record_path")}}
    from lib.opening_results import comparison_reasons, results_by_record
    imported_by_record = results_by_record(root)
    for item in results:
        item["opening_results"] = [
            {**row, "comparison_reasons": list(row["comparison_reasons"])}
            for row in imported_by_record.get(item["record_path"], [])
        ]
    for item in results:
        group = item["opening_group"]
        if not group or group["role"] == "baseline":
            continue
        baseline = next((other for other in results if other is not item and other["opening_group"]
            and other["opening_group"]["id"] == group["id"] and other["opening_group"]["role"] == "baseline"), None)
        for row in item["opening_results"]:
            if baseline is None or not baseline["opening_results"]:
                row["comparison_reasons"].append("缺少同源基线实测")
                continue
            candidates = baseline["opening_results"]
            comparable = False
            reasons = []
            for base in candidates:
                current_reasons = comparison_reasons(row, base, group_same=True,
                    scope_same=group["scope"] == baseline["opening_group"]["scope"],
                    duration_same=(item["duration_seconds"] == baseline["duration_seconds"]
                        if (isinstance(item["duration_seconds"], (int, float))
                            and item["duration_seconds"] > 0
                            and isinstance(baseline["duration_seconds"], (int, float))
                            and baseline["duration_seconds"] > 0) else None))
                if not current_reasons:
                    comparable = True
                    if any(metric["status"] == "undefined" for metric in row["metrics"] + base["metrics"]):
                        row["comparison_reasons"].append("指标分母或数值缺失")
                    break
                reasons.extend(current_reasons)
            if not comparable:
                row["comparison_status"] = "不可比"
                row["comparison_reasons"].extend(sorted(set(reasons)))
            elif not row["comparison_reasons"]:
                row["comparison_reasons"].append("未预注册胜出规则或独立新窗口复验")
    return results
