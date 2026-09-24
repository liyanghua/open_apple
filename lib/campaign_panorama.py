"""Deterministic, read-only campaign views over a plan and canonical run records.

This module does no I/O and owns no state. ``verification_reports`` is a trusted
server-side input, produced by re-reading media, dependencies, quality reports
and exact-version human approvals (see ``production_evidence``). Never populate
it from request JSON or from a run's self-declared status/hash. Release context
likewise comes from approved canonical records, not from this projection.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import math
import re
from typing import Any, Mapping, Sequence

from lib.artifact_hashing import attach_hashes
from lib.campaign_contracts import create_campaign_plan
from schemas.artifacts import validate_artifact

DIRECTIONS = {
    "实测与选购": "test_selection", "治愈微仪式": "healing_ritual",
    "关系微故事": "relationship_story", "空间与玩趣": "space_play",
    "真实评论与答疑": "comment_faq", "交易与直播承接": "transaction",
}
STATES = ("planned", "awaiting_assets", "in_production", "awaiting_review",
          "approved", "rework", "cancelled", "deferred")
TIMING_FIELDS = ("queue_ms", "generation_ms", "agent_work_ms", "review_wait_ms", "render_ms", "human_work_ms", "rework_ms")
ORIGINAL_QUOTAS = {
    "direction": dict(zip(DIRECTIONS.values(), (90, 75, 60, 45, 15, 15))),
    "sku": {"S01": 100, "S08": 120, "S04": 80},
    "week": {1: 75, 2: 75, 3: 75, 4: 75},
}


def normalize_original_campaign_plan(
    raw: Mapping[str, Any], *, campaign_id: str = "playboy-towel-original-300",
) -> dict[str, Any]:
    """Adapt the actual v2 schedule without treating P1/P2 pilots as its SKUs.

    Ambiguous recipe options stay options; importing a plan creates no facts,
    budget authority, run, completed stage, or approval.
    """
    records = raw.get("records")
    if not isinstance(records, list) or len(records) != 300:
        raise ValueError("original schedule requires exactly 300 records")
    slots = []
    for row in records:
        direction = DIRECTIONS.get(row.get("content_direction"))
        if direction is None:
            raise ValueError("unknown original content direction")
        source_structure = str(row.get("content_structure") or "")
        options = re.findall(r"P[1-6]", source_structure)
        support = row.get("kind") == "支持"
        route = str(row.get("production_route") or "")
        route_id = "support" if support else "manual" if route.startswith("人工") else "ai_assisted"
        slots.append({
            "content_slot_id": row["content_slot_id"], "week": row["week"],
            "direction_id": direction, "structure_id": options[0] if source_structure in options else None,
            "structure_options": options, "support_type": (
                "faq" if support and direction == "comment_faq" else
                "transaction" if support and direction == "transaction" else "trust" if support else "experiment"),
            "sku": row["sku_family_id"], "product_id": row.get("platform_sku_id"),
            "item_code": row["sku_family_id"], "fact_snapshot_ref": row.get("approved_fact_version"),
            "recipe_id": None, "content_version_id": None,
            "experiment_family_id": row.get("experiment_group_id"),
            "matched_brief_id": row.get("matched_brief_id"), "baseline_slot_id": row.get("control_ref"),
            "production_route": route_id, "source_angle": row.get("working_title"),
            "changed_variable": row.get("changed_variable"),
            "required_evidence": list(row.get("evidence_required") or []),
            "original_slot": True, "status": "planned",
        })
    for dimension, field in (("direction", "direction_id"), ("sku", "sku"), ("week", "week")):
        if Counter(row[field] for row in slots) != ORIGINAL_QUOTAS[dimension]:
            raise ValueError(f"original {dimension} quota mismatch")
    if sum(row["support_type"] == "experiment" for row in slots) != 240:
        raise ValueError("original schedule requires 240 experimental and 60 support slots")
    if Counter(row["production_route"] for row in slots if row["week"] == 4) != {"manual": 30, "ai_assisted": 30, "support": 15}:
        raise ValueError("W4 requires 30 manual, 30 AI and 15 support slots")
    plan = create_campaign_plan(campaign_id, slots=slots, target_count=300, pilot_count=0)
    plan["origin"] = "original_300_schedule"
    plan["source_revision"] = str(raw.get("version") or "")
    plan = attach_hashes(plan)
    validate_artifact("campaign_plan", plan)
    return plan


def _number(value: Any) -> float | int | None:
    return value if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def _release(slot: Mapping, context: Mapping) -> dict:
    facts = context.get("fact_versions") or {}
    structures = slot.get("structure_options") or ([slot["structure_id"]] if slot.get("structure_id") else [])
    structure = slot.get("structure_id")
    fact = slot.get("fact_snapshot_ref") or facts.get(slot["sku"])
    brand = context.get("brand_version")
    budget = context.get("production_budget") or {}
    first = context.get("recipe_first_articles") or {}
    blockers = []
    if not fact:
        blockers.append("facts_not_approved")
    if not brand:
        blockers.append("brand_not_approved")
    if budget.get("approved") is not True or not _number(budget.get("cap_cny")) or not budget.get("approval_ref"):
        blockers.append("production_budget_not_approved")
    if not structure:
        blockers.append("structure_not_selected")
    if not structure or not first.get(structure):
        blockers.append("recipe_first_article_not_approved")
    if slot["week"] not in (context.get("approved_weeks") or []):
        blockers.append("week_not_approved")
    if slot["week"] == 1 and structure in {"P3", "P4", "P5"}:
        blockers.append("structure_not_in_w1_calibration")
    return {"ready": not blockers, "blockers": blockers,
            "fact_version": fact, "brand_version": brand, "structure_options": list(structures)}


def _identity_matches(row: Mapping, report: Mapping) -> bool:
    keys = ("run_id", "content_version_id", "media_sha256", "dependency_sha256",
            "content_slot_id", "sku", "production_route", "work_id")
    return all(row.get(key) and row.get(key) == report.get(key) for key in keys)


def _verification(row: Mapping, report: Mapping | None) -> tuple[bool, list[str]]:
    if not report:
        return False, ["verification_missing"]
    if not _identity_matches(row, report):
        return False, ["stale_verification"]
    reasons = []
    for key, reason in (("media_verified", "media_unverified"), ("quality_passed", "quality_not_passed"), ("approval_valid", "exact_version_approval_missing")):
        if report.get(key) is not True:
            reasons.append(reason)
    return not reasons, reasons


def _summary(slots: Sequence[Mapping]) -> dict:
    costs, timing = {}, {}
    for field in ("estimated_cny", "paid_cny"):
        values = [row["costs"][field] for row in slots]
        known = [value for value in values if value is not None]
        costs[field] = round(sum(known), 6) if len(known) == len(values) else None
        costs[f"known_{field}"] = round(sum(known), 6) if known else None
        costs[f"unknown_{field}_count"] = len(values) - len(known)
    for field in TIMING_FIELDS:
        values = [row["timing"][field] for row in slots]
        known = [value for value in values if value is not None]
        timing[field] = sum(known) if len(known) == len(values) else None
        timing[f"known_{field}"] = sum(known) if known else None
        timing[f"unknown_{field}_count"] = len(values) - len(known)
    return {"planned": len(slots), "approved_unique": sum(row["counted"] for row in slots),
            "status_counts": {state: sum(row["status"] == state for row in slots) for state in STATES},
            "costs": costs, "timing": timing}


def summarize_path_costs(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Project canonical W4 cost-entry references; common cost is paid once.

    Entries carry ``cost_id``, ``category`` (shared_preparation/path_increment),
    a manual/ai_assisted route for increments and nullable estimated/paid CNY.
    Callers select the campaign/W4 cohort before calling. A missing category is
    unknown, not zero; record a canonical zero entry to establish zero cost.
    Identical IDs deduplicate, conflicting IDs remain unknown with a warning.
    """
    grouped = defaultdict(list)
    warnings = []
    for entry in entries:
        if not entry.get("cost_id"):
            warnings.append("cost_entry_id_missing")
        else:
            grouped[str(entry["cost_id"])].append(entry)
    buckets = {"shared_preparation": [], "manual": [], "ai_assisted": []}
    for key, values in sorted(grouped.items()):
        relevant = [(row.get("category"), row.get("production_route"),
                     _number(row.get("estimated_cny")), _number(row.get("paid_cny"))) for row in values]
        category, route, estimated, paid = relevant[0]
        if any(value != relevant[0] for value in relevant):
            warnings.append(f"conflicting_cost_entry:{key}")
            # A conflict has no canonical category. Do not let input ordering
            # decide which route inherits it; all totals remain incomplete.
            for rows in buckets.values():
                rows.append({"estimated_cny": None, "paid_cny": None})
            continue
        bucket = "shared_preparation" if category == "shared_preparation" else route if category == "path_increment" else None
        if bucket not in buckets:
            warnings.append(f"invalid_cost_category:{key}")
            continue
        buckets[bucket].append({"estimated_cny": estimated, "paid_cny": paid})

    def total(rows):
        output = {"entry_count": len(rows)}
        for field in ("estimated_cny", "paid_cny"):
            known = [row[field] for row in rows if row[field] is not None]
            output[field] = round(sum(known), 6) if rows and len(known) == len(rows) else None
            output[f"known_{field}"] = round(sum(known), 6) if known else None
            output[f"unknown_{field}_count"] = len(rows) - len(known)
        return output

    shared = total(buckets["shared_preparation"])
    routes = {}
    for route in ("manual", "ai_assisted"):
        incremental = total(buckets[route])
        allocation, full = {}, {}
        for field in ("estimated_cny", "paid_cny"):
            allocation[field] = round(shared[field] * 0.5, 6) if shared[field] is not None else None
            full[field] = round(incremental[field] + allocation[field], 6) if not warnings and incremental[field] is not None and allocation[field] is not None else None
        routes[route] = {"incremental": incremental, "shared_allocation_fraction": 0.5,
                         "allocated_shared": allocation, "full_cost": full}
    project = total([row for rows in buckets.values() for row in rows])
    for field in ("estimated_cny", "paid_cny"):
        if warnings or any(total(rows)[field] is None for rows in buckets.values()):
            project[field] = None
    return {"currency": "CNY", "shared_preparation": shared, "routes": routes,
            "project_total": project, "complete": not warnings and all(project[key] is not None for key in ("estimated_cny", "paid_cny")),
            "cost_entry_refs": sorted(grouped), "warnings": sorted(set(warnings))}


