"""Versioned source observations, purpose eligibility and review identity."""
import copy
import hashlib
import json

import pytest

from schemas.artifacts import ARTIFACT_NAMES, validate_artifact


def source_fixture(root, *, shot_id="sofa", revision="v6"):
    """Synthetic local evidence; never performs generation or semantic inference."""
    def put(path, value):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return {"path": path, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}

    base = f"artifacts/shot_sources/{shot_id}/{revision}"
    source = {**put(f"assets/{shot_id}.mp4", b"synthetic-source"), "duration_seconds": 8}
    evidence = {**put(f"assets/{shot_id}-frame.jpg", b"synthetic-frame"), "time_seconds": 1}
    dependencies = {name: put(f"artifacts/{shot_id}-{name}.json", {"version": 1, "project_id": "test"})
                    for name in ("fact_snapshot", "category_profile", "production_lock")}
    plan = {"version": "1.0", "project_id": "test", "shot_id": shot_id, "revision": revision,
            "sku": "sofa-pad", "parent_budget_id": "production-budget", "lineage_id": f"lineage-{shot_id}", "dependencies": dependencies,
            "original_purpose_id": "whole-sofa", "global_requirement_ids": ["texture"], "references": [],
            "requirements": [
                {"id": "full-view", "required": True, "method": "frame_sampling", "description": "Both arms visible"},
                {"id": "texture", "required": True, "method": "frame_sampling", "description": "Correct weave"},
                {"id": "release", "required": True, "method": "full_playback", "description": "Hand leaves", "deadline_seconds": 3}],
            "uses": [{"purpose_id": "whole-sofa", "required_requirement_ids": ["full-view", "texture", "release"]},
                     {"purpose_id": "local-touch", "required_requirement_ids": ["texture"], "interval": [0, 2]}]}
    plan_ref = put(f"{base}/plan.json", plan)
    observations = [{"id": req["id"], "status": "pass", "method": req["method"],
                     "observed": "Actually inspected source", "evidence": [evidence],
                     **({"actual_start": 0, "actual_end": 2.9} if req["id"] == "release" else {})}
                    for req in plan["requirements"]]
    evaluation = {"version": "1.0", "project_id": "test", "scope": "source_clip",
                  "created_at": "2026-10-16T00:00:00Z", "judge_version": "source-v1", "rubric_version": "source-v1",
                  "subject_ref": {"name": "source", "path": source["path"]}, "subject_version": revision,
                  "subject_hash": source["sha256"], "hard_gate": {"pass": True, "checks": []},
                  "creative_advisory": {"scored": False, "dimensions": [], "summary": "Evidence only"},
                  "repair_targets": [], "status": "pass", "recommended_action": "proceed",
                  "source_review": {"shot_id": shot_id, "revision": revision,
                                    "source_sha256": source["sha256"], "plan_sha256": plan_ref["sha256"],
                                    "reviewers": [{"reviewer_id": "producer", "type": "production_agent",
                                                   "input_modalities": ["video", "image"],
                                                   "coverage": {"method": "full_playback", "interval": [0, 8]}}],
                                    "technical": {"status": "pass", "checks": [
                                        {"id": "decode", "status": "pass", "method": "decode", "observed": "Decoded all frames", "evidence": [evidence]}]},
                                    "observations": observations}}
    generation_identity = {"task_id": f"task-{shot_id}-{revision}", "attempt_id": f"attempt-{shot_id}-{revision}",
                           "request_id": f"request-{shot_id}-{revision}", "parent_budget_id": plan["parent_budget_id"],
                           "lineage_id": plan["lineage_id"], "request_fingerprint": hashlib.sha256(b"synthetic-provider-payload").hexdigest()}
    inputs = {"project_id": "test", "shot_id": shot_id, "revision_id": revision,
              **{key: generation_identity[key] for key in ("request_id", "parent_budget_id", "lineage_id")},
              "plan_ref": plan_ref, "prompt": "Synthetic source request, no generation performed"}
    inputs_ref = put(f"{base}/inputs.json", inputs)
    receipt = {"success": True, "data": {"provider": "synthetic", "status": "succeeded",
               "project_id": "test", "shot_id": shot_id, "revision": revision, **generation_identity,
               "media_sha256": source["sha256"],
               "source_inputs_fingerprint": hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}}
    record = {"version": "1.0", "project_id": "test", "shot_id": shot_id, "revision": revision,
              "source": source, "plan_ref": plan_ref, "evaluation_ref": put(f"{base}/evaluation.json", evaluation),
              "generation_inputs_ref": inputs_ref, "generation_identity": generation_identity,
              "generation_receipt_ref": put(f"{base}/receipt.json", receipt)}
    record_path = f"{base}/record.json"
    put(record_path, record)
    return plan, evaluation, record, record_path, put


