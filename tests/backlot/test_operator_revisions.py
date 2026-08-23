from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest


RESEARCH_HASH = "b" * 64


def _setup(tmp_path):
    from backlot.operator_drafts import DraftService
    from backlot.operator_impact import ImpactService
    from backlot.project_commit import ProjectCommitStore

    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")
    before = {"hook": "旧钩子", "cta": "了解更多"}
    (project / "artifacts/proposal_packet.json").write_text(json.dumps(before), encoding="utf-8")
    store = ProjectCommitStore(project)
    pointer = store.initialize()
    draft = DraftService(project).save(
        actor_id="user-a", stage="proposal", base_revision="r" * 64,
        base_artifact_hash="a" * 64,
        changes=[{"op": "replace_hook", "text": "新钩子"}],
    )
    after = {"hook": "新钩子", "cta": "了解更多"}
    impact = ImpactService(secret=b"revision-secret", clock=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc))
    preview = impact.preview(
        draft=draft, actor_id="user-a", base_generation=pointer["generation_id"],
        before=before, after=after,
    )
    return project, store, draft, before, after, impact, preview, pointer


def _research_commit(
    project,
    *,
    changes,
    base_snapshot,
    reason="更新研究决定",
):
    from backlot.operator_adapters import get_adapter
    from backlot.operator_drafts import DraftService
    from backlot.operator_impact import ImpactService
    from backlot.operator_revisions import RevisionService
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_hashing import semantic_sha256

    store = ProjectCommitStore(project)
    pointer = store.initialize()
    draft = DraftService(project).save(
        actor_id="user-a",
        stage="research",
        base_revision=RESEARCH_HASH,
        base_artifact_hash=semantic_sha256(base_snapshot),
        changes=changes,
    )
    impact = ImpactService(
        secret=b"research-revision-secret",
        clock=lambda: datetime(2026, 8, 19, tzinfo=timezone.utc),
    )
    preview = impact.preview(
        draft=draft,
        actor_id="user-a",
        base_generation=pointer["generation_id"],
        before=base_snapshot,
        after=get_adapter("research").apply(base_snapshot, changes),
    )
    return RevisionService(
        project,
        store=store,
        clock=lambda: datetime(2026, 8, 19, 8, 30, tzinfo=timezone.utc),
    ).commit_draft(
        draft=draft,
        actor_id="user-a",
        reason=reason,
        preview_token=preview["preview_token"],
        impact_service=impact,
        base_generation=pointer["generation_id"],
        base_snapshot=base_snapshot,
    )


def test_commit_draft_is_append_only_and_atomic(tmp_path) -> None:
    from backlot.operator_revisions import RevisionService

    project, store, draft, before, _after, impact, preview, pointer = _setup(tmp_path)
    service = RevisionService(project, store=store)
    revision = service.commit_draft(
        draft=draft, actor_id="user-a", reason="强化前三秒钩子",
        preview_token=preview["preview_token"], impact_service=impact,
        base_generation=pointer["generation_id"], base_snapshot=before,
    )
    assert json.loads((project / "artifacts/proposal_packet.json").read_text())["hook"] == "新钩子"
    assert revision["parent_revision_id"] is None
    assert revision["changes"] == [{
        "field": "hook", "label": "开头钩子已调整",
        "before": "旧钩子", "after": "新钩子",
    }]
    assert service.list("proposal")[0]["revision_id"] == revision["revision_id"]
    current = json.loads((project / "operator/current-generation.json").read_text())
    manifest = json.loads((project / "operator/generations" / current["generation_id"] / "manifest.json").read_text())
    assert manifest["draft_transition"] == {"draft_id": draft["draft_id"], "status": "committed"}
    assert {item["relative_path"] for item in manifest["write_set"]} >= {
        "artifacts/proposal_packet.json", f"operator/revisions/proposal/000001-{revision['revision_id']}.json"
    }


