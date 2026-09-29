"""Frozen-body comparisons bind current files, not caller-supplied pass labels."""
import copy
import hashlib
import json
import struct
import wave
from pathlib import Path

import pytest

import importlib.util


def test_freeze_validator_is_available():
    assert importlib.util.find_spec("lib.opening_freeze") is not None
from lib.production_evidence import build_production_subject, production_subject_hash


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return ref(root, name)


def ref(root, name):
    return {"path": name, "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}


def wav(root, name, *, opening=1, body=2, frames=4000):
    with wave.open(str(root / name), "wb") as stream:
        stream.setparams((1, 2, 1000, frames, "NONE", "not compressed"))
        stream.writeframes(b"".join(struct.pack("<h", opening if i < 3000 else body) for i in range(frames)))
    return ref(root, name)


@pytest.fixture
def frozen(tmp_path):
    global opening_freeze
    from lib import opening_freeze
    (tmp_path / "public").mkdir()
    (tmp_path / "public/body.mp4").write_bytes(b"source-body")
    (tmp_path / "public/hook.mp4").write_bytes(b"source-hook")
    (tmp_path / "render.mp4").write_bytes(b"render")
    for name in ("facts", "reference", "brand", "renderer"):
        write(tmp_path, name + ".json", {"sku": "sku", "version": "1"})
    (tmp_path / "approved-one.png").write_bytes(b"approved-reference-one")
    (tmp_path / "approved-two.png").write_bytes(b"approved-reference-two")
    write(tmp_path, "reference.json", {"version": "1.0", "sku": "sku", "reference_boundaries": [0, 4],
        "reference_images": [ref(tmp_path, "approved-one.png"), ref(tmp_path, "approved-two.png")]})
    (tmp_path / "renderer-source.bin").write_bytes(b"original renderer implementation")
    write(tmp_path, "renderer.json", {"implementation_ref": ref(tmp_path, "renderer-source.bin")})
    baseline_pcm = wav(tmp_path, "baseline.wav")
    props = {"fps": 30, "width": 64, "height": 64, "durationInFrames": 120,
        "opening": {"scope": "full_variant", "endFrameExclusive": 90, "transitionFrames": 5},
        "footage": {"hook": "hook.mp4", "body": "body.mp4"},
        "scenes": [{"id": "hook", "assetId": "hook", "footageKey": "hook", "fromFrame": 0,
            "toFrameExclusive": 90, "durationInFrames": 90, "sourceInSeconds": 0, "sourceOutSeconds": 3},
            {"id": "body", "assetId": "body", "footageKey": "body", "fromFrame": 90,
            "toFrameExclusive": 120, "durationInFrames": 30, "sourceInSeconds": 1, "sourceOutSeconds": 2}],
        "titles": [{"fromFrame": 0, "text": "common"}],
        "captions": [{"startMs": 2900, "endMs": 3300, "text": "common"}],
        "words": [{"startMs": 2950, "endMs": 3250, "text": "common"}],
        "profile": {"production": {"font_mode": "strict", "transition": {"frames": 5, "rule": "incoming_only"}}},
        "finalMix": {**baseline_pcm, "mode": "external_mux"}}
    raw = wav(tmp_path, "raw.wav")
    mix = {"scope": "full_variant", "source_kind": "raw_plus_common_body", "raw_refs": [raw], "output_ref": baseline_pcm,
        "narration_segments": props["words"],
        "bgm": {"track_ref": raw, "position_seconds": 0, "mix_rules": {"volume": .1, "duck": []}}}
    # B5 fixture supplies all canonical/raw evidence contracts. These small bytes
    # remain synthetic; this exercises gates without claiming real media QA.
    from lib.artifact_hashing import attach_hashes
    font_files = []
    for weight in (400, 700):
        name = f"font-{weight}.ttf"
        (tmp_path / 'public' / name).write_bytes(f"fixture-font-{weight}".encode())
        font_files.append({'path': 'public/' + name, 'src': name, 'weight': weight, 'sha256': ref(tmp_path, 'public/' + name)['sha256']})
    props['profile'].update(profile_id='fixture', font={'files': font_files})
    props['profile']['production'].update(slogan='common', min_tail_seconds=.4)
    props.update(version='1.0', project_id='fixture', created_at='2026-09-29T00:00:00Z', producer='fixture', input_hashes={}, compositionId='ProductionBrand')
    props['render_input_refs'] = [ref(tmp_path, name) for name in ('public/body.mp4', 'public/hook.mp4', 'public/font-400.ttf', 'public/font-700.ttf', 'baseline.wav')]
    props = attach_hashes(props)
    receipt = write(tmp_path, 'mix-receipt.json', {'version': '1.0', 'tool': 'audio_mixer', 'operation': 'full_mix', 'scope': 'full_variant',
        'input_refs': [raw], 'output_ref': baseline_pcm, 'returncode': 0, 'command': ['ffmpeg', '-filter_complex', 'fixture'],
        'arguments': {'operation': 'full_mix', 'opening_scope': 'full_variant', 'target_duration': 4, 'tracks': [{'path': str(tmp_path / 'raw.wav'), 'role': 'speech'}]}})
    mix['execution_receipt_ref'] = receipt
    props_ref = write(tmp_path, "baseline_props.json", props)
    mix_ref = write(tmp_path, "baseline_mix.json", mix)
    deps = {key: ref(tmp_path, key + ".json") for key in ("facts", "reference", "brand", "renderer")}
    deps["mix_plan"] = mix_ref
    from tests.contracts.test_opening_contracts import hook_v2
    plan = hook_v2()
    plan["sku"] = "sku"
    plan["promise_fulfillment"]["evidence_ref"] = deps["facts"]
    shot = plan["shots"][0]
    shot["asset_identity"].update(sku="sku", source=ref(tmp_path, "public/hook.mp4"), reference_images=[ref(tmp_path, "approved-one.png")])
    shot["source_mapping"]["source_interval_seconds"] = [0, 3]
    hook_ref = write(tmp_path, "preparation_hook.json", plan)
    identity_ref = write(tmp_path, "prep_identity.json", {"version": "1.0", "role": "baseline_preparation", "sku": "sku", "candidate_id": "B0", "content_slot_id": "B0"})
    pending = opening_freeze.create_pending_freeze_descriptor(tmp_path,
        identity={"sku": "sku", "fact_version": "1", "reference_boundaries": [0, 4], "brand_profile": "brand"},
        dependencies={k: v for k, v in deps.items() if k != "mix_plan"})
    pending_ref = write(tmp_path, "pending.json", pending)
    prep_experiment = {"version": "2.0", "experiment_id": "prep", "sku": "sku", "window_seconds": [0, 3],
        "master_ref": {**deps["facts"], "sku": "sku"}, "baseline_ref": {**identity_ref, "sku": "sku"},
        "facts_ref": {**deps["facts"], "sku": "sku"}, "brand_ref": deps["brand"], "budget_ref": deps["facts"],
        "frozen_body_ref": pending_ref, "candidates": [{"candidate_id": "B0", "hook_plan_ref": {**hook_ref, "version": "2.0"}}]}
    prep_ref = write(tmp_path, "preparation_experiment.json", prep_experiment)
    render_ref = ref(tmp_path, "render.mp4")
    reviewer = {"kind": "semantic_verifier", "id": "independent-fixture", "reviewed_at": "2026-09-29T10:00:00Z"}
    observation = {"version": "1.0", "scope": "full_variant", "shot_id": "s1", "method": "independent_semantic_review",
        "render_sha256": render_ref["sha256"], "hook_plan_sha256": hook_ref["sha256"], "reviewer": reviewer,
        "evidence_interval_seconds": [.5, 2.5], "actual_action": {"source_interval_seconds": [.5, 2.5], "output_interval_seconds": [.5, 2.5]},
        "evidence": {"frames": [], "segments": [{"ref": render_ref, "output_interval_seconds": [.5, 2.5]}]},
        "motion": {"subject": "bag lid", "verb": "opens", "start_state": "closed", "end_state": "open", "visible_result": "contents visible",
            "subject_motion": True, "still_image_transform": False, "camera_only": False, "background_only": False, "forbidden_changes": []},
        "framing": {"fit": "contain", "output_aspect_ratio": "9:16", "visible_parts": ["lid", "bag edge"], "clipped_parts": [],
            "subject_within_safe_area": True, "subject_box": [.2, .2, .6, .6], "action_box": [.25, .25, .5, .5]}}
    observation_ref = write(tmp_path, "preparation_observation.json", observation)
    opening_report = {"version": "2.0", "scope": "full_variant", "render": render_ref,
        "dependencies": {"hook_plan": hook_ref, "experiment": prep_ref, "source:s1": shot["asset_identity"]["source"], "reference:s1:0": shot["asset_identity"]["reference_images"][0]},
        "checks": [{"id": name, "shot_id": "s1", "status": "pass", "method": "independent_semantic_review", "evidence_interval_seconds": [.5, 2.5],
                    "reviewer": reviewer, "observation_ref": observation_ref} for name in ("opening_motion", "opening_framing")]}
    opening_report_ref = write(tmp_path, "preparation_report.json", opening_report)
    record = {"content_slot_id": "B0", "sku": "sku", "render": ref(tmp_path, "render.mp4"),
        "canonical_artifacts": {"final_props": props_ref["path"], **{k: v["path"] for k, v in deps.items()}},
        "review_dependencies": {"pcm": "baseline.wav", "raw": "raw.wav", "body_source": "public/body.mp4", "hook_source": "public/hook.mp4", "reference_one": "approved-one.png", "reference_two": "approved-two.png", "renderer_implementation": "renderer-source.bin"}}
    record["opening"] = {"scope": "full_variant", "candidate_id": "B0", "experiment_ref": prep_ref,
        "hook_plan_ref": {**hook_ref, "version": "2.0"}, "validation_report_ref": opening_report_ref}
    record["canonical_artifacts"].update(preparation_identity="prep_identity.json", preparation_experiment="preparation_experiment.json",
        preparation_hook="preparation_hook.json", pending_freeze="pending.json", preparation_report="preparation_report.json", preparation_observation="preparation_observation.json")
    from tests.production_evidence_fixture import create_bound_opening_quality
    record["quality_report_ref"] = "quality.json"
    write(tmp_path, "quality.json", create_bound_opening_quality(tmp_path, record))
    write(tmp_path, "record.json", record)
    subject = build_production_subject(tmp_path, "record.json")
    approval = write(tmp_path, "operator/reviews/B0-review.json", {"schema_version": "1.0", "review_id": "B0-review", "project_id": tmp_path.name,
        "submitted_by": "agent", "subject_version": 1, "reason": None, "created_at": "2026-09-29T00:00:00Z",
        "decided_at": "2026-09-29T00:01:00Z", "kind": "final_review", "status": "approved", "decided_by": "user", "subject_id": "B0",
        "subject_hash": production_subject_hash(subject), "production_subject": subject})
    descriptor = opening_freeze.create_freeze_descriptor(tmp_path, baseline_props_ref=props_ref,
        identity={"sku": "sku", "fact_version": "1", "reference_boundaries": [0, 4], "brand_profile": "brand"},
        dependencies=deps, baseline_approval_ref=approval)
    descriptor_ref = write(tmp_path, "freeze.json", descriptor)
    candidate = copy.deepcopy(props)
    candidate["finalMix"] = {**wav(tmp_path, "candidate.wav", opening=9), "mode": "external_mux"}
    candidate_mix = copy.deepcopy(mix)
    candidate_mix["output_ref"] = {k: candidate["finalMix"][k] for k in ("path", "sha256")}
    return tmp_path, descriptor_ref, candidate, candidate_mix


def verify(frozen, candidate=None, mix=None):
    root, descriptor, props, plan = frozen
    return opening_freeze.verify_frozen_body(root, descriptor_ref=descriptor,
        candidate_props_ref=write(root, "candidate_props.json", candidate or props),
        candidate_mix_plan_ref=write(root, "candidate_mix.json", mix or plan))


def test_opening_only_pcm_change_keeps_body_frozen(frozen):
    assert verify(frozen)["status"] == "pass"


@pytest.mark.parametrize("field", ["frame90", "caption", "title", "words", "bgm_position", "duck"])
def test_body_or_cross_boundary_overlay_change_fails(frozen, field):
    _, _, props, mix = frozen
    if field == "frame90": props["scenes"][1]["sourceInSeconds"] += .1; props["scenes"][1]["sourceOutSeconds"] += .1
    if field == "caption": props["captions"][0]["text"] = "changed"
    if field == "title": props["titles"][0]["text"] = "changed"
    if field == "words": props["words"][0]["text"] = "changed"
    if field == "bgm_position": mix["bgm"]["position_seconds"] = 3
    if field == "duck": mix["bgm"]["mix_rules"]["duck"] = [[2.9, 3.2]]
    assert verify(frozen)["status"] == "fail"


@pytest.mark.parametrize("length", [4000, 3999])
def test_body_pcm_difference_and_length_difference_fail(frozen, length):
    root, _, props, _ = frozen
    props["finalMix"] = {**wav(root, "different.wav", body=8, frames=length), "mode": "external_mux"}
    assert verify(frozen)["status"] == "fail"


def test_preview_mix_cannot_be_spliced_into_full_film(frozen):
    _, _, _, mix = frozen
    mix.update(scope="preview", source_kind="preview_tail_fade")
    assert verify(frozen)["status"] == "fail"


def test_unrelated_pcm_and_forged_pass_do_not_bypass_actual_props(frozen):
    root, desc, props, _ = frozen
    descriptor = json.loads((root / desc["path"]).read_text())
    descriptor["status"] = "pass"
    write(root, "freeze.json", descriptor)
    assert verify(frozen)["status"] == "error"


def test_pending_descriptor_does_not_authorize_freeze(frozen):
    root, _, _, _ = frozen
    d = json.loads((root / "freeze.json").read_text())
    d.pop("baseline_approval_ref")
    d["state"] = "pending"
    frozen = root, write(root, "freeze.json", d), frozen[2], frozen[3]
    assert verify(frozen)["status"] == "not_run"


def test_mutated_approved_body_source_invalidates_proof(frozen):
    (frozen[0] / "public/body.mp4").write_bytes(b"altered")
    assert verify(frozen)["status"] == "error"


def test_approval_string_or_historical_mother_is_insufficient(frozen):
    root, _, _, _ = frozen
    approval = json.loads((root / "operator/reviews/B0-review.json").read_text())
    approval["subject_id"] = "A01"
    write(root, "operator/reviews/B0-review.json", approval)
    assert verify(frozen)["status"] == "error"


@pytest.fixture
def registered(frozen):
    from tests.contracts.test_opening_contracts import hook_v2
    root, freeze_ref, props, mix = frozen
    descriptor = json.loads((root / freeze_ref["path"]).read_text())
    (root / "public/other.mp4").write_bytes(b"different-opening")
    refs = []
    for candidate_id in ("B0", "H01"):
        plan = hook_v2()
        plan["sku"] = "sku"
        plan["shots"][0]["asset_identity"]["sku"] = "sku"
        plan["promise_fulfillment"]["evidence_ref"] = ref(root, "facts.json")
        plan["shots"][0]["asset_identity"]["source"] = ref(root, "public/hook.mp4" if candidate_id == "B0" else "public/other.mp4")
        plan["shots"][0]["source_mapping"]["source_interval_seconds"] = [0, 3]
        plan["shots"][0]["asset_identity"]["reference_images"] = [ref(root, "approved-one.png")]
        refs.append({"candidate_id": candidate_id, "hook_plan_ref": {**write(root, candidate_id + "_hook.json", plan), "version": "2.0"}})
    write(root, "master.json", {"sku": "sku"})
    write(root, "budget.json", {"sku": "sku"})
    experiment = {"version": "2.0", "experiment_id": "exp", "sku": "sku", "window_seconds": [0, 3],
        "master_ref": {**ref(root, "master.json"), "sku": "sku"}, "baseline_ref": {**ref(root, "record.json"), "sku": "sku"},
        "facts_ref": {**ref(root, "facts.json"), "sku": "sku"}, "brand_ref": ref(root, "brand.json"),
        "frozen_body_ref": freeze_ref, "budget_ref": ref(root, "budget.json"), "candidates": refs}
    experiment_ref = write(root, "experiment.json", experiment)
    evidence = {}
    for index, candidate_id in enumerate(("B0", "H01")):
        if candidate_id == "B0":
            props_ref = descriptor["baseline_props_ref"]
            mix_ref = descriptor["dependencies"]["mix_plan"]
            record_ref = ref(root, "record.json")
            media_ref = ref(root, "render.mp4")
        else:
            (root / "public/other.mp4").write_bytes(b"different-opening")
            props["footage"]["hook"] = "other.mp4"
            props_ref = write(root, "H01_props.json", props)
            mix_ref = write(root, "H01_mix.json", mix)
            (root / "H01_render.mp4").write_bytes(b"distinct-candidate-render-bytes")
            media_ref = ref(root, "H01_render.mp4")
            record_ref = write(root, "H01_record.json", {"content_slot_id": "H01", "sku": "sku", "render": media_ref,
                "canonical_artifacts": {"final_props": props_ref["path"]},
                "opening": {"scope": "full_variant", "candidate_id": "H01", "experiment_ref": experiment_ref, "hook_plan_ref": refs[index]["hook_plan_ref"]}})
        evidence[candidate_id] = write(root, candidate_id + "_evidence.json", {"version": "1.0", "candidate_id": candidate_id,
            "experiment_ref": experiment_ref, "hook_plan_ref": refs[index]["hook_plan_ref"], "freeze_ref": freeze_ref,
            "candidate_props_ref": props_ref, "candidate_mix_plan_ref": mix_ref, "media_ref": media_ref, "production_record_ref": record_ref})
    return root, {"root": root, "experiment_ref": experiment_ref, "candidate_evidence_refs": evidence}


def signature(candidate_id):
    from lib.differentiation import CandidateSignature
    return CandidateSignature(candidate_id=candidate_id, product_id="sku", hook_pattern="base" if candidate_id == "B0" else "new",
        primary_action_keys=("show",), action_keys=("show",), copy_text="body", beat_durations=(3, 1), beat_order=("hook", "body"),
        scene_context="room", pacing_curve="steady", caption_strategy="fixed", audio_strategy="fixed",
        experiment_family_id="exp", baseline_candidate_id="B0", preregistered_variable="opening_package", registration_ref="experiment.json")


def test_registered_opening_exception_uses_actual_freeze_and_entrypoints(registered):
    from lib.differentiation import compare_candidates, build_differentiation_plan
    from lib.candidate_diversity import build_variant_plan, selection_diversity_failures, compare_candidate_pair
    _, context = registered
    a, b = signature("B0"), signature("H01")
    assert compare_candidates(a, b)["status"] != "controlled_experiment"
    assert compare_candidates(a, b, opening_context=context)["status"] == "controlled_experiment"
    assert build_differentiation_plan("batch", [a, b], opening_context=context)["status"] == "pass"
    plans = [build_variant_plan(batch_id="batch", candidate_id=name, variant_revision=1, baseline_ref={"path": "record.json"},
        dimensions={}, shot_differences=[], opening_only_change=True,
        provenance={"preregistered_variable": "opening_package", "registration_ref": "experiment.json"}) for name in ("B0", "H01")]
    assert selection_diversity_failures(plans[1], [plans[0]])["structural_failures"]
    assert selection_diversity_failures(plans[1], [plans[0]], opening_context=context)["structural_failures"] == []
    assert compare_candidate_pair(*plans, opening_context=context)["passes"]


def test_forged_status_or_unregistered_candidate_cannot_use_exception(registered):
    from lib.differentiation import compare_candidates
    root, context = registered
    assert compare_candidates(signature("B0"), signature("other"), opening_context=context)["status"] != "controlled_experiment"
    props = json.loads((root / "H01_props.json").read_text())
    props["captions"][0]["text"] = "body changed"
    write(root, "H01_props.json", props)
    assert compare_candidates(signature("B0"), signature("H01"), opening_context=context)["status"] != "controlled_experiment"


def test_color_font_only_is_not_creative_opening_difference(registered):
    from lib.differentiation import compare_candidates
    root, context = registered
    props = json.loads((root / "H01_props.json").read_text())
    props["footage"]["hook"] = "hook.mp4"
    props["scenes"][0]["color"] = "red"
    props_ref = write(root, "H01_props.json", props)
    doc = json.loads((root / "H01_evidence.json").read_text())
    doc["candidate_props_ref"] = props_ref
    context["candidate_evidence_refs"]["H01"] = write(root, "H01_evidence.json", doc)
    assert compare_candidates(signature("B0"), signature("H01"), opening_context=context)["status"] != "controlled_experiment"


def test_declared_nested_dependency_and_logo_bytes_are_rechecked(frozen):
    root, _, props, _ = frozen
    props["dependency_ref"] = {"path": "facts.json", "sha256": "f" * 64}
    assert verify(frozen)["status"] != "pass"


def test_incomplete_baseline_quality_cannot_mint_freeze(frozen):
    root, _, _, _ = frozen
    quality = json.loads((root / "quality.json").read_text())
    quality["checks"] = []
    write(root, "quality.json", quality)
    assert verify(frozen)["status"] == "error"


def test_aac_disguised_as_wav_is_not_preencode_pcm(frozen):
    root, _, props, _ = frozen
    (root / "candidate.wav").write_bytes(b"not-PCM-AAC")
    props["finalMix"]["sha256"] = ref(root, "candidate.wav")["sha256"]
    assert verify(frozen)["status"] == "fail"


def test_pcm_container_metadata_only_difference_preserves_freeze(frozen):
    root, _, props, _ = frozen
    path = root / "candidate.wav"
    data = bytearray(path.read_bytes())
    chunk = b"JUNK" + struct.pack("<I", 4) + b"meta"
    data[4:8] = struct.pack("<I", len(data) + len(chunk) - 8)
    path.write_bytes(data + chunk)
    props["finalMix"] = {**ref(root, "candidate.wav"), "mode": "external_mux"}
    frozen[3]["output_ref"] = ref(root, "candidate.wav")
    assert verify(frozen)["status"] == "pass"


def test_read_adapter_uses_manifest_and_never_decodes_on_read(registered, monkeypatch):
    root, context = registered
    from lib import media_fingerprint
    monkeypatch.setattr(media_fingerprint, "decoded_interval_evidence", lambda *a, **k: pytest.fail("Read-side decode forbidden"))
    manifest = json.loads((root / "H01_evidence.json").read_text())
    manifest.pop("production_record_ref")
    manifest_ref = write(root, "manifest.json", manifest)
    record = json.loads((root / "H01_record.json").read_text())
    report_ref = write(root, "report.json", {"scope": "full_variant", "render": record["render"],
        "dependencies": {"freeze_evidence": manifest_ref}})
    record["opening"]["validation_report_ref"] = report_ref
    result = opening_freeze.evaluate_freeze_checks(root, record)
    assert result["frozen_body"]["status"] == "pass"
    assert result["opening_join"]["status"] == "not_run"
    record["canonical_artifacts"]["final_props"] = "baseline_props.json"
    assert opening_freeze.evaluate_freeze_checks(root, record)["frozen_body"]["status"] == "error"


def test_nested_dependency_hash_mismatch_cannot_hide_as_opening_input(frozen):
    root, _, props, _ = frozen
    props["scenes"][0]["generation_ref"] = {"path": "facts.json", "sha256": "f" * 64}
    assert verify(frozen)["status"] != "pass"


def test_malformed_registered_experiment_is_reported_without_exception(registered):
    from lib.differentiation import compare_candidates
    root, context = registered
    context["experiment_ref"] = write(root, "experiment.json", {"version": "2.0", "status": "pass"})
    assert compare_candidates(signature("B0"), signature("H01"), opening_context=context)["status"] != "controlled_experiment"


def test_pending_registration_does_not_require_unrendered_B0_media(frozen):
    root, _, _, _ = frozen
    descriptor = json.loads((root / "freeze.json").read_text())
    (root / "baseline.wav").unlink()
    pending = opening_freeze.create_pending_freeze_descriptor(root, identity=descriptor["identity"],
        dependencies={k: v for k, v in descriptor["dependencies"].items() if k != "mix_plan"})
    assert pending["state"] == "pending"
    frozen = root, write(root, "pending.json", pending), frozen[2], frozen[3]
    assert verify(frozen)["status"] == "not_run"


def test_unregistered_final_review_copy_cannot_authorize_freeze(frozen):
    root, _, _, _ = frozen
    descriptor = json.loads((root / "freeze.json").read_text())
    approval = json.loads((root / "operator/reviews/B0-review.json").read_text())
    descriptor["baseline_approval_ref"] = write(root, "copy.json", approval)
    frozen = root, write(root, "freeze.json", descriptor), frozen[2], frozen[3]
    assert verify(frozen)["status"] == "error"


def test_unverified_opening_claim_keeps_three_dimension_minimum():
    from lib.differentiation import compare_candidates
    assert compare_candidates(signature("B0"), signature("H01"))["minimum_effective_axes"] == 3


def test_controlled_pair_cannot_bypass_forged_difference_fingerprint(registered):
    from lib.candidate_diversity import build_variant_plan, compare_candidate_pair
    _, context = registered
    plans = [build_variant_plan(batch_id="batch", candidate_id=name, variant_revision=1,
        baseline_ref={"path": "record.json"}, dimensions={}, shot_differences=[], opening_only_change=True,
        provenance={"preregistered_variable": "opening_package", "registration_ref": "experiment.json"}) for name in ("B0", "H01")]
    plans[1]["difference_fingerprint"]["structural_shot_count"] = 8
    assert not compare_candidate_pair(*plans, opening_context=context)["passes"]


def rebind_registered_hook(root, context, references):
    hook = json.loads((root / "H01_hook.json").read_text())
    hook["shots"][0]["asset_identity"]["reference_images"] = references
    hook_ref = {**write(root, "H01_hook.json", hook), "version": "2.0"}
    experiment = json.loads((root / "experiment.json").read_text())
    next(row for row in experiment["candidates"] if row["candidate_id"] == "H01")["hook_plan_ref"] = hook_ref
    context["experiment_ref"] = write(root, "experiment.json", experiment)
    for candidate_id in ("B0", "H01"):
        evidence = json.loads((root / (candidate_id + "_evidence.json")).read_text())
        evidence["experiment_ref"] = context["experiment_ref"]
        if candidate_id == "H01":
            evidence["hook_plan_ref"] = hook_ref
            record = json.loads((root / "H01_record.json").read_text())
            record["opening"]["experiment_ref"] = context["experiment_ref"]
            record["opening"]["hook_plan_ref"] = hook_ref
            evidence["production_record_ref"] = write(root, "H01_record.json", record)
        context["candidate_evidence_refs"][candidate_id] = write(root, candidate_id + "_evidence.json", evidence)


def test_other_product_reference_cannot_enter_approved_pool(registered):
    from lib.opening_experiment_evidence import verify_controlled_opening
    root, context = registered
    (root / "OTHER_PRODUCT.png").write_bytes(b"other-product-reference")
    rebind_registered_hook(root, context, [ref(root, "OTHER_PRODUCT.png")])
    assert verify_controlled_opening(context, "B0", "H01")["status"] != "pass"


def test_multiple_explicitly_approved_references_are_supported(registered):
    from lib.opening_experiment_evidence import verify_controlled_opening
    root, context = registered
    rebind_registered_hook(root, context, [ref(root, "approved-two.png"), ref(root, "approved-one.png")])
    assert verify_controlled_opening(context, "B0", "H01")["status"] == "pass"


def test_forged_reference_boundaries_cannot_replace_approved_identity(frozen):
    root, _, props, mix = frozen
    descriptor = json.loads((root / "freeze.json").read_text())
    descriptor["identity"]["reference_boundaries"] = [1, 2]
    changed = root, write(root, "freeze.json", descriptor), props, mix
    assert verify(changed)["status"] != "pass"


@pytest.mark.parametrize("bad_refs", [[True], [{"path": "raw.wav"}], [{"path": "raw.wav", "sha256": "a" * 64, "scope": "preview"}]])
def test_raw_mix_inputs_must_be_typed_current_refs(frozen, bad_refs):
    frozen[3]["raw_refs"] = bad_refs
    assert verify(frozen)["status"] != "pass"


def test_mix_output_must_bind_measured_full_pcm(frozen):
    root, _, _, mix = frozen
    mix["output_ref"] = ref(root, "baseline.wav")
    assert verify(frozen)["status"] != "pass"


def test_preview_source_provenance_is_rejected(frozen):
    root, _, _, mix = frozen
    mix["source_provenance_ref"] = write(root, "preview_provenance.json", {"scope": "preview", "source_kind": "preview_tail_fade"})
    assert verify(frozen)["status"] != "pass"


def test_changed_raw_source_is_not_hidden_by_unchanged_pcm(frozen):
    root, _, _, _ = frozen
    (root / "raw.wav").write_bytes(b"changed raw input")
    assert verify(frozen)["status"] != "pass"


def test_raw_file_refs_do_not_claim_measured_source_provenance(frozen):
    assert verify(frozen)["source_provenance_status"] == "not_run"


def scoped_registered_group(root, group):
    group_root = root / group
    group_root.mkdir()
    fixture = frozen.__wrapped__(group_root)
    _, descriptor_ref, props, mix = fixture
    record = json.loads((group_root / "record.json").read_text())
    record["content_slot_id"] = group + "-B0"
    identity = json.loads((group_root / "prep_identity.json").read_text())
    identity["content_slot_id"] = record["content_slot_id"]
    identity_ref = write(group_root, "prep_identity.json", identity)
    prep = json.loads((group_root / "preparation_experiment.json").read_text())
    prep["baseline_ref"] = {**identity_ref, "sku": "sku"}
    prep_ref = write(group_root, "preparation_experiment.json", prep)
    record["opening"]["experiment_ref"] = prep_ref
    report = json.loads((group_root / "preparation_report.json").read_text())
    report["dependencies"]["experiment"] = prep_ref
    record["opening"]["validation_report_ref"] = write(group_root, "preparation_report.json", report)
    from tests.production_evidence_fixture import create_bound_opening_quality
    write(group_root, "quality.json", create_bound_opening_quality(group_root, record))
    write(group_root, "record.json", record)
    subject = build_production_subject(group_root, "record.json")
    review = json.loads((group_root / "operator/reviews/B0-review.json").read_text())
    review.update(subject_id=record["content_slot_id"], production_subject=subject, subject_hash=production_subject_hash(subject))
    approval_ref = write(group_root, "operator/reviews/B0-review.json", review)
    descriptor = json.loads((group_root / "freeze.json").read_text())
    descriptor.update(baseline_approval_ref=approval_ref, baseline_candidate_id="B0", baseline_slot_id=record["content_slot_id"])
    descriptor_ref = write(group_root, "freeze.json", descriptor)
    fixture = group_root, descriptor_ref, props, mix
    _, context = registered.__wrapped__(fixture)
    candidate = json.loads((group_root / "H01_record.json").read_text())
    candidate["content_slot_id"] = group + "-H1"
    candidate_ref = write(group_root, "H01_record.json", candidate)
    evidence = json.loads((group_root / "H01_evidence.json").read_text())
    evidence["production_record_ref"] = candidate_ref
    context["candidate_evidence_refs"]["H01"] = write(group_root, "H01_evidence.json", evidence)
    return context


def publish_group_in_shared_project(project, group, context):
    """Namespace synthetic fixtures into one actual project and review directory."""
    import shutil
    root = project / group
    snapshots = {path.relative_to(root).as_posix(): json.loads(path.read_text()) for path in root.rglob("*.json")}
    hashes = {hashlib.sha256((root / name).read_bytes()).hexdigest(): name for name in snapshots}
    completed, active = {}, set()
    public = project / "public" / group
    public.mkdir(parents=True)
    for path in (root / "public").iterdir():
        shutil.copyfile(path, public / path.name)

    def target(name):
        if name == "operator/reviews/B0-review.json":
            return f"operator/reviews/{group}-review.json"
        if name.startswith("public/"):
            return f"public/{group}/" + name[len("public/"):]
        return group + "/" + name

    def update(value):
        if isinstance(value, list):
            return [update(item) for item in value]
        if isinstance(value, dict):
            result = {key: update(item) for key, item in value.items()}
            if "path" in value and "sha256" in value:
                result["path"] = target(value["path"])
                result["sha256"] = rewrite(value["path"]) if value["path"] in snapshots else ref(project, result["path"])["sha256"]
            if "footage" in value:
                result["footage"] = {key: group + "/" + name for key, name in value["footage"].items()}
            if 'footage' in value and 'profile' in value:
                for font in result.get('profile', {}).get('font', {}).get('files', []):
                    font['src'] = group + '/' + font['src']
            if 'artifact_sha256' in value and 'compositionId' in value:
                from lib.artifact_hashing import attach_hashes
                result = attach_hashes(result)
            if 'baseline_props_ref' in result and 'body' in result:
                baseline = json.loads((project / result['baseline_props_ref']['path']).read_text())
                result['body'] = opening_freeze._body(project, baseline)
            if value.get("kind") == "final_review":
                result["review_id"] = group + "-review"
                result["project_id"] = project.name
                result["production_subject"] = build_production_subject(project, result["production_subject"]["record_path"])
                result["subject_hash"] = production_subject_hash(result["production_subject"])
            return result
        if isinstance(value, str):
            if Path(value).is_absolute():
                return value
            if value in snapshots or (len(value) < 240 and "\n" not in value and (root / value).is_file()):
                if value in snapshots:
                    rewrite(value)
                return target(value)
            if value in hashes:
                return rewrite(hashes[value])
        return value

    def rewrite(name):
        if name in completed:
            return completed[name]
        assert name not in active, "Synthetic fixture must remain acyclic"
        active.add(name)
        data = update(snapshots[name])
        completed[name] = write(project, target(name), data)["sha256"]
        active.remove(name)
        return completed[name]

    for name in snapshots:
        rewrite(name)
    return {"root": project, "experiment_ref": ref(project, target("experiment.json")),
        "candidate_evidence_refs": {candidate: ref(project, target(candidate + "_evidence.json")) for candidate in ("B0", "H01")}}


def test_product_groups_map_local_candidate_labels_to_unique_slots(tmp_path):
    from lib.opening_experiment_evidence import verify_controlled_opening
    first = publish_group_in_shared_project(tmp_path, "A01", scoped_registered_group(tmp_path, "A01"))
    second = publish_group_in_shared_project(tmp_path, "A03", scoped_registered_group(tmp_path, "A03"))
    assert first["root"] == second["root"] == tmp_path
    from lib.production_evidence import quality_summary
    for group in ("A01", "A03"):
        record = json.loads((tmp_path / group / "record.json").read_text())
        assert quality_summary(tmp_path, record)["eligible"]
    assert verify_controlled_opening(first, "B0", "H01")["status"] == "pass"
    assert verify_controlled_opening(second, "B0", "H01")["status"] == "pass"
    later = json.loads((tmp_path / "operator/reviews/A03-review.json").read_text())
    later.update(review_id="A03-review-v2", subject_version=99, status="rejected")
    write(tmp_path, "operator/reviews/A03-review-v2.json", later)
    assert verify_controlled_opening(first, "B0", "H01")["status"] == "pass"
    assert verify_controlled_opening(second, "B0", "H01")["status"] != "pass"


def test_baseline_preparation_role_is_bound_to_actual_approved_slot(frozen):
    root, _, _, _ = frozen
    identity = json.loads((root / "prep_identity.json").read_text())
    identity["content_slot_id"] = "OTHER-B0"
    write(root, "prep_identity.json", identity)
    assert verify(frozen)["status"] == "error"


def test_nested_renderer_dependencies_are_rechecked(frozen):
    root, _, _, _ = frozen
    (root / "renderer-source.bin").write_bytes(b"changed renderer implementation")
    assert verify(frozen)["status"] != "pass"


def test_actual_renderer_implementation_must_be_in_approval_graph(frozen):
    root, _, props, mix = frozen
    record = json.loads((root / "record.json").read_text())
    record["review_dependencies"].pop("renderer_implementation")
    write(root, "record.json", record)
    subject = build_production_subject(root, "record.json")
    review = json.loads((root / "operator/reviews/B0-review.json").read_text())
    review.update(production_subject=subject, subject_hash=production_subject_hash(subject))
    approval_ref = write(root, "operator/reviews/B0-review.json", review)
    descriptor = json.loads((root / "freeze.json").read_text())
    descriptor["baseline_approval_ref"] = approval_ref
    assert ref(root, 'renderer-source.bin') in subject['dependencies'].values()
    assert verify((root, write(root, "freeze.json", descriptor), props, mix))["status"] == "pass"


@pytest.mark.parametrize("copied_path", [False, True])
def test_exact_render_duplicate_cannot_use_exception(registered, copied_path):
    from lib.opening_experiment_evidence import verify_controlled_opening
    root, context = registered
    if copied_path:
        (root / "duplicate.mp4").write_bytes((root / "render.mp4").read_bytes())
    media = ref(root, "duplicate.mp4" if copied_path else "render.mp4")
    record = json.loads((root / "H01_record.json").read_text())
    record["render"] = media
    record_ref = write(root, "H01_record.json", record)
    evidence = json.loads((root / "H01_evidence.json").read_text())
    evidence.update(media_ref=media, production_record_ref=record_ref)
    context["candidate_evidence_refs"]["H01"] = write(root, "H01_evidence.json", evidence)
    assert verify_controlled_opening(context, "B0", "H01")["status"] != "pass"


def test_opening_input_difference_does_not_claim_rendered_perceptual_difference(registered):
    from lib.opening_experiment_evidence import verify_controlled_opening
    _, context = registered
    proof = verify_controlled_opening(context, "B0", "H01")
    assert proof["opening_input_difference"] is True
    assert proof["rendered_difference_status"] == proof["perceptual_difference_status"] == "not_run"
    assert proof["counts_as_new_work"] is False


def rebuild_approved_subject(root):
    subject = build_production_subject(root, "record.json")
    review = json.loads((root / "operator/reviews/B0-review.json").read_text())
    review.update(production_subject=subject, subject_hash=production_subject_hash(subject))
    return write(root, "operator/reviews/B0-review.json", review)


def test_body_title_projection_preserves_actual_renderer_array_precedence(frozen):
    root, _, candidate, mix = frozen
    baseline = json.loads((root / "baseline_props.json").read_text())
    baseline["titles"] = [{"fromFrame": 100, "text": "later"}, {"fromFrame": 0, "text": "common"}]
    candidate["titles"] = list(reversed(baseline["titles"]))
    # ProductionBrand.getBrandFrameState uses reverse().find(fromFrame <= frame).
    def rendered_title(titles, frame):
        return next(row["text"] for row in reversed(titles) if row["fromFrame"] <= frame)
    assert rendered_title(baseline["titles"], 90) == rendered_title(candidate["titles"], 90) == "common"
    assert rendered_title(baseline["titles"], 100) == "common"
    assert rendered_title(candidate["titles"], 100) == "later"
    updated = root, frozen[1], candidate, mix
    assert verify(updated)["status"] == "fail"


def test_current_truncated_candidate_wav_returns_structured_failure(frozen):
    root, _, props, mix = frozen
    (root / "candidate.wav").write_bytes(b"RIFF")
    current = ref(root, "candidate.wav")
    props["finalMix"] = {**current, "mode": "external_mux"}
    mix["output_ref"] = current
    assert verify(frozen)["status"] in ("fail", "error")


def test_current_truncated_baseline_wav_returns_structured_error(frozen):
    root, _, candidate, mix = frozen
    (root / "baseline.wav").write_bytes(b"RIFF")
    current = ref(root, "baseline.wav")
    baseline = json.loads((root / "baseline_props.json").read_text())
    baseline["finalMix"] = {**current, "mode": "external_mux"}
    descriptor = json.loads((root / "freeze.json").read_text())
    descriptor["baseline_props_ref"] = write(root, "baseline_props.json", baseline)
    baseline_mix = json.loads((root / "baseline_mix.json").read_text())
    baseline_mix["output_ref"] = current
    descriptor["dependencies"]["mix_plan"] = write(root, "baseline_mix.json", baseline_mix)
    with pytest.raises(ValueError, match='hash mismatch'):
        rebuild_approved_subject(root)
    assert verify((root, write(root, "freeze.json", descriptor), candidate, mix))["status"] == "error"


def test_truncated_pcm_cannot_crash_read_adapter_or_diversity(registered):
    from lib.candidate_diversity import build_variant_plan, selection_diversity_failures
    from lib.differentiation import compare_candidates
    root, context = registered
    (root / "candidate.wav").write_bytes(b"RIFF")
    current = ref(root, "candidate.wav")
    props = json.loads((root / "H01_props.json").read_text())
    props["finalMix"] = {**current, "mode": "external_mux"}
    mix = json.loads((root / "H01_mix.json").read_text())
    mix["output_ref"] = current
    evidence = json.loads((root / "H01_evidence.json").read_text())
    evidence["candidate_props_ref"] = write(root, "H01_props.json", props)
    evidence["candidate_mix_plan_ref"] = write(root, "H01_mix.json", mix)
    context["candidate_evidence_refs"]["H01"] = write(root, "H01_evidence.json", evidence)
    assert compare_candidates(signature("B0"), signature("H01"), opening_context=context)["status"] != "controlled_experiment"
    plan = build_variant_plan(batch_id="batch", candidate_id="H01", variant_revision=1, baseline_ref={"path": "record.json"},
        dimensions={}, shot_differences=[], opening_only_change=True,
        provenance={"preregistered_variable": "opening_package", "registration_ref": "experiment.json"})
    assert selection_diversity_failures(plan, [], opening_context=context)["structural_failures"]
    evidence.pop("production_record_ref")
    record = json.loads((root / "H01_record.json").read_text())
    report = {"scope": "full_variant", "render": record["render"], "dependencies": {"freeze_evidence": write(root, "manifest.json", evidence)}}
    record["opening"]["validation_report_ref"] = write(root, "report.json", report)
    assert opening_freeze.evaluate_freeze_checks(root, record)["frozen_body"]["status"] in ("fail", "error")
