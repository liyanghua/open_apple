from __future__ import annotations

import pytest


def test_registry_is_explicit_and_rejects_unknown_stage() -> None:
    from backlot.operator_adapters import get_adapter

    assert get_adapter("script").adapter_id == "script-v1"
    assert get_adapter("edit").adapter_id == "edit-v1"
    with pytest.raises(KeyError):
        get_adapter("compose")


def test_research_changes_create_annotations_without_mutating_evidence() -> None:
    from backlot.operator_adapters import get_adapter

    adapter = get_adapter("research")
    source = {
        "project_id": "demo",
        "source_media_review": {"items": [{"media_id": "m1", "quality": "good"}]},
    }
    changed = adapter.apply(
        source,
        [
            {"op": "set_media_disposition", "media_id": "m1", "disposition": "priority"},
            {"op": "set_logo_usage", "media_id": "m1", "allowed": True},
            {"op": "set_business_note", "target_id": "m1", "text": "主镜头"},
        ],
    )
    assert changed["source_media_review"] == source["source_media_review"]
    assert changed["research_annotations"]["media_dispositions"]["m1"] == "priority"
    assert changed["research_annotations"]["logo_usage"]["m1"] is True
    assert source.get("research_annotations") is None


def test_research_changes_update_top_level_persisted_annotations_in_place() -> None:
    from backlot.operator_adapters import get_adapter

    adapter = get_adapter("research")
    source = {
        "version": "1.0",
        "project_id": "demo",
        "revision_id": "revision-1",
        "media_dispositions": {"m1": "priority"},
        "business_notes": {},
    }
    changed = adapter.apply(
        source,
        [{"op": "set_business_note", "target_id": "m1", "text": "保留原片"}],
    )

    assert changed["media_dispositions"] == {"m1": "priority"}
    assert changed["business_notes"] == {"m1": "保留原片"}
    assert "research_annotations" not in changed
    assert source["business_notes"] == {}


@pytest.mark.parametrize(
    "operation,field",
    [
        ({"op": "set_media_disposition", "media_id": "m1", "disposition": "priority"}, "media_dispositions.m1"),
        ({"op": "set_business_note", "target_id": "m1", "text": "保留"}, "business_notes.m1"),
        ({"op": "set_logo_usage", "media_id": "m1", "allowed": True}, "logo_usage.m1"),
        ({"op": "set_claim_boundary", "claim_id": "c1", "text": "仅演示"}, "claim_boundaries.c1"),
        ({"op": "set_reference_method", "method_id": "proof", "selected": True}, "reference_methods.proof"),
        ({"op": "set_direction_preference", "direction_id": "d1", "preference": "prefer", "rationale": "适合"}, "direction_preferences.d1"),
        ({"op": "resolve_matrix_row", "matrix_row_id": "row-1", "resolution": "accept", "source_media_id": "m1", "note": "采用"}, "matrix_resolutions.row-1"),
        ({"op": "request_local_reanalysis", "target_type": "shot", "target_id": "s1", "dimensions": ["dialogue"], "reason": "听不清"}, "local_reanalysis_requests"),
    ],
)
def test_research_touched_fields_use_persisted_collection_paths(operation, field) -> None:
    from backlot.operator_adapters import get_adapter

    assert get_adapter("research").touched_fields([operation]) == {field}


@pytest.mark.parametrize(
    "stage,operation,field",
    [
        ("proposal", {"op": "replace_hook", "text": "先刮给你看"}, "hook"),
        (
            "script",
            {"op": "replace_section_narration", "section_id": "s1", "text": "新的口播"},
            "sections.s1.narration",
        ),
        (
            "scene_plan",
            {"op": "set_shot_speed", "shot_id": "q1", "speed": 1.2},
            "shots.q1.speed",
        ),
        (
            "assets",
            {"op": "set_runtime", "runtime": "remotion"},
            "render_runtime",
        ),
        (
            "sample",
            {"op": "add_timecode_comment", "start_seconds": 1, "end_seconds": 2, "text": "节奏慢"},
            "comments",
        ),
    ],
)
def test_touched_fields_are_business_fields(stage, operation, field) -> None:
    from backlot.operator_adapters import get_adapter

    assert field in get_adapter(stage).touched_fields([operation])


def test_adapters_reject_unknown_operations_and_raw_patch_fields() -> None:
    from backlot.operator_adapters import get_adapter
    from backlot.operator_errors import OperatorError

    for operation in (
        {"op": "replace", "path": "/sections/0", "value": {}},
        {"op": "replace_hook", "text": "x", "semantic_sha256": "secret"},
    ):
        with pytest.raises(OperatorError) as failure:
            get_adapter("proposal").apply({}, [operation])
        assert failure.value.code == "validation_failed"


