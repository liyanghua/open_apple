from __future__ import annotations

import json
from pathlib import Path

import pytest


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "film"
    project.mkdir()
    (project / "project.json").write_text(
        json.dumps({"project_id": "film"}), encoding="utf-8"
    )
    return project


def _manifest(version_id: str = "v1", *, qa_status: str = "pass") -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "film",
        "version_id": version_id,
        "created_at": "2026-08-19T12:00:00Z",
        "review_revision_id": "rev-review-1",
        "video": {
            "path": f"renders/final-{version_id}.mp4",
            "poster_path": f"renders/poster-{version_id}.jpg",
            "subtitles_path": "assets/subtitles.srt",
        },
        "audio_mix": {"bgm_id": "music-main", "narration_enabled": True},
        "qa": {"status": qa_status, "issues": []},
        "change_summary": "调整前三秒并保留当前结尾",
        "video_master_sha256": "a" * 64,
    }


def test_certify_writes_immutable_manifest_and_moves_delivery_pointer_atomically(tmp_path) -> None:
    from backlot.delivery_versions import DeliveryVersionService

    project = _project(tmp_path)
    service = DeliveryVersionService(project)
    result = service.certify(_manifest(), actor_id="operator-a")

    manifest_path = project / "operator/delivery-versions/v1/manifest.json"
    pointer_path = project / "operator/current-delivery.json"
    assert json.loads(manifest_path.read_text()) == _manifest()
    assert json.loads(pointer_path.read_text()) == {
        "schema_version": "1.0",
        "project_id": "film",
        "version_id": "v1",
        "manifest_sha256": result["manifest_sha256"],
    }
    assert service.list()[0]["version_id"] == "v1"
    assert service.current()["version_id"] == "v1"


def test_failed_qa_never_moves_current_delivery_pointer(tmp_path) -> None:
    from backlot.delivery_versions import DeliveryVersionService
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = DeliveryVersionService(project)
    service.certify(_manifest("v1"), actor_id="operator-a")
    pointer_before = (project / "operator/current-delivery.json").read_bytes()

    with pytest.raises(OperatorError) as failed:
        service.certify(_manifest("v2", qa_status="fail"), actor_id="operator-a")

    assert failed.value.code == "validation_failed"
    assert (project / "operator/current-delivery.json").read_bytes() == pointer_before
    assert not (project / "operator/delivery-versions/v2").exists()


def test_certified_version_is_immutable_and_reference_media_is_rejected(tmp_path) -> None:
    from backlot.delivery_versions import DeliveryVersionService
    from backlot.operator_errors import OperatorError

    project = _project(tmp_path)
    service = DeliveryVersionService(project)
    service.certify(_manifest(), actor_id="operator-a")
    changed = _manifest()
    changed["change_summary"] = "尝试覆盖"

    with pytest.raises(OperatorError):
        service.certify(changed, actor_id="operator-a")

    unsafe = _manifest("v2")
    unsafe["video"]["poster_path"] = "inputs/reference/hit.mp4"
    with pytest.raises(OperatorError) as reference:
        service.certify(unsafe, actor_id="operator-a")
    assert reference.value.code == "validation_failed"
    assert service.current()["version_id"] == "v1"