def test_contracts_registered():
    assert {"shot_source_plan", "shot_source_record"} <= set(ARTIFACT_NAMES)


def make_case(root, shot_id="A", revision="v1", full_pass=False):
    """Shared Backlot integration fixture with an independently eligible local use."""
    _, evaluation, record, path, put = source_fixture(root, shot_id=shot_id, revision=revision)
    if not full_pass:
        evaluation["source_review"]["observations"][0].update(status="fail", observed="Right arm missing")
        record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
        put(path, record)
    return path


def test_original_failure_preserved_and_candidate_separate(tmp_path):
    from lib.shot_source_contracts import build_source_subject, validate_source_record
    _, evaluation, record, path, put = source_fixture(tmp_path)
    evaluation["source_review"]["observations"][0].update(status="fail", observed="Right arm missing")
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    put(path, record)
    summary = validate_source_record(tmp_path, record)
    assert summary["technical_status"] == "pass"
    assert summary["original_purpose_status"] == "fail"
    assert summary["purposes"]["local-touch"]["status"] == "pass"
    assert summary["purposes"]["local-touch"]["approval_status"] == "pending"
    with pytest.raises(ValueError, match="purpose"):
        build_source_subject(tmp_path, path, "whole-sofa")
    assert build_source_subject(tmp_path, path, "local-touch")["purpose_id"] == "local-touch"


@pytest.mark.parametrize("change,expected", [
    (lambda x: x.update(status="fail", observed="Wrong weave"), "fail"),
    (lambda x: x.update(actual_end=3.01), "fail"),
    (lambda x: x.update(evidence=[]), "error"),
    (lambda x: x.update(method="frame_sampling"), "error"),
    (lambda x: x.update(observed=""), "error"),
])
def test_observation_constraints(tmp_path, change, expected):
    from lib.shot_source_contracts import validate_source_record
    _, evaluation, record, _, put = source_fixture(tmp_path)
    change(evaluation["source_review"]["observations"][2])
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    summary = validate_source_record(tmp_path, record)
    assert summary["original_purpose_status"] == expected


def test_sampling_cannot_claim_playback(tmp_path):
    from lib.shot_source_contracts import validate_source_record
    _, evaluation, record, _, put = source_fixture(tmp_path)
    evaluation["source_review"]["reviewers"][0]["input_modalities"] = ["image"]
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    with pytest.raises(ValueError, match="playback"):
        validate_source_record(tmp_path, record)


def test_global_technical_failure_blocks_alternate(tmp_path):
    from lib.shot_source_contracts import build_source_subject
    _, evaluation, record, path, put = source_fixture(tmp_path)
    evaluation["source_review"]["technical"]["checks"][0]["status"] = "fail"
    evaluation["source_review"]["technical"]["status"] = "fail"
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    put(path, record)
    with pytest.raises(ValueError, match="technical"):
        build_source_subject(tmp_path, path, "local-touch")


def test_subject_hash_stale_and_slots_separate(tmp_path):
    from lib.shot_source_contracts import build_source_subject, verify_source_subject, source_subject_hash
    _, _, record, path, put = source_fixture(tmp_path)
    original = build_source_subject(tmp_path, path, "whole-sofa")
    alternate = build_source_subject(tmp_path, path, "local-touch")
    assert original["content_slot_id"] != alternate["content_slot_id"]
    assert source_subject_hash(original) != source_subject_hash(alternate)
    assert verify_source_subject(tmp_path, original)
    put(record["source"]["path"], b"changed-source")
    assert not verify_source_subject(tmp_path, original)


