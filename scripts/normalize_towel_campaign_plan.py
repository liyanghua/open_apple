"""Normalize the existing P1/P2 batch plan into campaign artifacts.

This is a deterministic, read/write-free-of-provider migration helper. It
creates the campaign plan and pending-confirmation fact snapshots; it never
approves facts, schedules paid generation, publishes, or changes the legacy
batch plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lib.artifact_io import write_artifact_atomic
from lib.campaign_contracts import (
    build_content_recipe_from_slot,
    create_content_link,
    create_campaign_plan,
    create_fact_snapshot,
    migrate_legacy_batch_plan,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_from_product_facts(facts_path: Path, *, snapshot_id: str, source_record_id: str) -> dict:
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    claims = []
    for claim in facts.get("claims") or []:
        claims.append({
            "claim_id": str(claim.get("claim_id") or ""),
            "claim": str(claim.get("claim") or claim.get("statement") or ""),
            "status": str(claim.get("status") or "needs_evidence"),
            "evidence_status": str(claim.get("evidence_status") or "needs_human_confirmation"),
            "allowed_wording": list(claim.get("allowed_wording") or []),
            "forbidden_wording": list(claim.get("prohibited_wording") or []),
            "evidence_ids": [str(claim.get("claim_id") or "")],
        })
    return create_fact_snapshot(
        product_id=str(facts.get("product_id") or ""),
        sku=str(facts.get("sku") or ""),
        source_hash=_sha256(facts_path),
        source_record_id=source_record_id,
        claims=claims,
        snapshot_id=snapshot_id,
        status="pending_confirmation",
    )


def normalize(project_dir: Path) -> dict:
    legacy_path = project_dir / "batch_plan.json"
    if not legacy_path.is_file():
        raise FileNotFoundError(f"legacy batch plan not found: {legacy_path}")
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))

    snapshots = []
    for key in ("P1", "P2"):
        product_dir = project_dir.parent / f"playboy-towel-{key.lower()}-v1"
        facts_path = product_dir / "artifacts" / "product_facts.json"
        snapshot = _snapshot_from_product_facts(
            facts_path,
            snapshot_id=f"fact-{key.lower()}-v1",
            source_record_id=f"{key}_fact_v1",
        )
        write_artifact_atomic(
            f"artifacts/fact_snapshot_{key}.json",
            "fact_snapshot",
            snapshot,
            project_dir=project_dir,
        )
        snapshots.append(snapshot["snapshot_id"])

    migrated = migrate_legacy_batch_plan(
        legacy,
        campaign_id=str(legacy.get("campaign_id") or project_dir.name),
        target_count=300,
        pilot_count=60,
    )
    recipes = []
    links = []
    fact_by_sku = {
        str(json.loads((project_dir.parent / f"playboy-towel-{key.lower()}-v1" / "artifacts" / "product_facts.json").read_text(encoding="utf-8")).get("sku") or ""): f"fact-{key.lower()}-v1"
        for key in ("P1", "P2")
    }
    for slot in migrated["slots"]:
        snapshot_ref = str(slot.get("fact_snapshot_ref") or fact_by_sku.get(str(slot.get("sku") or "")) or "")
        recipe = build_content_recipe_from_slot(slot, fact_snapshot_ref=snapshot_ref)
        write_artifact_atomic(
            f"artifacts/recipes/{recipe['recipe_id']}.json",
            "content_recipe",
            recipe,
            project_dir=project_dir,
        )
        recipes.append(recipe)
        links.append(create_content_link(
            campaign_id=migrated["campaign_id"],
            content_slot_id=str(slot["content_slot_id"]),
            content_version_id=str(slot["content_version_id"]),
            direction_id=str(slot["direction_id"]),
            structure_id=str(slot["structure_id"]),
            support_type=str(slot["support_type"]),
            recipe_id=str(recipe["recipe_id"]),
            sku=str(slot["sku"]),
            fact_snapshot_ref=snapshot_ref,
            changed_variable=str(slot.get("changed_variable") or "") or None,
        ))
    write_artifact_atomic(
        "artifacts/campaign_content_links.json",
        "campaign_content_links",
        {"version": "1.0", "campaign_id": migrated["campaign_id"], "links": links},
        project_dir=project_dir,
    )
    for slot in migrated["slots"]:
        slot["fact_snapshot_ref"] = str(slot.get("fact_snapshot_ref") or fact_by_sku.get(str(slot.get("sku") or "")) or "")
    plan = create_campaign_plan(
        migrated["campaign_id"],
        slots=migrated["slots"],
        target_count=300,
        pilot_count=60,
        fact_snapshot_refs=snapshots,
    )
    write_artifact_atomic("artifacts/campaign_plan.json", "campaign_plan", plan, project_dir=project_dir)
    return {
        "campaign_id": plan["campaign_id"],
        "target_count": plan["target_count"],
        "pilot_count": plan["pilot_count"],
        "slot_count": len(plan["slots"]),
        "recipe_count": len(recipes),
        "fact_snapshot_refs": snapshots,
        "status": "pending_confirmation",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(normalize(args.project_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