def test_compare_and_restore_prepare_do_not_expose_structural_diff(tmp_path) -> None:
    from backlot.operator_revisions import RevisionService

    project, store, draft, before, _after, impact, preview, pointer = _setup(tmp_path)
    service = RevisionService(project, store=store)
    first = service.commit_draft(
        draft=draft, actor_id="user-a", reason="修改钩子",
        preview_token=preview["preview_token"], impact_service=impact,
        base_generation=pointer["generation_id"], base_snapshot=before,
    )
    comparison = service.compare("proposal", None, first["revision_id"], base_snapshot=before)
    assert comparison == ["开头钩子已调整"]
    pointer_before = (project / "operator/current-generation.json").read_bytes()
    restore = service.prepare_restore("proposal", first["revision_id"], actor_id="user-a")
    assert restore["requires_impact_preview"] is True
    assert restore["snapshot"]["hook"] == "新钩子"
    assert (project / "operator/current-generation.json").read_bytes() == pointer_before


def test_restore_appends_new_revision_instead_of_overwriting_history(tmp_path) -> None:
    from backlot.operator_revisions import RevisionService

    project, store, draft, before, _after, impact, preview, pointer = _setup(tmp_path)
    service = RevisionService(project, store=store)
    first = service.commit_draft(
        draft=draft, actor_id="user-a", reason="修改钩子",
        preview_token=preview["preview_token"], impact_service=impact,
        base_generation=pointer["generation_id"], base_snapshot=before,
    )
    restored = service.commit_restore(
        stage="proposal", revision_id=first["revision_id"], actor_id="user-a",
        reason="恢复已确认版本", current_snapshot=before,
        idempotency_key="restore-one", request_digest="d" * 64,
    )
    assert restored["revision_id"] != first["revision_id"]
    assert restored["parent_revision_id"] == first["revision_id"]
    assert len(service.list("proposal")) == 2
    assert json.loads((project / "artifacts/proposal_packet.json").read_text())["hook"] == "新钩子"


def test_research_commit_persists_schema_valid_hashed_artifact(tmp_path) -> None:
    from lib.artifact_hashing import verify_hashes
    from schemas.artifacts import validate_artifact

    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")

    revision = _research_commit(
        project,
        base_snapshot={},
        changes=[
            {"op": "set_media_disposition", "media_id": "m1", "disposition": "priority"},
        ],
    )

    artifact = json.loads(
        (project / "artifacts/research_annotations.json").read_text(encoding="utf-8")
    )
    validate_artifact("research_annotations", artifact)
    assert verify_hashes(artifact).valid is True
    assert artifact["revision_id"] == revision["revision_id"]
    assert artifact["base_research_revision"] == RESEARCH_HASH
    assert artifact["project_id"] == "demo"
    assert artifact["producer"] == "backlot.operator_revisions"


def test_research_commit_keeps_completed_research_checkpoint(tmp_path) -> None:
    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")
    checkpoint = {
        "stage": "research", "status": "completed",
        "artifacts": {"research_brief": {"summary": "已完成"}},
    }
    (project / "checkpoint_research.json").write_text(
        json.dumps(checkpoint), encoding="utf-8"
    )

    _research_commit(
        project,
        base_snapshot={},
        changes=[
            {"op": "set_direction_preference", "direction_id": "direction-1", "preference": "prefer", "rationale": "采用"},
        ],
    )

    assert json.loads((project / "checkpoint_research.json").read_text(encoding="utf-8")) == checkpoint


def test_second_research_edit_preserves_old_and_new_annotation_collections(tmp_path) -> None:
    from schemas.artifacts import validate_artifact

    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")

    _research_commit(
        project,
        base_snapshot={},
        changes=[
            {"op": "set_media_disposition", "media_id": "m1", "disposition": "priority"},
            {"op": "set_logo_usage", "media_id": "m1", "allowed": True},
            {"op": "set_claim_boundary", "claim_id": "claim-1", "text": "仅限演示场景"},
            {"op": "set_reference_method", "method_id": "proof-pair", "selected": True},
        ],
    )
    first = json.loads(
        (project / "artifacts/research_annotations.json").read_text(encoding="utf-8")
    )
    _research_commit(
        project,
        base_snapshot=first,
        changes=[
            {
                "op": "set_direction_preference",
                "direction_id": "direction-1",
                "preference": "prefer",
                "rationale": "更符合自有素材",
            },
            {
                "op": "resolve_matrix_row",
                "matrix_row_id": "matrix-1",
                "resolution": "accept",
                "source_media_id": "m1",
                "note": "采用现有证明镜头",
            },
        ],
    )

    artifact = json.loads(
        (project / "artifacts/research_annotations.json").read_text(encoding="utf-8")
    )
    validate_artifact("research_annotations", artifact)
    assert artifact["media_dispositions"] == {"m1": "priority"}
    assert artifact["logo_usage"] == {"m1": True}
    assert artifact["claim_boundaries"] == {"claim-1": "仅限演示场景"}
    assert artifact["reference_methods"] == {"proof-pair": True}
    assert artifact["direction_preferences"]["direction-1"]["preference"] == "prefer"
    assert artifact["matrix_resolutions"]["matrix-1"]["source_media_id"] == "m1"


