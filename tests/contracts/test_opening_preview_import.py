"""Prepared preview migration keeps current bytes and pending authority distinct."""
import copy
import contextlib
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from lib.opening_contracts import verify_opening_experiment_files
from lib.opening_preview_import import import_prepared_previews
from backlot.project_commit import ProjectCommitStore
from lib.opening_review_scope import opening_review_scope
from lib.production_evidence import read_object
from schemas.artifacts import validate_artifact
from tests.contracts.test_opening_contracts import hook_v2


def _put(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode())
    return {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _packet(root):
    _put(root, "project.json", {"project_id": root.name})
    source_doc = root / "source-document.md"
    source_doc.write_text("Original document excerpt", encoding="utf-8")
    source_hash = hashlib.sha256(source_doc.read_bytes()).hexdigest()
    facts = _put(root, "artifacts/facts.json", {"sku": "sku-1", "status": "pending_confirmation"})
    brand = _put(root, "artifacts/brand.json", {"version": "1.0", "font_files": []})
    reference = _put(root, "assets/reference.png", b"synthetic-reference")
    mix = _put(root, "assets/mix.wav", b"synthetic-mix")
    logo = _put(root, "assets/logo.png", b"synthetic-logo")
    old = _put(root, "historical/mother.json", {"sku": "pilot-sku-1", "approval_render_only": True})
    voice = {"version": "1.0", "source_document_sha256": source_hash,
             "status": "platform_verification_pending", "records": [{
                 "source_id": "DOC-1", "document_row": 1, "excerpt": "有没有其他颜色呢",
                 "source_kind": "document_excerpt", "verification_status": "pending",
                 "document_sha256": source_hash, "platform_label_in_document": "document label only",
                 "platform_url": None, "platform_record_id": None, "collected_at": None,
                 "original_product_id": None, "deduplication_status": "pending",
                 "source_gap": "Platform identity and permission unverified",
                 "deidentification": "Nickname omitted", "public_testimonial_use": "not_authorized",
                 "can_support": "Question only"}]}
    hooks, previews, imported_files = {}, {}, []
    for cid in ("A01", "A03"):
        source = _put(root, f"assets/{cid}-source.mp4", cid.encode())
        render = _put(root, f"renders/{cid}.mp4", (cid + "-render").encode())
        imported_files.append({**source, "bytes": len((root / source["path"]).read_bytes())})
        scene = {"id": "s1", "footageKey": "hook", "fromFrame": 0,
                 "durationInFrames": 90, "sourceInSeconds": .25, "playbackRate": 1}
        runtime = {"profile": {}, "scenes": [scene], "footage": {"hook": source["path"]},
                   "titles": [], "words": [], "captions": [], "durationInFrames": 90,
                   "finalMix": {**mix, "mode": "external_mux"}, "logoSrc": "assets/logo.png",
                   "opening": {"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5},
                   "fps": 30, "width": 1080, "height": 1920}
        snapshot = _put(root, f"artifacts/{cid}-snapshot.json", {
            **runtime, "render_input_refs": [source, mix, logo]})
        render_input = _put(root, f"artifacts/{cid}-render-input.json", {"edit_decisions": runtime})
        render_result = _put(root, f"artifacts/{cid}-render-result.json", {"success": True, "data": {
            "renderer_props_ref": snapshot, "output": str(root / render["path"]), "final_review_status": "revise"}})
        canonical = copy.deepcopy(runtime)
        canonical["scenes"][0].update(assetId="source", toFrameExclusive=90, sourceOutSeconds=3.25)
        canonical.update(version="1.0", project_id=root.name, created_at="2026-09-30T00:00:00Z",
                         producer="legacy_import_reconstruction", compositionId="ProductionBrand",
                         input_hashes={"source": source["sha256"]})
        plan = hook_v2()
        plan.update(project_id=root.name, sku="sku-1", source={
            "kind": "document_excerpt", "verification_status": "pending", "source_id": "DOC-1",
            "excerpt": "有没有其他颜色呢", "gap": "Platform identity and permission unverified"})
        plan["shots"][0]["asset_identity"].update(sku="sku-1", source=source, reference_images=[reference])
        plan["shots"][0]["source_mapping"]["source_duration_seconds"] = 4.0
        plan["promise_fulfillment"].pop("evidence_ref")
        hooks[cid] = plan
        previews[cid] = {"candidate_id": cid, "title": cid + " preview", "task_id": cid + "-task",
                         "source_ref": source, "render_ref": render, "render_result_ref": render_result,
                         "render_input_ref": render_input, "renderer_snapshot_ref": snapshot,
                         "source_task_receipt_ref": None, "evidence_refs": {}, "canonical_props": canonical,
                         "validation_report": {"version": "2.0", "scope": "preview", "checks": [{
                             "id": "opening_motion", "shot_id": "s1", "status": "not_run", "method": "unmeasured",
                             "evidence_interval_seconds": [0, 3], "reviewer": {"kind": "agent", "id": "migration",
                             "reviewed_at": "2026-09-30T00:00:00Z"}}]},
                         "quality_report": {"version": "1.0", "checks": [], "costs": {"paid_cny": None}},
                         "production_record": {"version": "1.0", "content_slot_id": cid + "-preview",
                                               "sku": "sku-1", "provenance": "legacy_import",
                                               "campaign_role": "pilot", "work_id": "pilot-preview:" + cid}}
    manifest = _put(root, "artifacts/imported_inputs.json", {"files": imported_files})
    return {"version": "1.0", "project_id": root.name, "imported_inputs_ref": manifest,
            "source_document_path": str(source_doc), "voice_source_register": voice,
            "sku_alias": {"canonical_sku": "sku-1", "legacy_sku": "pilot-sku-1",
                          "original_records": [{"absolute_path": str(root / old["path"]), "sha256": old["sha256"]}]},
            "body_payoff_pending": {"status": "planning", "body_frozen": False,
                                    "full_render_ref": None, "approval_ref": None},
            "hooks": hooks,
            "experiment": {"version": "2.0", "status": "planning", "experiment_id": "pilot-plan",
                           "sku": "sku-1", "window_seconds": [0, 3],
                           "facts_ref": {**facts, "sku": "sku-1"}, "brand_ref": brand},
            "previews": previews}


def test_prepared_import_is_hash_bound_idempotent_and_unapproved(tmp_path):
    packet = _packet(tmp_path)
    first = import_prepared_previews(tmp_path, packet)
    assert first["status"] == "imported" and first["new_original_work_count"] == 0
    index = read_object(tmp_path, "artifacts/production_review_index.json")
    assert len(index["items"]) == 2
    for row in index["items"]:
        record = read_object(tmp_path, row["record_path"])
        assert record["provenance"] == "legacy_import" and record["campaign_role"] == "pilot"
        assert record["opening"]["scope"] == "preview" and "approval_ref" not in record
        assert opening_review_scope(tmp_path, record)["scope"] == "preview"
        plan = read_object(tmp_path, record["opening"]["hook_plan_ref"]["path"])
        assert plan["source"]["record_id"] == "DOC-1"
        assert plan["source"]["verification_status"] == "pending"
    generation = read_object(tmp_path, "operator/current-generation.json")["generation_id"]
    assert import_prepared_previews(tmp_path, packet)["status"] == "replayed"
    assert read_object(tmp_path, "operator/current-generation.json")["generation_id"] == generation
    with pytest.raises(ValidationError):
        verify_opening_experiment_files(tmp_path, read_object(tmp_path, index["items"][0]["record_path"])["opening"]["experiment_ref"])
    changed = copy.deepcopy(packet)
    changed["sku_alias"]["canonical_sku"] = "other"
    with pytest.raises(ValueError, match="packet changed"):
        import_prepared_previews(tmp_path, changed)
    (tmp_path / packet["previews"]["A01"]["source_ref"]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Input hash changed"):
        import_prepared_previews(tmp_path, packet)


def test_voice_source_register_rejects_duplicate_or_false_verification(tmp_path):
    voice = _packet(tmp_path)["voice_source_register"]
    validate_artifact("voice_source_register", voice)
    falsely_verified = copy.deepcopy(voice)
    falsely_verified["records"][0]["verification_status"] = "verified"
    with pytest.raises(ValidationError):
        validate_artifact("voice_source_register", falsely_verified)
    voice["records"].append(copy.deepcopy(voice["records"][0]))
    with pytest.raises(ValidationError, match="Duplicate voice source"):
        validate_artifact("voice_source_register", voice)
    voice.pop("records")
    with pytest.raises(ValidationError):
        validate_artifact("voice_source_register", voice)


def test_import_rejects_wrong_historical_sku_alias_before_writing(tmp_path):
    packet = _packet(tmp_path)
    packet["sku_alias"]["legacy_sku"] = "different"
    with pytest.raises(ValueError, match="Historical SKU alias"):
        import_prepared_previews(tmp_path, packet)
    assert not (tmp_path / "artifacts/production_review_index.json").exists()


def test_import_replay_identifies_audited_successor_index_without_new_work(tmp_path):
    packet = _packet(tmp_path)
    receipt = import_prepared_previews(tmp_path, packet)
    original_index = receipt["outputs"]["artifacts/production_review_index.json"]
    import_receipt = _put(tmp_path, "artifacts/opening-import/import_receipt.json",
                          read_object(tmp_path, "artifacts/opening-import/import_receipt.json"))
    _put(tmp_path, "artifacts/post-import-audit/audit_receipt.json", {
        "kind": "post_import_measurement_binding", "original_index_ref": original_index,
        "original_import_receipt_ref": import_receipt})
    index = read_object(tmp_path, "artifacts/production_review_index.json")
    index["items"][0]["record_path"] = "artifacts/post-import-audit/A01/production_record.json"
    _put(tmp_path, "artifacts/production_review_index.json", index)
    with pytest.raises(ValueError, match="Import already registered.*do not re-import"):
        import_prepared_previews(tmp_path, packet)


def test_import_refuses_to_replace_existing_review_cards(tmp_path):
    packet = _packet(tmp_path)
    existing = {"version": "1.0", "items": [{"id": "existing-slot", "title": "Existing review",
        "record_path": "artifacts/existing/production_record.json"}]}
    original = _put(tmp_path, "artifacts/production_review_index.json", existing)
    with pytest.raises(ValueError, match="nonempty review index"):
        import_prepared_previews(tmp_path, packet)
    assert read_object(tmp_path, original["path"]) == existing
    assert not (tmp_path / "artifacts/opening-import/import_receipt.json").exists()


def test_import_refuses_duplicate_preview_content_slots(tmp_path):
    packet = _packet(tmp_path)
    packet["previews"]["A03"]["production_record"]["content_slot_id"] = (
        packet["previews"]["A01"]["production_record"]["content_slot_id"])
    with pytest.raises(ValueError, match="Duplicate preview content_slot_id"):
        import_prepared_previews(tmp_path, packet)
    assert not (tmp_path / "artifacts/production_review_index.json").exists()


def test_interleaved_different_packet_conflicts_under_project_lock(tmp_path, monkeypatch):
    first = _packet(tmp_path)
    second = copy.deepcopy(first)
    second["previews"]["A01"]["title"] = "second packet title"
    original_transaction = ProjectCommitStore.transaction
    entered = False

    @contextlib.contextmanager
    def interleaved(self, **kwargs):
        nonlocal entered
        if not entered:
            entered = True
            assert import_prepared_previews(tmp_path, second)["status"] == "imported"
        with original_transaction(self, **kwargs) as sink:
            yield sink

    monkeypatch.setattr(ProjectCommitStore, "transaction", interleaved)
    with pytest.raises(ValueError, match="packet changed"):
        import_prepared_previews(tmp_path, first)
    index = read_object(tmp_path, "artifacts/production_review_index.json")
    assert index["items"][0]["title"] == "second packet title"


@pytest.mark.parametrize("change,issue", [
    (lambda p: p["previews"]["A01"]["production_record"].update(campaign_role="original"), "pilot identity"),
    (lambda p: p["previews"]["A01"]["production_record"].update(provenance="canonical"), "pilot identity"),
    (lambda p: p["previews"]["A01"]["production_record"].update(approval_ref="historical/mother.json"), "authority or history"),
    (lambda p: p["previews"]["A01"]["production_record"].update(historical_stage_gaps={"status": "completed"}), "authority or history"),
    (lambda p: p["previews"]["A01"]["production_record"].update(costs={"paid_cny": 0}), "settled proof"),
    (lambda p: p["previews"]["A01"]["quality_report"]["costs"].update(paid_cny=0), "settled proof"),
    (lambda p: p["previews"]["A01"]["quality_report"]["costs"].update(source_task_id="other-task"), "task identity"),
    (lambda p: p["previews"]["A01"]["production_record"].update(costs={"estimated_cny": 1}), "catalog estimate"),
    (lambda p: p["previews"]["A01"]["quality_report"].update(certification_eligible=True), "certification"),
])
def test_import_rejects_authority_history_and_cost_claims(tmp_path, change, issue):
    packet = _packet(tmp_path)
    change(packet)
    with pytest.raises(ValueError, match=issue):
        import_prepared_previews(tmp_path, packet)
    assert not (tmp_path / "artifacts/production_review_index.json").exists()


def test_import_rejects_stale_renderer_input_pin_after_source_mutation(tmp_path):
    packet = _packet(tmp_path)
    preview = packet["previews"]["A01"]
    source = _put(tmp_path, preview["source_ref"]["path"], b"changed source at same path")
    preview["source_ref"] = source
    packet["hooks"]["A01"]["shots"][0]["asset_identity"]["source"] = source
    manifest = read_object(tmp_path, packet["imported_inputs_ref"]["path"])
    manifest["files"][0]["sha256"] = source["sha256"]
    manifest["files"][0]["bytes"] = len(b"changed source at same path")
    packet["imported_inputs_ref"] = _put(tmp_path, packet["imported_inputs_ref"]["path"], manifest)
    with pytest.raises(ValueError, match="Input hash changed"):
        import_prepared_previews(tmp_path, packet)
    assert not (tmp_path / "artifacts/production_review_index.json").exists()


def test_import_requires_pins_for_actual_footage_logo_and_mix(tmp_path):
    packet = _packet(tmp_path)
    preview = packet["previews"]["A01"]
    snapshot_path = preview["renderer_snapshot_ref"]["path"]
    snapshot = read_object(tmp_path, snapshot_path)
    snapshot["render_input_refs"] = [snapshot["render_input_refs"][1]]  # mix only
    preview["renderer_snapshot_ref"] = _put(tmp_path, snapshot_path, snapshot)
    result_path = preview["render_result_ref"]["path"]
    result = read_object(tmp_path, result_path)
    result["data"]["renderer_props_ref"] = preview["renderer_snapshot_ref"]
    preview["render_result_ref"] = _put(tmp_path, result_path, result)
    source = _put(tmp_path, preview["source_ref"]["path"], b"replaced source")
    preview["source_ref"] = source
    packet["hooks"]["A01"]["shots"][0]["asset_identity"]["source"] = source
    manifest_path = packet["imported_inputs_ref"]["path"]
    manifest = read_object(tmp_path, manifest_path)
    manifest["files"][0].update(sha256=source["sha256"], bytes=len(b"replaced source"))
    packet["imported_inputs_ref"] = _put(tmp_path, manifest_path, manifest)
    with pytest.raises(ValueError, match="Renderer input pins do not cover"):
        import_prepared_previews(tmp_path, packet)
    assert not (tmp_path / "artifacts/production_review_index.json").exists()


@pytest.mark.parametrize("change,issue", [
    (lambda p: p["hooks"]["A01"]["source"].update(excerpt="different question"), "Hook excerpt"),
    (lambda p: p["hooks"]["A01"]["shots"][0]["source_mapping"].update(source_interval_seconds=[0.5, 3.5]), "Opening source interval"),
])
def test_import_rejects_hook_source_mismatch_before_commit(tmp_path, change, issue):
    packet = _packet(tmp_path)
    change(packet)
    with pytest.raises(ValueError, match=issue):
        import_prepared_previews(tmp_path, packet)
    assert not (tmp_path / "artifacts/production_review_index.json").exists()
