"""Import prepared opening preview evidence without inventing production history.

The caller supplies creative plans and reconstructed canonical props. This
module only verifies immutable inputs, binds their hashes, and commits a
planning experiment plus two legacy preview records atomically.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Mapping

from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes
from lib.final_props import validate_final_props
from lib.opening_contracts import validate_opening_experiment
from lib.production_evidence import file_sha256, project_file, read_object
from schemas.artifacts import validate_artifact


RUNTIME_FIELDS = ("profile", "scenes", "footage", "titles", "words", "captions",
                  "durationInFrames", "finalMix", "logoSrc", "opening", "fps", "width", "height")
RECEIPT = "artifacts/opening-import/import_receipt.json"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _ref(root: Path, path: str, sha256: str | None = None) -> dict[str, str]:
    target = project_file(root, path)
    actual = file_sha256(target)
    if sha256 is not None and actual != sha256:
        raise ValueError(f"Input hash changed: {path}")
    return {"path": path, "sha256": actual}


def _written_ref(relative: str, value: Mapping) -> dict[str, str]:
    return {"path": relative, "sha256": _digest(value)}


def _verify_source_manifest(root: Path, manifest_ref: Mapping) -> None:
    manifest = read_object(root, _ref(root, manifest_ref["path"], manifest_ref["sha256"])["path"])
    for row in manifest["files"]:
        _ref(root, row["path"], row["sha256"])


def _verify_reconstruction(root: Path, preview: Mapping) -> None:
    render_ref = _ref(root, **preview["render_ref"])
    _ref(root, **preview["source_ref"])
    result = read_object(root, _ref(root, **preview["render_result_ref"])["path"])
    render_input = read_object(root, _ref(root, **preview["render_input_ref"])["path"])
    snapshot = read_object(root, _ref(root, **preview["renderer_snapshot_ref"])["path"])
    result_data = result.get("data") or {}
    if not result.get("success") or result_data.get("renderer_props_ref") != preview["renderer_snapshot_ref"]:
        raise ValueError("Renderer snapshot is not bound to successful render result")
    if result_data.get("final_review_status") == "approved":
        raise ValueError("Engineering import cannot assert final approval")
    if Path(result_data.get("output", "")).resolve() != project_file(root, render_ref["path"]):
        raise ValueError("Render result output differs from imported file")
    original = render_input.get("edit_decisions") or {}
    canonical = preview["canonical_props"]
    for key in RUNTIME_FIELDS:
        expected = snapshot.get(key)
        actual = canonical.get(key)
        if key == "scenes":
            actual = [{k: v for k, v in scene.items() if k not in {"assetId", "toFrameExclusive", "sourceOutSeconds"}}
                      for scene in actual or []]
        if actual != expected or original.get(key) != expected:
            raise ValueError(f"Canonical/rendered input mismatch: {key}")
    if canonical.get("compositionId") != "ProductionBrand" or canonical.get("producer") != "legacy_import_reconstruction":
        raise ValueError("Canonical props must declare reconstructed provenance")
    if canonical.get("finalMix", {}).get("sha256") != _ref(root, canonical["finalMix"]["path"])["sha256"]:
        raise ValueError("Actual preview mix hash mismatch")
    validate_artifact("final_props", attach_hashes(canonical))
    validate_final_props(canonical)
    if canonical.get("opening", {}).get("scope") != "preview":
        raise ValueError("Only three-second previews may be imported")
    for key, ref in preview["evidence_refs"].items():
        _ref(root, **ref)
    if preview["source_task_receipt_ref"]:
        receipt = read_object(root, _ref(root, **preview["source_task_receipt_ref"])["path"])
        # The GET receipt proves remote task status/model, not the local source hash.
        if preview["task_id"] not in _json_bytes(receipt).decode("utf-8"):
            raise ValueError("Recovery receipt does not identify the source task")


def import_prepared_previews(root: Path, packet: Mapping) -> dict:
    """Atomically import an explicit, already authored packet; replay is read-only."""
    root = Path(root).resolve()
    if packet.get("version") != "1.0" or packet.get("project_id") != root.name:
        raise ValueError("Import packet version/project mismatch")
    if set(packet.get("previews", {})) != set(packet.get("hooks", {})) or len(packet["previews"]) != 2:
        raise ValueError("Exactly two prepared preview plans and records are required")
    fingerprint = _digest(packet)
    receipt_path = root / RECEIPT
    if receipt_path.exists():
        previous = read_object(root, RECEIPT)
        if previous.get("packet_sha256") != fingerprint:
            raise ValueError("Import packet changed after registration")
        for ref in previous["outputs"].values():
            _ref(root, **ref)
        _verify_source_manifest(root, packet["imported_inputs_ref"])
        if file_sha256(Path(packet["source_document_path"])) != packet["voice_source_register"]["source_document_sha256"]:
            raise ValueError("Source document hash changed after import")
        for old in packet["sku_alias"]["original_records"]:
            if file_sha256(Path(old["absolute_path"])) != old["sha256"]:
                raise ValueError("Original production record changed after import")
            if json.loads(Path(old["absolute_path"]).read_text(encoding="utf-8")).get("sku") != packet["sku_alias"]["legacy_sku"]:
                raise ValueError("Historical SKU alias differs from original record")
        for preview in packet["previews"].values():
            _verify_reconstruction(root, preview)
        return {**previous, "status": "replayed"}

    _verify_source_manifest(root, packet["imported_inputs_ref"])
    source_doc = Path(packet["source_document_path"])
    if file_sha256(source_doc) != packet["voice_source_register"]["source_document_sha256"]:
        raise ValueError("Source document hash mismatch")
    voice = copy.deepcopy(packet["voice_source_register"])
    validate_artifact("voice_source_register", attach_hashes(voice))
    source_ids = {item["source_id"] for item in voice["records"]}
    for old in packet["sku_alias"]["original_records"]:
        if file_sha256(Path(old["absolute_path"])) != old["sha256"]:
            raise ValueError("Original production record hash mismatch")
        if json.loads(Path(old["absolute_path"]).read_text(encoding="utf-8")).get("sku") != packet["sku_alias"]["legacy_sku"]:
            raise ValueError("Historical SKU alias differs from original record")
    if packet["sku_alias"]["canonical_sku"] != packet["experiment"]["sku"]:
        raise ValueError("SKU alias does not bind experiment SKU")
    for candidate, preview in packet["previews"].items():
        if preview["candidate_id"] != candidate:
            raise ValueError("Preview candidate identity mismatch")
        _verify_reconstruction(root, preview)
        plan = packet["hooks"][candidate]
        if plan["sku"] != packet["experiment"]["sku"]:
            raise ValueError("Hook plan SKU mismatch")
        if plan["source"].get("kind") in {"document_excerpt", "problem_rewrite"}:
            if plan["source"].get("source_id") not in source_ids:
                raise ValueError("Hook source ID is not registered")
        clean_plan = copy.deepcopy(plan)
        source_id = clean_plan["source"].pop("source_id", None)
        if source_id:
            clean_plan["source"]["record_id"] = source_id
        clean_plan["promise_fulfillment"]["evidence_ref"] = {
            "path": "artifacts/opening-import/body_payoff.pending.json", "sha256": _digest(packet["body_payoff_pending"])}
        validate_artifact("hook_plan", attach_hashes(clean_plan))
        for shot in plan["shots"]:
            _ref(root, **shot["asset_identity"]["source"])
            for image in shot["asset_identity"]["reference_images"]:
                _ref(root, **image)
    # Source IDs are packet metadata; the immutable hook schema itself only
    # accepts kind/status/ref/excerpt/gap. Assert record identity separately.
    experiment = copy.deepcopy(packet["experiment"])
    if experiment.get("status") != "planning" or any(k in experiment for k in ("frozen_body_ref", "budget_ref")):
        raise ValueError("Imported experiment must remain pending baseline/body freeze")
    for key in ("facts_ref", "brand_ref"):
        _ref(root, experiment[key]["path"], experiment[key]["sha256"])
    if read_object(root, experiment["facts_ref"]["path"]).get("sku") != experiment["sku"]:
        raise ValueError("Fact snapshot SKU differs from planned experiment")
    outputs: dict[str, dict[str, str]] = {}
    store = ProjectCommitStore(root)
    with store.transaction(action={"action_id": "opening-preview-import-v1", "type": "legacy_opening_import"},
                           result={"status": "imported", "preview_count": 2},
                           audit={"event_type": "legacy_opening_preview_imported", "actor_id": "migration"},
                           business_diff=["Registered two historical engineering previews as pending pilot evidence."]) as sink:
        def stage(relative: str, name: str, value: dict) -> dict[str, str]:
            attached = attach_hashes(value)
            validate_artifact(name, attached)
            sink.stage_json(relative, attached, schema=name)
            ref = _written_ref(relative, attached)
            outputs[relative] = ref
            return ref

        voice_ref = stage("artifacts/opening-import/voice_source_register.json", "voice_source_register", voice)
        alias = copy.deepcopy(packet["sku_alias"])
        sink.stage_json("artifacts/opening-import/sku_alias.json", alias, schema="opening_import_sku_alias")
        outputs["artifacts/opening-import/sku_alias.json"] = _written_ref("artifacts/opening-import/sku_alias.json", alias)
        payoff = copy.deepcopy(packet["body_payoff_pending"])
        if payoff.get("status") != "planning" or payoff.get("body_frozen") is not False or payoff.get("full_render_ref") is not None:
            raise ValueError("Body payoff planning may not claim an actual frozen film")
        sink.stage_json("artifacts/opening-import/body_payoff.pending.json", payoff, schema="opening_body_payoff_pending")
        payoff_ref = _written_ref("artifacts/opening-import/body_payoff.pending.json", payoff)
        outputs[payoff_ref["path"]] = payoff_ref
        plans = {}
        staged_plans = {}
        for candidate, source in packet["hooks"].items():
            plan = copy.deepcopy(source)
            plan["promise_fulfillment"]["evidence_ref"] = payoff_ref
            plan_source = plan["source"]
            if plan_source["kind"] in {"document_excerpt", "problem_rewrite"}:
                source_id = plan_source.pop("source_id")
                plan_source["record_id"] = source_id
                plan_source["ref" if plan_source["kind"] == "document_excerpt" else "parent_ref"] = voice_ref
                if not any(row["source_id"] == source_id for row in voice["records"]):
                    raise ValueError("Hook source row missing")
            ref = stage(f"artifacts/opening-import/hooks/{candidate}.json", "hook_plan", plan)
            plans[candidate] = {**ref, "version": "2.0"}
            staged_plans[candidate] = plan
        experiment["candidates"] = [{"candidate_id": cid, "hook_plan_ref": plans[cid]} for cid in packet["hooks"]]
        validate_opening_experiment(experiment, hook_plans=staged_plans)
        experiment_ref = stage("artifacts/opening-import/experiment.planning.json", "opening_experiment", experiment)
        index = {"version": "1.0", "items": []}
        for candidate, preview in packet["previews"].items():
            prefix = f"artifacts/opening-import/previews/{candidate}"
            props_ref = stage(prefix + "/final_props.json", "final_props", copy.deepcopy(preview["canonical_props"]))
            report = copy.deepcopy(preview["validation_report"])
            report["render"] = preview["render_ref"]
            report["dependencies"] = {"hook_plan": {k: plans[candidate][k] for k in ("path", "sha256")},
                                      "experiment": experiment_ref, "voice_source_register": voice_ref,
                                      "source_media": preview["source_ref"], **preview["evidence_refs"]}
            validation_ref = stage(prefix + "/opening_validation_report.json", "opening_validation_report", report)
            quality = copy.deepcopy(preview["quality_report"])
            quality["render_sha256"] = preview["render_ref"]["sha256"]
            quality_path = prefix + "/quality_evidence.json"
            sink.stage_json(quality_path, quality, schema="production_quality_evidence")
            outputs[quality_path] = _written_ref(quality_path, quality)
            record = copy.deepcopy(preview["production_record"])
            record["render"] = {**preview["render_ref"], "seconds": 3.0}
            record["quality_report_ref"] = quality_path
            record["canonical_artifacts"] = {"final_props": props_ref["path"],
                "render_input": preview["render_input_ref"]["path"],
                "renderer_snapshot": preview["renderer_snapshot_ref"]["path"],
                "render_result": preview["render_result_ref"]["path"]}
            record["opening"] = {"scope": "preview", "candidate_id": candidate,
                                  "experiment_ref": experiment_ref,
                                  "hook_plan_ref": plans[candidate],
                                  "validation_report_ref": validation_ref}
            record_path = prefix + "/production_record.json"
            stage(record_path, "production_record", record)
            index["items"].append({"id": record["content_slot_id"],
                                   "title": preview["title"], "record_path": record_path})
        sink.stage_json("artifacts/production_review_index.json", index, schema="production_review_index")
        outputs["artifacts/production_review_index.json"] = _written_ref("artifacts/production_review_index.json", index)
        receipt = {"version": "1.0", "packet_sha256": fingerprint,
                   "imported_inputs_ref": packet["imported_inputs_ref"], "outputs": outputs,
                   "status": "pending_review", "preview_count": 2, "new_original_work_count": 0}
        history_path = "artifacts/opening-import/history/first_import_receipt.json"
        if (root / history_path).is_file():
            receipt["reconstruction_history_ref"] = _ref(root, history_path)
        sink.stage_json(RECEIPT, receipt, schema="opening_import_receipt")
    return {**receipt, "status": "imported"}
