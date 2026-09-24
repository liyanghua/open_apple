"""Read-only campaign adapter. Verification is computed from canonical files."""

from __future__ import annotations

from pathlib import Path

from backlot.operator_reviews import ReviewService
from backlot.production_review_items import _json
from lib.campaign_panorama import build_campaign_panorama
from lib.production_evidence import build_production_subject, production_subject_hash, quality_summary, verify_production_subject


def campaign_production_panorama(project_dir: Path, index: dict) -> dict | None:
    if not index or not isinstance(index.get("plan_ref"), str):
        return None
    root = Path(project_dir)
    plan = _json(root, index["plan_ref"])
    if not plan:
        return None
    reviews = ReviewService(root).list()
    records, proofs = [], {}
    for ref in index.get("production_record_refs", []):
        record = _json(root, ref)
        if not record:
            continue
        run_id = str(record.get("run_id") or f"{root.name}:{record.get('content_slot_id', '')}")
        render = record.get("render") or {}
        row = {
            **record, "run_id": run_id,
            "media_sha256": render.get("sha256"),
            "content_version_id": record.get("content_version_id") or f"{record.get('content_slot_id')}@{render.get('sha256')}",
            "review_url": f"/p/{root.name}?stage=compose&artifact=production_reviews&content={record.get('content_slot_id', '')}",
        }
        try:
            subject = build_production_subject(root, ref)
            digest = production_subject_hash(subject)
            row["dependency_sha256"] = digest
            matching = [r for r in reviews if r.get("kind") == "final_review"
                        and r.get("subject_hash") == digest and r.get("subject_id") == record.get("content_slot_id")]
            review = max(matching, key=lambda r: r.get("subject_version", 0), default={})
            quality = quality_summary(root, record)
            approved = review.get("status") == "approved" and verify_production_subject(root, review.get("production_subject", {}))
            row["approval"] = {"status": review.get("status"), "review_id": review.get("review_id")}
            row["quality_status"] = "pass" if quality["eligible"] else "incomplete"
            proofs[run_id] = {"run_id": run_id, "content_version_id": row["content_version_id"],
                             **{name: record.get(name) for name in ("content_slot_id", "sku", "production_route", "work_id")},
                             "media_sha256": row["media_sha256"], "dependency_sha256": digest,
                             "media_verified": True, "quality_passed": quality["eligible"], "approval_valid": approved}
        except (ValueError, OSError, TypeError, KeyError):
            pass
        records.append(row)
    # This is the server's canonical release artifact, never request JSON.
    # An unbound context is planning data and has no release authority.
    context = _json(root, index.get("release_context_ref"))
    authority = context.get("authorization") or {}
    context_hash = production_subject_hash({key: value for key, value in context.items() if key != "authorization"})
    authoritative = next((r for r in reviews if r.get("review_id") == authority.get("review_id")
                          and r.get("status") == "approved" and r.get("kind") == "creative_lock"
                          and r.get("subject_hash") == authority.get("subject_hash")
                          and context_hash in (r.get("approval_subject_hashes") or [])), None)
    if not authoritative:
        context = {}
    result = build_campaign_panorama(plan, records, verification_reports=proofs, release_context=context,
                                     cost_entries=_json(root, index.get("path_cost_entries_ref")).get("entries", []))
    pilot_slots = {r.get("content_slot_id") for r in records if r.get("campaign_role") == "pilot"}
    result["pilot_review_count"] = len({r.get("subject_id") for r in reviews
                                      if r.get("kind") == "final_review" and r.get("status") == "approved"
                                      and r.get("subject_id") in pilot_slots
                                      and verify_production_subject(root, r.get("production_subject", {}))})
    comparison = _json(root, index.get("pilot_media_comparison_ref"))
    verified_media = {proof.get("media_sha256") for proof in proofs.values() if proof.get("media_verified")}
    if comparison.get("left_sha256") in verified_media and comparison.get("right_sha256") in verified_media:
        result["pilot_media_comparison"] = comparison
    return result
