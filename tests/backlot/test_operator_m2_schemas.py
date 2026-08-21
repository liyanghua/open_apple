from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "schemas" / "backlot"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / f"{name}.schema.json").read_text(encoding="utf-8"))


def _draft(adapter: str = "script-v1", changes: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "draft_id": "draft-1",
        "project_id": "film",
        "stage": "script",
        "base_revision": "r" * 64,
        "base_artifact_hash": "a" * 64,
        "adapter": adapter,
        "changes": changes or [{
            "op": "replace_section_narration",
            "section_id": "S04",
            "text": "新的旁白",
        }],
        "status": "active",
        "created_by": "user-1",
        "created_at": "2026-08-15T00:00:00Z",
        "updated_at": "2026-08-15T00:01:00Z",
    }


def _impact() -> dict:
    return {
        "schema_version": "1.0",
        "draft_id": "draft-1",
        "valid": True,
        "summary": "将更新 1 句旁白并重新生成声音",
        "changed_fields": [{
            "field": "section.S04.narration",
            "label": "S04 旁白",
            "before": "原文",
            "after": "新文",
        }],
        "affected_stages": ["剧本生成", "制作准备"],
        "affected_scene_ids": ["SC04"],
        "render_mode": "保留画面，仅更新声音",
        "reopen_reviews": ["creative_lock", "sample"],
        "estimated_seconds": 420,
        "estimate_confidence": "low",
        "estimated_cost_usd": 0.06,
        "warnings": [],
        "preview_token": "signed-token",
        "expires_at": "2026-08-15T00:16:00Z",
    }


def _revision() -> dict:
    return {
        "schema_version": "1.0",
        "revision_id": "revision-2",
        "parent_revision_id": "revision-1",
        "project_id": "film",
        "artifact_name": "script",
        "base_semantic_sha256": "b" * 64,
        "result_semantic_sha256": "c" * 64,
        "actor_id": "user-1",
        "reason": "调整尾句节奏",
        "created_at": "2026-08-15T00:02:00Z",
        "snapshot": {"version": "1.0", "sections": []},
        "changes": [{
            "field": "section.S04.narration",
            "label": "S04 旁白",
            "before": "原文",
            "after": "新文",
        }],
    }


def _review() -> dict:
    return {
        "schema_version": "1.0",
        "review_id": "film-creative-lock-v3",
        "project_id": "film",
        "kind": "creative_lock",
        "subject_id": "bundle-1",
        "subject_version": 3,
        "subject_hash": "d" * 64,
        "status": "awaiting_human",
        "submitted_by": "user-1",
        "decided_by": None,
        "reason": None,
        "created_at": "2026-08-15T00:03:00Z",
        "decided_at": None,
    }


def _mutation_result() -> dict:
    return {
        "schema_version": "1.0",
        "action_id": "action-1",
        "result_revision": "e" * 64,
        "status": "committed",
        "links": [{"rel": "project", "href": "/api/v2/projects/film/operator-state"}],
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("operator_draft", _draft()),
        ("impact_preview", _impact()),
        ("operator_revision", _revision()),
        ("operator_review", _review()),
        ("mutation_result", _mutation_result()),
    ],
)
def test_m2_schemas_are_valid_and_accept_minimal_objects(name: str, value: dict) -> None:
    schema = _schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(value, schema)


@pytest.mark.parametrize(
    ("adapter", "stage", "change"),
    [
        ("research-v1", "research", {"op": "set_media_disposition", "media_id": "m1", "disposition": "priority"}),
        ("proposal-v1", "proposal", {"op": "replace_hook", "text": "先测试再下结论"}),
        ("script-v1", "script", {"op": "replace_section_screen_copy", "section_id": "S01", "text": "透明但更耐用"}),
        ("scene-plan-v1", "scene_plan", {"op": "set_source_range", "shot_id": "SC01", "in_seconds": 1.2, "out_seconds": 3.4}),
        ("assets-v1", "assets", {"op": "set_tts", "provider": "doubao", "model": "tts", "voice": "warm", "rate": 1.0}),
        ("sample-v1", "sample", {"op": "add_timecode_comment", "start_seconds": 2.0, "end_seconds": 3.0, "text": "字幕再短一些"}),
    ],
)
def test_draft_schema_binds_typed_operations_to_adapter(
    adapter: str, stage: str, change: dict
) -> None:
    value = _draft(adapter, [change])
    value["stage"] = stage
    jsonschema.validate(value, _schema("operator_draft"))


@pytest.mark.parametrize(
    "change",
    [
        {"op": "replace", "path": "/sections/0/text", "value": "raw patch"},
        {"op": "replace_section_narration", "section_id": "S04", "text": "ok", "path": "/secret"},
        {"op": "unknown_operation", "value": "x"},
    ],
)
def test_draft_schema_rejects_raw_patch_unknown_ops_and_fields(change: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_draft(changes=[change]), _schema("operator_draft"))


@pytest.mark.parametrize(
    ("name", "factory"),
    [
        ("operator_draft", _draft),
        ("impact_preview", _impact),
        ("operator_revision", _revision),
        ("operator_review", _review),
        ("mutation_result", _mutation_result),
    ],
)
def test_m2_schemas_reject_unknown_top_level_fields(name: str, factory) -> None:
    value = factory()
    value["raw_payload"] = {"path": "/Users/secret"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, _schema(name))


def test_review_schema_rejects_unknown_status() -> None:
    value = _review()
    value["status"] = "expired"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, _schema("operator_review"))


def test_operator_error_uses_fixed_safe_public_shape() -> None:
    from backlot.operator_errors import OperatorError

    error = OperatorError.validation_failed(
        "提交内容不符合要求",
        field_errors=[{"field": "script.S04", "message": "旁白不能为空"}],
    )

    assert error.status_code == 422
    assert error.to_public_dict() == {
        "error": {
            "code": "validation_failed",
            "message": "提交内容不符合要求",
            "field_errors": [{"field": "script.S04", "message": "旁白不能为空"}],
        }
    }
    with pytest.raises(ValueError):
        OperatorError("validation_failed", "/Users/private/traceback", 422)
