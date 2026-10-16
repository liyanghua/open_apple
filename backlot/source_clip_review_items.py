"""Read-only, purpose-bound source review cards derived from canonical files."""
from pathlib import Path
from urllib.parse import quote

from backlot.operator_reviews import ReviewService
from backlot.production_review_items import _file, _json
from lib.shot_source_contracts import build_source_subject, validate_source_record, verify_source_subject


def _url(root, path):
    return f"/media/{quote(root.name, safe='')}/{quote(path, safe='/')}" if _file(root, path) else None


def source_clip_review_items(project_dir: Path, notes: list) -> list[dict]:
    root = Path(project_dir)
    paths = sorted((root / "artifacts/shot_sources").glob("*/*/record.json"))
    if len(paths) > 3000:
        raise ValueError("Source review candidates exceed the 3000-record limit")
    reviews = [r for r in ReviewService(root).list() if r.get("kind") == "source_clip"]
    items = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        record = _json(root, relative)
        try:
            summary = validate_source_record(root, record)
            plan = _json(root, record["plan_ref"]["path"])
        except (ValueError, OSError, KeyError, TypeError):
            items.append({"id": relative, "title": "源片记录需要核对", "review_kind": "source_clip",
                          "review_allowed": False, "counts_as_film": False,
                          "scope_error": "源片、依据或版本已变化，请核对记录", "record_path": relative})
            continue
        source = record["source"]
        evaluation = _json(root, record["evaluation_ref"]["path"])
        technical = evaluation["source_review"]["technical"]
        receipt = _json(root, record["generation_receipt_ref"]["path"])
        result = receipt.get("data") or receipt
        estimate = result.get("estimated_cost_cny")
        for use in plan["uses"]:
            purpose = use["purpose_id"]
            item_id = f"{record['shot_id']}:{record['revision']}:{purpose}"
            interval = use.get("interval") or [0, source["duration_seconds"]]
            eligible = summary["technical_status"] == "pass" and summary["purposes"][purpose]["status"] == "pass"
            matches = [r for r in reviews if r.get("subject_id") == item_id]
            latest = max(matches, key=lambda r: r.get("subject_version", 0), default=None)
            valid_review = latest if latest and verify_source_subject(root, latest.get("source_subject", {})) else None
            if valid_review and eligible:
                try:
                    valid_review = latest if latest["source_subject"] == build_source_subject(root, relative, purpose, interval) else None
                except (ValueError, OSError, KeyError, TypeError):
                    valid_review = None
            status = "该用途已通过" if valid_review and valid_review["status"] == "approved" else "该用途需调整" if valid_review and valid_review["status"] == "rejected" else "待审核" if eligible else "该用途尚未满足"
            observations = summary["observations"]
            references = [{"roles": ref.get("roles", []), "media_type": ref.get("media_type", "image"), "url": _url(root, ref.get("source", {}).get("path", ""))}
                          for ref in plan.get("references", [])]
            items.append({
                "id": item_id, "title": f"{record['shot_id']} · {record['revision']} · {purpose}",
                "shot_id": record["shot_id"], "revision": record["revision"], "purpose_id": purpose,
                "interval": interval, "record_path": relative, "review_kind": "source_clip",
                "review_allowed": eligible, "counts_as_film": False, "scope_error": None,
                "video_url": _url(root, source["path"]), "duration_seconds": source["duration_seconds"],
                "version_ref": f"{item_id}@{source['sha256']}", "review_status": status,
                "review": valid_review, "review_history": matches,
                "original_purpose_status": summary["original_purpose_status"],
                "original_purpose_id": summary["original_purpose_id"],
                "requirements": plan["requirements"], "source_observations": observations,
                "references": references,
                "technical_label": "源片技术检查通过" if summary["technical_status"] == "pass" else "源片技术检查未完成或失败",
                "quality_label": "仅审核本用途；原用途结论保留，完整片另审",
                "judge_label": "以实际检查证据为准；未调用评估模型不计自动评分",
                "alignment_label": "原始源片，口播与成片alignment另行检查",
                "checks": {check["id"]: {"status": check["status"]} for check in technical["checks"]},
                "cost_label": f"本次目录估算 ¥{float(estimate):.3f}；实付待核实" if isinstance(estimate, (int, float)) else "费用待核实",
                "notes": [n for n in notes if n.get("version_ref") == f"{item_id}@{source['sha256']}"],
            })
    return items
