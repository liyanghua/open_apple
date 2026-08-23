"""Backfill batch reports: read-only + idempotent (Task 6)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from lib.artifact_hashing import semantic_sha256
from lib.batch_reporting import build_batch_run_report, build_batch_quality_report
from scripts.backfill_batch_reports import _write


def _fixture() -> Path:
    tmp = Path(tempfile.mkdtemp())
    batch = tmp / "batch-b1"
    (batch / "artifacts").mkdir(parents=True)
    index = {
        "version": "1.0", "batch_id": "b1", "project_id": "batch-b1",
        "created_at": "2026-08-23T00:00:00+00:00",
        "shared_research": {"refs": [{"name": "x", "path": "p"}]},
        "concurrency": {"max_candidates": 5, "max_parallel": 3},
        "differentiation_axes": {},
        "candidates": [
            {"candidate_id": "cand-01", "label": "c1", "direction": {"hook": "h1"},
             "project_id": "cand-01", "status": "evaluated", "cost_usd": 0.5, "attempts": 1},
        ],
        "selection": {"selected_candidate_ids": [], "reason": ""},
    }
    (batch / "artifacts" / "candidate_batch.json").write_text(json.dumps(index), encoding="utf-8")
    child = tmp / "cand-01"
    (child / "artifacts").mkdir(parents=True, exist_ok=True)
    (child / "artifacts" / "evaluation_report.final.json").write_text(
        json.dumps({"version": "1.0", "status": "revise",
                    "hard_gate": {"pass": False, "checks": []}, "recommended_action": "repair"}),
        encoding="utf-8")
    return batch


def test_backfill_writes_reports_and_is_idempotent() -> None:
    batch = _fixture()
    rr = build_batch_run_report(batch)
    qr = build_batch_quality_report(batch)
    _write(batch, "batch_run_report", rr)
    _write(batch, "batch_quality_report", qr)

    assert (batch / "artifacts" / "batch_run_report.json").is_file()
    assert (batch / "artifacts" / "batch_quality_report.json").is_file()

    # rebuild same inputs -> same semantic hashes (idempotent)
    rr2 = build_batch_run_report(batch)
    qr2 = build_batch_quality_report(batch)
    assert semantic_sha256(rr) == semantic_sha256(rr2)
    assert semantic_sha256(qr) == semantic_sha256(qr2)


def test_backfill_is_read_only() -> None:
    """构建器不产生 provider/VLM/render 调用：只读 JSON/事件文件，且不写候选目录。"""
    batch = _fixture()
    child = batch.parent / "cand-01"
    before = {p.name for p in child.rglob("*") if p.is_file()}
    build_batch_run_report(batch)
    build_batch_quality_report(batch)
    after = {p.name for p in child.rglob("*") if p.is_file()}
    assert before == after  # 候选目录未变（零副作用）
