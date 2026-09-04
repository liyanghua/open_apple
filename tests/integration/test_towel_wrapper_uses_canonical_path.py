from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.differentiation import build_differentiation_plan
from lib.template_batch import create_template_batch, persist_template_batch
from lib.template_run_plan import bind_slot, create_template_run
from schemas.artifacts import validate_artifact


def test_stage25_source_research_wrapper_delegates_to_canonical_builder(monkeypatch, tmp_path: Path):
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage25_research_artifacts")
    seen = {}

    def fake_builder(**kwargs):
        seen.update(kwargs)
        return {"source_semantic_index": {"version": "1.0"}, "reference_source_matrix": {"version": "1.0"}}

    monkeypatch.setattr(mod, "build_source_research_artifacts", fake_builder, raising=False)
    result = mod.build_canonical_source_artifacts(
        project_id="p", input_mode="source_led_template", semantic_map={}, media_index={"entries": []},
        product_facts={"claims": []}, evidence={}, project_dir=tmp_path,
    )
    assert result["source_semantic_index"]["version"] == "1.0"
    assert seen["input_mode"] == "source_led_template"


def test_stage25_research_root_materializes_local_template_prior_before_completion(monkeypatch, tmp_path: Path):
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage25_research_artifacts")
    from lib.checkpoint import _validate_artifacts_for_stage, _validate_source_led_template_prior
    from lib.pipeline_loader import load_input_context

    project, pack_env = mod.initialize_research_root_provenance(
        pipeline_dir=tmp_path,
        project_id="towel-research",
        title="Towel Research",
        template_pack=_template_pack(),
    )

    local_pack = json.loads((project / "artifacts/template_pack.json").read_text(encoding="utf-8"))
    assert local_pack["artifact_sha256"] == pack_env["data"]["artifact_sha256"]
    context = load_input_context(project)
    assert context["template_prior"]["template_pack_ref"] == "artifacts/template_pack.json"
    _validate_source_led_template_prior(project, context)

    scorecard = attach_hashes({
        "version": "1.0", "project_id": project.name,
        "created_at": "2026-09-04T00:00:00+00:00", "producer": "test",
        "input_hashes": {}, "score": 10, "max_score": 10, "status": "pass",
        "checks": [{"id": check_id, "label": check_id, "score": 2,
                    "status": "pass", "message": "ok"}
                   for check_id in (
                       "input_coverage", "evidence_traceability", "source_matching",
                       "production_readiness", "execution_discipline",
                   )],
        "hard_failures": [], "warnings": [],
    })
    scorecard_env = write_artifact_atomic(
        "artifacts/research_scorecard.json", "research_scorecard", scorecard,
        project_dir=project,
    )
    import lib.pipeline_loader as pipeline_loader
    monkeypatch.setattr(pipeline_loader, "load_pipeline_readonly", lambda _name: {"artifact_contract_version": 2})
    monkeypatch.setattr(pipeline_loader, "get_stage_produces", lambda *_args, **_kwargs: ["research_scorecard"])
    _validate_artifacts_for_stage(
        "research", "completed", {"research_scorecard": scorecard_env},
        "cinematic-fast", project_dir=project,
    )


def test_stage30_batch_wrapper_accepts_the_real_canonical_signature():
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage30_build_batch")
    result = mod.build_canonical_template_batch(
        attach_hashes({"version": "1.0", "templates": []}),
        product_facts_ref={"artifact_sha256": "b" * 64},
        template_run_plan_refs={},
        shared_research_refs=[{"name": "source_semantic_index", "path": "artifacts/source_semantic_index.json", "artifact_sha256": "c" * 64}],
        max_parallel=2,
        max_cost_usd=20.0,
        max_retries_per_run=1,
        publish_policy="selective",
        render_runtime="remotion",
        batch_id="towel-batch",
        differentiation_plan_ref={"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": "d" * 64},
    )
    assert result["status"] == "planned"
    assert result["batch_id"] == "towel-batch"
    assert result["shared_research_refs"][0]["name"] == "source_semantic_index"
    assert result["differentiation_plan_ref"]["artifact_sha256"] == "d" * 64


