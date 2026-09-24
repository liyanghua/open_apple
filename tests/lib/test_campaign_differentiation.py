"""Creative axes are substantive; registered experiments compare to one baseline."""
from dataclasses import replace
import pytest

from lib.differentiation import CandidateSignature, build_differentiation_plan, compare_candidates


def candidate(name):
    return CandidateSignature(candidate_id=name, product_id="S01", hook_pattern="question",
        primary_action_keys=("unfold",), action_keys=("unfold", "hang"), copy_text="真实展开查看尺寸",
        beat_durations=(3, 4), beat_order=("question", "proof"), scene_context="bathroom",
        pacing_curve="steady", caption_strategy="plain", audio_strategy="voice")


def test_two_substantive_axes_plus_cosmetics_do_not_pass_three_axis_rule():
    a = candidate("a")
    b = replace(a, candidate_id="b", hook_pattern="result", scene_context="gym",
                caption_strategy="bigger-red", audio_strategy="new-track", pacing_curve="fast",
                copy_text="完全不同的说明文本")
    result = compare_candidates(a, b)
    assert result["status"] == "needs_redesign"
    assert set(result["effective_differing_axes"]) == {"hook_pattern", "scene_context"}
    assert result["minimum_effective_axes"] == 3
    assert result["human_review_required"] is True


def test_cross_product_also_requires_three_substantive_axes():
    a = candidate("a")
    b = replace(a, candidate_id="b", product_id="S08", hook_pattern="result", scene_context="gym")
    assert compare_candidates(a, b)["status"] == "needs_redesign"
    b = replace(b, action_keys=("wipe", "fold"))
    assert compare_candidates(a, b)["status"] == "distinct"


def controlled(name="base"):
    return replace(candidate(name), experiment_family_id="E-W3-S01-G01", baseline_candidate_id="base",
                   preregistered_variable="hook_pattern", registration_ref="experiment-card-v1")


def test_preregistered_single_variable_is_not_rejected_by_similarity_threshold():
    baseline = controlled()
    variant = replace(controlled("variant"), hook_pattern="result")
    result = compare_candidates(baseline, variant)
    assert result["status"] == "controlled_experiment"
    assert result["baseline_candidate_id"] == "base"
    assert result["minimum_effective_axes"] == 1
    assert result["human_review_required"] is True


def test_registration_or_baseline_cannot_be_inferred_from_family_name():
    baseline = controlled()
    variant = replace(controlled("variant"), hook_pattern="result", registration_ref="")
    assert compare_candidates(baseline, variant)["status"] != "controlled_experiment"


def test_registered_experiment_cannot_hide_sku_or_new_evidence_changes():
    baseline = controlled()
    changed_sku = replace(controlled("variant"), hook_pattern="result", product_id="S08")
    assert compare_candidates(baseline, changed_sku)["status"] != "controlled_experiment"
    changed_evidence = replace(controlled("variant"), hook_pattern="result", evidence_keys=("new-test",))
    assert compare_candidates(baseline, changed_evidence)["status"] != "controlled_experiment"


def test_missing_baseline_cannot_produce_pass_with_one_variant():
    variant = replace(controlled("variant"), hook_pattern="result")
    plan = build_differentiation_plan("batch", [variant], created_at="2026-09-24T00:00:00Z")
    assert plan["status"] == "needs_redesign"
    assert "missing_experiment_baseline:base" in plan["warnings"]


@pytest.mark.parametrize("changes", [{"copy_text": "完全不同的口播"}, {"audio_strategy": "new-audio"},
                                    {"beat_durations": (1, 6)}, {"pacing_curve": "new-pace"},
                                    {"caption_strategy": "big-red"}])
def test_single_variable_registration_locks_all_other_control_fields(changes):
    variant = replace(controlled("variant"), hook_pattern="result", **changes)
    comparison = compare_candidates(controlled(), variant)
    assert comparison["status"] == "needs_redesign"
    assert comparison["unregistered_changed_fields"]


def test_explicit_registered_opening_copy_change_is_allowed_but_audio_is_not():
    baseline = replace(controlled(), allowed_changed_fields=("hook_pattern", "copy_text"))
    variant = replace(baseline, candidate_id="variant", hook_pattern="result", copy_text="预登记开场文本")
    assert compare_candidates(baseline, variant)["status"] == "controlled_experiment"
    changed_audio = replace(variant, audio_strategy="new-audio")
    assert compare_candidates(baseline, changed_audio)["status"] == "needs_redesign"


def test_chained_variant_cannot_hide_extra_change_against_baseline():
    baseline = controlled()
    variant_a = replace(controlled("variant-a"), hook_pattern="result")
    variant_b = replace(controlled("variant-b"), hook_pattern="result", scene_context="gym")
    plan = build_differentiation_plan("batch", [baseline, variant_a, variant_b], created_at="2026-09-24T00:00:00Z")
    rows = plan["sibling_comparisons"]
    assert len(rows) == 2
    assert all(row["candidate_a"] == "base" for row in rows)
    assert next(row for row in rows if row["candidate_b"] == "variant-a")["status"] == "controlled_experiment"
    assert next(row for row in rows if row["candidate_b"] == "variant-b")["status"] == "needs_redesign"


def test_asset_opening_and_keyframe_duplicates_are_advisory_warnings():
    a = replace(candidate("a"), media_segment_ids=("clip1:0-4", "clip2:0-2"),
                first_three_seconds_sha256="a" * 64, keyframe_sha256s=("b" * 64,))
    b = replace(a, candidate_id="b", hook_pattern="new", scene_context="gym", action_keys=("wipe",),
                copy_text="另外的素材说明")
    result = compare_candidates(a, b)
    assert result["media_segment_overlap"] == 1
    assert result["first_three_seconds_repeated"] is True
    assert result["keyframe_overlap"] == 1
    assert set(result["warning_fields"]) >= {"media_segment_overlap", "first_three_seconds_repeated", "keyframe_overlap"}
    assert result["advisory_only"] is True
