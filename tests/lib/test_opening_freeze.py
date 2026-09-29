"""Frozen-body comparisons bind current files, not caller-supplied pass labels."""
import copy
import hashlib
import json
import struct
import wave

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
    mix = {"scope": "full_variant", "source_kind": "raw_plus_common_body", "raw_refs": [raw],
        "narration_segments": props["words"],
        "bgm": {"track_ref": raw, "position_seconds": 0, "mix_rules": {"volume": .1, "duck": []}}}
    props_ref = write(tmp_path, "baseline_props.json", props)
    mix_ref = write(tmp_path, "baseline_mix.json", mix)
    deps = {key: ref(tmp_path, key + ".json") for key in ("facts", "reference", "brand", "renderer")}
    deps["mix_plan"] = mix_ref
    record = {"content_slot_id": "B0", "sku": "sku", "render": ref(tmp_path, "render.mp4"),
        "canonical_artifacts": {"final_props": props_ref["path"], **{k: v["path"] for k, v in deps.items()}},
        "review_dependencies": {"pcm": "baseline.wav", "raw": "raw.wav", "body_source": "public/body.mp4", "hook_source": "public/hook.mp4"}}
    from tests.production_evidence_fixture import create_bound_quality
    record["quality_report_ref"] = "quality.json"
    write(tmp_path, "quality.json", create_bound_quality(tmp_path, record))
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
    return tmp_path, descriptor_ref, candidate, mix


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
        plan["shots"][0]["asset_identity"]["reference_images"] = [ref(root, "public/hook.mp4")]
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
            media_ref = ref(root, "render.mp4")
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