def _template_pack() -> dict:
    return attach_hashes({
        "version": "1.0",
        "project_id": "towel-batch",
        "created_at": "2026-09-04T00:00:00+00:00",
        "taxonomy_version": "template-pack@1",
        "source_document": {"path": "fixture.json", "sha256": "a" * 64, "parser_version": "fixture@1"},
        "templates": [{
            "template_id": "towel-A", "sheet_name": "A", "archetype": "proof",
            "slots": [{
                "slot_id": "towel-A-slot-001", "ordinal": 1, "duration_s": 2.0,
                "shot_language": {}, "visual_content": "倒水吸收", "overlay_text": "可见吸水",
                "caption_treatment": "subtitle", "effect_treatment": "subtitle",
                "audio_layers": ["narration"], "music_profile": "light", "scene": "bathroom",
                "dialogue": "analysis only",
            }],
        }],
        "normalization_warnings": [],
    })


def test_template_run_provenance_materializes_local_pack_and_batch_owner(tmp_path: Path):
    from lib.checkpoint import _validate_source_led_template_prior, init_project
    from lib.pipeline_loader import load_input_context
    from lib.template_fork import materialize_template_run_provenance

    batch = init_project("towel-batch", title="batch", pipeline_type="cinematic-fast", pipeline_dir=tmp_path)
    pack_env = write_artifact_atomic(
        "artifacts/template_pack.json", "template_pack", _template_pack(), project_dir=batch,
    )
    run = init_project(
        "template-run-towel-A", title="run", pipeline_type="cinematic-fast", pipeline_dir=tmp_path,
        input_mode="source_led_template",
        template_prior={"present": True, "usage": "structural_only", "template_pack_ref": "artifacts/template_pack.json"},
        owned_source_root="inputs/source",
    )

    materialize_template_run_provenance(
        run,
        template_pack_path=batch / "artifacts/template_pack.json",
        batch_project_id=batch.name,
    )

    local_pack = json.loads((run / "artifacts/template_pack.json").read_text(encoding="utf-8"))
    assert local_pack["artifact_sha256"] == pack_env["data"]["artifact_sha256"]
    context = load_input_context(run)
    assert context["template_prior"]["template_pack_ref"] == "artifacts/template_pack.json"
    _validate_source_led_template_prior(run, context)
    marker = json.loads((run / "project.json").read_text(encoding="utf-8"))
    assert marker["template_run"]["batch_project_id"] == "towel-batch"


def test_stage30_persists_one_batch_differentiation_plan_and_shared_ref(tmp_path: Path):
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage30_build_batch")
    candidates = [{
        "candidate_id": "towel-A", "product_id": "towel", "hook_pattern": "result-first",
        "primary_action_keys": ["pour"], "action_keys": ["pour", "absorb"],
        "copy_text": "倒水后可见吸水", "beat_durations": [2.0], "beat_order": ["proof"],
        "scene_context": "bathroom", "pacing_curve": "fast-proof",
        "caption_strategy": "proof-word", "audio_strategy": "narration-light-bgm",
        "forbidden_repeats": [], "matrix_row_refs": ["evidence-001"],
    }]

    plan_env, ref = mod.persist_canonical_differentiation_plan(
        tmp_path, batch_id="towel-batch", candidates=candidates,
        research_refs=[{"name": "source_semantic_index", "path": "artifacts/source_semantic_index.json", "artifact_sha256": "c" * 64}],
    )

    assert ref == {
        "name": "differentiation_plan", "path": "artifacts/differentiation_plan.json",
        "artifact_sha256": plan_env["data"]["artifact_sha256"],
    }
    stored = json.loads((tmp_path / "artifacts/differentiation_plan.json").read_text(encoding="utf-8"))
    assert stored["batch_id"] == "towel-batch"
    assert stored["candidate_signatures"][0]["matrix_row_refs"] == ["evidence-001"]


def test_stage30_candidate_signatures_resolve_only_canonical_evidence_rows():
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage30_build_batch")
    templates = [{
        "template_id": "towel-A", "archetype": "proof-first",
        "slots": [{"duration_s": 2.0, "role": "proof", "domain": "absorb"}],
    }]
    bindings = {"towel-A": [{"stem": "m1", "domain": "absorb"}]}
    matrix = {"matrix_mode": "source_led_template", "rows": [{
        "matrix_row_id": "evidence-001", "source_media_id": "m1", "resolution": "accept",
        "action_keys": ["pour", "absorb"], "allowed_wording": ["可见吸水"],
    }]}

    signatures, refs_by_template = mod.build_differentiation_candidates(
        product_id="towel", templates=templates, bindings=bindings, matrix=matrix,
    )

    assert signatures[0]["matrix_row_refs"] == ["evidence-001"]
    assert refs_by_template == {"towel-A": ["evidence-001"]}
    matrix["rows"][0]["matrix_row_id"] = "matrix-001"
    with pytest.raises(ValueError, match="canonical evidence"):
        mod.build_differentiation_candidates(
            product_id="towel", templates=templates, bindings=bindings, matrix=matrix,
        )


