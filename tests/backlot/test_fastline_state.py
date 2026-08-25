"""Fastline production status exposed by Backlot."""

from __future__ import annotations

import json
from pathlib import Path

from backlot.state import load_board_state
from backlot.state_cache import clear_state_cache, get_cached_board_state


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _bundle(version: int, script_hash: str) -> dict:
    return {
        "bundle_id": "table-mat-creative_lock",
        "bundle_version": version,
        "group": "creative_lock",
        "terminal_stage": "assets",
        "members": ["proposal", "scene_plan", "assets"],
        "artifact_refs": [
            {
                "name": "script",
                "path": "artifacts/script.json",
                "semantic_sha256": script_hash,
                "artifact_sha256": script_hash,
            },
            {
                "name": "scene_plan",
                "path": "artifacts/scene_plan.json",
                "semantic_sha256": "b" * 64,
                "artifact_sha256": "b" * 64,
            },
        ],
        "status": "approved",
    }


def test_fastline_state_uses_business_facing_progress_language(tmp_path: Path) -> None:
    project = tmp_path / "table-mat"
    approvals = project / "artifacts" / "approvals"
    approvals.mkdir(parents=True)
    _write(
        project / "project.json",
        {"project_id": "table-mat", "title": "透明桌垫", "pipeline_type": "cinematic-fast"},
    )
    _write(
        project / "checkpoint_assets.json",
        {
            "stage": "assets",
            "status": "completed",
            "human_approved": True,
            "approval_group": "creative_lock",
            "approval_bundle_id": "table-mat-creative_lock",
            "approval_bundle_version": 2,
            "artifacts": {},
        },
    )
    _write(
        project / "checkpoint_sample.json",
        {"stage": "sample", "status": "awaiting_human", "artifacts": {}},
    )
    _write(approvals / "table-mat-creative_lock-v1-approved.json", _bundle(1, "a" * 64))
    _write(approvals / "table-mat-creative_lock-v2-approved.json", _bundle(2, "c" * 64))
    _write(
        project / "artifacts" / "change_impact.json",
        {
            "route": "mux_only",
            "dirty_scene_ids": [],
            "reasons": ["background music gain changed"],
            "reopen_creative_lock": False,
            "reopen_sample": False,
        },
    )
    _write(project / "artifacts" / "render_plan.json", {"mode": "mux_only"})

    events = [
        {"ts": "2026-08-15T01:00:00Z", "tool": "audio_mixer", "event": "finish", "duration_s": 45},
        {"ts": "2026-08-15T01:01:00Z", "tool": "audio_mixer", "event": "finish", "duration_s": 48},
        {"ts": "2026-08-15T01:02:00Z", "tool": "audio_mixer", "event": "finish", "duration_s": 60},
        {"ts": "2026-08-15T01:03:00Z", "tool": "audio_mixer", "event": "start"},
        *[
            {
                "ts": f"2026-08-15T01:0{4 + index}:00Z",
                "tool": "media_proxy",
                "event": "cache_hit",
                "cache_key": f"hit-{index}",
                "reused_from": f"cache/item-{index}",
                "saved_seconds": saved,
            }
            for index, saved in enumerate((100, 120, 180, 220))
        ],
        {
            "ts": "2026-08-15T01:08:00Z",
            "tool": "subtitle_gen",
            "event": "cache_miss",
            "cache_key": "miss-1",
        },
    ]
    (project / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    fastline = load_board_state(project)["fastline"]

    assert fastline["gate"] == "sample"
    assert fastline["current_task"] == "样片已准备好，等待确认效果"
    assert fastline["bundle"]["version"] == 2
    assert fastline["bundle"]["status"] == "approved"
    assert fastline["bundle"]["changed_artifacts"] == ["script"]
    assert fastline["cache"] == {"hits": 4, "misses": 1, "saved_seconds": 620.0}
    assert fastline["render"]["mode"] == "mux_only"
    assert fastline["render"]["business_label"] == "只更新声音，无需重做画面"
    assert fastline["render"]["dirty_scene_ids"] == []
    assert fastline["eta"] == {"seconds": 48, "confidence": "high", "operation": "audio_mixer"}
    assert fastline["blocker"] == "等待确认样片效果"
    assert fastline["next_action"] == "请回到任务中确认样片效果"


def test_superseded_bundle_is_never_presented_as_approved(tmp_path: Path) -> None:
    project = tmp_path / "superseded"
    approvals = project / "artifacts" / "approvals"
    approvals.mkdir(parents=True)
    _write(project / "project.json", {"pipeline_type": "cinematic-fast"})
    _write(
        project / "checkpoint_assets.json",
        {
            "stage": "assets",
            "status": "awaiting_human",
            "approval_group": "creative_lock",
            "approval_bundle_id": "table-mat-creative_lock",
            "approval_bundle_version": 2,
            "artifacts": {},
        },
    )
    bundle = _bundle(2, "c" * 64)
    bundle["status"] = "superseded"
    _write(approvals / "table-mat-creative_lock-v2-superseded.json", bundle)

    fastline = load_board_state(project)["fastline"]

    assert fastline["bundle"]["status"] == "superseded"
    assert fastline["blocker"] == "已确认内容发生变化，需要重新确认"
    assert fastline["next_action"] == "请回到任务中确认最新方案与素材"


def test_board_state_cache_reuses_and_invalidates_on_state_file_change(tmp_path: Path) -> None:
    project = tmp_path / "cached"
    (project / "artifacts").mkdir(parents=True)
    artifact = project / "artifacts" / "render_plan.json"
    _write(artifact, {"mode": "sample"})
    calls = 0

    def build(_: Path) -> dict:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    clear_state_cache()
    assert get_cached_board_state(project, build) == {"calls": 1}
    assert get_cached_board_state(project, build) == {"calls": 1}

    _write(artifact, {"mode": "mux_only", "revision": "changed-size"})
    assert get_cached_board_state(project, build) == {"calls": 2}


def test_board_state_cache_invalidates_on_new_render_media(tmp_path: Path) -> None:
    """新增/替换成片 mp4 必须让缓存失效，否则 Renders 面板不显示新版本。"""
    project = tmp_path / "cached-media"
    (project / "artifacts").mkdir(parents=True)
    (project / "renders").mkdir(parents=True)
    _write(project / "artifacts" / "render_plan.json", {"mode": "full"})
    calls = 0

    def build(_: Path) -> dict:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    clear_state_cache()
    assert get_cached_board_state(project, build) == {"calls": 1}
    assert get_cached_board_state(project, build) == {"calls": 1}

    # 新增一个成片 mp4（无 JSON 变更）→ 缓存必须失效
    (project / "renders" / "final-cinematic.mp4").write_bytes(b"new render bytes")
    assert get_cached_board_state(project, build) == {"calls": 2}
