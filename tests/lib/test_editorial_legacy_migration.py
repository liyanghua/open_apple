from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _legacy_candidate(tmp_path: Path, *, generated_approved: bool = True) -> Path:
    project = tmp_path / "legacy-silver-ion"
    source = project / "inputs/source/video/product/towel.mp4"
    generated = project / "assets/video/generated/shot-02.mp4"
    narration = project / "assets/audio/sample-mix.mp3"
    music = project / "assets/music/bgm-30s.mp3"
    for path, data in ((source, b"source-video"), (generated, b"generated-video"), (narration, b"narration"), (music, b"music")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    source_hash, generated_hash = _sha256(source), _sha256(generated)
    _write_json(project / "project.json", {"project_id": project.name, "pipeline_type": "cinematic-fast"})
    _write_json(project / "artifacts/product_facts.json", {"version": "1.0", "claims": [
        {"claim_id": "claim-owned", "statement": "真实吸水画面"},
        {"claim_id": "claim-generated", "statement": "商品页主打银离子"},
    ]})
    _write_json(project / "artifacts/source_media_review.json", {"version": "1.0", "files": [{
        "media_id": "source-01", "reviewed": True, "media_type": "video",
        "path": "inputs/source/video/product/towel.mp4", "technical_probe": {"duration_seconds": 4.0},
    }]})
    _write_json(project / "artifacts/media_index.json", {"version": "1.0", "entries": [{
        "media_id": "source-01", "path": str(source),
        "fingerprint": {"content_sha256": source_hash}, "probe": {"duration_seconds": 4.0},
    }]})
    _write_json(project / "artifacts/reference_source_matrix.json", {"version": "1.0", "project_id": project.name,
        "matrix_mode": "source_led_template", "rows": [
            {"matrix_row_id": "row-owned", "claim_ids": ["claim-owned"], "resolution": "accept",
             "source_media_id": "source-01", "source_time_range": {"start_seconds": 1.0, "end_seconds_exclusive": 3.0}},
            {"matrix_row_id": "row-generated", "claim_ids": ["claim-generated"], "resolution": "accept",
             "visual_route": "generated_from_product_image", "source_time_range": {"start_seconds": 0.0, "end_seconds_exclusive": 2.0}},
        ]})
    _write_json(project / "artifacts/shot_execution_plan.json", {"version": "1.0", "project_id": project.name,
        "status": "approved", "shots": [
            {"id": "shot-01", "claim_ids": ["claim-owned"], "screen_copy": "吸水过程清楚可见",
             "evidence_row_ids": ["row-owned"], "visual_route": "owned_source", "source_media_id": "source-01",
             "source_selection": {"media_id": "source-01", "start_seconds": 1.0, "end_seconds": 3.0}},
            {"id": "shot-02", "claim_ids": ["claim-generated"], "screen_copy": "商品页主打银离子",
             "evidence_row_ids": ["row-generated"], "visual_route": "generated_from_product_image",
             "selected_generation_task_id": "legacy-generation-02"},
        ]})
    _write_json(project / "artifacts/asset_manifest.json", {"version": "1.0", "assets": [
        {"id": "sample-mix", "type": "audio", "path": "assets/audio/sample-mix.mp3"},
        {"id": "bgm-30s", "type": "music", "path": "assets/music/bgm-30s.mp3"},
    ]})
    _write_json(project / "artifacts/edit_decisions.json", {"version": "1.0", "render_runtime": "remotion", "cuts": [
        {"id": "shot-01", "speed": 1.0}, {"id": "shot-02", "speed": 1.0},
    ]})
    _write_json(project / "artifacts/final_props.json", {"version": "1.0", "project_id": project.name,
        "fps": 30, "width": 1080, "height": 1440, "scenes": [
            {"id": "shot-01", "fromFrame": 0, "toFrameExclusive": 60, "sourceInSeconds": 0.0, "sourceOutSeconds": 2.0},
            {"id": "shot-02", "fromFrame": 60, "toFrameExclusive": 120, "sourceInSeconds": 0.0, "sourceOutSeconds": 2.0},
        ], "captions": [
            {"text": "吸水过程清楚可见", "startMs": 0, "endMs": 2000},
            {"text": "商品页主打银离子", "startMs": 2000, "endMs": 4000},
        ]})
    _write_json(project / "operator/shot-generation/tasks/legacy-generation-02.json", {
        "task_id": "legacy-generation-02", "shot_id": "shot-02", "proposal_id": "generate-shot-02",
        "status": "completed", "output_path": "assets/video/generated/shot-02.mp4",
    })
    _write_json(project / "operator/product-image-execution/legacy-generation-02.json", {
        "idempotency_key": "legacy-generation-02", "shot_id": "shot-02",
        "proposal_id": "generate-shot-02", "output_path": "assets/video/generated/shot-02.mp4",
        "output_sha256": generated_hash, "reference_hash": "a" * 64,
        "approved": generated_approved,
    })
    return project


def test_migrate_legacy_source_led_candidate_rebuilds_trusted_timeline_and_catalogue(tmp_path: Path) -> None:
    from lib.editorial_legacy_migration import migrate_legacy_source_led_candidate

    project = _legacy_candidate(tmp_path)
    result = migrate_legacy_source_led_candidate(project, actor_id="migration-test")

    timeline = json.loads((project / "artifacts/editorial_timeline.json").read_text())
    catalogue = json.loads((project / "operator/editorial/asset-catalogue.json").read_text())
    assert result["status"] == "migrated"
    assert timeline["base_generation_id"] == result["generation_id"]
    assert {clip["fact_scope"]["shot_id"] for clip in timeline["tracks"][0]["clips"]} == {"shot-01", "shot-02"}
    assert {item["source_class"] for item in catalogue["assets"] if "source_class" in item} == {"owned_source", "generated_from_product_image"}


def test_migrate_legacy_source_led_candidate_rejects_unapproved_generated_media_without_writing(tmp_path: Path) -> None:
    from lib.editorial_legacy_migration import LegacyEditorialMigrationError, migrate_legacy_source_led_candidate

    project = _legacy_candidate(tmp_path, generated_approved=False)
    with pytest.raises(LegacyEditorialMigrationError, match="approved"):
        migrate_legacy_source_led_candidate(project, actor_id="migration-test")
    assert not (project / "artifacts/editorial_timeline.json").exists()
    assert not (project / "operator/editorial/asset-catalogue.json").exists()


def test_migrate_legacy_source_led_candidate_derives_generated_range_from_approved_final_props(tmp_path: Path) -> None:
    from lib.editorial_legacy_migration import migrate_legacy_source_led_candidate

    project = _legacy_candidate(tmp_path)
    matrix_path = project / "artifacts/reference_source_matrix.json"
    matrix = json.loads(matrix_path.read_text())
    matrix["rows"][1].pop("source_time_range")
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")

    migrate_legacy_source_led_candidate(project, actor_id="migration-test")
    timeline = json.loads((project / "artifacts/editorial_timeline.json").read_text())
    generated = next(clip for clip in timeline["tracks"][0]["clips"] if clip["fact_scope"]["shot_id"] == "shot-02")
    assert (generated["source_in_seconds"], generated["source_out_seconds"]) == (0.0, 2.0)


def test_migrate_legacy_source_led_candidate_keeps_captions_inside_frame_boundary(tmp_path: Path) -> None:
    from lib.editorial_legacy_migration import migrate_legacy_source_led_candidate

    project = _legacy_candidate(tmp_path)
    migrate_legacy_source_led_candidate(project, actor_id="migration-test")
    timeline = json.loads((project / "artifacts/editorial_timeline.json").read_text())
    first_caption = timeline["tracks"][4]["clips"][0]
    assert first_caption["end_seconds"] < 2.0
