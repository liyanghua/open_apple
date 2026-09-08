from __future__ import annotations

import json
from pathlib import Path

from backlot.batch_actions import selection_quality_failures


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _eligible_fixture(child: Path, *, evaluation_status: str, alignment_status: str) -> None:
    _write(child / "artifacts" / "evaluation_report.json", {
        "status": evaluation_status,
        "alignment": {"status": alignment_status},
    })
    _write(child / "artifacts" / "final_props.json", {
        "captions": [{"text": "真实动作，真实结果"}],
    })
    _write(child / "artifacts" / "shot_execution_plan.json", {
        "shots": [{"id": "shot-01", "screen_copy": "真实动作"}],
    })
    _write(child / "operator" / "reviews" / "sample.json", {
        "review_id": "sample-1",
        "kind": "sample",
        "status": "approved",
        "created_at": "2026-09-06T10:00:00Z",
        "effect_confirmation": {
            "creative_direction": "pass",
            "hook": "pass",
            "proof": "pass",
            "pacing": "pass",
            "readability": "pass",
        },
    })


def test_selection_requires_evaluation_and_alignment_to_both_pass(tmp_path: Path) -> None:
    child = tmp_path / "candidate-1"
    _eligible_fixture(child, evaluation_status="revise", alignment_status="revise")
    candidate = {"candidate_id": "candidate-1", "direction": {"hook": "A"}}
    batch = {"diversity_mode": "legacy_read_only", "candidates": [candidate]}

    failures = selection_quality_failures(batch, candidate, child)

    assert any("evaluation" in item.lower() or "评价" in item for item in failures)
    assert any("alignment" in item.lower() or "对齐" in item for item in failures)
