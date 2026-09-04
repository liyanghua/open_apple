"""Deterministic candidate differentiation and batch dedup contracts."""

from __future__ import annotations

import json

import pytest

from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.candidate_batch import create_candidate_batch
from lib.checkpoint import FASTLINE_ARTIFACTS, SUPPLEMENTARY_ARTIFACTS
from lib.differentiation import (
    CandidateSignature,
    action_jaccard,
    beat_duration_delta,
    build_dedup_summary,
    build_differentiation_plan,
    compare_candidates,
    copy_ngram_dice,
    normalize_copy,
)
from lib.template_batch import create_template_batch
from lib.template_batch import persist_template_batch, resolve_run_batch_differentiation_ref
from lib.candidate_batch import persist_candidate_batch
from lib.template_run_plan import create_template_run
from lib.template_run_plan import check_template_run_plan_ready, validate_differentiation_plan_ref
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact


PLAN_REF = {
    "name": "differentiation_plan",
    "path": "artifacts/differentiation_plan.json",
    "artifact_sha256": "d" * 64,
}


def _candidate(
    candidate_id: str,
    product_id: str,
    *,
    hook: str,
    primary_actions: tuple[str, ...],
    actions: tuple[str, ...],
    copy: str,
    beats: tuple[float, ...],
    beat_order: tuple[str, ...] = ("hook", "proof", "cta"),
    scene_context: str = "bathroom",
    pacing_curve: str = "fast-steady",
    caption_strategy: str = "proof-labels",
    audio_strategy: str = "tts-bgm",
    sibling_similarity_budget: float = 0.8,
) -> CandidateSignature:
    return CandidateSignature(
        candidate_id=candidate_id,
        product_id=product_id,
        hook_pattern=hook,
        primary_action_keys=primary_actions,
        action_keys=actions,
        copy_text=copy,
        beat_durations=beats,
        beat_order=beat_order,
        scene_context=scene_context,
        pacing_curve=pacing_curve,
        caption_strategy=caption_strategy,
        audio_strategy=audio_strategy,
        forbidden_repeats=("same-opening",),
        matrix_row_refs=(f"row-{candidate_id}",),
        sibling_similarity_budget=sibling_similarity_budget,
    )


def test_copy_normalization_and_two_gram_dice_are_unicode_stable() -> None:
    assert normalize_copy("ＡＢＣ，  毛巾！\n123") == "abc 毛巾 123"
    assert copy_ngram_dice("ＡＢＣ，毛巾！", "abc 毛巾") == pytest.approx(1.0)
    assert copy_ngram_dice("单", "单") == 0.0


def test_action_jaccard_and_normalized_beat_delta_follow_v1_formula() -> None:
    assert action_jaccard([], []) == 0.0
    assert action_jaccard(["a", "b", "c", "d", "e"], ["a", "b", "c", "d"]) == pytest.approx(0.8)
    assert beat_duration_delta([5, 5], [4, 6]) == pytest.approx(0.2)
    assert beat_duration_delta([], []) == 0.0


def test_same_product_threshold_fixture_marks_high_similarity_and_distinct() -> None:
    a = _candidate(
        "a", "towel", hook="吸水动作看得见", primary_actions=("pour", "absorb"),
        actions=("pour", "absorb", "squeeze", "touch", "fold"),
        copy="吸水动作看得见 柔软触感也看得见", beats=(50, 50),
    )
    b = _candidate(
        "b", "towel", hook="吸水动作看得见", primary_actions=("pour", "absorb"),
        actions=("pour", "absorb", "squeeze", "touch"),
        copy="吸水动作看得见 柔软触感也看得见", beats=(46, 54),
    )
    c = _candidate(
        "c", "towel", hook="收纳展示", primary_actions=("fold",),
        actions=("fold",), copy="折叠以后整齐收纳", beats=(18, 82),
        beat_order=("hook", "context", "cta"), scene_context="bedroom",
        pacing_curve="slow-reveal", caption_strategy="minimal",
    )

    high = compare_candidates(a, b)
    distinct = compare_candidates(a, c)

    assert high["scope"] == "same_product"
    assert high["action_jaccard"] == pytest.approx(0.8)
    assert high["copy_ngram_dice"] >= 0.85
    assert high["beat_duration_delta"] == pytest.approx(0.08)
    assert high["status"] == "high_similarity"
    assert distinct["action_jaccard"] == pytest.approx(0.2)
    assert distinct["copy_ngram_dice"] < 0.85
    assert distinct["beat_duration_delta"] > 0.15
    assert distinct["status"] == "distinct"