def test_source_scope_requires_explicit_canonical_path(tmp_path):
    from lib.artifact_io import scoped_artifact_relative_path, write_artifact_atomic
    _, evaluation, _, _, _ = source_fixture(tmp_path)
    with pytest.raises(ValueError, match="explicit"):
        scoped_artifact_relative_path("evaluation_report", "source_clip")
    with pytest.raises(ValueError, match="shot_sources"):
        write_artifact_atomic("artifacts/evaluation_report.source_clip.json", "evaluation_report", evaluation, project_dir=tmp_path)
    write_artifact_atomic("artifacts/shot_sources/sofa/v6/evaluation.json", "evaluation_report", evaluation, project_dir=tmp_path)


def test_plan_original_use_must_include_all_required(tmp_path):
    from lib.shot_source_contracts import validate_source_plan
    plan, _, _, _, _ = source_fixture(tmp_path)
    plan["uses"][0]["required_requirement_ids"].remove("full-view")
    with pytest.raises(ValueError, match="required"):
        validate_source_plan(tmp_path, plan)


def test_schema_source_scope_and_legacy_compatibility(tmp_path):
    _, evaluation, _, _, _ = source_fixture(tmp_path)
    validate_artifact("evaluation_report", evaluation)
    for scope in ("sample", "final", "preview", "full_variant"):
        legacy = copy.deepcopy(evaluation)
        legacy.pop("source_review")
        legacy["scope"] = scope
        validate_artifact("evaluation_report", legacy)


def test_repair_source_scope_never_falls_back_to_sample(tmp_path):
    from lib.repair import repairs_from_evaluation_report
    _, evaluation, _, _, _ = source_fixture(tmp_path)
    with pytest.raises(ValueError, match="path"):
        repairs_from_evaluation_report("test", evaluation, production_lock_hash="a" * 64)
    assert repairs_from_evaluation_report("test", evaluation, production_lock_hash="a" * 64,
                                         evaluation_report_path="artifacts/shot_sources/sofa/v6/evaluation.json") == []


def test_source_repair_targets_bind_source_and_do_not_render_final(tmp_path):
    from lib.repair import repairs_from_evaluation_report
    _, evaluation, _, _, _ = source_fixture(tmp_path)
    evaluation["repair_targets"] = [{"check_id": "full-view", "action": "replace_asset", "affected_shots": ["sofa"]}]
    repair = repairs_from_evaluation_report("test", evaluation, production_lock_hash="a" * 64,
                                           evaluation_report_path="artifacts/shot_sources/sofa/v6/evaluation.json")[0]
    assert repair["evaluation_report_ref"]["path"] == "artifacts/shot_sources/sofa/v6/evaluation.json"
    assert repair["evaluation_report_ref"]["scope"] == "source_clip"
    assert repair["render_route"] == "no_render"


def test_missing_requirement_and_stale_plan_version(tmp_path):
    from lib.shot_source_contracts import validate_source_record
    _, evaluation, record, _, put = source_fixture(tmp_path)
    evaluation["source_review"]["observations"].pop(0)
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    assert validate_source_record(tmp_path, record)["original_purpose_status"] == "not_run"
    evaluation["source_review"]["plan_sha256"] = "a" * 64
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    with pytest.raises(ValueError, match="plan binding"):
        validate_source_record(tmp_path, record)


def test_evidence_needs_actual_observation_time(tmp_path):
    from lib.shot_source_contracts import validate_source_record
    _, evaluation, record, _, put = source_fixture(tmp_path)
    evaluation["source_review"]["observations"][0]["evidence"] = [
        {k: v for k, v in evaluation["source_review"]["observations"][0]["evidence"][0].items() if k != "time_seconds"}]
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    assert validate_source_record(tmp_path, record)["original_purpose_status"] == "error"


