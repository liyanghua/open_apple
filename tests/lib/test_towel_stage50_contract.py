from __future__ import annotations

import importlib.util
from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]


def _stage50():
    path = ROOT / "scripts/towel_batch_2026_09_02/stage50_sample.py"
    spec = importlib.util.spec_from_file_location("stage50_sample_contract", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _stage51():
    path = ROOT / "scripts/towel_batch_2026_09_02/stage51_verify_alignment.py"
    spec = importlib.util.spec_from_file_location("stage51_alignment_contract", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sample_render_plan_declares_real_audio_asset_path() -> None:
    mod = _stage50()
    plan = mod.build_render_plan(
        ROOT / "projects" / "test-run",
        caption_revision_env={
            "name": "caption_policy_revision",
            "path": "artifacts/caption_policy_revision.json",
            "artifact_sha256": "a" * 64,
            "semantic_sha256": "b" * 64,
        },
        audio_path="assets/audio/bgm-ducked.mp3",
        audio_sha256="c" * 64,
    )
    assert plan["audio"] == {
        "path": "assets/audio/bgm-ducked.mp3",
        "sha256": "c" * 64,
    }


def test_sample_probe_summary_uses_ffprobe_dimensions_and_rate() -> None:
    mod = _stage50()
    probe = {
        "format": {"duration": "4.25"},
        "streams": [{
            "codec_type": "video", "width": 540, "height": 720,
            "r_frame_rate": "24/1",
        }],
    }
    summary = mod.sample_probe_summary(probe, fallback_frame_count=99)
    assert summary == {
        "duration_seconds": 4.25,
        "fps": 24,
        "frame_count": 102,
        "height": 720,
        "width": 540,
    }


def test_source_led_sample_selects_the_full_timeline() -> None:
    mod = _stage50()
    shots = [{"id": f"shot-{index:02d}"} for index in range(1, 13)]

    assert mod.select_sample_shots(shots) == shots


def test_sample_render_window_includes_generated_route_within_10_to_15_seconds() -> None:
    mod = _stage50()
    shots = [
        {"id": "shot-01", "duration_seconds": 7.2, "visual_route": "owned_source"},
        {"id": "shot-02", "duration_seconds": 3.0, "visual_route": "owned_source"},
        {"id": "shot-03", "duration_seconds": 3.0, "visual_route": "owned_source"},
        {"id": "shot-09", "duration_seconds": 3.0, "visual_route": "generated_from_product_image"},
    ]

    selected = mod.select_sample_render_shots(shots)

    assert [shot["id"] for shot in selected] == ["shot-01", "shot-02", "shot-09"]
    assert 10.0 <= sum(float(shot["duration_seconds"]) for shot in selected) <= 15.0


def test_alignment_review_covers_every_script_section() -> None:
    mod = _stage51()
    sections = [{"id": f"sec-{index:02d}"} for index in range(1, 13)]

    assert mod.select_review_sections(sections) == sections


def test_proof_shot_review_uses_before_action_and_result_points() -> None:
    mod = _stage51()
    section = {
        "id": "sec-02",
        "start_seconds": 2.0,
        "end_seconds": 6.0,
        "action_keys": ["pour_water", "absorb"],
    }

    assert mod.review_timestamps(section) == [2.8, 4.0, 5.4]


def test_generated_alignment_review_records_text_and_timing_contract() -> None:
    mod = _stage51()
    check = mod.canonicalize_vlm_check(
        {field: "pass" for field in mod.DIMENSIONS},
        expected_shot_id="shot-09",
        expected_section_id="sec-009",
        generated_route=True,
    )
    assert check["generated_text_integrity"] == "pass"
    assert check["voice_caption_timing_match"] == "pass"


def test_aligned_run_uses_project_local_research_artifacts(tmp_path: Path) -> None:
    mod = _stage50()
    project = tmp_path / "template-run-yinlizi-aligned-A"
    (project / "artifacts").mkdir(parents=True)
    (project / "artifacts" / "product_facts.json").write_text("{}", encoding="utf-8")

    assert mod.research_root_for(project) == project


def test_generated_shot_resolves_completed_generation_task(tmp_path: Path) -> None:
    mod = _stage50()
    project = tmp_path / "run"
    task_dir = project / "operator" / "shot-generation" / "tasks"
    output = project / "assets" / "video" / "generated-shot-09-fast.mp4"
    task_dir.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    output.write_bytes(b"video")
    (task_dir / "shotgen-1.json").write_text(json.dumps({
        "task_id": "shotgen-1",
        "status": "completed",
        "quality": "fast",
        "shot_id": "shot-09",
        "proposal_id": "generate-shot-09",
        "output_path": "assets/video/generated-shot-09-fast.mp4",
        "provider": "grok",
        "model": "grok-imagine-video",
        "actual_cost_usd": 0.202,
    }), encoding="utf-8")

    resolved = mod.resolve_shot_video(project, {
        "id": "shot-09",
        "visual_route": "generated_from_product_image",
        "generation_proposals": [{"id": "generate-shot-09"}],
    })

    assert resolved["path"] == "assets/video/generated-shot-09-fast.mp4"
    assert resolved["provider"] == "grok"
    assert resolved["quality"] == "fast"


def test_canonical_props_use_generated_render_asset_without_source_seek(tmp_path: Path) -> None:
    from lib.template_render import build_final_props

    props = build_final_props(tmp_path / "run", {}, [{
        "id": "shot-09",
        "duration_seconds": 3.0,
        "visual_route": "generated_from_product_image",
        "render_asset_path": "assets/video/generated-shot-09-fast.mp4",
        "source_selection": None,
    }])

    assert props["footage"]["shot_09"] == "assets/video/generated-shot-09-fast.mp4"
    assert props["scenes"][0]["sourceInSeconds"] == 0.0
    assert props["scenes"][0]["sourceOutSeconds"] == 3.0


def test_core_selling_point_copy_removes_page_attribution_prefix() -> None:
    mod = _stage50()

    assert mod.core_selling_point("商品页主打吸水速干") == "吸水速干"
    assert mod.core_selling_point("商品页参数标注双面毛圈") == "双面毛圈"
    assert mod.core_selling_point("商品页主打AG+银离子净护") == "银离子净护"
    assert mod.core_selling_point("日常洁面使用画面") == "日常洁面"


def test_alignment_report_freshness_distinguishes_stale_sample(tmp_path: Path) -> None:
    mod = _stage50()
    project = tmp_path / "run"
    (project / "analysis").mkdir(parents=True)
    report = {
        "sample_sha256": "old-sample",
        "script_sha256": "script-hash",
        "checks": [],
    }
    (project / "analysis" / "alignment_check.json").write_text(
        json.dumps(report), encoding="utf-8"
    )

    assert mod.alignment_report_freshness(
        project, sample_sha256="new-sample", script_sha256="script-hash"
    ) == "stale"
    assert mod.alignment_report_freshness(
        project, sample_sha256="old-sample", script_sha256="script-hash"
    ) == "current"


def test_alignment_report_freshness_marks_missing_report(tmp_path: Path) -> None:
    mod = _stage50()
    project = tmp_path / "run"
    (project / "analysis").mkdir(parents=True)

    assert mod.alignment_report_freshness(
        project, sample_sha256="sample", script_sha256="script"
    ) == "missing"


def test_stage51_maps_review_sections_to_sample_timeline(tmp_path: Path) -> None:
    mod = _stage51()
    sections = [
        {"id": "sec-001", "start_seconds": 0.0, "end_seconds": 7.2},
        {"id": "sec-002", "start_seconds": 7.2, "end_seconds": 10.2},
        {"id": "sec-009", "start_seconds": 27.1, "end_seconds": 30.1},
    ]
    shot_plan = {"shots": [
        {"id": "shot-01", "section_id": "sec-001", "duration_seconds": 7.2},
        {"id": "shot-02", "section_id": "sec-002", "duration_seconds": 3.0},
        {"id": "shot-09", "section_id": "sec-009", "duration_seconds": 3.0},
    ]}

    mapped = mod.sample_review_sections(sections, shot_plan, sample_duration=13.2)

    assert [(item["section"]["id"], item["start_seconds"], item["end_seconds"])
            for item in mapped] == [
        ("sec-001", 0.0, 7.2),
        ("sec-002", 7.2, 10.2),
        ("sec-009", 10.2, 13.2),
    ]


def test_stage51_reviews_the_same_proxy_file_as_the_sample_gate() -> None:
    source = (ROOT / "scripts/towel_batch_2026_09_02/stage51_verify_alignment.py").read_text(
        encoding="utf-8"
    )
    assert 'sample_path = d / "renders" / "sample-v1-540x960.mp4"' in source
    assert 'sample_path = d / "renders" / "sample-v1.mp4"' in source
    assert 'str(sample_path), "-frames:v", "1"' in source


def test_canonical_props_carry_product_identity_into_realized_scenes(tmp_path: Path) -> None:
    from lib.template_render import build_final_props

    props = build_final_props(tmp_path / "run", {}, [{
        "id": "shot-01",
        "duration_seconds": 3.0,
        "product_id": "tmall:1060430166297:6276962282892",
        "product_name": "银离子毛巾",
        "sku": "6276962282892",
    }])

    assert props["scenes"][0]["product_id"] == "tmall:1060430166297:6276962282892"