def test_fewer_than_two_changed_axes_requires_redesign() -> None:
    a = _candidate(
        "a", "towel", hook="同一片头", primary_actions=("pour",), actions=("pour",),
        copy="完全不同的口播甲", beats=(50, 50),
    )
    b = _candidate(
        "b", "towel", hook="同一片头", primary_actions=("pour",), actions=("pour", "fold"),
        copy="另一套完全不同的口播乙", beats=(20, 30, 50),
    )
    result = compare_candidates(a, b)
    assert result["differing_axes"] == []
    assert result["status"] == "needs_redesign"


def test_cross_product_status_ignores_every_axis_except_hook_and_primary_actions() -> None:
    a = _candidate("a", "p1", hook="same", primary_actions=("pour",), actions=("pour",), copy="same", beats=(1,), scene_context="x")
    b = _candidate("b", "p2", hook="different", primary_actions=("touch",), actions=("pour",), copy="same", beats=(1,), scene_context="x")
    result = compare_candidates(a, b)
    assert result["differing_axes"] == ["hook_pattern", "primary_action_keys"]
    assert result["status"] == "distinct"


def test_pair_uses_the_stricter_sibling_similarity_budget_for_action_gate() -> None:
    a = _candidate("a", "p", hook="h", primary_actions=("a", "b", "c", "d"), actions=("a", "b", "c", "d"), copy="相同 文案", beats=(1,), sibling_similarity_budget=0.9)
    b = _candidate("b", "p", hook="h", primary_actions=("a", "b", "c"), actions=("a", "b", "c"), copy="相同 文案", beats=(1,), sibling_similarity_budget=0.8)
    result = compare_candidates(a, b)
    assert result["sibling_similarity_budget"] == 0.8
    assert result["action_jaccard"] == 0.75
    assert result["status"] != "high_similarity"


@pytest.mark.parametrize("bad", [
    [],
    [{"candidate_id": "", "product_id": "p"}],
    [{"candidate_id": "a", "product_id": ""}],
    [{"candidate_id": "a", "product_id": "p"}, {"candidate_id": "a", "product_id": "p"}],
    [{"candidate_id": "a", "product_id": "p", "hook_pattern": "h", "primary_action_keys": ["x"], "action_keys": ["x"], "copy_text": "x", "beat_durations": [True], "beat_order": ["hook"], "scene_context": "x", "pacing_curve": "x", "caption_strategy": "x", "audio_strategy": "x"}],
    [{"candidate_id": "a", "product_id": "p", "hook_pattern": "h", "primary_action_keys": ["x"], "action_keys": ["x"], "copy_text": "x", "beat_durations": [float("inf")], "beat_order": ["hook"], "scene_context": "x", "pacing_curve": "x", "caption_strategy": "x", "audio_strategy": "x"}],
    [{"candidate_id": "a", "product_id": "p", "hook_pattern": "", "primary_action_keys": ["x"], "action_keys": ["x"], "copy_text": "x", "beat_durations": [1], "beat_order": ["hook"], "scene_context": "x", "pacing_curve": "x", "caption_strategy": "x", "audio_strategy": "x"}],
])
def test_plan_builder_rejects_invalid_or_incomplete_candidates(bad) -> None:
    with pytest.raises((ValueError, TypeError)):
        build_differentiation_plan("b", bad)


def test_plan_compares_all_same_product_pairs_and_cross_product_openings() -> None:
    candidates = [
        _candidate("p1-a", "p1", hook="结果先行", primary_actions=("pour",), actions=("pour",), copy="甲", beats=(1, 1)),
        _candidate("p1-b", "p1", hook="痛点先行", primary_actions=("touch",), actions=("touch",), copy="乙", beats=(1, 2)),
        _candidate("p2-a", "p2", hook="结果先行", primary_actions=("pour",), actions=("pour",), copy="丙", beats=(2, 1)),
        _candidate("p2-b", "p2", hook="场景先行", primary_actions=("fold",), actions=("fold",), copy="丁", beats=(2, 2)),
    ]
    plan = build_differentiation_plan(
        "batch-1",
        candidates,
        research_refs=[{"product_id": "p1", "artifact_sha256": "a" * 64}],
        created_at="2026-09-03T00:00:00+00:00",
    )

    assert len(plan["sibling_comparisons"]) == 6
    assert sum(row["scope"] == "same_product" for row in plan["sibling_comparisons"]) == 2
    assert sum(row["scope"] == "cross_product" for row in plan["sibling_comparisons"]) == 4
    cross = next(row for row in plan["sibling_comparisons"] if {row["candidate_a"], row["candidate_b"]} == {"p1-a", "p2-a"})
    assert cross["compared_axes"] == ["hook_pattern", "primary_action_keys"]
    assert cross["beat_duration_delta"] is None
    assert cross["status"] == "high_similarity"
    assert plan["status"] == "needs_redesign"
    assert all(row["sibling_similarity_budget"] == 0.8 for row in plan["candidate_signatures"])
    validate_artifact("differentiation_plan", plan)

    dedup = build_dedup_summary(plan)
    assert dedup["thresholds"] == {
        "action_jaccard": 0.8,
        "copy_ngram_dice": 0.85,
        "beat_duration_delta": 0.15,
    }
    assert dedup["comparisons"] == plan["sibling_comparisons"]
    assert dedup["status"] == "needs_redesign"


