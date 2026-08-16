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
