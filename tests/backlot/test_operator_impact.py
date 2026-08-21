from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


def _draft(text="新钩子"):
    return {
        "schema_version": "1.0", "draft_id": "draft-1", "project_id": "demo",
        "stage": "proposal", "base_revision": "r" * 64,
        "base_artifact_hash": "a" * 64, "adapter": "proposal-v1",
        "changes": [{"op": "replace_hook", "text": text}], "status": "active",
        "created_by": "user-a", "created_at": "2026-08-15T00:00:00+00:00",
        "updated_at": "2026-08-15T00:00:00+00:00",
    }


def test_preview_is_pure_schema_valid_and_unknown_estimates_are_null(tmp_path) -> None:
    import json
    from backlot.operator_impact import ImpactService

    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    service = ImpactService(secret=b"test-secret", clock=lambda: now)
    preview = service.preview(
        draft=_draft(), actor_id="user-a", base_generation="generation-000001",
        before={"hook": "旧钩子"}, after={"hook": "新钩子"},
    )
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/backlot/impact_preview.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(preview)
    assert preview["estimated_seconds"] is None
    assert preview["estimated_cost_usd"] is None
    assert preview["render_mode"] == "重新生成完整画面"
    assert list(tmp_path.iterdir()) == []


def test_preview_token_binds_content_actor_generation_and_expiry() -> None:
    from backlot.operator_errors import OperatorError
    from backlot.operator_impact import ImpactService

    now = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
    service = ImpactService(secret=b"test-secret", clock=lambda: now[0], ttl_seconds=900)
    draft = _draft()
    preview = service.preview(
        draft=draft, actor_id="user-a", base_generation="generation-000001",
        before={"hook": "旧"}, after={"hook": "新"},
    )
    assert service.verify_token(
        preview["preview_token"], draft=draft, actor_id="user-a",
        base_generation="generation-000001",
    )
    invalid_cases = [
        (_draft("又变了"), "user-a", "generation-000001"),
        (draft, "user-b", "generation-000001"),
        (draft, "user-a", "generation-000002"),
    ]
    for changed, actor, generation in invalid_cases:
        with pytest.raises(OperatorError) as failure:
            service.verify_token(preview["preview_token"], draft=changed, actor_id=actor, base_generation=generation)
        assert failure.value.code == "revision_conflict"
    now[0] += timedelta(seconds=901)
    with pytest.raises(OperatorError):
        service.verify_token(preview["preview_token"], draft=draft, actor_id="user-a", base_generation="generation-000001")


def test_delivery_preview_uses_business_labels_and_copy_values() -> None:
    from backlot.operator_adapters import get_adapter
    from backlot.operator_impact import ImpactService

    changes = [
        {"op": "select_delivery_candidate", "candidate_kind": "hook", "candidate_id": "hook-current"},
        {"op": "replace_delivery_copy", "section_id": "s01", "text": "新的完整文案", "sync_narration": False},
    ]
    draft = {
        "schema_version": "1.0", "draft_id": "draft-delivery", "project_id": "demo",
        "stage": "delivery_review", "base_revision": "r" * 64,
        "base_artifact_hash": "a" * 64, "adapter": "delivery-review-v1",
        "changes": changes, "status": "active", "created_by": "user-a",
        "created_at": "2026-08-19T00:00:00+00:00", "updated_at": "2026-08-19T00:00:00+00:00",
    }
    before = {"selected_hook_id": None, "copy_overrides": []}
    after = get_adapter("delivery_review").apply(before, changes)

    preview = ImpactService(secret=b"test-secret").preview(
        draft=draft, actor_id="user-a", base_generation="generation-000001",
        before=before, after=after,
    )
    fields = {item["field"]: item for item in preview["changed_fields"]}

    assert fields["selected_hook_id"]["label"] == "前三秒"
    assert fields["copy_overrides.s01"]["label"] == "文案"
    assert fields["copy_overrides.s01"]["before"] is None
    assert fields["copy_overrides.s01"]["after"] == "新的完整文案"


def test_research_decisions_explain_their_downstream_stages() -> None:
    from backlot.operator_impact import ImpactService

    draft = {
        "schema_version": "1.0", "draft_id": "research-draft", "project_id": "project",
        "stage": "research", "base_revision": "a" * 64, "base_artifact_hash": "b" * 64,
        "adapter": "research-v1", "status": "active", "created_by": "operator",
        "created_at": "2026-08-20T00:00:00+00:00", "updated_at": "2026-08-20T00:00:00+00:00",
        "changes": [{
            "op": "resolve_matrix_row", "matrix_row_id": "rebound", "resolution": "rewrite",
            "source_media_id": None, "note": "改成柔韧不易变形",
        }],
    }
    preview = ImpactService(secret=b"research-impact-preview").preview(
        draft=draft, actor_id="operator", base_generation="c" * 64,
        before={}, after={"matrix_resolutions": {"rebound": {"resolution": "rewrite"}}},
    )
    assert preview["affected_stages"] == ["参考解析与素材体检", "创意方案", "口播与字幕", "分镜"]