def test_unexplained_not_applicable_cannot_pass_technical(tmp_path):
    from lib.shot_source_contracts import validate_source_record
    _, evaluation, record, _, put = source_fixture(tmp_path)
    evaluation["source_review"]["technical"]["checks"].append(
        {"id": "audio", "status": "not_applicable", "method": "probe"})
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    with pytest.raises(ValueError, match="technical"):
        validate_source_record(tmp_path, record)


def test_silent_source_audio_inapplicable_does_not_skip_decode(tmp_path):
    from lib.shot_source_contracts import validate_source_record
    _, evaluation, record, _, put = source_fixture(tmp_path)
    evaluation["source_review"]["technical"]["checks"].append(
        {"id": "audio", "status": "not_applicable", "method": "probe",
         "applicability": {"applies": False, "reason": "Silent source clip"}})
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    assert validate_source_record(tmp_path, record)["technical_status"] == "pass"
    evaluation["source_review"]["technical"]["checks"][0].update(
        status="not_applicable", applicability={"applies": False, "reason": "No decode"})
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    with pytest.raises(ValueError, match="decode"):
        validate_source_record(tmp_path, record)


@pytest.mark.parametrize("dependency", ["fact_snapshot", "category_profile", "production_lock"])
def test_approval_invalidated_by_each_material_dependency(tmp_path, dependency):
    from lib.shot_source_contracts import build_source_subject, verify_source_subject
    plan, _, _, path, put = source_fixture(tmp_path)
    subject = build_source_subject(tmp_path, path, "local-touch")
    put(plan["dependencies"][dependency]["path"], {"version": 2})
    assert not verify_source_subject(tmp_path, subject)


def test_project_root_identity_checked(tmp_path):
    from lib.shot_source_contracts import validate_source_record
    _, _, record, _, put = source_fixture(tmp_path)
    put("project.json", {"project_id": "another-project"})
    with pytest.raises(ValueError, match="project root"):
        validate_source_record(tmp_path, record)


def test_required_technical_not_run_is_not_eligible(tmp_path):
    from lib.shot_source_contracts import build_source_subject
    _, evaluation, record, path, put = source_fixture(tmp_path)
    evaluation["source_review"]["technical"]["checks"][0]["status"] = "not_run"
    evaluation["source_review"]["technical"]["status"] = "not_run"
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    put(path, record)
    with pytest.raises(ValueError, match="technical"):
        build_source_subject(tmp_path, path, "local-touch")


def test_playback_coverage_must_span_observation(tmp_path):
    from lib.shot_source_contracts import validate_source_record
    _, evaluation, record, _, put = source_fixture(tmp_path)
    evaluation["source_review"]["reviewers"][0]["coverage"]["interval"] = [0, 1]
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    assert validate_source_record(tmp_path, record)["original_purpose_status"] == "error"


def test_selected_interval_cannot_expand_allowed_use(tmp_path):
    from lib.shot_source_contracts import build_source_subject
    _, _, _, path, _ = source_fixture(tmp_path)
    with pytest.raises(ValueError, match="outside selected purpose"):
        build_source_subject(tmp_path, path, "local-touch", [0, 3])


def test_unknown_scope_cannot_become_final_repair(tmp_path):
    from lib.repair import repairs_from_evaluation_report
    _, evaluation, _, _, _ = source_fixture(tmp_path)
    evaluation["scope"] = "unrecognized"
    with pytest.raises(ValueError, match="Unknown evaluation scope"):
        repairs_from_evaluation_report("test", evaluation, production_lock_hash="a" * 64)


def test_fatal_hard_gate_cannot_be_bypassed_by_alternate_purpose(tmp_path):
    from lib.shot_source_contracts import build_source_subject
    _, evaluation, record, path, put = source_fixture(tmp_path)
    evaluation["hard_gate"] = {"pass": False, "checks": [
        {"id": "corruption", "name": "Decode corruption", "status": "fail", "severity": "fatal",
         "message": "Broken frame stream", "fixable": False}]}
    evaluation.update(status="fail", recommended_action="reject")
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    put(path, record)
    with pytest.raises(ValueError, match="technical"):
        build_source_subject(tmp_path, path, "local-touch")


