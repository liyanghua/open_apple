"""Campaign and content-type contracts for the towel batch mainline.

This module deliberately contains deterministic validation and construction only.
Creative selection remains in the pipeline director/agent; this layer makes the
approved decision explicit and prevents an unbound slot from entering paid work.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import uuid4

from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact

CONTENT_DIRECTIONS = {
    "test_selection",
    "healing_ritual",
    "relationship_story",
    "space_play",
    "comment_faq",
    "transaction",
}
SUPPORT_TYPES = {"experiment", "trust", "faq", "transaction"}
CONTENT_ROLES = {"product_evidence", "life_context", "graphic_support"}
STRUCTURES = {f"P{i}" for i in range(1, 7)}
ACTION_KEYS = {
    "product_full_view",
    "weave_macro",
    "touch_brush",
    "lift_unfold",
    "fold_fall",
    "color_reveal",
    "use_context",
}
MOTION_FAILURE_CLASSES = {
    "input_ratio",
    "privacy_block",
    "identity_drift",
    "composition_failure",
    "incomplete_action",
    "texture_color_drift",
    "provider_error",
}

TYPE_STRUCTURE_HINTS: dict[str, set[str]] = {
    "test_selection": {"P1", "P6"},
    "healing_ritual": {"P2"},
    "relationship_story": {"P3"},
    "space_play": {"P4", "P5"},
    "comment_faq": STRUCTURES,
    "transaction": {"P6"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unique(values: Sequence[Any]) -> bool:
    return len(values) == len(set(values))


def validate_campaign_plan_semantics(plan: Mapping[str, Any]) -> None:
    """Validate invariants that JSON Schema cannot express cleanly."""
    slots = list(plan.get("slots") or [])
    target = int(plan.get("target_count") or 0)
    pilot = int(plan.get("pilot_count") or 0)
    ids = [str(slot.get("content_slot_id") or "") for slot in slots]
    if len(slots) > target:
        raise ValueError("campaign plan contains more slots than target_count")
    if pilot > target:
        raise ValueError("pilot_count must be within target_count")
    if not _unique(ids) or any(not item for item in ids):
        raise ValueError("content_slot_id values must be unique and non-empty")
    for index, slot in enumerate(slots, 1):
        direction = str(slot.get("direction_id") or "")
        structure = slot.get("structure_id")
        if direction not in CONTENT_DIRECTIONS:
            raise ValueError(f"unknown content direction: {direction}")
        if structure is not None and structure not in STRUCTURES:
            raise ValueError(f"unknown content structure: {structure}")
        if structure is not None and structure not in TYPE_STRUCTURE_HINTS[direction]:
            raise ValueError(f"structure {structure} is not valid for direction {direction}")
        fact_ref = slot.get("fact_snapshot_ref")
        if fact_ref is not None and not str(fact_ref).strip():
            raise ValueError(f"slot {ids[index - 1]} has an empty fact_snapshot_ref")
        version_id = slot.get("content_version_id")
        if version_id is not None and not str(version_id).strip():
            raise ValueError(f"slot {ids[index - 1]} has an empty content_version_id")


def validate_content_recipe_semantics(recipe: Mapping[str, Any]) -> None:
    direction = str(recipe.get("direction_id") or "")
    structure = str(recipe.get("structure_id") or "")
    role = str(recipe.get("content_role") or "")
    if direction not in CONTENT_DIRECTIONS:
        raise ValueError(f"unknown content direction: {direction}")
    if structure not in STRUCTURES:
        raise ValueError(f"unknown content structure: {structure}")
    if structure not in TYPE_STRUCTURE_HINTS[direction]:
        raise ValueError(f"structure {structure} is not valid for direction {direction}")
    if role not in CONTENT_ROLES:
        raise ValueError(f"unknown content role: {role}")
    asset_slots = {str(item) for item in (recipe.get("asset_slots") or [])}
    unknown_actions = asset_slots - ACTION_KEYS
    if unknown_actions:
        raise ValueError(f"unknown asset action slot(s): {', '.join(sorted(unknown_actions))}")
    fixed = list((recipe.get("control_variables") or {}).get("fixed") or [])
    variable = list((recipe.get("control_variables") or {}).get("variable") or [])
    if set(fixed) & set(variable):
        raise ValueError("control variable cannot be both fixed and variable")
    if recipe.get("support_type") == "experiment" and not variable:
        raise ValueError("experiment recipe requires at least one variable")
    if direction == "comment_faq" and not recipe.get("evidence_ids"):
        raise ValueError("comment_faq recipe requires a source evidence id")
    if direction == "healing_ritual" and not asset_slots & {"touch_brush", "fold_fall", "use_context"}:
        raise ValueError("healing_ritual recipe requires a real life action slot")
    if direction == "relationship_story" and "use_context" not in asset_slots:
        raise ValueError("relationship_story recipe requires a use_context action slot")
    if direction == "space_play" and len(asset_slots) < 2:
        raise ValueError("space_play recipe requires at least two action slots for a before/after change")
    if direction == "transaction":
        if not str(recipe.get("cta") or "").strip():
            raise ValueError("transaction recipe requires a CTA")
        if not asset_slots & {"product_full_view", "color_reveal"}:
            raise ValueError("transaction recipe requires a product identity or color action slot")


_EVIDENCE_ACTION_MAP = {
    "product_full_view": "product_full_view",
    "weave_macro": "weave_macro",
    "edge_label": "color_reveal",
    "label_or_sku": "color_reveal",
    "sku_color_options": "color_reveal",
    "page_params_snapshot": "product_full_view",
    "page_and_detail_reference": "product_full_view",
    "fold_storage": "fold_fall",
    "real_use_action": "use_context",
    "absorbency_field": "product_full_view",
    "price_snapshot": "product_full_view",
    "sku_option_copy": "color_reveal",
    "review_snapshot": "use_context",
    "claim_evidence_map": "product_full_view",
    "same_condition_test": "lift_unfold",
    "production_log": "use_context",
}


def build_content_recipe_from_slot(
    slot: Mapping[str, Any],
    *,
    fact_snapshot_ref: str,
    need_id: str | None = None,
) -> dict[str, Any]:
    """Build a conservative recipe from one normalized legacy slot.

    The mapper only maps existing source metadata to action slots; it does not
    invent a product claim. Unknown evidence remains explicit and is surfaced
    as a recipe blocker rather than silently treated as proof.
    """
    direction = str(slot.get("direction_id") or "")
    role = {
        "test_selection": "product_evidence",
        "healing_ritual": "life_context",
        "relationship_story": "life_context",
        "space_play": "life_context",
        "comment_faq": "graphic_support",
        "transaction": "graphic_support",
    }[direction]
    evidence = [str(item) for item in slot.get("required_evidence") or [] if str(item).strip()]
    actions = [_EVIDENCE_ACTION_MAP[item] for item in evidence if item in _EVIDENCE_ACTION_MAP]
    if not actions:
        actions = ["product_full_view"]
    if direction == "relationship_story" and "use_context" not in actions:
        actions.append("use_context")
    if direction == "transaction" and not set(actions) & {"product_full_view", "color_reveal"}:
        actions.append("product_full_view")
    # Keep order stable while removing duplicates.
    actions = list(dict.fromkeys(actions))
    support = str(slot.get("support_type") or "experiment")
    variable = str(slot.get("changed_variable") or "source_angle").strip()
    recipe = {
        "version": "1.0",
        "recipe_id": str(slot.get("recipe_id") or f"{slot.get('content_slot_id')}-recipe-v1"),
        "sku": str(slot.get("sku") or ""),
        "direction_id": direction,
        "structure_id": str(slot.get("structure_id") or "P1"),
        "support_type": support,
        "content_role": role,
        "need_id": need_id or str(slot.get("source_angle") or slot.get("content_slot_id") or "need"),
        "fact_snapshot_ref": fact_snapshot_ref,
        "claim_ids": [],
        "evidence_ids": evidence or ["source_media_required"],
        "visual_action": str(slot.get("source_angle") or "商品事实表达"),
        "asset_slots": actions,
        "control_variables": {
            "fixed": ["sku", "fact_snapshot", "brand_visual_system"],
            "variable": [variable] if support == "experiment" else [],
        },
        "allowed_wording": [],
        "forbidden_wording": ["检测证明", "保证", "绝对不掉毛", "100%抗菌"],
        "cta": "查看商品页当前规格与颜色" if direction == "transaction" else None,
    }
    validate_content_recipe_semantics(recipe)
    validate_artifact("content_recipe", recipe)
    return attach_hashes(recipe)


def validate_fact_snapshot_semantics(snapshot: Mapping[str, Any]) -> None:
    claims = list(snapshot.get("claims") or [])
    ids = [str(claim.get("claim_id") or "") for claim in claims]
    if not _unique(ids) or any(not item for item in ids):
        raise ValueError("fact snapshot claim_id values must be unique and non-empty")
    if snapshot.get("status") == "approved" and not snapshot.get("approved_by"):
        raise ValueError("approved fact snapshot requires approved_by")
    if snapshot.get("effective_from") and snapshot.get("effective_until"):
        if snapshot["effective_until"] <= snapshot["effective_from"]:
            raise ValueError("fact snapshot effective_until must be after effective_from")
    for claim in claims:
        if claim.get("status") == "forbidden" and claim.get("allowed_wording"):
            raise ValueError("forbidden claim cannot have allowed_wording")


def validate_campaign_bundle(
    plan: Mapping[str, Any],
    snapshots: Mapping[str, Mapping[str, Any]],
    recipes: Mapping[str, Mapping[str, Any]],
    *,
    paid: bool = False,
) -> dict[str, Any]:
    """Validate the cross-artifact campaign admission contract.

    ``validate_artifact`` protects one JSON document at a time.  This function
    is the next-stage gate: it proves every slot resolves to the right SKU,
    fact snapshot and recipe, and that the recipe's claims/actions are in the
    snapshot.  Pending snapshots are allowed for a visual-only sample, but
    block paid work until a human approves them.
    """
    validate_campaign_plan_semantics(plan)
    blockers: list[str] = []
    snapshot_by_id = {str(key): value for key, value in snapshots.items()}
    for ref, snapshot in snapshot_by_id.items():
        try:
            validate_fact_snapshot_semantics(snapshot)
        except ValueError as exc:
            blockers.append(f"snapshot {ref}: {exc}")
    for slot in plan.get("slots") or []:
        slot_id = str(slot.get("content_slot_id") or "")
        ref = str(slot.get("fact_snapshot_ref") or "").strip()
        recipe_id = str(slot.get("recipe_id") or "").strip()
        if not ref or ref not in snapshot_by_id:
            blockers.append(f"slot {slot_id}: missing fact snapshot {ref or '<empty>'}")
            continue
        snapshot = snapshot_by_id[ref]
        if str(snapshot.get("sku") or "") != str(slot.get("sku") or ""):
            blockers.append(f"slot {slot_id}: SKU does not match fact snapshot {ref}")
        if paid and snapshot.get("status") != "approved":
            blockers.append(f"slot {slot_id}: fact snapshot {ref} is not approved")
        if not recipe_id or recipe_id not in recipes:
            blockers.append(f"slot {slot_id}: missing content recipe {recipe_id or '<empty>'}")
            continue
        recipe = recipes[recipe_id]
        try:
            validate_content_recipe_semantics(recipe)
        except ValueError as exc:
            blockers.append(f"recipe {recipe_id}: {exc}")
            continue
        if str(recipe.get("sku") or "") != str(slot.get("sku") or ""):
            blockers.append(f"recipe {recipe_id}: SKU does not match slot {slot_id}")
        if str(recipe.get("fact_snapshot_ref") or "") != ref:
            blockers.append(f"recipe {recipe_id}: fact_snapshot_ref does not match slot {slot_id}")
        claim_ids = {str(item.get("claim_id") or "") for item in snapshot.get("claims") or []}
        missing_claims = sorted(set(recipe.get("claim_ids") or []) - claim_ids)
        if missing_claims:
            blockers.append(f"recipe {recipe_id}: claims not found in snapshot: {', '.join(missing_claims)}")
    return {"ready": not blockers, "blockers": blockers, "slot_count": len(plan.get("slots") or [])}


def validate_motion_task_semantics(task: Mapping[str, Any]) -> None:
    status = str(task.get("status") or "")
    failure = task.get("failure_class")
    attempts = int(task.get("attempts") or 0)
    if status in {"failed", "reconcile_required"} and not failure:
        raise ValueError("failed or reconcile_required motion task requires failure_class")
    if failure is not None and failure not in MOTION_FAILURE_CLASSES:
        raise ValueError(f"unknown motion failure class: {failure}")
    if attempts < 1 and status not in {"planned", "queued"}:
        raise ValueError("running or terminal motion task requires at least one attempt")
    if task.get("pool_status") == "approved":
        if task.get("identity_score") is None or task.get("action_score") is None:
            raise ValueError("approved motion asset requires identity_score and action_score")


def validate_sample_shot_plan_semantics(plan: Mapping[str, Any]) -> None:
    """Enforce the previously approved single-shot pacing contract.

    A sample may be 8–15 seconds as a *multi-shot edit*, but each generated
    action clip is 3–5 seconds and each editorial beat may not exceed 5
    seconds.  Dense variants can use shorter 1.5–2.2 second editorial beats;
    that exception never applies to a Seedance motion task.
    """
    for sample in plan.get("samples") or []:
        sample_id = str(sample.get("sample_id") or "sample")
        motion_shots = sample.get("motion_shots") or []
        if not motion_shots:
            raise ValueError(f"{sample_id}: at least one motion_shot is required")
        for index, shot in enumerate(motion_shots, 1):
            try:
                duration = float(shot.get("duration_seconds"))
            except (TypeError, ValueError):
                raise ValueError(f"{sample_id}: motion_shots[{index}] duration is invalid")
            if not 3.0 <= duration <= 5.0:
                raise ValueError(
                    f"{sample_id}: motion_shots[{index}] duration {duration:g}s is outside 3–5s"
                )
        beats = sample.get("shots") or []
        if len(beats) < 2:
            raise ValueError(f"{sample_id}: a sample must contain at least two editorial shots")
        for shot in beats:
            timecode = str(shot.get("timecode") or "")
            try:
                start, end = (float(item) for item in timecode.split("-", 1))
            except (TypeError, ValueError):
                raise ValueError(f"{sample_id}: invalid shot timecode {timecode!r}")
            duration = end - start
            if duration <= 0 or duration > 5.0:
                raise ValueError(
                    f"{sample_id}: editorial shot {shot.get('id') or '<unknown>'} is {duration:g}s; max is 5s"
                )


def campaign_content_ref_blockers(run_plan: Mapping[str, Any]) -> list[str]:
    """Return fail-closed blockers for a campaign-aware template run.

    Legacy template runs have no ``campaign_content_ref`` and retain their
    existing readiness behavior. Once the ref is present, the run must carry
    enough type information to be auditable before paid assets are scheduled.
    """
    ref = run_plan.get("campaign_content_ref")
    if ref is None:
        return []
    if not isinstance(ref, Mapping):
        return ["campaign_content_ref must be an object"]
    required = (
        "campaign_id",
        "content_slot_id",
        "content_version_id",
        "direction_id",
        "structure_id",
        "support_type",
        "recipe_id",
    )
    blockers = [
        f"campaign_content_ref missing {key}"
        for key in required
        if not str(ref.get(key) or "").strip()
    ]
    if blockers:
        return blockers
    direction = str(ref["direction_id"])
    structure = str(ref["structure_id"])
    if direction not in CONTENT_DIRECTIONS:
        blockers.append(f"campaign_content_ref unknown direction_id: {direction}")
    elif structure not in TYPE_STRUCTURE_HINTS[direction]:
        blockers.append(
            f"campaign_content_ref structure {structure} is not valid for direction {direction}"
        )
    if str(ref["support_type"]) not in SUPPORT_TYPES:
        blockers.append(f"campaign_content_ref unknown support_type: {ref['support_type']}")
    return blockers


def create_campaign_plan(
    campaign_id: str,
    *,
    slots: Sequence[Mapping[str, Any]],
    target_count: int = 300,
    pilot_count: int = 60,
    plan_revision: int = 1,
    status: str = "draft",
    fact_snapshot_refs: Sequence[str] = (),
    wave_refs: Sequence[str] = (),
) -> dict[str, Any]:
    """Build a hashable campaign plan without inventing slot content."""
    plan = {
        "version": "1.0",
        "campaign_id": campaign_id,
        "plan_revision": plan_revision,
        "target_count": target_count,
        "pilot_count": pilot_count,
        "status": status,
        "fact_snapshot_refs": list(fact_snapshot_refs),
        "wave_refs": list(wave_refs),
        "slots": [dict(slot) for slot in slots],
    }
    validate_campaign_plan_semantics(plan)
    validate_artifact("campaign_plan", plan)
    return attach_hashes(plan)


def migrate_legacy_batch_plan(
    batch_plan: Mapping[str, Any],
    *,
    campaign_id: str | None = None,
    target_count: int = 300,
    pilot_count: int = 60,
) -> dict[str, Any]:
    """Normalize the existing P1/P2 60-slot plan into campaign slots.

    The legacy plan uses content groups rather than the six campaign
    directions.  This deterministic mapping keeps the old plan intact while
    making its first wave auditable under the new contract.
    """
    group_map = {
        "A": ("test_selection", "P1", "experiment"),
        "C": ("comment_faq", "P6", "faq"),
        "D": ("transaction", "P6", "transaction"),
    }
    relationship_markers = ("来客", "家庭", "关系", "成员")
    slots: list[dict[str, Any]] = []
    product_refs = {
        str(item.get("item_code") or item.get("product_key") or item.get("key") or ""): f"fact-{str(item.get('product_key') or item.get('key') or '').lower()}-v1"
        for item in (batch_plan.get("products") or [])
        if item.get("item_code") or item.get("product_key")
    }
    product_ids = {
        str(item.get("item_code") or item.get("product_key") or ""): str(item.get("product_id") or "")
        for item in (batch_plan.get("products") or [])
    }
    for source in batch_plan.get("slots") or []:
        group = str(source.get("content_group") or "")
        if group == "B":
            angle = str(source.get("angle") or "")
            direction, structure, support_type = (
                ("relationship_story", "P3", "trust")
                if any(marker in angle for marker in relationship_markers)
                else ("healing_ritual", "P2", "trust")
            )
        elif group in group_map:
            direction, structure, support_type = group_map[group]
        else:
            raise ValueError(f"legacy batch plan has unmapped content_group: {group}")
        slot_id = str(source.get("slot_id") or "")
        if not slot_id:
            raise ValueError("legacy batch plan slot is missing slot_id")
        week_raw = str(source.get("week") or "0").lstrip("Ww")
        try:
            week = int(week_raw)
        except ValueError as exc:
            raise ValueError(f"legacy batch plan slot has invalid week: {week_raw}") from exc
        slots.append({
            "content_slot_id": slot_id,
            "week": week,
            "direction_id": direction,
            "structure_id": structure,
            "support_type": support_type,
            "sku": str(source.get("item_code") or source.get("product_key") or "unknown"),
            "product_id": product_ids.get(str(source.get("item_code") or source.get("product_key") or "")),
            "item_code": str(source.get("item_code") or source.get("product_key") or ""),
            "fact_snapshot_ref": product_refs.get(
                str(source.get("item_code") or source.get("product_key") or "")
            ) or (
                f"fact-{slot_id.split('-', 1)[0].lower()}-v1" if "-" in slot_id else None
            ),
            "recipe_id": f"{slot_id}-recipe-v1",
            "content_version_id": f"{slot_id}-v001",
            "source_group": group,
            "source_angle": str(source.get("angle") or ""),
            "changed_variable": str(source.get("variable") or ""),
            "claim_mode": str(source.get("claim_mode") or ""),
            "required_evidence": list(source.get("required_evidence") or []),
            "status": str(source.get("status") or "planned"),
        })
    refs = [
        str(item.get("fact_version"))
        for item in (batch_plan.get("products") or [])
        if item.get("fact_version")
    ] or sorted(set(product_refs.values()))
    return create_campaign_plan(
        campaign_id or str(batch_plan.get("campaign_id") or "campaign-legacy"),
        slots=slots,
        target_count=target_count,
        pilot_count=pilot_count,
        fact_snapshot_refs=refs,
    )


def create_fact_snapshot(
    *,
    product_id: str,
    sku: str,
    source_hash: str,
    claims: Sequence[Mapping[str, Any]],
    snapshot_id: str | None = None,
    status: str = "pending_confirmation",
    approved_by: str | None = None,
    source_record_id: str | None = None,
    effective_from: str | None = None,
    effective_until: str | None = None,
) -> dict[str, Any]:
    snapshot = {
        "version": "1.0",
        "snapshot_id": snapshot_id or f"fact-{uuid4().hex[:12]}",
        "product_id": product_id,
        "sku": sku,
        "source_hash": source_hash,
        "source_record_id": source_record_id,
        "approved_by": approved_by,
        "approved_at": _now() if status == "approved" else None,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": status,
        "claims": [dict(claim) for claim in claims],
    }
    validate_fact_snapshot_semantics(snapshot)
    validate_artifact("fact_snapshot", snapshot)
    return attach_hashes(snapshot)


def create_content_link(
    *,
    campaign_id: str,
    content_slot_id: str,
    content_version_id: str,
    direction_id: str,
    structure_id: str,
    support_type: str,
    recipe_id: str,
    sku: str,
    fact_snapshot_ref: str,
    status: str = "planned",
    parent_content_version_id: str | None = None,
    changed_variable: str | None = None,
    run_project_id: str | None = None,
) -> dict[str, Any]:
    link = {
        "version": "1.0",
        "campaign_id": campaign_id,
        "content_slot_id": content_slot_id,
        "content_version_id": content_version_id,
        "parent_content_version_id": parent_content_version_id,
        "direction_id": direction_id,
        "structure_id": structure_id,
        "support_type": support_type,
        "recipe_id": recipe_id,
        "sku": sku,
        "fact_snapshot_ref": fact_snapshot_ref,
        "run_project_id": run_project_id,
        "changed_variable": changed_variable,
        "status": status,
        "created_at": _now(),
    }
    validate_artifact("campaign_content_link", link)
    return attach_hashes(link)


def affected_content_versions(
    links: Sequence[Mapping[str, Any]], *, changed_snapshot_ref: str
) -> list[str]:
    """Return content versions whose frozen fact snapshot is no longer current."""
    return [
        str(link["content_version_id"])
        for link in links
        if link.get("fact_snapshot_ref") == changed_snapshot_ref
        and link.get("status") not in {"superseded", "cancelled"}
    ]
