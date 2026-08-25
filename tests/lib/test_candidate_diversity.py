"""Candidate diversity contract tests (schema + custom validation).

Task 3 will add the pure-library tests (build_variant_plan, fingerprints,
pairwise comparison). These first tests freeze the candidate_variant_plan
artifact contract.
"""
from __future__ import annotations

import copy

import pytest
from jsonschema import ValidationError

from schemas.artifacts import validate_artifact


def _dimension(value: str = "v", baseline: str = "b", changed: bool = False) -> dict:
    return {"value": value, "baseline_value": baseline, "changed": changed, "rationale": "理由"}


def _valid_plan() -> dict:
    return {
        "version": "1.0",
        "batch_id": "b1",
        "candidate_id": "c1",
        "variant_revision": 1,
        "baseline_ref": {"name": "x", "path": "artifacts/x.json"},
        "dimensions": {
            "hook_type": _dimension(changed=True),
            "narrative_structure": _dimension(changed=True),
            "visual_grammar": _dimension(changed=True),
            "pacing_profile": _dimension(),
            "evidence_strategy": _dimension(),
            "asset_strategy": _dimension(),
        },
        "shot_differences": [
            {"shot_id": "s1", "difference_type": "shot_order", "evidence_class": "structural",
             "evidence_ref": {"kind": "artifact", "path": "p"}},
            {"shot_id": "s2", "difference_type": "duration", "evidence_class": "structural",
             "evidence_ref": {"kind": "artifact", "path": "p"}},
            {"shot_id": "s3", "difference_type": "source_window", "evidence_class": "structural",
             "evidence_ref": {"kind": "artifact", "path": "p"}},
        ],
        "difference_fingerprint": {
            "structure_hash": "a" * 64, "visual_hash": "b" * 64, "timing_hash": "c" * 64,
            "changed_dimension_count": 3, "structural_shot_count": 3,
        },
        "opening_window": {"start_seconds": 0, "end_seconds": 3},
        "opening_only_change": False,
        "provenance": {},
    }


def test_valid_six_dimension_plan_passes() -> None:
    validate_artifact("candidate_variant_plan", _valid_plan())


def test_missing_dimension_rejected() -> None:
    plan = _valid_plan()
    del plan["dimensions"]["asset_strategy"]
    with pytest.raises(ValidationError):
        validate_artifact("candidate_variant_plan", plan)


def test_duplicate_shot_id_rejected() -> None:
    plan = _valid_plan()
    plan["shot_differences"][1]["shot_id"] = "s1"
    with pytest.raises(ValidationError, match="unique"):
        validate_artifact("candidate_variant_plan", plan)


def test_invalid_fingerprint_hash_rejected() -> None:
    plan = _valid_plan()
    plan["difference_fingerprint"]["structure_hash"] = "not-hex"
    with pytest.raises(ValidationError):
        validate_artifact("candidate_variant_plan", plan)


def test_fingerprint_count_mismatch_rejected() -> None:
    plan = _valid_plan()
    plan["difference_fingerprint"]["changed_dimension_count"] = 2
    with pytest.raises(ValidationError, match="changed_dimension_count"):
        validate_artifact("candidate_variant_plan", plan)


def test_opening_only_change_with_late_difference_rejected() -> None:
    plan = _valid_plan()
    plan["opening_only_change"] = True
    plan["shot_differences"][0]["time_range"] = {"start_seconds": 0, "end_seconds": 5}
    with pytest.raises(ValidationError, match="opening_only_change"):
        validate_artifact("candidate_variant_plan", plan)


# ---------------------------------------------------------------------------
# Task 3: pure library tests
# ---------------------------------------------------------------------------
from lib.candidate_diversity import (
    DEFAULT_VARIANT_STRATEGIES,
    assert_candidate_variant_ready,
    build_default_variant_plan,
    build_variant_plan,
    changed_dimension_count,
    compare_candidate_pair,
    compute_difference_fingerprint,
    selection_diversity_failures,
)


def _dims(changed: tuple = ("hook_type", "narrative_structure", "visual_grammar"), prefix: str = "v") -> dict:
    return {
        key: {"value": f"{prefix}-{key}" if key in changed else f"{key}-baseline",
              "baseline_value": f"{key}-baseline", "changed": key in changed, "rationale": "r"}
        for key in ("hook_type", "narrative_structure", "visual_grammar",
                    "pacing_profile", "evidence_strategy", "asset_strategy")
    }


def _shots(n_structural: int = 3) -> list[dict]:
    rows = []
    for i in range(n_structural):
        rows.append({"shot_id": f"s{i}", "difference_type": "shot_order",
                     "evidence_class": "structural",
                     "evidence_ref": {"kind": "artifact", "path": f"p{i}"}})
    rows.append({"shot_id": "sv", "difference_type": "visual_grammar",
                 "evidence_class": "visual",
                 "evidence_ref": {"kind": "artifact", "path": "pv"}})
    return rows


def _plan(candidate_id: str, *, dims=None, shots=None, opening_only=False, prefix: str = "v") -> dict:
    return build_variant_plan(
        batch_id="b1", candidate_id=candidate_id, variant_revision=1,
        baseline_ref={"name": "x", "path": "artifacts/x.json"},
        dimensions=dims or _dims(prefix=prefix), shot_differences=shots or _shots(),
        opening_only_change=opening_only,
    )