def test_script_adapter_reports_caption_duration_and_tail_rate_risks() -> None:
    from backlot.operator_adapters import get_adapter

    adapter = get_adapter("script")
    snapshot = {
        "total_duration_seconds": 6,
        "sections": [
            {"id": "s1", "start_seconds": 0, "end_seconds": 3, "narration": "正常语速", "screen_copy": "短字幕", "delivery": {"rate": 1}},
            {"id": "s2", "start_seconds": 3, "end_seconds": 5, "narration": "结尾口播", "screen_copy": "这是一条明显超过移动端安全展示长度的字幕文案", "delivery": {"rate": 1.6}},
        ],
    }
    changed = adapter.apply(
        snapshot,
        [{"op": "set_strip_trailing_punctuation", "enabled": True}],
    )
    warnings = adapter.validate(changed)
    assert {item["code"] for item in warnings} >= {
        "duration_mismatch",
        "caption_too_long",
        "tail_delivery_too_fast",
    }


def test_scene_adapter_enforces_half_open_ranges_coverage_and_continuity() -> None:
    from backlot.operator_adapters import get_adapter
    from backlot.operator_errors import OperatorError

    adapter = get_adapter("scene_plan")
    valid = {
        "total_duration_seconds": 4,
        "sources": {"m1": {"duration_seconds": 10}},
        "shots": [
            {"id": "q1", "source_id": "m1", "source_in_seconds": 0, "source_out_seconds": 2, "start_seconds": 0, "end_seconds": 2, "speed": 1},
            {"id": "q2", "source_id": "m1", "source_in_seconds": 2, "source_out_seconds": 4, "start_seconds": 2, "end_seconds": 4, "speed": 1},
        ],
    }
    assert adapter.validate(valid) == []

    overlapped = adapter.apply(
        valid,
        [{"op": "set_timeline_range", "shot_id": "q2", "start_seconds": 1.5, "end_seconds": 4}],
        validate=False,
    )
    with pytest.raises(OperatorError) as overlap:
        adapter.validate(overlapped)
    assert overlap.value.code == "validation_failed"

    uncovered = adapter.apply(
        valid,
        [{"op": "set_source_range", "shot_id": "q1", "in_seconds": 9, "out_seconds": 11}],
        validate=False,
    )
    with pytest.raises(OperatorError):
        adapter.validate(uncovered)


def test_asset_changes_emit_reapproval_and_render_signals() -> None:
    from backlot.operator_adapters import get_adapter

    operations = [
        {"op": "set_tts", "provider": "doubao", "model": "seed-tts", "voice": "warm", "rate": 1},
        {"op": "set_bgm", "source": "library", "track_id": "warm-home"},
        {"op": "set_runtime", "runtime": "remotion"},
    ]
    signals = get_adapter("assets").change_signals(operations)
    assert signals == {"reopen_creative": True, "reopen_sample": True, "render_route": "full_render"}


def test_edit_changes_are_typed_and_route_to_preview_render() -> None:
    from backlot.operator_adapters import get_adapter

    adapter = get_adapter("edit")
    before = {
        "cuts": [
            {"id": "sc01", "in_seconds": 1, "out_seconds": 3, "speed": 1},
            {"id": "sc02", "in_seconds": 0, "out_seconds": 2, "speed": 1},
        ],
        "audio": {"music": {"volume": 0.08}, "sfx": [{"volume": 0.22}], "narration": {}},
    }
    after = adapter.apply(before, [
        {"op": "set_shot_enabled", "shot_id": "sc01", "enabled": False},
        {"op": "set_caption", "shot_id": "sc01", "text": "先划一下，桌面不怕"},
    ])
    assert after["cuts"][0]["enabled"] is False
    assert after["caption_overrides"][0]["text"] == "先划一下，桌面不怕"
    assert adapter.change_signals([{"op": "set_caption", "shot_id": "sc01", "text": "新字幕"}])["render_route"] == "full_render"


def test_diff_is_chinese_business_summary_not_structural_patch() -> None:
    from backlot.operator_adapters import get_adapter

    changes = get_adapter("proposal").diff(
        {"hook": "旧钩子", "cta": "旧收口"},
        {"hook": "新钩子", "cta": "立即购买"},
    )
    assert changes == ["开头钩子已调整", "结尾行动引导已调整"]
    assert "/hook" not in "".join(changes)
