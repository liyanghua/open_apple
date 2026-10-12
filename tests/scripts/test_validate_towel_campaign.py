from __future__ import annotations

from pathlib import Path

from scripts.validate_towel_campaign import validate


PROJECT = Path(__file__).resolve().parents[1] / "fixtures/towel_campaign"


def test_visual_sample_gate_accepts_pending_facts():
    result = validate(PROJECT)
    assert result["ready"] is True
    assert result["slot_count"] == 60
    assert result["recipe_count"] == 60


def test_paid_gate_rejects_pending_facts():
    result = validate(PROJECT, paid=True)
    assert result["ready"] is False
    assert any("not approved" in item for item in result["blockers"])
