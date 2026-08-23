"""Five-candidate fixture acceptance (Chunk 5 / Task 9).

Materializes the named-case fixture and verifies:
- pairwise diversity: a diverse pair passes, an opening-only pair fails;
- hard-gate precondition blocks an opening-only candidate;
- report reconstruction is idempotent and surfaces cost/event degradation.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from lib.artifact_hashing import semantic_sha256
from lib.batch_reporting import build_batch_run_report, build_batch_quality_report
from lib.candidate_diversity import (
    assert_candidate_variant_ready,
    build_variant_plan,
    compare_candidate_pair,
    selection_diversity_failures,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "batch_reporting" / "table_mat_batch_fixture.json"


def _shots(ids: list[str]) -> list[dict]:
    rows = [{"shot_id": sid, "difference_type": "shot_order", "evidence_class": "structural",
             "evidence_ref": {"kind": "artifact", "path": f"p/{sid}"}} for sid in ids]
    rows.append({"shot_id": "sv", "difference_type": "visual_grammar", "evidence_class": "visual",
                 "evidence_ref": {"kind": "artifact", "path": "p/sv"}})
    return rows


def _materialize(tmp_path: Path) -> Path:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    batch = tmp_path / fixture["project_id"]
    (batch / "artifacts").mkdir(parents=True)

    index_candidates = []
    for c in fixture["candidates"]:
        index_candidates.append({
            "candidate_id": c["candidate_id"], "label": c["label"], "direction": c["direction"],
            "project_id": c["candidate_id"], "status": c["status"],
            "cost_usd": c["cost_usd"], "attempts": c["attempts"],
        })
        child = tmp_path / c["candidate_id"]
        (child / "artifacts").mkdir(parents=True, exist_ok=True)
        _write(child / "project.json", {"project_id": c["candidate_id"], "title": c["candidate_id"],
                                        "pipeline_type": "cinematic-fast"})
        if c["dimensions"]:
            plan = build_variant_plan(
                batch_id=fixture["batch_id"], candidate_id=c["candidate_id"], variant_revision=1,
                baseline_ref={"name": "x", "path": "artifacts/x.json"},
                dimensions=c["dimensions"], shot_differences=_shots(c["structural_shot_ids"]),
                opening_only_change=c["opening_only_change"],
            )
            _write(child / "artifacts" / "candidate_variant_plan.json", plan)
        _write(child / "artifacts" / "evaluation_report.json", {
            "version": "1.0", "status": c["evaluation_status"],
            "hard_gate": {"pass": c["evaluation_status"] == "pass", "checks": []},
            "recommended_action": "repair" if c["evaluation_status"] != "pass" else "proceed",
        })
        if c["events_count"]:
            _write(child / "events.jsonl", "".join('{"n":%d}\n' % i for i in range(c["events_count"])))
        _write(child / "artifacts" / "cost_log.json", {"version": "1.0", "total_cost_usd": c["cost_log_total"]})

    index = {
        "version": "1.0", "batch_id": fixture["batch_id"], "project_id": fixture["project_id"],
        "created_at": "2026-08-23T00:00:00+00:00",
        "shared_research": {"refs": [{"name": "x", "path": "p"}]},
        "concurrency": {"max_candidates": 5, "max_parallel": 3},
        "differentiation_axes": {},
        "diversity_mode": fixture.get("diversity_mode") or "warning",
        "candidates": index_candidates,
        "selection": {"selected_candidate_ids": [], "reason": ""},
    }
    _write(batch / "artifacts" / "candidate_batch.json", index)
    return batch


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_variant_plans(batch: Path, ids: list[str]) -> dict[str, dict]:
    plans = {}
    for cid in ids:
        p = batch.parent / cid / "artifacts" / "candidate_variant_plan.json"
        if p.exists():
            plans[cid] = json.loads(p.read_text(encoding="utf-8"))
    return plans


def test_pairwise_diversity_blocks_opening_only_and_passes_diverse(tmp_path: Path) -> None:
    batch = _materialize(tmp_path)
    plans = _load_variant_plans(batch, ["cand-a", "cand-b", "cand-c"])

    # diverse pair passes
    assert compare_candidate_pair(plans["cand-a"], plans["cand-b"])["passes"] is True
    # opening-only pair fails
    assert compare_candidate_pair(plans["cand-a"], plans["cand-c"])["passes"] is False
    # hard-gate precondition blocks opening-only
    assert assert_candidate_variant_ready(plans["cand-c"]) != []
    assert assert_candidate_variant_ready(plans["cand-a"]) == []


def test_reports_reconstruct_idempotently_with_degradation(tmp_path: Path) -> None:
    batch = _materialize(tmp_path)
    rr1 = build_batch_run_report(batch)
    rr2 = build_batch_run_report(batch)
    qr1 = build_batch_quality_report(batch)
    qr2 = build_batch_quality_report(batch)

    assert semantic_sha256(rr1) == semantic_sha256(rr2)
    assert semantic_sha256(qr1) == semantic_sha256(qr2)

    # cand-e has cost_log_total != cost_usd -> cost_mismatch warning; no events -> missing_events
    codes = {w["code"] for w in rr1["data_quality"].get("warnings", [])}
    assert "cost_mismatch" in codes
    assert "missing_events" in codes

    # cand-d has no evaluation -> missing; cand-a -> revise
    statuses = {c["candidate_id"]: c["status"] for c in qr1["candidates"]}
    assert statuses["cand-d"] == "fail"
    assert statuses["cand-a"] == "revise"


def test_selection_diversity_failures_splits_structural_and_visual(tmp_path: Path) -> None:
    batch = _materialize(tmp_path)
    plans = _load_variant_plans(batch, ["cand-a", "cand-b"])
    result = selection_diversity_failures(plans["cand-a"], [plans["cand-b"]])
    assert "structural_failures" in result
    assert "visual_similarity_warnings" in result
    assert result["structural_failures"] == []  # cand-a is structurally diverse
