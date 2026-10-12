"""Version and permission boundaries for paid dynamic-opening pilots."""

import hashlib
import json
from pathlib import Path

import pytest

from lib.dynamic_hook_pilot import PilotEvidenceError, validate_generation_gate, validate_preview_evidence


def _write(root: Path, name: str, value: object) -> dict[str, str]:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
               if isinstance(value, (dict, list)) else bytes(value))
    target.write_bytes(payload)
    return {"path": name, "sha256": hashlib.sha256(payload).hexdigest()}


def _pilot(tmp_path: Path) -> dict:
    root = tmp_path
    reference = _write(root, "assets/reference/towel.png", b"approved-blue-towel")
    approval = _write(root, "artifacts/approval.json", {
        "approved_by": "human", "status": "approved_for_pilot_hook_sources",
        "scope": ["slot-a"], "max_paid_submissions": 1, "final_film_approval": False,
    })
    lock = _write(root, "artifacts/lock.json", {
        "status": "locked_for_pilot_source_generation", "approval_ref": approval["path"],
        "approval_sha256": approval["sha256"], "scope": ["slot-a"], "max_paid_submissions": 1,
        "tool": "seedance_ark", "provider": "ark", "model": "selected-model",
        "model_variant": "selected-variant", "operation": "reference_to_video",
        "source_duration_seconds": 4, "source_resolution": "720p", "source_ratio": "9:16",
        "generate_audio": False, "reference_images": [reference],
    })
    source = _write(root, "assets/video/new.mp4", b"moving-towel")
    ledger = _write(root, "artifacts/cost.json", {"entries": [{
        "id": "reservation-1", "idempotency_key": "pilot:slot-a:1",
        "tool": "seedance_ark", "operation": "reference_to_video", "status": "reserved",
    }]})
    inputs = _write(root, "artifacts/inputs.json", {
        "model": "selected-model", "model_variant": "selected-variant",
        "operation": "reference_to_video", "duration": 4, "resolution": "720p",
        "aspect_ratio": "9:16", "generate_audio": False, "task_action": "generate",
        "idempotency_key": "pilot:slot-a:1", "reservation_id": "reservation-1",
        "cost_log_path": str(root / ledger["path"]), "task_journal_path": "artifacts/tasks.json",
        "reference_image_paths": [str(root / reference["path"])],
        "output_path": str(root / source["path"]),
    })
    generation = _write(root, "artifacts/generation.json", {
        "success": True, "data": {"task_id": "remote-task-1", "model": "selected-model",
                               "provider": "ark", "operation": "reference_to_video",
                               "output_path": str(root / source["path"]),
                               "catalog_estimate": {"amount": 6.111}, "actual_cost": None},
    })
    preview = _write(root, "renders/preview.mp4", b"three-second-towel-opening")
    props_value = {
        "opening": {"scope": "preview"}, "durationInFrames": 90, "fps": 30,
        "width": 1080, "height": 1920, "footage": {"main": source["path"]},
        "scenes": [{"footageKey": "main", "asset_sha256": source["sha256"]}],
    }
    props = _write(root, "artifacts/props.json", props_value)
    render_inputs = _write(root, "artifacts/render-inputs.json", {"edit_decisions": props_value})
    renderer_props = _write(root, "artifacts/renderer-props.json",
                            {**props_value, "render_input_refs": [source]})
    render = _write(root, "artifacts/render.json", {
        "success": True, "data": {"output": str(root / preview["path"]),
                                  "renderer_props_ref": renderer_props},
    })
    technical = _write(root, "artifacts/technical.json", {
        "scope": "preview", "subject_hash": preview["sha256"],
        "media_sha256": preview["sha256"], "status": "revise",
    })
    return {"approval_ref": approval, "lock_ref": lock, "items": [{
        "slot_id": "slot-a", "generation_inputs_ref": inputs,
        "generation_result_ref": generation, "source_ref": source,
        "preview_props_ref": props, "render_inputs_ref": render_inputs, "preview_ref": preview,
        "render_result_ref": render, "technical_ref": technical,
    }]}


def test_completed_pilot_preserves_incomplete_technical_status(tmp_path):
    packet = _pilot(tmp_path)
    result = validate_preview_evidence(tmp_path, packet)
    assert result["status"] == "ready_for_preview_review"
    assert result["items"][0]["technical_status"] == "revise"
    assert result["items"][0]["actual_settlement"] is None
    assert result["final_film_approved"] is False


def test_generation_gate_rejects_unapproved_or_duplicate_paid_scope(tmp_path):
    packet = _pilot(tmp_path)
    packet["items"][0]["slot_id"] = "slot-b"
    with pytest.raises(PilotEvidenceError, match="approved scope"):
        validate_generation_gate(tmp_path, packet)


def test_generation_gate_accepts_reserved_unsubmitted_attempt(tmp_path):
    packet = _pilot(tmp_path)
    ledger = tmp_path / "artifacts/cost.json"
    data = json.loads(ledger.read_text())
    data["entries"][0].pop("idempotency_key")
    data["entries"][0]["submission_status"] = "not_submitted"
    ledger.write_text(json.dumps(data))
    assert validate_generation_gate(tmp_path, packet)["status"] == "ready"

    data["entries"][0]["provider_task_id"] = "already-submitted"
    ledger.write_text(json.dumps(data))
    with pytest.raises(PilotEvidenceError, match="paid reservation differs"):
        validate_generation_gate(tmp_path, packet)


def test_generation_gate_rejects_wrong_bound_idempotency_key(tmp_path):
    packet = _pilot(tmp_path)
    ledger = tmp_path / "artifacts/cost.json"
    data = json.loads(ledger.read_text())
    data["entries"][0]["idempotency_key"] = "another-attempt"
    ledger.write_text(json.dumps(data))
    with pytest.raises(PilotEvidenceError, match="paid reservation differs"):
        validate_generation_gate(tmp_path, packet)
    packet["items"][0]["slot_id"] = "slot-a"
    packet["items"].append(dict(packet["items"][0]))
    with pytest.raises(PilotEvidenceError, match="approved scope"):
        validate_generation_gate(tmp_path, packet)


def test_changed_reference_or_stale_render_cannot_be_reviewed(tmp_path):
    packet = _pilot(tmp_path)
    (tmp_path / "assets/reference/towel.png").write_bytes(b"another-product")
    with pytest.raises(PilotEvidenceError, match="Changed pilot media"):
        validate_generation_gate(tmp_path, packet)
    packet = _pilot(tmp_path)
    (tmp_path / "renders/preview.mp4").write_bytes(b"changed-after-check")
    with pytest.raises(PilotEvidenceError, match="Changed pilot media"):
        validate_preview_evidence(tmp_path, packet)


def test_existing_extra_paid_attempt_blocks_a_new_submission(tmp_path):
    packet = _pilot(tmp_path)
    ledger = tmp_path / "artifacts/cost.json"
    data = json.loads(ledger.read_text())
    data["entries"].append({"id": "reservation-2", "idempotency_key": "new-paid-key",
                            "tool": "seedance_ark", "operation": "reference_to_video"})
    ledger.write_text(json.dumps(data))
    with pytest.raises(PilotEvidenceError, match="approved paid-submission count"):
        validate_generation_gate(tmp_path, packet)
