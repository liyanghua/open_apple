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


def approved_manifest(project: Path, manifest: dict) -> dict:
    """Build test-only evidence and explicit human approval for these exact bytes."""
    import hashlib
    from backlot.operator_reviews import ReviewService
    from tests.production_evidence_fixture import create_bound_quality
    value = dict(manifest)
    video = project / value["video"]["path"]
    video.parent.mkdir(parents=True, exist_ok=True)
    if not video.exists():
        video.write_bytes(f"fixture-video-{value['version_id']}".encode())
    value["video_master_sha256"] = hashlib.sha256(video.read_bytes()).hexdigest()
    folder = Path("evidence") / value["version_id"]
    (project / folder).mkdir(parents=True, exist_ok=True)
    qa_path = (folder / "quality.json").as_posix()
    record_path = (folder / "production.json").as_posix()
    record = {"content_slot_id": value["version_id"],
              "render": {"path": value["video"]["path"], "sha256": value["video_master_sha256"], "seconds": 4},
              "quality_report_ref": qa_path}
    quality = create_bound_quality(project, record, prefix=(folder / "sources").as_posix())
    (project / qa_path).write_text(json.dumps(quality))
    (project / record_path).write_text(json.dumps(record))
    reviews = ReviewService(project)
    review = reviews.create_final_review(record_path=record_path, submitted_by="fixture-producer")
    reviews.decide(review_id=review["review_id"], decision="approved", actor_id="fixture-reviewer", reason="test fixture review",
                   expected_hash=review["subject_hash"], expected_version=review["subject_version"])
    value.update(production_record_path=record_path, final_review_id=review["review_id"])
    return value


def test_certify_writes_immutable_manifest_and_moves_delivery_pointer_atomically(tmp_path) -> None:
    from backlot.delivery_versions import DeliveryVersionService

    project = _project(tmp_path)
    service = DeliveryVersionService(project)
    manifest = approved_manifest(project, _manifest())
    result = service.certify(manifest, actor_id="operator-a")

    manifest_path = project / "operator/delivery-versions/v1/manifest.json"
    pointer_path = project / "operator/current-delivery.json"
    assert json.loads(manifest_path.read_text()) == manifest
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
    service.certify(approved_manifest(project, _manifest("v1")), actor_id="operator-a")
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
    manifest = approved_manifest(project, _manifest())
    service.certify(manifest, actor_id="operator-a")
    changed = dict(manifest)
    changed["change_summary"] = "尝试覆盖"

    with pytest.raises(OperatorError):
        service.certify(changed, actor_id="operator-a")

    unsafe = _manifest("v2")
    unsafe["video"]["poster_path"] = "inputs/reference/hit.mp4"
    with pytest.raises(OperatorError) as reference:
        service.certify(unsafe, actor_id="operator-a")
    assert reference.value.code == "validation_failed"
    assert service.current()["version_id"] == "v1"


def test_restore_historical_manifest_requires_live_production_evidence(tmp_path):
    import hashlib
    from backlot.delivery_versions import DeliveryVersionService
    from backlot.operator_errors import OperatorError
    project = _project(tmp_path)
    manifest = _manifest()
    video = project / manifest['video']['path']
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b'legacy-film')
    manifest['video_master_sha256'] = hashlib.sha256(video.read_bytes()).hexdigest()
    path = project / 'operator/delivery-versions/v1/manifest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest))
    service = DeliveryVersionService(project)
    assert service.manifest('v1')['version_id'] == 'v1'  # Historical reading stays supported.
    with pytest.raises(OperatorError):
        service.restore('v1', actor_id='operator-a', expected_generation=service.store.initialize()['generation_id'],
                        manifest_sha256=service.manifest_hash('v1'), output_sha256=manifest['video_master_sha256'],
                        idempotency_key='restore-legacy')
    assert service.current() is None


def test_restore_replay_rechecks_live_approval_dependencies(tmp_path):
    from backlot.delivery_versions import DeliveryVersionService
    from backlot.operator_errors import OperatorError
    project = _project(tmp_path)
    manifest = approved_manifest(project, _manifest())
    service = DeliveryVersionService(project)
    service.certify(manifest, actor_id='operator-a')
    arguments = {'actor_id':'operator-a', 'expected_generation':service.store.initialize()['generation_id'],
                 'manifest_sha256':service.manifest_hash('v1'), 'output_sha256':manifest['video_master_sha256'],
                 'idempotency_key':'restore-live-evidence'}
    assert service.restore('v1', **arguments)['status'] == 'restored'
    assert service.restore('v1', **arguments)['status'] == 'restored'
    pointer_before = (project / 'operator/current-delivery.json').read_bytes()
    qa = project / 'evidence/v1/quality.json'
    qa.write_text(qa.read_text() + '\n')
    with pytest.raises(OperatorError):
        service.restore('v1', **arguments)
    assert (project / 'operator/current-delivery.json').read_bytes() == pointer_before
