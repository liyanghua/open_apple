"""One-time, offline import of the two explicitly accepted historical films.

No generation, checkpoint backfill, billing claim or automatic certification.
Run from repository root: python -m scripts.migrate_towel_production_evidence
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backlot.operator_reviews import ReviewService
from backlot.project_commit import ProjectCommitStore
from lib.campaign_panorama import normalize_original_campaign_plan
from lib.production_brand import make_towel_brand_profile
from lib.production_evidence import build_production_subject, file_sha256, production_subject_hash
from lib.production_quality import collect_production_quality
from tools.video.seedance_ark import SeedanceArkVideo

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects/playboy-towel-p1p2-v1"
WAVE = "artifacts/waves/W1/first-two"
EXPECTED = {"P1-A01": "e5a714591f8ebf2da48bd75c5c7684af0c981934942e3f7b012786faeb2b2106",
            "P1-A03": "0faad06fc1cffd6141923ba1fd65c0ccfdf4017784c922d68768ee4e3df94ef0"}


def migrate():
    read = lambda ref: json.loads((PROJECT / ref).read_text(encoding="utf-8"))
    records = {key: read(f"{WAVE}/{key}/production_record.json") for key in EXPECTED}
    for key, record in records.items():
        if file_sha256(PROJECT / record["render"]["path"]) != EXPECTED[key]:
            raise ValueError(f"Historical approval does not authorize changed film: {key}")
    marker = PROJECT / "artifacts/production_migration_20260924.json"
    imported_now = not marker.exists()
    if imported_now:
        now = datetime.now(timezone.utc).isoformat()
        source = ROOT / "花花公子毛巾_300条_V2/300条周度实验排期.json"
        plan = normalize_original_campaign_plan(json.loads(source.read_text(encoding="utf-8")))
        acceptance_ref = "artifacts/historical_acceptance_20260924.json"
        acceptance = {"version": "1.0", "recorded_at": now, "approval_occurred_at": None,
                      "source": "explicit_user_conversation", "actor_id": "user:yichen",
                      "statement": "验收通过，我想把这2条成片的生产过程 需要总结下",
                      "implementation_authorization": "PLEASE IMPLEMENT THIS PLAN: 两条已验收成片复盘与 300 条批量生产升级计划",
                      "scope": "Two exact film versions; no assertion that missing machine checks passed.",
                      "media_sha256": EXPECTED}
        ledger_ref = f"{WAVE}/video_cost.json"
        with ProjectCommitStore(PROJECT).transaction(action={"type": "historical_production_import", "actor_id": "agent"}) as tx:
            tx.stage_json(acceptance_ref, acceptance, schema="historical_acceptance")
            tx.stage_json("artifacts/campaign_300_plan.json", plan, schema="campaign_plan")
            tx.stage_json("artifacts/production_brand_profile_v1.json", make_towel_brand_profile(), schema="brand_profile")
            tx.stage_json("artifacts/campaign_release_context.json", {"version": "1.0", "fact_versions": {},
                          "brand_version": None, "production_budget": None, "recipe_first_articles": {},
                          "approved_weeks": [], "note": "Planning estimates are not budget approval; original three SKUs are not the P1/P2 pilots."}, schema="campaign_release_context")
            tx.stage_json("artifacts/campaign_path_costs.json", {"version": "1.0", "entries": []}, schema="campaign_path_costs")
            tx.stage_json("artifacts/production_campaign_index.json", {
                "version": "1.0", "plan_ref": "artifacts/campaign_300_plan.json",
                "production_record_refs": [f"{WAVE}/{key}/production_record.json" for key in EXPECTED],
                "release_context_ref": "artifacts/campaign_release_context.json",
                "path_cost_entries_ref": "artifacts/campaign_path_costs.json",
            }, schema="production_campaign_index")
            tx.stage_json(f"{WAVE}/video_cost.pre-evidence-migration.json", read(ledger_ref), schema="cost_log")
            for key, record in records.items():
                record.update({"provenance": "legacy_import", "imported_at": now, "campaign_role": "pilot",
                               "run_id": f"playboy-towel-p1p2-v1:{key}", "work_id": f"pilot:{key}",
                               "content_version_id": f"{key}@{EXPECTED[key]}", "sku": "pilot-P1-yb-bb-03",
                               "production_route": "ai_assisted", "status": "human_accepted",
                               "original_campaign_slot": None, "fact_version": None,
                               "fact_snapshot_ref": "artifacts/fact_snapshot_P1.json",
                               "brand_version": "approved_production_baseline_v3",
                               "historical_stage_gaps": {"status": "unverified", "checkpoints_backfilled": False},
                               "review_dependencies": {"historical_acceptance": acceptance_ref},
                               "quality_report_ref": f"{WAVE}/{key}/quality_evidence.json",
                               "costs": {"estimated_cny": None, "paid_cny": None,
                                         "shared_action_pool_ledger_ref": ledger_ref},
                               "timing": {"generation_ms": None, "render_ms": None, "review_wait_ms": None, "human_work_ms": None}})
                report = collect_production_quality(PROJECT, record, {"technical": f"{WAVE}/{key}/final_qa.json"})
                judge_state = record.get("checks", {}).get("video_judge")
                report["checks"].append({"id": "video_judge", "status": "error" if key == "P1-A01" else "not_run",
                                          "method": "historical_import", "evidence_refs": [],
                                          "issues": [str(judge_state), "Original raw report retained; no new automatic score asserted."]})
                tx.stage_json(record["quality_report_ref"], report, schema="production_quality")
                tx.stage_json(f"{WAVE}/{key}/production_record.json", record, schema="production_record")
                old_review = read(record["human_review_ref"])
                tx.stage_json(f"{WAVE}/{key}/human_review.pre-evidence-migration.json", old_review, schema="historical_review")
                tx.stage_json(record["human_review_ref"], {"status": "approved", "render_sha256": EXPECTED[key],
                              "source_ref": acceptance_ref, "formal_review_source": "operator/reviews",
                              "note": "Human acceptance only; consult quality_evidence for automatic checks."}, schema="historical_review")
            tx.stage_json("artifacts/production_migration_20260924.json", {"version": "1.0", "recorded_at": now,
                          "scope": "historical records imported; per-film reviews and usage reconciliation are independently idempotent"}, schema="migration_record")
    # A rerun may replay an exact approved subject, never transfer its approval
    # to altered props, facts or evidence just because the film stayed the same.
    service = ReviewService(PROJECT)
    marker_doc = read("artifacts/production_migration_20260924.json")
    pinned = marker_doc.get("approval_subject_hashes")
    current = {key: production_subject_hash(build_production_subject(PROJECT, f"{WAVE}/{key}/production_record.json"))
               for key in EXPECTED}
    if imported_now:
        pinned = current
        marker_doc["approval_subject_hashes"] = pinned
        with ProjectCommitStore(PROJECT).transaction(action={"type": "pin_historical_approval_subjects", "actor_id": "agent"}) as tx:
            tx.stage_json("artifacts/production_migration_20260924.json", marker_doc, schema="migration_record")
    elif isinstance(pinned, dict):
        if any(pinned.get(key) != digest for key, digest in current.items()):
            raise ValueError("Historical approval does not authorize changed production dependencies")
    else:
        # Old migration markers have no recoverable pending-approval authority.
        # Accept only subjects that already have their own exact final approval.
        for key, digest in current.items():
            matching = [r for r in service.list() if r.get("kind") == "final_review"
                        and r.get("subject_id") == key and r.get("subject_hash") == digest]
            latest = max(matching, key=lambda r: r.get("subject_version", 0), default={})
            if latest.get("status") != "approved":
                raise ValueError("Historical approval is missing or its production dependencies changed")
        pinned = current
    ledger = read(f"{WAVE}/video_cost.json")
    for entry in ledger["entries"]:
        if entry["status"] not in {"reserved", "completed"}:
            continue
        receipt = read(f"{WAVE}/{entry['operation']}/query_result.json")
        task = receipt["data"]["task"]
        tool = SeedanceArkVideo()
        accounting = tool.reconcile_task(task, {})  # Pure projection, no ledger path.
        if (entry["status"] in {"completed", "failed"}
                and entry.get("provider_task_id") == task.get("id")
                and entry.get("provider_status") == task.get("status")
                and entry.get("usage") == (task.get("usage") or {})
                and entry.get("catalog_estimate") == accounting.get("catalog_estimate")):
            continue
        tool.reconcile_task(task, {
            "cost_log_path": str(PROJECT / WAVE / "video_cost.json"), "reservation_id": entry["id"]})
    approvals = []
    for key in EXPECTED:
        review = service.create_final_review(record_path=f"{WAVE}/{key}/production_record.json", submitted_by="historical-import")
        if review["subject_hash"] != pinned[key]:
            raise ValueError("Historical approval dependencies changed during migration")
        result = service.decide(review_id=review["review_id"], decision="approved", actor_id="user:yichen",
                                reason="用户已明确验收这两条具体成片，并授权登记正式审批；历史自动检查缺口保持原样。",
                                expected_version=review["subject_version"], expected_hash=review["subject_hash"])
        approvals.append({"content_slot_id": key, "review_id": result["review_id"], "status": result["status"]})
    print(json.dumps({"approvals": approvals, "paid_generation_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    migrate()
