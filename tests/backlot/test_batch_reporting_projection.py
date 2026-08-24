"""Report projection tests (Task 7): complete / partial / degraded / missing."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from backlot.batch_state import build_batch_review_data
from lib.batch_reporting import build_batch_run_report, build_batch_quality_report


def _materialize(tmp_path: Path, *, with_reports: bool = False) -> tuple[Path, dict]:
    batch = tmp_path / "batch-b1"
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
    child = tmp_path / "cand-01"
    (child / "artifacts").mkdir(parents=True, exist_ok=True)
    (child / "artifacts" / "evaluation_report.json").write_text(
        json.dumps({"version": "1.0", "status": "revise", "hard_gate": {"pass": False, "checks": []},
                    "recommended_action": "repair"}), encoding="utf-8")
    (child / "events.jsonl").write_text('{"n":1,"ts":"2026-08-24T00:00:00+00:00"}\n', encoding="utf-8")

    if with_reports:
        from scripts.backfill_batch_reports import _write
        _write(batch, "batch_run_report", build_batch_run_report(batch))
        _write(batch, "batch_quality_report", build_batch_quality_report(batch))
    return batch, index


def _projection(tmp_path: Path, with_reports: bool) -> dict:
    batch, index = _materialize(tmp_path, with_reports=with_reports)
    board = {"_project_dir": batch, "project_id": "batch-b1"}
    return build_batch_review_data(board, index)


def test_projection_missing_reports_disables_select_publish(tmp_path: Path) -> None:
    data = _projection(tmp_path, with_reports=False)
    assert data["reports"]["status"] == "missing"
    assert "select" in data["reports"]["disabled_actions"]
    assert "publish" in data["reports"]["disabled_actions"]
    assert data["reports"]["recovery_action"] == "rebuild_reports"


def test_projection_complete_reports_enable_actions(tmp_path: Path) -> None:
    data = _projection(tmp_path, with_reports=True)
    assert data["reports"]["status"] == "complete"
    assert data["reports"]["disabled_actions"] == []
    assert data["reports"]["recovery_action"] is None
    assert data["reports"]["run"]["cost"] is not None
    assert data["reports"]["quality"]["recommendations"] is not None


def test_projection_survives_unreadable_reports(tmp_path: Path) -> None:
    batch, index = _materialize(tmp_path, with_reports=True)
    (batch / "artifacts" / "batch_run_report.json").write_text("{not json", encoding="utf-8")
    board = {"_project_dir": batch, "project_id": "batch-b1"}
    data = build_batch_review_data(board, index)
    assert data["reports"]["status"] in {"partial", "missing"}
    assert any("batch_run_report" in w for w in data["reports"]["warnings"])
