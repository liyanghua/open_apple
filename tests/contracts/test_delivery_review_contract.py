from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from lib.checkpoint import (
    SUPPLEMENTARY_ARTIFACTS,
    CheckpointValidationError,
    validate_checkpoint,
)
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact
from tests.backlot.test_operator_m2_schemas import _draft
from tests.backlot.test_operator_state_schema import minimal_operator_state


ROOT = Path(__file__).resolve().parents[2]


def _delivery_review() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "table-mat-mix-v6",
        "base_render_id": "render-v1",
        "base_version_id": "v1",
        "selected_cover_id": "cover-02",
        "selected_hook_id": "hook-01",
        "selected_bgm_id": None,
        "selected_ending_id": "ending-02",
        "copy_overrides": [
            {
                "segment_id": "sentence-01",
                "text": "透明桌垫，一擦就净",
                "sync_narration": True,
            }
        ],
        "updated_by": "operator-id",
        "updated_at": "2026-08-19T10:00:00Z",
    }


def _compose_checkpoint(*, include_delivery_review: bool) -> dict:
    artifacts = {
        "render_report": {
            "version": "1.0",
            "outputs": [
                {
                    "path": "renders/final.mp4",
                    "format": "mp4",
                    "resolution": "1080x1920",
                    "duration_seconds": 30,
                }
            ],
        },
        "final_review": {
            "version": "1.0",
            "output_path": "renders/final.mp4",
            "status": "pass",
            "checks": {
                "technical_probe": {},
                "visual_spotcheck": {},
                "audio_spotcheck": {},
                "promise_preservation": {},
                "subtitle_check": {},
            },
        },
    }
    if include_delivery_review:
        artifacts["delivery_review"] = _delivery_review()
    return {
        "version": "1.0",
        "project_id": "table-mat-mix-v6",
        "pipeline_type": "animated-explainer",
        "stage": "compose",
        "status": "completed",
        "timestamp": "2026-08-19T10:00:00Z",
        "artifacts": artifacts,
    }


def _delivery_editor_data() -> dict:
    return {
        "duration_seconds": 30,
        "qa_status": "检查通过",
        "download_url": "/media/table-mat/renders/final.mp4",
        "format_label": "竖屏 1080x1920",
        "player": {
            "video_url": "/media/table-mat/renders/final.mp4",
            "poster_url": "/thumb/table-mat/renders/final.mp4?w=640&t=1",
            "duration_seconds": 30,
        },
        "timeline": {
            "duration_seconds": 30,
            "tracks": [
                {
                    "kind": "copy",
                    "label": "文案",
                    "empty_message": None,
                    "segments": [
                        {
                            "id": "sentence-01",
                            "label": "透明桌垫，一擦就净",
                            "start_seconds": 0,
                            "end_seconds": 3,
                            "shot_ids": ["shot-01"],
                            "editable": True,
                            "sync_narration": True,
                        }
                    ],
                }
            ],
        },
        "candidate_groups": [
            {
                "kind": "cover",
                "label": "封面",
                "empty_message": None,
                "candidates": [
                    {
                        "id": "cover-02",
                        "label": "产品清晰帧",
                        "summary": "保留产品主体和文字安全区",
                        "preview_url": "/thumb/table-mat/renders/final.mp4?w=640&t=1",
                        "selected": True,
                    }
                ],
            }
        ],
        "versions": [
            {
                "id": "version-v1",
                "label": "V1",
                "active": True,
                "qa_status": "检查通过",
                "video_url": "/media/table-mat/renders/final.mp4",
                "poster_url": "/thumb/table-mat/renders/final.mp4?w=640&t=1",
                "change_summary": "当前已认证成片",
            }
        ],
        "pending_changes": [],
    }


def _operator_schema() -> dict:
    path = ROOT / "schemas" / "backlot" / "operator_state.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _draft_schema() -> dict:
    path = ROOT / "schemas" / "backlot" / "operator_draft.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_delivery_review_is_registered_and_accepts_minimal_artifact() -> None:
    assert "delivery_review" in ARTIFACT_NAMES
    assert "delivery_review" in SUPPLEMENTARY_ARTIFACTS
    validate_artifact("delivery_review", _delivery_review())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_cover_id", "hook-01"),
        ("selected_hook_id", "unknown-01"),
        ("selected_bgm_id", "cover-02"),
        ("selected_ending_id", "bgm-01"),
    ],
)
def test_delivery_review_rejects_candidate_ids_from_unknown_groups(
    field: str, value: str
) -> None:
    artifact = _delivery_review()
    artifact[field] = value

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("delivery_review", artifact)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unexpected", True),
        ("video_path", "/Users/operator/final.mp4"),
        ("start_seconds", 1.25),
    ],
)
def test_delivery_review_rejects_unknown_media_and_timecode_fields(
    field: str, value: object
) -> None:
    artifact = _delivery_review()
    artifact[field] = value

    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("delivery_review", artifact)


