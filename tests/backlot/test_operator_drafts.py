from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "demo"
    path.mkdir()
    (path / "project.json").write_text('{"project_id":"demo"}', encoding="utf-8")
    return path


def test_one_active_draft_per_user_stage_and_user_isolation(project) -> None:
    from backlot.operator_drafts import DraftService

    service = DraftService(project)
    first = service.save(
        actor_id="user-a", stage="proposal", base_revision="r" * 64,
        base_artifact_hash="a" * 64,
        changes=[{"op": "replace_hook", "text": "第一次"}],
    )
    updated = service.save(
        actor_id="user-a", stage="proposal", base_revision="r" * 64,
        base_artifact_hash="a" * 64,
        changes=[{"op": "replace_hook", "text": "第二次"}],
    )
    other = service.save(
        actor_id="user-b", stage="proposal", base_revision="r" * 64,
        base_artifact_hash="a" * 64,
        changes=[{"op": "replace_hook", "text": "另一用户"}],
    )
    assert updated["draft_id"] == first["draft_id"]
    assert other["draft_id"] != first["draft_id"]
    assert service.load("user-a", "proposal")["changes"][0]["text"] == "第二次"
    assert service.discard("user-a", "proposal")["status"] == "discarded"


def test_rebase_requires_new_preview_and_reports_field_conflicts(project) -> None:
    from backlot.operator_drafts import DraftService
    from backlot.operator_errors import OperatorError

    service = DraftService(project)
    draft = service.save(
        actor_id="user-a", stage="proposal", base_revision="r" * 64,
        base_artifact_hash="a" * 64,
        changes=[{"op": "replace_hook", "text": "我的钩子"}],
    )
    rebased = service.rebase(
        draft,
        current_revision="1" * 64,
        current_artifact_hash="b" * 64,
        base_snapshot={"hook": "旧", "cta": "旧 CTA"},
        current_snapshot={"hook": "旧", "cta": "新 CTA"},
    )
    assert rebased["status"] == "active"
    assert rebased["base_revision"] == "1" * 64
    assert rebased["preview_required"] is True

    with pytest.raises(OperatorError) as conflict:
        service.rebase(
            draft,
            current_revision="2" * 64,
            current_artifact_hash="c" * 64,
            base_snapshot={"hook": "旧"},
            current_snapshot={"hook": "别人改过"},
        )
    assert conflict.value.code == "revision_conflict"
    assert conflict.value.field_errors[0]["field"] == "hook"


def test_research_rebase_detects_conflict_on_same_annotation_collection_entry(project) -> None:
    from backlot.operator_drafts import DraftService
    from backlot.operator_errors import OperatorError

    service = DraftService(project)
    draft = service.save(
        actor_id="user-a",
        stage="research",
        base_revision="r" * 64,
        base_artifact_hash="a" * 64,
        changes=[
            {"op": "set_media_disposition", "media_id": "m1", "disposition": "priority"},
        ],
    )

    with pytest.raises(OperatorError) as conflict:
        service.rebase(
            draft,
            current_revision="1" * 64,
            current_artifact_hash="b" * 64,
            base_snapshot={"media_dispositions": {"m1": "usable"}},
            current_snapshot={"media_dispositions": {"m1": "unused"}},
        )

    assert conflict.value.code == "revision_conflict"
    assert conflict.value.field_errors == [{
        "field": "media_dispositions.m1",
        "message": "该字段与你的草稿同时发生了变化",
    }]


def test_terminal_status_projects_from_committed_generation(project) -> None:
    import json

    from backlot.operator_drafts import DraftService
    from backlot.project_commit import ProjectCommitStore

    store = ProjectCommitStore(project)
    store.initialize()
    service = DraftService(project)
    draft = service.save(
        actor_id="user-a", stage="proposal", base_revision="r" * 64,
        base_artifact_hash="a" * 64, changes=[],
    )
    with store.transaction(
        action={"action_id": "commit-draft"},
        draft_transition={"draft_id": draft["draft_id"], "status": "committed"},
    ):
        pass
    assert service.load("user-a", "proposal")["status"] == "committed"