def test_research_restore_rebuilds_artifact_revision_provenance(tmp_path) -> None:
    from backlot.operator_revisions import RevisionService
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_hashing import verify_hashes
    from schemas.artifacts import validate_artifact

    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")
    first = _research_commit(
        project,
        base_snapshot={},
        changes=[
            {"op": "set_media_disposition", "media_id": "m1", "disposition": "priority"},
        ],
    )
    first_artifact = json.loads(
        (project / "artifacts/research_annotations.json").read_text(encoding="utf-8")
    )
    _research_commit(
        project,
        base_snapshot=first_artifact,
        changes=[
            {"op": "set_media_disposition", "media_id": "m1", "disposition": "unused"},
        ],
    )
    current = json.loads(
        (project / "artifacts/research_annotations.json").read_text(encoding="utf-8")
    )
    store = ProjectCommitStore(project)
    restored = RevisionService(
        project,
        store=store,
        clock=lambda: datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
    ).commit_restore(
        stage="research",
        revision_id=first["revision_id"],
        actor_id="user-a",
        reason="恢复首版研究决定",
        current_snapshot=current,
        idempotency_key="restore-research-one",
        request_digest="d" * 64,
        expected_generation=store.initialize()["generation_id"],
    )

    artifact = json.loads(
        (project / "artifacts/research_annotations.json").read_text(encoding="utf-8")
    )
    validate_artifact("research_annotations", artifact)
    assert verify_hashes(artifact).valid is True
    assert artifact["revision_id"] == restored["revision_id"]
    assert restored["snapshot"]["revision_id"] == restored["revision_id"]
    assert artifact["revision_id"] != first["snapshot"]["revision_id"]
    assert artifact["created_at"] == "2026-08-20T09:00:00+00:00"
    assert artifact["producer"] == "backlot.operator_revisions"
    assert artifact["base_research_revision"] == first_artifact["base_research_revision"]
    assert artifact["media_dispositions"] == {"m1": "priority"}


def test_research_commit_reports_malformed_legacy_annotations_as_operator_error(tmp_path) -> None:
    from backlot.operator_errors import OperatorError

    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")
    malformed = {
        "base_research_revision": RESEARCH_HASH,
        "logo_usage": {"m1": "yes"},
        "business_notes": {},
    }

    with pytest.raises(OperatorError) as failure:
        _research_commit(
            project,
            base_snapshot=malformed,
            changes=[
                {"op": "set_business_note", "target_id": "m1", "text": "保留"},
            ],
        )

    assert failure.value.code == "validation_failed"
    assert failure.value.status_code == 422


def test_unknown_stage_raises_not_found_instead_of_key_error(tmp_path) -> None:
    """批级 rail 相位（如 sampling）不是可编辑阶段：404 not_found，绝不 500 KeyError。"""
    from backlot.operator_errors import OperatorError
    from backlot.operator_revisions import RevisionService
    from backlot.project_commit import ProjectCommitStore

    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")
    ProjectCommitStore(project).initialize()
    service = RevisionService(project)

    for stage in ("sampling", "building", "selection", "unknown-stage"):
        with pytest.raises(OperatorError) as failure:
            service.list(stage)
        assert failure.value.code == "not_found"
        assert failure.value.status_code == 404


def test_known_stages_still_resolve_revision_dirs(tmp_path) -> None:
    from backlot.operator_revisions import RevisionService
    from backlot.project_commit import ProjectCommitStore

    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")
    ProjectCommitStore(project).initialize()
    service = RevisionService(project)
    for stage in ("proposal", "script", "assets", "sample"):
        assert service._revision_dir(stage) == project / "operator" / "revisions" / stage