def test_selected_interval_must_include_required_actual_evidence(tmp_path):
    from lib.shot_source_contracts import build_source_subject
    _, _, _, path, _ = source_fixture(tmp_path)
    with pytest.raises(ValueError, match="evidence"):
        build_source_subject(tmp_path, path, "whole-sofa", [6, 8])
    with pytest.raises(ValueError, match="evidence"):
        build_source_subject(tmp_path, path, "whole-sofa", [0, 2])


def test_decode_id_cannot_disguise_frame_sampling(tmp_path):
    from lib.shot_source_contracts import build_source_subject
    _, evaluation, record, path, put = source_fixture(tmp_path)
    evaluation["source_review"]["technical"]["checks"][0]["method"] = "frame_sampling"
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    put(path, record)
    with pytest.raises(ValueError, match="decode"):
        build_source_subject(tmp_path, path, "local-touch")


@pytest.mark.parametrize("field,value", [
    ("status", "failed"), ("media_sha256", "a" * 64), ("task_id", "another-task"),
    ("attempt_id", "another-attempt"), ("request_id", "another-request"),
    ("parent_budget_id", "another-budget"), ("lineage_id", "another-lineage"),
    ("shot_id", "another-shot"), ("revision", "another-revision"), ("project_id", "another-project"),
    ("source_inputs_fingerprint", "b" * 64), ("request_fingerprint", "c" * 64),
])
def test_generation_receipt_binds_output_and_request_identity(tmp_path, field, value):
    from lib.shot_source_contracts import build_source_subject
    _, _, record, path, put = source_fixture(tmp_path)
    receipt = json.loads((tmp_path / record["generation_receipt_ref"]["path"]).read_text())
    receipt["data"][field] = value
    record["generation_receipt_ref"] = put(record["generation_receipt_ref"]["path"], receipt)
    put(path, record)
    with pytest.raises(ValueError, match="generation"):
        build_source_subject(tmp_path, path, "local-touch")


def test_failed_receipt_envelope_never_eligible(tmp_path):
    from lib.shot_source_contracts import build_source_subject
    _, _, record, path, put = source_fixture(tmp_path)
    receipt = json.loads((tmp_path / record["generation_receipt_ref"]["path"]).read_text())
    receipt["success"] = False
    record["generation_receipt_ref"] = put(record["generation_receipt_ref"]["path"], receipt)
    put(path, record)
    with pytest.raises(ValueError, match="generation"):
        build_source_subject(tmp_path, path, "local-touch")


@pytest.mark.parametrize("field", ["task_id", "attempt_id", "parent_budget_id", "source_inputs_fingerprint"])
def test_historical_receipt_gaps_are_not_recorded(tmp_path, field):
    from lib.shot_source_contracts import build_source_subject
    _, _, record, path, put = source_fixture(tmp_path)
    receipt = json.loads((tmp_path / record["generation_receipt_ref"]["path"]).read_text())
    receipt["data"].pop(field)
    record["generation_receipt_ref"] = put(record["generation_receipt_ref"]["path"], receipt)
    put(path, record)
    with pytest.raises(ValueError, match="not recorded"):
        build_source_subject(tmp_path, path, "local-touch")


def test_original_request_not_recorded_cannot_be_invented(tmp_path):
    from lib.shot_source_contracts import validate_source_record
    _, _, record, _, _ = source_fixture(tmp_path)
    record.pop("generation_inputs_ref")
    with pytest.raises(ValueError, match="not recorded"):
        validate_source_record(tmp_path, record)


@pytest.mark.parametrize("field,value", [("plan_ref", {"path": "artifacts/wrong-plan.json", "sha256": "a" * 64}),
                                         ("parent_budget_id", "wrong-budget"), ("lineage_id", "wrong-lineage"),
                                         ("request_id", "wrong-request"), ("shot_id", "wrong-shot"), ("revision_id", "wrong-revision")])
