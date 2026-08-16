from __future__ import annotations

import json
from datetime import datetime, timezone


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
