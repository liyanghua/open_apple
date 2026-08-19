from __future__ import annotations

import json
from datetime import datetime, timezone


def test_delivery_review_commit_preserves_compose_and_queues_generation(tmp_path) -> None:
    from backlot.delivery_review_revisions import DeliveryReviewRevisionService
    from backlot.delivery_versions import DeliveryVersionService
    from backlot.operator_drafts import DraftService
    from backlot.operator_impact import ImpactService
    from backlot.project_commit import ProjectCommitStore

    project = tmp_path / "film"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({
        "project_id": "film", "created_at": "2026-08-19T00:00:00Z",
    }))
    (project / "artifacts/render_report.json").write_text(json.dumps({
        "outputs": [{"path": "renders/final-v1.mp4", "duration_seconds": 30}],
        "video_master_sha256": "a" * 64,
    }))
    checkpoint = b'{"stage":"compose","status":"completed"}'
    (project / "checkpoint_compose.json").write_bytes(checkpoint)
    DeliveryVersionService(project).certify({
        "schema_version": "1.0", "project_id": "film", "version_id": "v1",
        "created_at": "2026-08-19T00:00:00Z", "review_revision_id": None,
        "video": {"path": "renders/final-v1.mp4", "poster_path": None, "subtitles_path": None},
        "audio_mix": {}, "qa": {"status": "pass", "issues": []},
        "change_summary": "首个认证版本", "video_master_sha256": "a" * 64,
    }, actor_id="system")
    current_before = (project / "operator/current-delivery.json").read_bytes()
    store = ProjectCommitStore(project)
    pointer = store.initialize()
    before = DeliveryReviewRevisionService(project).load_snapshot()
    draft = DraftService(project).save(
        actor_id="operator-a", stage="delivery_review", base_revision="r" * 64,
        base_artifact_hash="b" * 64,
        changes=[{
            "op": "replace_delivery_copy", "section_id": "sentence-1",
            "text": "新的完整文案", "sync_narration": False,
        }],
    )
    impact = ImpactService(
        secret=b"delivery-review-secret",
        clock=lambda: datetime(2026, 8, 19, tzinfo=timezone.utc),
    )
    after = DeliveryReviewRevisionService(project).adapter.apply(before, draft["changes"])
    preview = impact.preview(
        draft=draft, actor_id="operator-a", base_generation=pointer["generation_id"],
        before=before, after=after,
    )

    revision = DeliveryReviewRevisionService(project).commit(
        draft=draft, actor_id="operator-a", reason="调整成片文案",
        preview_token=preview["preview_token"], impact_service=impact,
        base_generation=pointer["generation_id"], base_snapshot=before,
    )

    assert revision["artifact_name"] == "delivery_review"
    assert (project / "checkpoint_compose.json").read_bytes() == checkpoint
    assert (project / "operator/current-delivery.json").read_bytes() == current_before
    artifact = json.loads((project / "artifacts/delivery_review.json").read_text())
    assert artifact["copy_overrides"] == [{
        "segment_id": "sentence-1", "text": "新的完整文案", "sync_narration": False,
    }]
    events = [json.loads(line) for line in (project / "operator/actions.jsonl").read_text().splitlines()]
    assert events[-1]["event_type"] == "delivery_generation_requested"
    assert events[-1]["review_revision_id"] == revision["revision_id"]