def test_original_generation_inputs_must_match_source_plan(tmp_path, field, value):
    from lib.shot_source_contracts import build_source_subject
    _, _, record, path, put = source_fixture(tmp_path)
    inputs = json.loads((tmp_path / record["generation_inputs_ref"]["path"]).read_text())
    inputs[field] = value
    record["generation_inputs_ref"] = put(record["generation_inputs_ref"]["path"], inputs)
    receipt = json.loads((tmp_path / record["generation_receipt_ref"]["path"]).read_text())
    receipt["data"]["source_inputs_fingerprint"] = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    record["generation_receipt_ref"] = put(record["generation_receipt_ref"]["path"], receipt)
    put(path, record)
    with pytest.raises(ValueError, match="generation"):
        build_source_subject(tmp_path, path, "local-touch")


def test_source_record_path_must_be_canonical_for_its_own_identity(tmp_path):
    from lib.shot_source_contracts import build_source_subject
    _, _, record, _, put = source_fixture(tmp_path)
    put("artifacts/shot_sources/other/v6/record.json", record)
    with pytest.raises(ValueError, match="canonical"):
        build_source_subject(tmp_path, "artifacts/shot_sources/other/v6/record.json", "local-touch")


def test_real_seedance_receipt_can_enter_source_review_offline(tmp_path, monkeypatch):
    """Use real adapter/accounting output; provider I/O is fully mocked."""
    from tools.cost_tracker import CostTracker
    from tools.video.seedance_ark import SeedanceArkVideo
    from lib.shot_source_contracts import build_source_subject

    plan, _, record, path, put = source_fixture(tmp_path)
    identity = record["generation_identity"]
    tracker = CostTracker(project_dir=tmp_path)
    tracker.create_parent_budget(plan["parent_budget_id"], currency="CNY", amount="50", max_paid_calls=2,
                                 authorization_ref="approval:offline", shot_id=plan["shot_id"], lineage_id=plan["lineage_id"])
    reservation = tracker.estimate_native("seedance_ark", "text_to_video", "20", currency="CNY",
        parent_budget_id=plan["parent_budget_id"], shot_id=plan["shot_id"], lineage_id=plan["lineage_id"],
        request_id=identity["request_id"])
    tracker.reserve(reservation)
    inputs = {"project_id": "test", "revision_id": plan["revision"], "project_dir": str(tmp_path),
              "parent_budget_id": plan["parent_budget_id"], "shot_id": plan["shot_id"], "lineage_id": plan["lineage_id"],
              "request_id": identity["request_id"], "reservation_id": reservation, "shot_source_plan": plan,
              "production_lock_ref": plan["dependencies"]["production_lock"],
              "model_variant": "2.5", "duration": 8, "generate_audio": False, "prompt": "Synthetic offline product shot",
              "idempotency_key": "offline-source", "output_path": str(tmp_path / record["source"]["path"])}
    record["generation_inputs_ref"] = put(record["generation_inputs_ref"]["path"], inputs)
    monkeypatch.setenv("ARK_API_KEY", "offline-test-only")
    monkeypatch.setenv("ARK_TASK_JOURNAL_PATH", str(tmp_path / "tasks.json"))
    tool = SeedanceArkVideo()
    task = {"id": "task-offline", "model": "doubao-seedance-2-5-260628", "status": "succeeded",
            "resolution": "720p", "usage": {"completion_tokens": 87300},
            "content": {"video_url": "https://example.test/offline.mp4"}}
    monkeypatch.setattr(tool, "_create_task", lambda *_: task["id"])
    monkeypatch.setattr(tool, "_poll_task", lambda *_: task)
    monkeypatch.setattr(tool, "_download_video", lambda _, output: output.write_bytes(b"synthetic-source"))
    monkeypatch.setattr("tools.video._shared.probe_output", lambda _: {"duration_seconds": 8})
    result = tool.execute(inputs)
    assert result.success, result.error
    record["generation_receipt_ref"] = put(record["generation_receipt_ref"]["path"], {"success": result.success, "data": result.data})
    record["generation_identity"] = {key: result.data[key] for key in identity}
    put(path, record)
    subject = build_source_subject(tmp_path, path, "local-touch")
    assert subject["summary"]["eligible"]
    assert record["generation_inputs_ref"]["path"] in subject["dependencies"]