def test_artifact_registry_checkpoint_sets_and_batch_refs_are_closed() -> None:
    assert "differentiation_plan" in ARTIFACT_NAMES
    assert "differentiation_plan" in FASTLINE_ARTIFACTS
    assert "differentiation_plan" in SUPPLEMENTARY_ARTIFACTS

    candidate_batch = create_candidate_batch(
        "b1",
        shared_research_refs=[{"name": "research_synthesis", "path": "artifacts/research_synthesis.json"}],
        candidates=[{"candidate_id": "c1", "project_id": "c1"}],
        differentiation_plan_ref=PLAN_REF,
    )
    assert candidate_batch["differentiation_plan_ref"] == PLAN_REF
    assert all("differentiation_plan_ref" not in row for row in candidate_batch["candidates"])

    template = {"template_id": "t1", "slots": []}
    run = create_template_run(
        template,
        template_pack_ref={"artifact_sha256": "a" * 64, "version": "1.0"},
        product_facts_ref={"artifact_sha256": "b" * 64},
        differentiation_plan_ref=PLAN_REF,
    )
    assert run["differentiation_plan_ref"] == PLAN_REF
    validate_artifact("template_run_plan", attach_hashes(run))

    template_batch = create_template_batch(
        attach_hashes({"version": "1.0", "templates": [template]}),
        product_facts_ref={"artifact_sha256": "b" * 64},
        differentiation_plan_ref=PLAN_REF,
    )
    assert template_batch["differentiation_plan_ref"] == PLAN_REF
    assert all("differentiation_plan_ref" not in row for row in template_batch["runs"])
    validate_artifact("template_batch", attach_hashes(template_batch))