def test_stage30_proposal_handoff_accepts_actual_canonical_evidence_ids():
    from lib.research_validation import validate_proposal_research_handoff

    matrix = {"matrix_mode": "source_led_template", "rows": [{
        "matrix_row_id": "evidence-001", "resolution": "accept",
    }]}
    synthesis = {"differentiation_directions": [{
        "direction_id": "direction-towel-A", "matrix_row_refs": ["evidence-001"],
    }]}
    proposal = {"concept_options": [{
        "research_direction_refs": ["direction-towel-A"],
        "matrix_row_refs": ["evidence-001"],
        "fingerprint_rule_refs": ["proof"],
    }]}

    validate_proposal_research_handoff(
        proposal, synthesis, matrix, input_mode="source_led_template",
    )
    proposal["concept_options"][0]["matrix_row_refs"] = ["matrix-001"]
    with pytest.raises(ValueError, match="unknown research matrix row"):
        validate_proposal_research_handoff(
            proposal, synthesis, matrix, input_mode="source_led_template",
        )


def test_source_led_template_readiness_blocks_unapproved_and_accepts_matching_owner(tmp_path: Path, monkeypatch):
    from lib.checkpoint import init_project
    from lib.template_batch import resolve_run_batch_differentiation_ref
    from lib.template_run_plan import check_template_run_plan_ready
    import lib.template_source_match as source_match

    monkeypatch.setattr(source_match, "is_template_calibrated", lambda _template_id: True)
    monkeypatch.setattr(source_match, "capacity_verdict", lambda _template: {"verdict": "OK", "reasons": []})

    pack = _template_pack()
    batch_root = init_project("towel-batch", title="batch", pipeline_type="cinematic-fast", pipeline_dir=tmp_path)
    template = pack["templates"][0]
    provisional = create_template_batch(
        pack, batch_id="towel-batch", product_facts_ref={"artifact_sha256": "b" * 64},
    )
    plan = build_differentiation_plan("towel-batch", [{
        "candidate_id": "towel-A", "product_id": "towel", "hook_pattern": "proof",
        "primary_action_keys": ["pour"], "action_keys": ["pour"], "copy_text": "吸水",
        "beat_durations": [2.0], "beat_order": ["proof"], "scene_context": "bathroom",
        "pacing_curve": "fast", "caption_strategy": "short", "audio_strategy": "tts",
    }])
    write_artifact_atomic("artifacts/differentiation_plan.json", "differentiation_plan", plan, project_dir=batch_root)
    ref = {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": plan["artifact_sha256"]}
    provisional["differentiation_plan_ref"] = ref
    provisional["runs"][0]["project_id"] = "template-run-towel-A"
    persist_template_batch(batch_root, provisional)

    run = init_project(
        "template-run-towel-A", title="run", pipeline_type="cinematic-fast", pipeline_dir=tmp_path,
        input_mode="source_led_template",
        template_prior={"present": True, "usage": "structural_only", "template_pack_ref": "artifacts/template_pack.json"},
        owned_source_root="inputs/source",
    )
    marker = json.loads((run / "project.json").read_text(encoding="utf-8"))
    marker["template_run"] = {"batch_project_id": "towel-batch"}
    (run / "project.json").write_text(json.dumps(marker), encoding="utf-8")
    mode, owner_ref = resolve_run_batch_differentiation_ref(run, tmp_path)
    run_plan = create_template_run(
        template,
        template_pack_ref={"artifact_sha256": pack["artifact_sha256"], "version": pack["version"]},
        product_facts_ref={"artifact_sha256": "b" * 64},
        differentiation_plan_ref=ref,
    )
    run_plan = bind_slot(run_plan, "towel-A-slot-001", source="owned", source_media_id="m1", reason="proof")

    assert check_template_run_plan_ready(
        run_plan, template=template, input_mode=mode,
        authoritative_differentiation_plan_ref=owner_ref,
    )["ready"] is False
    run_plan["status"] = "approved"
    assert check_template_run_plan_ready(
        run_plan, template=template, input_mode=mode,
        authoritative_differentiation_plan_ref=owner_ref,
    )["ready"] is True


def test_stage30_script_wrapper_delegates_to_canonical_builder(monkeypatch, tmp_path: Path):
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage30_build_batch")
    called = {}

    def fake_builder(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs
        return {"data": {"title": kwargs["title"]}}

    monkeypatch.setattr(mod, "build_canonical_script", fake_builder, raising=False)
    result = mod.build_canonical_script_for_run(tmp_path, {}, {}, {}, {}, title="银离子毛巾")
    assert result["data"]["title"] == "银离子毛巾"
    assert called["kwargs"]["approved"] is False


def test_stage40_scene_wrapper_delegates_to_canonical_scene_builder(monkeypatch, tmp_path: Path):
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage40_scene_assets")
    called = {}

    def fake_builder(*args, **kwargs):
        called["args"] = args
        return {"data": {"version": "1.0", "scenes": []}}

    monkeypatch.setattr(mod, "build_canonical_scene_plan", fake_builder, raising=False)
    result = mod.build_canonical_scene_plan_for_run(tmp_path, {}, {}, {}, {})
    assert result["data"]["version"] == "1.0"
    assert called["args"][0] == tmp_path


def test_stage40_assets_wrapper_uses_readiness_gated_builder(monkeypatch, tmp_path: Path):
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage40_scene_assets")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for name in ("template_run_plan", "creative_control_plan", "product_facts"):
        (artifacts / f"{name}.json").write_text("{}", encoding="utf-8")
    scene_env = {"name": "scene_plan", "path": "artifacts/scene_plan.json", "data": {"version": "1.0"}}
    asset_envs = {
        name: {"name": name, "path": f"artifacts/{name}.json", "data": {}}
        for name in ("shot_execution_plan", "asset_plan", "production_lock", "approval_bundle")
    }
    called = {}
    monkeypatch.setattr(mod, "build_canonical_scene_plan_for_run", lambda *_: scene_env)
    monkeypatch.setattr(mod, "build_assets", lambda project, template, **kwargs: called.update({"project": project, **kwargs}) or asset_envs, raising=False)
    monkeypatch.setattr(mod, "sync_assets_artifacts", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("sync bypass used")), raising=False)

    result = mod.build_canonical_assets_for_run(tmp_path, {"template_id": "towel-A"})

    assert called["project"] == tmp_path
    assert called["pipeline_dir"] == mod.PROJECTS
    assert result["scene_plan"] == scene_env
    assert result["approval_bundle"] == asset_envs["approval_bundle"]


def test_stage40_rebuilt_assets_always_reopen_human_approval():
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage40_scene_assets")
    assert mod.assets_checkpoint_state(previous={"status": "completed", "human_approved": True}) == {
        "status": "awaiting_human", "human_approved": False,
    }


def test_stage50_sample_wrapper_uses_canonical_final_props_for_dry_run(monkeypatch, tmp_path: Path):
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage50_sample")
    called = {}

    def fake_builder(*args, **kwargs):
        called["kwargs"] = kwargs
        return {"version": "1.0", "scenes": []}

    monkeypatch.setattr(mod, "build_canonical_final_props", fake_builder, raising=False)
    result = mod.build_dry_run_final_props(tmp_path, {}, [], {}, "a" * 64, "b" * 64)
    assert result["version"] == "1.0"
    assert called["kwargs"]["profile"] == "social_vertical_3_4_1080p30"


def test_stage50_real_dry_process_reports_probe_matching_three_by_four_final_props(monkeypatch, tmp_path: Path):
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage50_sample")
    candidate_id = "fixture-run"
    project = tmp_path / candidate_id
    project.mkdir()
    artifacts = {
        "script": {"sections": []},
        "production_lock": {"artifact_sha256": "b" * 64},
        "shot_execution_plan": {
            "semantic_sha256": "a" * 64,
            "shots": [{"id": f"shot-{index:02d}", "duration_seconds": 1} for index in range(1, 6)],
        },
        "scene_plan": {"semantic_sha256": "c" * 64},
        "product_facts": {"product_name": "towel"},
    }
    captured = {}

    monkeypatch.setattr(mod, "PIPELINE_DIR", tmp_path)
    monkeypatch.setitem(mod.RESEARCH_ROOTS, candidate_id, project)
    monkeypatch.setattr(mod, "load", lambda _project, name: artifacts[name])
    monkeypatch.setattr(mod, "build_screen_copy_captions", lambda _project: [])
    monkeypatch.setattr(mod, "build_asset_manifest", lambda *_args, **_kwargs: {"assets": []})
    monkeypatch.setattr(mod, "build_dry_run_final_props", lambda *_args, **_kwargs: {
        "fps": 30, "width": 1080, "height": 1440, "durationInFrames": 150,
        "scenes": [], "captions": [],
    })
    monkeypatch.setattr(mod, "build_caption_policy_revision", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(mod, "build_render_plan", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(mod, "build_sample_edit_decisions", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(mod, "build_sample_execution_trace", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(mod, "validate_dry_run_sample_contract", lambda *_args, **_kwargs: {"alignment": {}})
    monkeypatch.setattr(mod, "build_evaluation_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        mod, "validate_artifact",
        lambda name, value: captured.setdefault(name, value) if name == "sample_report" else None,
    )
    import lib.template_alignment as template_alignment
    monkeypatch.setattr(template_alignment, "shot_alignment_errors", lambda *_args, **_kwargs: [])

    assert "dry-run" in mod.process_candidate(candidate_id, dry_run=True)
    probe = captured["sample_report"]["probe"]
    assert probe["width"] == 540
    assert probe["height"] == 720
    assert probe["width"] * 4 == probe["height"] * 3


def test_stage50_tts_wrapper_delegates_to_canonical_audio_generator(monkeypatch, tmp_path: Path):
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage50_sample")
    monkeypatch.setattr(mod, "PIPELINE_DIR", tmp_path)
    project = tmp_path / "run-a"
    (project / "assets" / "audio").mkdir(parents=True)
    (project / "artifacts").mkdir()
    script = attach_hashes({"sections":[{"id":"sec-001","scene_id":"scene-001","narration":"x","start_seconds":0,"end_seconds":2}]})
    (project / "artifacts" / "script.json").write_text(json.dumps(script), encoding="utf-8")
    shot_plan = attach_hashes({
        "version": "1.0", "project_id": "run-a", "plan_id": "towel-A", "plan_version": 1,
        "status": "approved", "created_at": "2026-09-04T00:00:00+00:00",
        "creative_control_ref": {"artifact": "creative_control_plan", "version": 1, "artifact_sha256": "a" * 64},
        "script_ref": {"artifact": "script", "version": 1, "artifact_sha256": script["artifact_sha256"]},
        "scene_plan_ref": {"artifact": "scene_plan", "version": 1, "artifact_sha256": "b" * 64},
        "approval": {"approved_by": "operator", "approved_at": "2026-09-04T00:00:00+00:00"},
        "shots": [{
            "id": "shot-01", "order": 1, "scene_id": "scene-001", "section_id": "sec-001",
            "template_slot_ref": "towel-A-slot-001", "purpose": "proof", "duration_seconds": 2.0,
            "narration": "x", "screen_copy": "x", "subject_action": "pour", "setting": "bathroom",
            "framing": "close", "camera": "static", "lighting": "natural", "sound": "narration",
            "evidence_type": "real_proof", "coverage_status": "enough", "gap_class": "none", "gap_strategy": "none",
            "source_selection": {"media_id": "m1", "path": "inputs/source/m1.mp4", "start_seconds": 0, "end_seconds": 2, "fit_reason": "proof"},
            "reference_mechanisms": ["structural"], "industry_notes": [], "control_rule_refs": [],
            "generation_proposals": [], "selected_generation_task_id": None,
            "source_interval": {"start_seconds": 0, "end_seconds_exclusive": 2},
            "narration_hash": "c" * 64, "screen_copy_hash": "d" * 64,
            "tts_asset_hash": None, "tts_measured_duration": None, "caption_timeline_hash": "e" * 64,
        }],
    })
    (project / "artifacts" / "shot_execution_plan.json").write_text(json.dumps(shot_plan), encoding="utf-8")
    audio = project / "assets" / "audio" / "narration-s001.mp3"
    audio.write_bytes(b"audio")
    (project / "assets" / "audio" / "narration-s001.mp3.lock.json").write_text(
        json.dumps({"text_sha": hashlib.sha256(b"x").hexdigest(), "voice_id": "zh_female_vv_uranus_bigtts", "resource_id": "seed-tts-2.0", "format": "mp3", "speech_rate": 0}),
        encoding="utf-8",
    )
    (project / "assets" / "audio" / "narration-s001.mp3.json").write_text(
        json.dumps({"data": {"sentences": [{"endTime": 1250, "words": []}]}}), encoding="utf-8",
    )
    monkeypatch.setattr(mod, "generate_canonical_audio", lambda run, section_ids=None: [{
        "section": "sec-001", "status": "ok", "audio_s": 1.25, "output": str(audio),
    }], raising=False)

    files, words = mod.run_tts_with_fit(project)

    assert files == [("sec-001", audio, 1.25)]
    assert words == []
    rebound = json.loads((project / "artifacts" / "shot_execution_plan.json").read_text(encoding="utf-8"))
    assert rebound["shots"][0]["tts_asset_hash"] == hashlib.sha256(b"audio").hexdigest()
    assert rebound["shots"][0]["tts_measured_duration"] == 1.25
    assert rebound["artifact_sha256"] != shot_plan["artifact_sha256"]
    validate_artifact("shot_execution_plan", rebound)


def test_stage50_dry_run_executes_canonical_payload_and_five_dimension_alignment():
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage50_sample")
    from lib.template_assets import _content_hash
    narration = "可见吸水"
    screen_copy = "可见吸水"
    artifacts = {
        "script": attach_hashes({"sections": [{
            "id": "sec-001", "scene_id": "scene-001", "narration": narration, "screen_copy": screen_copy,
            "start_seconds": 0, "end_seconds": 2, "claim_ids": ["absorb"], "action_keys": ["pour"],
            "evidence_row_ids": ["evidence-001"],
        }]}),
        "scene_plan": attach_hashes({
            "scenes": [{"id": "scene-001", "script_section_id": "sec-001", "action_keys": ["pour"], "claim_ids": ["absorb"], "evidence_row_ids": ["evidence-001"]}],
            "metadata": {"source_mapping": [{
                "scene_id": "scene-001", "script_section_id": "sec-001",
                "action_keys": ["pour"], "claim_ids": ["absorb"], "evidence_row_ids": ["evidence-001"],
                "source_hash": "a" * 64,
                "source_interval": {"start_seconds": 0, "end_seconds_exclusive": 2},
            }]},
        }),
        "shot_execution_plan": attach_hashes({"shots": [{
            "id": "shot-01", "scene_id": "scene-001", "section_id": "sec-001", "duration_seconds": 2,
            "narration": narration, "screen_copy": screen_copy, "action_keys": ["pour"], "claim_ids": ["absorb"],
            "evidence_row_ids": ["evidence-001"], "source_hash": "a" * 64,
            "source_interval": {"start_seconds": 0, "end_seconds_exclusive": 2},
            "narration_hash": _content_hash({"section_id": "sec-001", "text": narration}),
            "screen_copy_hash": _content_hash({"section_id": "sec-001", "text": screen_copy}),
            "caption_timeline_hash": _content_hash({"section_id": "sec-001", "screen_copy": screen_copy, "start_seconds": 0, "end_seconds": 2}),
            "tts_asset_hash": None, "tts_measured_duration": None,
        }]}),
        "final_props": attach_hashes({
            "fps": 30, "durationInFrames": 60, "width": 540, "height": 720,
            "scenes": [{"id": "shot-01", "assetId": "asset-01", "fromFrame": 0, "toFrameExclusive": 60,
                        "sourceInSeconds": 0, "action_keys": ["pour"], "claim_ids": ["absorb"],
                        "evidence_row_ids": ["evidence-001"], "product_id": "towel"}],
            "captions": [{"text": screen_copy, "startMs": 0, "endMs": 2000}],
        }),
        "asset_manifest": {"assets": [{"id": "asset-01", "type": "video", "path": "assets/video/shot-01.mp4", "duration_seconds": 2}]},
        "product_facts": {"product_name": "towel"},
        "render": {"sha256": "e" * 64},
    }
    result = mod.validate_dry_run_sample_contract(artifacts)
    assert result["payload"]["cuts"][0]["id"] == "shot-01"
    assert result["alignment"]["status"] == "pass"
    row = result["alignment"]["per_shot_results"][0]
    assert all(row[field] == "pass" for field in (
        "action_match", "result_support", "narration_caption_match",
        "product_identity_match", "crop_completeness",
    ))


def test_stage50_dry_run_alignment_only_marks_rendered_sample_shots():
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage50_sample")
    from lib.template_assets import _content_hash

    def section(section_id: str, scene_id: str, text: str, start: int, end: int) -> dict:
        return {
            "id": section_id, "scene_id": scene_id, "narration": text, "screen_copy": text,
            "start_seconds": start, "end_seconds": end, "claim_ids": ["absorb"],
            "action_keys": ["pour"], "evidence_row_ids": ["evidence-001"],
        }

    def shot(shot_id: str, scene_id: str, section_id: str, text: str, start: int, end: int) -> dict:
        return {
            "id": shot_id, "scene_id": scene_id, "section_id": section_id,
            "duration_seconds": end - start, "narration": text, "screen_copy": text,
            "claim_ids": ["absorb"], "action_keys": ["pour"],
            "evidence_row_ids": ["evidence-001"], "source_hash": "a" * 64,
            "source_interval": {"start_seconds": start, "end_seconds_exclusive": end},
            "narration_hash": _content_hash({"section_id": section_id, "text": text}),
            "screen_copy_hash": _content_hash({"section_id": section_id, "text": text}),
            "caption_timeline_hash": _content_hash({
                "section_id": section_id, "screen_copy": text,
                "start_seconds": start, "end_seconds": end,
            }),
            "tts_asset_hash": None, "tts_measured_duration": None,
        }

    sections = [
        section(f"sec-{index:03d}", f"scene-{index:03d}", chr(96 + index), index - 1, index)
        for index in range(1, 13)
    ]
    shots = [
        shot(f"shot-{index:02d}", f"scene-{index:03d}", f"sec-{index:03d}", chr(96 + index), index - 1, index)
        for index in range(1, 13)
    ]
    scene_plan_scenes = [{
        "id": f"scene-{index:03d}", "script_section_id": f"sec-{index:03d}",
        "claim_ids": ["absorb"], "action_keys": ["pour"],
        "evidence_row_ids": ["evidence-001"],
    } for index in range(1, 13)]
    source_mapping = [{
        "scene_id": f"scene-{index:03d}", "script_section_id": f"sec-{index:03d}",
        "claim_ids": ["absorb"], "action_keys": ["pour"],
        "evidence_row_ids": ["evidence-001"], "source_hash": "a" * 64,
        "source_interval": {"start_seconds": index - 1, "end_seconds_exclusive": index},
    } for index in range(1, 13)]
    rendered_scenes = [{
        "id": f"shot-{index:02d}", "assetId": f"asset-{index:02d}",
        "fromFrame": (index - 1) * 30, "toFrameExclusive": index * 30,
        "sourceInSeconds": index - 1, "claim_ids": ["absorb"],
        "action_keys": ["pour"], "evidence_row_ids": ["evidence-001"],
        "product_id": "towel",
    } for index in range(1, 6)]

    artifacts = {
        "script": attach_hashes({"sections": sections}),
        "scene_plan": attach_hashes({
            "scenes": scene_plan_scenes,
            "metadata": {"source_mapping": source_mapping},
        }),
        "shot_execution_plan": attach_hashes({"shots": shots}),
        "final_props": attach_hashes({
            "fps": 30, "durationInFrames": 150,
            "scenes": rendered_scenes,
            "captions": [],
        }),
        "asset_manifest": {"assets": [{
            "id": f"asset-{index:02d}", "path": f"assets/video/shot-{index:02d}.mp4",
            "duration_seconds": 1,
        } for index in range(1, 6)]},
        "product_facts": {"product_name": "towel"}, "render": {"sha256": "e" * 64},
    }

    result = mod.validate_dry_run_sample_contract(artifacts)

    assert [row["shot_id"] for row in result["alignment"]["per_shot_results"]] == [
        f"shot-{index:02d}" for index in range(1, 6)
    ]


def test_stage51_gate_consumes_explicit_dimensions_not_legacy_match():
    mod = importlib.import_module("scripts.towel_batch_2026_09_02.stage51_verify_alignment")
    passed = {"shot_id": "shot-01", "section_id": "sec-001",
              **{field: "pass" for field in mod.DIMENSIONS}}
    assert mod.canonical_alignment_gate_errors([passed]) == []
    passed.pop("crop_completeness")
    assert mod.canonical_alignment_gate_errors([passed])