def test_fingerprint_is_deterministic_and_counts_match() -> None:
    fp1 = compute_difference_fingerprint(_dims(), _shots())
    fp2 = compute_difference_fingerprint(_dims(), _shots())
    assert fp1 == fp2
    assert fp1["changed_dimension_count"] == 3
    assert fp1["structural_shot_count"] == 3
    assert len(fp1["structure_hash"]) == 64


def test_build_variant_plan_computes_fingerprint() -> None:
    plan = _plan("c1")
    assert plan["difference_fingerprint"]["changed_dimension_count"] == 3
    assert plan["opening_only_change"] is False


def test_default_variant_catalogue_produces_reviewable_distinct_plans() -> None:
    plans = [
        build_default_variant_plan("b1", f"c{i}", i)
        for i in range(len(DEFAULT_VARIANT_STRATEGIES))
    ]
    assert all(plan["approval_status"] == "awaiting_human" for plan in plans)
    assert all(selection_diversity_failures(plan, [])['structural_failures'] == [] for plan in plans)
    assert all(
        compare_candidate_pair(plans[i], plans[j])["passes"]
        for i in range(len(plans))
        for j in range(i + 1, len(plans))
    )


def test_pair_passes_for_distinct_candidates() -> None:
    distinct_shots = _shots()
    for row in distinct_shots:
        row["evidence_ref"] = {"kind": "artifact", "path": f"other-{row['shot_id']}"}
    result = compare_candidate_pair(
        _plan("c1", prefix="A"),
        _plan("c2", prefix="B", shots=distinct_shots),
    )
    assert result["passes"] is True
    assert result["changed_dimensions"] >= 3
    assert result["structural_shot_count"] >= 3


def test_pair_rejects_identical_structural_shots_even_when_dimensions_differ() -> None:
    result = compare_candidate_pair(_plan("c1", prefix="A"), _plan("c2", prefix="B"))

    assert result["structural_shot_count"] == 0
    assert result["passes"] is False


def test_readiness_recomputes_structural_count_instead_of_trusting_fingerprint() -> None:
    plan = _plan("c1")
    plan["shot_differences"] = []
    plan["difference_fingerprint"]["structural_shot_count"] = 3

    failures = assert_candidate_variant_ready(plan)

    assert any("结构镜头差异少于三个" in item for item in failures)


def test_pair_fails_for_opening_only_change() -> None:
    a = _plan("c1", opening_only=True)
    result = compare_candidate_pair(a, _plan("c2"))
    assert result["passes"] is False


def test_pair_fails_for_insufficient_dimensions() -> None:
    a = _plan("c1", dims=_dims(changed=("hook_type",)))
    result = compare_candidate_pair(a, _plan("c2"))
    assert result["passes"] is False
    assert result["changed_dimensions"] < 3


def test_selection_diversity_failures_splits_classes() -> None:
    opening_plan = _plan("c1", opening_only=True)
    result = selection_diversity_failures(opening_plan, [_plan("c2")])
    assert any("前三秒" in item for item in result["structural_failures"])

    # identical visual hash between two plans -> visual warning
    shared = _plan("c1")
    sibling = _plan("c2", shots=_shots(3))
    # force identical visual fingerprints by using the same visual-only shot rows
    shared_visual = build_variant_plan(
        batch_id="b1", candidate_id="c1", variant_revision=1,
        baseline_ref={"name": "x", "path": "artifacts/x.json"},
        dimensions=_dims(), shot_differences=_shots(),
        opening_only_change=False,
    )
    sibling_visual = build_variant_plan(
        batch_id="b1", candidate_id="c2", variant_revision=1,
        baseline_ref={"name": "x", "path": "artifacts/x.json"},
        dimensions=_dims(), shot_differences=_shots(),
        opening_only_change=False,
    )
    res = selection_diversity_failures(shared_visual, [sibling_visual])
    assert any("视觉指纹一致" in item for item in res["visual_similarity_warnings"])


def test_proposal_concept_diversity_requires_two_structural_dims():
    from lib.candidate_diversity import proposal_concept_diversity

    same_structure = [
        {"id": "c1", "narrative_structure": "problem_solution", "visual_approach": "真实测试+短字幕"},
        {"id": "c2", "narrative_structure": "problem_solution", "visual_approach": "真实测试+短字幕"},
    ]
    res = proposal_concept_diversity(same_structure)
    assert res["pass"] is False
    assert res["distinct_dims"] == []

    diverse = [
        {"id": "c1", "narrative_structure": "problem_solution", "visual_approach": "真实测试+短字幕"},
        {"id": "c2", "narrative_structure": "story", "visual_approach": "产品质感+氛围"},
        {"id": "c3", "narrative_structure": "data_narrative", "visual_approach": "快剪+数据字卡"},
    ]
    res2 = proposal_concept_diversity(diverse)
    assert res2["pass"] is True
    assert set(res2["distinct_dims"]) == {"narrative_structure", "visual_approach"}
    assert res2["concept_count"] == 3


def test_proposal_concept_diversity_rejects_under_two_concepts():
    from lib.candidate_diversity import proposal_concept_diversity

    res = proposal_concept_diversity([{"id": "c1", "narrative_structure": "story", "visual_approach": "a"}])
    assert res["pass"] is False
    assert res["concept_count"] == 1