def build_campaign_panorama(
    plan: Mapping[str, Any], records: Sequence[Mapping[str, Any]], *,
    verification_reports: Mapping[str, Mapping[str, Any]] | None = None,
    release_context: Mapping[str, Any] | None = None,
    cost_entries: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Join original slots to verified run snapshots; never persist or repair.

    One active record per slot is required. If historical versions exist, bind
    ``content_version_id`` in the plan (or explicitly mark historical records
    ``superseded=True``); input ordering is never a recency heuristic.
    """
    proofs, context = verification_reports or {}, release_context or {}
    planned = list(plan.get("slots") or [])
    slot_ids = {row["content_slot_id"] for row in planned}
    if len(slot_ids) != len(planned):
        raise ValueError("campaign slot ids must be unique")
    by_slot = defaultdict(list)
    excluded = []
    for record in records:
        sid = record.get("content_slot_id")
        if sid not in slot_ids or record.get("pilot") is True:
            excluded.append({"run_id": record.get("run_id"), "reasons": ["original_slot_unresolved" if sid not in slot_ids else "pilot_not_original_plan"]})
        elif record.get("superseded") is not True:
            by_slot[sid].append(record)
    slots, seen_media, seen_work = [], {}, {}
    # Verified historical/reference media remains occupied even though it does
    # not contribute to the 300. Renaming it into a new slot cannot create work.
    for row in records:
        if row.get("reference_only") is True or row.get("pilot") is True or row.get("content_slot_id") not in slot_ids:
            report = proofs.get(row.get("run_id")) or {}
            if report.get("media_verified") is True and _identity_matches(row, report):
                seen_media[row["media_sha256"]] = row.get("content_slot_id")
                if row.get("work_id"):
                    seen_work[row["work_id"]] = row.get("content_slot_id")
    for slot in sorted(planned, key=lambda item: (item["week"], item["content_slot_id"])):
        sid = slot["content_slot_id"]
        candidates = by_slot.get(sid, [])
        if slot.get("content_version_id"):
            candidates = [r for r in candidates if r.get("content_version_id") == slot["content_version_id"]]
        ambiguous = len(candidates) > 1
        row = candidates[0] if len(candidates) == 1 else {}
        run_id = row.get("run_id")
        verified, reasons = _verification(row, proofs.get(run_id)) if row else (False, [])
        if row and any(not slot.get(key) or row.get(key) != slot[key] for key in ("content_slot_id", "sku", "production_route")):
            verified = False
            reasons.append("plan_identity_mismatch")
        if ambiguous:
            reasons.append("ambiguous_current_version")
        if row.get("reference_only") is True:
            reasons.append("reference_only")
        if row and not row.get("work_id"):
            reasons.append("missing_work_identity")
        if slot.get("original_slot") is False:
            reasons.append("not_original_slot")
        state = row.get("status") or slot.get("status") or "planned"
        state = {"in_progress": "in_production", "awaiting_human": "awaiting_review",
                 "completed": "awaiting_review", "blocked": "awaiting_assets", "skipped": "deferred"}.get(state, state)
        if state not in STATES:
            state = "planned"
        if verified and state not in {"cancelled", "deferred", "rework"}:
            state = "approved"
        elif state == "approved":
            state = "awaiting_review"
        if ambiguous:
            state = "awaiting_review"
        eligible = verified and not reasons and state == "approved"
        if eligible:
            media, work = row["media_sha256"], row["work_id"]
            if media in seen_media:
                reasons.append("duplicate_media")
            if work in seen_work:
                reasons.append("duplicate_work")
            seen_media.setdefault(media, sid)
            seen_work.setdefault(work, sid)
        costs = row.get("costs") or {}
        timing = row.get("timing") or {}
        resolved_slot = {**slot}
        if row.get("structure_id") and row["structure_id"] in (slot.get("structure_options") or [slot.get("structure_id")]):
            resolved_slot["structure_id"] = row["structure_id"]
        result = {key: deepcopy(resolved_slot.get(key)) for key in (
            "content_slot_id", "week", "sku", "product_id", "direction_id", "structure_id",
            "structure_options", "support_type", "experiment_family_id", "matched_brief_id", "production_route", "baseline_slot_id")}
        result.update({
            "status": state, "canonical_run_id": run_id, "content_version_id": row.get("content_version_id"),
            "review_url": row.get("review_url"), "counted": eligible and not reasons,
            "counting_exclusions": reasons, "verification_status": "verified" if verified else "unverified",
            "release": _release(resolved_slot, context),
            "costs": {key: _number(costs.get(key)) for key in ("estimated_cny", "paid_cny")},
            "timing": {key: _number(timing.get(key)) for key in TIMING_FIELDS},
            "fact_version": row.get("fact_version") or slot.get("fact_snapshot_ref"),
            "brand_version": row.get("brand_version"), "media_reuse": deepcopy(row.get("media_reuse") or []),
            "human_review_required": True,
        })
        slots.append(result)
    coverage = {}
    for week in sorted({row["week"] for row in slots}):
        subset = [row for row in slots if row["week"] == week]
        coverage[f"W{week}"] = {
            "directions": sorted({row["direction_id"] for row in subset}),
            "structures": sorted({value for row in subset for value in (row["structure_options"] or ([row["structure_id"]] if row["structure_id"] else []))}),
            "experimental_slots": sum(row["support_type"] == "experiment" for row in subset),
            "support_slots": sum(row["support_type"] != "experiment" for row in subset),
        }
    result = {
        "version": "1.0", "campaign_id": plan["campaign_id"], "plan_revision": plan.get("plan_revision", 1),
        "target_count": plan["target_count"], "slots": slots, "summary": _summary(slots),
        "excluded_records": sorted(excluded, key=lambda row: str(row["run_id"])),
        "coverage": {"weeks": coverage, "calibration": {"target_count": 30, "does_not_cover_all_structures": True,
            "directions": coverage.get("W1", {}).get("directions", []), "requires_individual_human_review": True}},
        "release_prerequisites": {"required": ["approved_facts", "approved_brand", "approved_production_budget", "recipe_first_article", "week_approval"],
            "per_slot_human_review_required": True, "budget_estimates_are_not_authorization": True},
        "path_cost_comparison": summarize_path_costs(cost_entries),
    }
    for dimension, field in (("week", "week"), ("sku", "sku"), ("direction", "direction_id"), ("structure", "structure_id")):
        groups = defaultdict(list)
        for slot in slots:
            key = f"W{slot[field]}" if dimension == "week" else str(slot[field] or "unassigned")
            groups[key].append(slot)
        result[f"by_{dimension}"] = {key: _summary(value) for key, value in sorted(groups.items())}
    return result
