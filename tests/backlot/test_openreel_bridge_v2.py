from __future__ import annotations

import pytest


def _snapshot() -> dict:
    return {
        "session_id": "s-1",
        "timeline": {
            "version": "1.0",
            "base_generation_id": "generation-1",
            "timeline_id": "tl-1",
            "base_edit_revision": "edit-1",
            "source_artifact_hashes": {},
            "tracks": [
                {"id": "video", "kind": "video", "clips": [{"id": "clip-1", "asset_id": "asset-1", "fact_scope": {"claim_ids": ["claim-1"], "shot_id": "shot-1", "visual_requirement_id": "visual-1", "allowed_source_classes": ["owned_source"]}}]},
                {"id": "music", "kind": "music", "clips": [{"id": "music-1", "asset_id": "music-1", "start_seconds": 0, "end_seconds": 10}]},
                {"id": "subtitle", "kind": "subtitle", "clips": [{"id": "subtitle-1", "text": "旧", "start_seconds": 0, "end_seconds": 2, "claim_ids": ["claim-1"]}]},
            ],
        },
        "asset_catalogue": {"assets": [{"asset_id": "asset-2", "candidate_id": "c1", "project_id": "p1", "source_sha256": "b" * 64, "fact_scope": {"claim_ids": ["claim-1"], "shot_id": "shot-1", "visual_requirement_id": "visual-1", "allowed_source_classes": ["owned_source"]}}]},
    }


def test_openreel_actions_map_to_typed_edit_delta() -> None:
    from backlot.openreel_bridge import actions_to_delta

    delta = actions_to_delta(_snapshot(), [
        {"type": "clip/trim", "params": {"clipId": "clip-1", "inPoint": 0.5, "outPoint": 1.5}},
        {"type": "clip/split", "params": {"clipId": "clip-1", "time": 0.8}},
        {"type": "clip/move", "params": {"clipId": "clip-1", "start": 2}},
        {"type": "clip/replace", "params": {"clipId": "clip-1", "assetId": "asset-2", "sourceSha256": "b" * 64, "inPoint": 0, "outPoint": 1}},
        {"type": "audio/gain", "params": {"clipId": "music-1", "gainDb": -4}},
        {"type": "audio/fade", "params": {"clipId": "music-1", "fadeIn": 0.2, "fadeOut": 0.3}},
        {"type": "audio/duck", "params": {"clipId": "music-1", "enabled": True, "reductionDb": -8}},
        {"type": "caption/timing", "params": {"clipId": "subtitle-1", "start": 0.2, "end": 1.8}},
    ], idempotency_key="k-1")
    assert delta["base_generation_id"] == "generation-1"
    assert [item["op"] for item in delta["operations"]] == ["trim_clip", "split_clip", "move_clip", "replace_clip", "set_gain", "set_fade", "set_ducking", "set_caption_timing"]


@pytest.mark.parametrize("action", [
    {"type": "clip/trim", "params": {"clipId": "missing", "inPoint": 0, "outPoint": 1}},
    {"type": "clip/replace", "params": {"clipId": "clip-1", "assetId": "forged", "sourceSha256": "a" * 64, "inPoint": 0, "outPoint": 1}},
])
def test_unknown_clip_or_asset_fails_without_delta(action: dict) -> None:
    from backlot.openreel_bridge import BridgeError, actions_to_delta

    with pytest.raises(BridgeError) as failure:
        actions_to_delta(_snapshot(), [action], idempotency_key="bad")
    assert failure.value.code in {"clip_not_found", "asset_not_approved"}


def test_unsupported_color_grade_is_explicit_and_not_saved() -> None:
    from backlot.openreel_bridge import BridgeError, actions_to_delta

    with pytest.raises(BridgeError) as failure:
        actions_to_delta(_snapshot(), [{"type": "color_grade/apply", "params": {"preset": "cinematic"}}], idempotency_key="grade")
    assert failure.value.code == "unsupported_action"


def test_snapshot_adapter_exposes_server_ids_and_fact_scopes_only() -> None:
    from backlot.openreel_bridge import snapshot_to_openreel

    adapted = snapshot_to_openreel(_snapshot())
    assert adapted["session_id"] == "s-1"
    assert adapted["clips"][0]["id"] == "clip-1"
    assert adapted["clips"][0]["fact_scope"]["claim_ids"] == ["claim-1"]
    assert "source_sha256" not in adapted["clips"][0]


def test_clip_add_uses_approved_asset_and_server_issued_clip_id() -> None:
    from backlot.openreel_bridge import actions_to_delta

    delta = actions_to_delta(_snapshot(), [{
        "type": "clip/add",
        "params": {
            "trackId": "video",
            "clipId": "clip-new",
            "assetId": "asset-2",
            "inPoint": 1,
            "outPoint": 2,
            "start": 3,
        },
    }], idempotency_key="add-1")
    operation = delta["operations"][0]
    assert operation["op"] == "add_clip"
    assert operation["track_id"] == "video"
    assert operation["clip"]["id"] == "clip-new"
    assert operation["clip"]["fact_scope"]["visual_requirement_id"] == "visual-1"


def test_clip_add_rejects_unknown_track() -> None:
    from backlot.openreel_bridge import BridgeError, actions_to_delta

    with pytest.raises(BridgeError) as failure:
        actions_to_delta(_snapshot(), [{
            "type": "clip/add",
            "params": {"trackId": "forged-track", "clipId": "clip-new", "assetId": "asset-2", "inPoint": 0, "outPoint": 1, "start": 0},
        }], idempotency_key="add-bad-track")
    assert failure.value.code == "track_not_found"


def test_editorial_shell_is_same_origin_and_exposes_required_states() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "backlot" / "ui"
    html = (root / "editorial-editor-shell.html").read_text(encoding="utf-8")
    js = (root / "editorial-editor" / "shell.js").read_text(encoding="utf-8")
    for term in ("Source-led", "商品事实", "批准素材", "保存", "预览", "成片", "不支持"):
        assert term in html + js
    assert "fetch(path" in js
    assert "/api/v2/" in js
    assert "http://" not in js and "https://" not in js


def test_editorial_build_manifest_records_pinned_source_license_and_bundle_hash(tmp_path) -> None:
    from scripts.build_openreel_editor import build_manifest

    source = tmp_path / "source"
    source.mkdir()
    (source / "shell.js").write_text("console.log('editor');", encoding="utf-8")
    license_path = source / "LICENSE"
    license_path.write_text("OpenReel license", encoding="utf-8")
    output = tmp_path / "dist"
    manifest = build_manifest(source, output, revision="openreel-test-rev", license_path=license_path)
    assert manifest["source_revision"] == "openreel-test-rev"
    assert manifest["license_file"] == "LICENSE"
    assert len(manifest["bundle_sha256"]) == 64
    assert (output / "manifest.json").is_file()