def test_batch_owner_persistence_and_run_resolution(tmp_path) -> None:
    candidate_root = tmp_path / "candidate-root"
    candidate_plan = build_differentiation_plan("candidate-root", [_candidate("c1", "p1", hook="h", primary_actions=("x",), actions=("x",), copy="x y", beats=(1,))])
    candidate_ref = {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": candidate_plan["artifact_sha256"]}
    write_artifact_atomic("artifacts/differentiation_plan.json", "differentiation_plan", candidate_plan, project_dir=candidate_root)
    persist_candidate_batch(candidate_root, create_candidate_batch("candidate-root", shared_research_refs=[{"name": "x", "path": "x"}], candidates=[{"candidate_id": "c1", "project_id": "c1"}], differentiation_plan_ref=candidate_ref))
    assert (candidate_root / "artifacts" / "candidate_batch.json").is_file()

    run_id = "template-run-t1"
    template_root = tmp_path / "batch-root"
    batch = create_template_batch(attach_hashes({"version": "1.0", "templates": [{"template_id": "t1"}]}), product_facts_ref={"artifact_sha256": "b" * 64})
    plan = build_differentiation_plan(batch["batch_id"], [_candidate("c1", "p1", hook="h", primary_actions=("x",), actions=("x",), copy="x y", beats=(1,))])
    ref = {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": plan["artifact_sha256"]}
    write_artifact_atomic("artifacts/differentiation_plan.json", "differentiation_plan", plan, project_dir=template_root)
    batch["differentiation_plan_ref"] = ref
    batch["runs"][0]["project_id"] = run_id
    persist_template_batch(template_root, batch)
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "project.json").write_text(json.dumps({"input_mode": "source_led_template", "template_run": {"batch_project_id": "batch-root"}}), encoding="utf-8")
    mode, resolved = resolve_run_batch_differentiation_ref(run_dir, tmp_path)
    assert mode == "source_led_template"
    assert resolved == ref


def test_batch_quality_report_schema_accepts_dedup_summary() -> None:
    report = {
        "version": "1.0",
        "batch_id": "b1",
        "run_id": "r1",
        "generated_at": "2026-09-03T00:00:00+00:00",
        "input_hashes": {},
        "rubric_version": "1.0",
        "source_refs": [],
        "data_quality": {"status": "complete"},
        "candidates": [],
        "pairwise_diversity": [],
        "dedup": {
            "thresholds": {"action_jaccard": 0.8, "copy_ngram_dice": 0.85, "beat_duration_delta": 0.15},
            "comparisons": [],
            "status": "pass",
        },
        "human_review": {},
        "recommendations": [],
    }
    validate_artifact("batch_quality_report", report)


def test_batch_quality_builder_reads_canonical_differentiation_plan(tmp_path) -> None:
    from lib.batch_reporting import build_batch_quality_report

    batch_dir = tmp_path / "batch-b1"
    artifacts = batch_dir / "artifacts"
    artifacts.mkdir(parents=True)
    plan = build_differentiation_plan(
        "b1",
        [_candidate("c1", "p1", hook="结果", primary_actions=("pour",), actions=("pour",), copy="结果", beats=(1,))],
        created_at="2026-09-03T00:00:00+00:00",
    )
    (artifacts / "differentiation_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    plan_ref = {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": plan["artifact_sha256"]}
    batch = create_candidate_batch(
        "b1",
        shared_research_refs=[{"name": "research_synthesis", "path": "artifacts/research_synthesis.json"}],
        candidates=[{"candidate_id": "c1", "project_id": "c1"}],
        differentiation_plan_ref=plan_ref,
    )
    (artifacts / "candidate_batch.json").write_text(json.dumps(batch), encoding="utf-8")

    report = build_batch_quality_report(batch_dir)
    assert report["dedup"] == build_dedup_summary(plan)
    assert report["input_hashes"]["differentiation_plan"]


@pytest.mark.parametrize("case", ["missing_ref", "missing_file", "bad_hash", "bad_batch"])
def test_batch_quality_builder_fails_closed_on_untrusted_plan_ref(tmp_path, case) -> None:
    from lib.batch_reporting import build_batch_quality_report
    batch_dir = tmp_path / "batch-b1"
    artifacts = batch_dir / "artifacts"
    artifacts.mkdir(parents=True)
    plan = build_differentiation_plan("wrong" if case == "bad_batch" else "b1", [_candidate("c1", "p1", hook="h", primary_actions=("x",), actions=("x",), copy="x y", beats=(1,))])
    if case != "missing_file":
        (artifacts / "differentiation_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    ref = None if case == "missing_ref" else {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": ("0" * 64 if case == "bad_hash" else plan["artifact_sha256"])}
    batch = create_candidate_batch("b1", shared_research_refs=[{"name": "x", "path": "x"}], candidates=[{"candidate_id": "c1", "project_id": "c1"}], differentiation_plan_ref=ref)
    (artifacts / "candidate_batch.json").write_text(json.dumps(batch), encoding="utf-8")
    report = build_batch_quality_report(batch_dir)
    assert report["dedup"]["status"] == "needs_redesign"
    assert report["data_quality"]["status"] in {"partial", "degraded"}


def test_approved_run_requires_trusted_batch_differentiation_ref() -> None:
    draft = create_template_run({"template_id": "t", "slots": []}, template_pack_ref={"artifact_sha256": "a" * 64, "version": "1.0"}, product_facts_ref={"artifact_sha256": "b" * 64})
    assert draft["differentiation_plan_ref"] is None
    approved = {**draft, "status": "approved", "slot_bindings": [{"slot_id": "s", "source": "owned", "source_media_id": "m", "reason": "r"}]}
    assert check_template_run_plan_ready(approved, template={"template_id": "t", "slots": [{"slot_id": "s"}]})["ready"] is False
    with pytest.raises(ValueError):
        validate_differentiation_plan_ref(approved, PLAN_REF)
    bound = {**approved, "differentiation_plan_ref": PLAN_REF}
    assert validate_differentiation_plan_ref(bound, PLAN_REF) is None


def test_legacy_approved_run_without_ref_remains_compatible_but_new_source_led_template_blocks() -> None:
    plan = {"status": "approved", "slot_bindings": [{"slot_id": "s", "source": "owned", "source_media_id": "m", "reason": "r"}]}
    assert check_template_run_plan_ready(plan)["ready"] is True
    result = check_template_run_plan_ready(plan, input_mode="source_led_template", authoritative_differentiation_plan_ref=PLAN_REF)
    assert result["ready"] is False


def test_prep_paid_media_gate_rejects_missing_and_mismatched_authoritative_ref(tmp_path, monkeypatch) -> None:
    import scripts.prep_template_media as prep_module
    from scripts.prep_template_media import assert_paid_media_ready
    project = tmp_path / "run"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({"input_mode": "source_led_template", "template_run": {"batch_project_id": "missing"}}), encoding="utf-8")
    run_plan = {"status": "approved", "differentiation_plan_ref": {**PLAN_REF, "artifact_sha256": "e" * 64}, "slot_bindings": [{"slot_id": "s", "source": "owned", "source_media_id": "m", "reason": "r"}]}
    with pytest.raises(SystemExit, match="differentiation"):
        assert_paid_media_ready(project, run_plan, None, pipeline_dir=tmp_path)
    monkeypatch.setattr(prep_module, "resolve_run_batch_differentiation_ref", lambda *_: ("source_led_template", PLAN_REF))
    with pytest.raises(SystemExit, match="does not match"):
        assert_paid_media_ready(project, run_plan, None, pipeline_dir=tmp_path)
