"""Tests for the localized repair planner (Design_Review P1-3)."""

from __future__ import annotations

import pytest

from lib.repair import assert_lock_unchanged, plan_repair, repair_decision_entry
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact

LOCK_HASH = "a" * 64


def _ref():
    return {"name": "evaluation_report", "path": "artifacts/evaluation_report.json", "artifact_sha256": "b" * 64}


def test_repair_registered():
    assert "repair" in ARTIFACT_NAMES


def test_plan_repair_defaults_per_action():
    cases = {
        "rewrite_hook": ("sample", "weak_hook"),
        "edit_caption": ("still", "caption_overlap"),
        "replace_asset": ("sample", "cover_mismatch"),
        "shorten_shot": ("full_render", "slow_start"),
    }
    for action, (route, tag) in cases.items():
        repair = plan_repair("p-test", repair_id=f"r-{action}", action=action,
                             targets=[{"type": "shot", "id": "shot-01"}],
                             evaluation_report_ref=_ref(), production_lock_hash=LOCK_HASH)
        validate_artifact("repair", repair)
        assert repair["render_route"] == route
        assert tag in repair["issue_tags"]


def test_plan_repair_rejects_unknown_action():
    with pytest.raises(ValueError):
        plan_repair("p-test", repair_id="r-x", action="rotate_shot",
                    targets=[{"type": "shot", "id": "s1"}],
                    evaluation_report_ref=_ref(), production_lock_hash=LOCK_HASH)


def test_plan_repair_rejects_shorten_shot_with_sample_route():
    with pytest.raises(ValueError, match="full_render"):
        plan_repair("p-test", repair_id="r-x", action="shorten_shot",
                    targets=[{"type": "shot", "id": "s1"}],
                    evaluation_report_ref=_ref(), production_lock_hash=LOCK_HASH,
                    render_route="sample")


def test_assert_lock_unchanged():
    repair = plan_repair("p-test", repair_id="r-1", action="edit_caption",
                         targets=[{"type": "caption", "id": "c1"}],
                         evaluation_report_ref=_ref(), production_lock_hash=LOCK_HASH)
    assert_lock_unchanged(repair, LOCK_HASH)
    with pytest.raises(ValueError, match="re-approval"):
        assert_lock_unchanged(repair, "f" * 64)


def test_repair_decision_entry_is_schema_shape():
    repair = plan_repair("p-test", repair_id="r-1", action="rewrite_hook",
                         targets=[{"type": "hook", "id": "hook-01"}],
                         evaluation_report_ref=_ref(), production_lock_hash=LOCK_HASH,
                         rework_round=2)
    entry = repair_decision_entry(repair, subject="钩子重写", reason="五项确认钩子不抓人")
    assert entry["category"] == "rework_cause"
    assert entry["issue_tags"] == ["weak_hook"]
    assert entry["rework_round"] == 2
    assert entry["decision_id"] == "repair-r-1"