def test_operator_state_accepts_legacy_and_enriched_delivery_editors() -> None:
    schema = _operator_schema()
    jsonschema.validate(minimal_operator_state("delivery_review"), schema)

    enriched = minimal_operator_state("delivery_review")
    enriched["stages"][0]["editor"]["data"] = _delivery_editor_data()
    enriched["workspace"]["editor"]["data"] = copy.deepcopy(_delivery_editor_data())
    jsonschema.validate(enriched, schema)


@pytest.mark.parametrize(
    ("path", "unsafe_value"),
    [
        (("player", "video_url"), "/Users/operator/final.mp4"),
        (("player", "poster_url"), "/thumb/table-mat/inputs/reference/hit.mp4?w=640"),
        (("player", "poster_url"), "/thumb/table-mat/inputs/%72eference/hit.mp4?w=640"),
        (("candidate_groups", 0, "candidates", 0, "preview_url"), "/media/table-mat/inputs/reference/hit.mp4"),
    ],
)
def test_operator_state_delivery_editor_rejects_unsafe_media_urls(
    path: tuple[object, ...], unsafe_value: str
) -> None:
    state = minimal_operator_state("delivery_review")
    state["stages"][0]["editor"]["data"] = _delivery_editor_data()
    cursor = state["stages"][0]["editor"]["data"]
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = unsafe_value

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(state, _operator_schema())


def test_operator_state_delivery_player_requires_a_real_poster() -> None:
    state = minimal_operator_state("delivery_review")
    state["stages"][0]["editor"]["data"] = _delivery_editor_data()
    state["stages"][0]["editor"]["data"]["player"]["poster_url"] = None

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(state, _operator_schema())


def test_operator_state_candidate_id_matches_its_group() -> None:
    state = minimal_operator_state("delivery_review")
    state["stages"][0]["editor"]["data"] = _delivery_editor_data()
    state["stages"][0]["editor"]["data"]["candidate_groups"][0]["candidates"][0]["id"] = "hook-foreign"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(state, _operator_schema())


@pytest.mark.parametrize(
    "change",
    [
        {
            "op": "select_delivery_candidate",
            "candidate_kind": "cover",
            "candidate_id": "cover-02",
        },
        {
            "op": "replace_delivery_copy",
            "section_id": "sentence-01",
            "text": "透明桌垫，一擦就净",
            "sync_narration": False,
        },
        {"op": "clear_delivery_selection", "kind": "cover"},
    ],
)
def test_operator_draft_accepts_independent_delivery_review_mutation(
    change: dict,
) -> None:
    draft = _draft(
        "delivery-review-v1",
        [change],
    )
    draft["stage"] = "delivery_review"
    jsonschema.validate(draft, _draft_schema())


@pytest.mark.parametrize(
    "change",
    [
        {"op": "select_delivery_candidate", "candidate_kind": "cover", "candidate_id": "hook-01"},
        {"op": "select_delivery_candidate", "candidate_kind": "cover", "candidate_id": "cover-02", "media_path": "/tmp/x.mp4"},
        {"op": "select_delivery_candidate", "candidate_kind": "hook", "candidate_id": "hook-01", "start_seconds": 0.25},
        {"op": "select_delivery_candidate", "candidate_kind": "bgm", "candidate_id": None},
    ],
)
def test_operator_draft_delivery_review_mutation_stays_closed(change: dict) -> None:
    draft = _draft("delivery-review-v1", [change])
    draft["stage"] = "delivery_review"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(draft, _draft_schema())


@pytest.mark.parametrize("include_delivery_review", [False, True])
def test_compose_checkpoint_accepts_optional_delivery_review(
    include_delivery_review: bool,
) -> None:
    validate_checkpoint(
        _compose_checkpoint(include_delivery_review=include_delivery_review)
    )


def test_delivery_review_is_rejected_outside_compose_checkpoint() -> None:
    checkpoint = _compose_checkpoint(include_delivery_review=True)
    checkpoint["stage"] = "edit"
    checkpoint["status"] = "in_progress"

    with pytest.raises(CheckpointValidationError, match="compose"):
        validate_checkpoint(checkpoint)
