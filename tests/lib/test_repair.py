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


def test_failure_dimension_maps_to_single_repair_action():
    from lib.repair import repair_action_for_dimension

    assert repair_action_for_dimension("hook_clarity")["action"] == "rewrite_hook"
    assert repair_action_for_dimension("caption_readability")["action"] == "edit_caption"
    assert repair_action_for_dimension("product_evidence")["action"] == "replace_asset"
    assert repair_action_for_dimension("rhythm_pacing")["action"] == "shorten_shot"
    # 四类局部修复之外 → 必须走 rework
    assert repair_action_for_dimension("audio_quality")["action"] is None
    assert repair_action_for_dimension("commercial_originality")["action"] is None


def _block(total, scores):
    return {"weighted_total": total, "dimension_scores": scores}


def test_keep_when_total_and_target_dimension_improve():
    from lib.repair import keep_or_rollback

    decision = keep_or_rollback(
        _block(7.8, {"product_evidence": 7.0}),
        _block(8.6, {"product_evidence": 8.4}),
        target_dimensions=["product_evidence"],
    )
    assert decision["decision"] == "keep"


def test_rollback_when_total_drops():
    from lib.repair import keep_or_rollback

    decision = keep_or_rollback(
        _block(8.6, {"product_evidence": 8.4}),
        _block(8.4, {"product_evidence": 9.0}),
        target_dimensions=["product_evidence"],
    )
    assert decision["decision"] == "rollback"
    assert "总分未提升" in decision["reason"]


def test_rollback_when_target_dimension_does_not_improve():
    from lib.repair import keep_or_rollback

    decision = keep_or_rollback(
        _block(7.8, {"product_evidence": 7.0}),
        _block(8.6, {"product_evidence": 6.9}),
        target_dimensions=["product_evidence"],
    )
    assert decision["decision"] == "rollback"
    assert "product_evidence 未提升" in decision["reason"]


def test_rollback_when_new_version_unscored():
    from lib.repair import keep_or_rollback

    decision = keep_or_rollback(
        _block(7.8, {"product_evidence": 7.0}),
        _block(None, {}),
        target_dimensions=["product_evidence"],
    )
    assert decision["decision"] == "rollback"


def test_repairs_from_evaluation_report_bridges_targets():
    from lib.repair import repairs_from_evaluation_report

    report = {
        "scope": "sample",
        "artifact_sha256": "b" * 64,  # 评价制品自身 hash
        "subject_hash": "c" * 64,  # 被评估媒体的 hash（不应被当 artifact_sha256）
        "repair_targets": [
            {
                "check_id": "l1a_subtitle_bounds", "action": "edit_caption",
                "affected_shots": ["shot-03"], "scene_id": "s03",
                "upstream_stage": "edit", "rerun_scope": "local", "estimated_cost_usd": 0.1,
            },
            {
                "check_id": "l1a_black_frames", "action": "shorten_shot",
                "affected_shots": ["shot-05"], "upstream_stage": "edit",
                "rerun_scope": "preview", "estimated_cost_usd": 0.4,
            },
        ],
    }
    repairs = repairs_from_evaluation_report(
        "p-test", report, production_lock_hash="a" * 64, rework_round=1,
    )
    assert len(repairs) == 2
    caption, shorten = repairs
    assert caption["action"] == "edit_caption"
    assert caption["targets"] == [{"type": "shot", "id": "s03"}, {"type": "shot", "id": "shot-03"}]
    assert caption["render_route"] == "still"  # local -> still
    assert "upstream_stage=edit" in caption["note"]
    assert shorten["action"] == "shorten_shot"
    assert shorten["render_route"] == "full_render"  # shorten_shot 强制 full
    # RepairPlan 绑定评价 scope + 评价制品自身的 artifact_sha256（不是 subject_hash）
    assert caption["evaluation_report_ref"]["path"] == "artifacts/evaluation_report.sample.json"
    assert caption["evaluation_report_ref"]["scope"] == "sample"
    assert caption["evaluation_report_ref"]["artifact_sha256"] == "b" * 64


def test_repairs_from_evaluation_report_skips_invalid_action():
    from lib.repair import repairs_from_evaluation_report

    report = {"repair_targets": [{"check_id": "x", "action": "not_real", "affected_shots": []}]}
    assert repairs_from_evaluation_report("p", report, production_lock_hash="b" * 64) == []