def test_fixed_model_mismatch_cannot_enter_source_review(tmp_path):
    from lib.shot_source_contracts import build_source_subject
    from lib.generation_attempts import GenerationAttempts
    _, _, record, path, put = source_fixture(tmp_path)
    inputs = json.loads((tmp_path / record["generation_inputs_ref"]["path"]).read_text())
    inputs["model"] = "approved-fixed-model"
    record["generation_inputs_ref"] = put(record["generation_inputs_ref"]["path"], inputs)
    receipt = json.loads((tmp_path / record["generation_receipt_ref"]["path"]).read_text())
    receipt["data"].update(model="observed-other-model", source_inputs_fingerprint=GenerationAttempts.fingerprint(inputs))
    record["generation_receipt_ref"] = put(record["generation_receipt_ref"]["path"], receipt)
    put(path, record)
    with pytest.raises(ValueError, match="model"):
        build_source_subject(tmp_path, path, "local-touch")
    receipt["data"]["model"] = inputs["model"]
    record["generation_receipt_ref"] = put(record["generation_receipt_ref"]["path"], receipt)
    put(path, record)
    assert build_source_subject(tmp_path, path, "local-touch")["summary"]["eligible"]


def test_alternate_use_cannot_drop_global_identity_requirement(tmp_path):
    from lib.shot_source_contracts import validate_source_record, build_source_subject
    from lib.generation_attempts import GenerationAttempts
    plan, evaluation, record, path, put = source_fixture(tmp_path)
    # Explicit identity constraint belongs to every use. Whole view remains original-only.
    plan["requirements"].append({"id": "sku-identity", "required": True, "method": "frame_sampling", "description": "SKU identity must remain correct in every use"})
    plan["global_requirement_ids"].append("sku-identity")
    plan["uses"][0]["required_requirement_ids"].append("sku-identity")
    record["plan_ref"] = put(record["plan_ref"]["path"], plan)
    evaluation["source_review"]["plan_sha256"] = record["plan_ref"]["sha256"]
    evaluation["source_review"]["observations"].append({"id": "sku-identity", "status": "fail", "method": "frame_sampling",
        "observed": "Wrong SKU visible", "evidence": evaluation["source_review"]["observations"][0]["evidence"]})
    record["evaluation_ref"] = put(record["evaluation_ref"]["path"], evaluation)
    inputs = json.loads((tmp_path / record["generation_inputs_ref"]["path"]).read_text())
    inputs["plan_ref"] = record["plan_ref"]
    record["generation_inputs_ref"] = put(record["generation_inputs_ref"]["path"], inputs)
    receipt = json.loads((tmp_path / record["generation_receipt_ref"]["path"]).read_text())
    receipt["data"]["source_inputs_fingerprint"] = GenerationAttempts.fingerprint(inputs)
    record["generation_receipt_ref"] = put(record["generation_receipt_ref"]["path"], receipt)
    put(path, record)
    summary = validate_source_record(tmp_path, record)
    assert summary["purposes"]["local-touch"]["status"] == "fail"
    assert summary["original_purpose_status"] == "fail"
    with pytest.raises(ValueError, match="purpose"):
        build_source_subject(tmp_path, path, "local-touch")


@pytest.mark.parametrize("globals", [[], ["unknown"], ["texture", "texture"]])
def test_global_requirements_must_be_explicit_unique_known_ids(tmp_path, globals):
    from lib.shot_source_contracts import validate_source_plan
    plan, _, _, _, _ = source_fixture(tmp_path)
    plan["global_requirement_ids"] = globals
    with pytest.raises(ValueError):
        validate_source_plan(tmp_path, plan)
