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


def production_review_items(project_dir: Path, index: dict, notes: list) -> list[dict]:
    """Never advance checkpoints or transfer approval from a different render."""
    root = Path(project_dir)
    from backlot.operator_reviews import ReviewService
    from lib.production_evidence import quality_summary, verify_production_subject

    reviews = [r for r in ReviewService(root).list() if r.get("kind") == "final_review"]
    results = []
    entries = index.get("items")
    for entry in (entries if isinstance(entries, list) else [])[:300]:
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
        latest = max(matches, key=lambda r: (r.get("subject_version", 0), r.get("created_at", "")), default=None)
        review_valid = bool(valid and latest and verify_production_subject(root, latest.get("production_subject") or {}))
        human_status = latest.get("status") if review_valid else "pending"
        qa = quality_summary(root, record)
        if not valid:
            qa["eligible"] = False
        final_review = ({key: latest[key] for key in ("review_id", "subject_version", "subject_hash", "status")}
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
            "final_review": final_review,
            "record_path": entry["record_path"],
            "cost_label": cost_label,
            "review_status": ({"approved": "已通过", "rejected": "需调整"}.get(human_status, "待审核")
                if valid and (not latest or review_valid) else "文件已变化，请重新提交审核"),
            "notes": [{"note": str(n.get("note") or ""), "ts": str(n.get("ts") or "")}
                      for n in notes if isinstance(n, dict) and n.get("stage") == "compose"
                      and n.get("version_ref") == version_ref] if valid else [],
        })
    return results
