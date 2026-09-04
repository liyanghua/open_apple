from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.checkpoint import CheckpointValidationError, init_project, validate_checkpoint
from lib.pipeline_loader import (
    get_stage_required_artifacts,
    get_stage_produces,
    load_input_context,
    load_pipeline,
    get_required_tools,
    get_stage_required_tools,
    PipelineManifestError,
)


def test_manifest_declares_three_input_modes_and_resolves_reference_only_inputs() -> None:
    manifest = load_pipeline("cinematic-fast")
    assert set(manifest["mode_requirements"]) >= {
        "reference_driven", "source_led", "source_led_template"
    }

    reference = get_stage_required_artifacts(
        manifest, "scene_plan", input_mode="reference_driven"
    )
    source_led = get_stage_required_artifacts(
        manifest, "scene_plan", input_mode="source_led"
    )
    source_template = get_stage_required_artifacts(
        manifest, "scene_plan", input_mode="source_led_template"
    )
    assert "video_analysis_brief" in reference
    assert "reference_fingerprint" in reference
    assert "video_analysis_brief" not in source_led
    assert "reference_fingerprint" not in source_led
    assert "template_run_plan" in source_template


def test_source_led_research_produces_do_not_require_reference_artifacts() -> None:
    manifest = load_pipeline("cinematic-fast")
    produces = get_stage_produces(manifest, "research", input_mode="source_led")
    assert "source_media_review" in produces
    assert "video_analysis_brief" not in produces
    assert "reference_fingerprint" not in produces
    assert "video_analyzer" in get_required_tools(manifest, input_mode="reference_driven")
    assert "video_analyzer" not in get_required_tools(manifest, input_mode="source_led")
    assert get_stage_required_tools(manifest, "research", input_mode="source_led") == [
        "scene_detect", "frame_sampler"
    ]
    with pytest.raises(PipelineManifestError, match="Invalid input_mode"):
        get_required_tools(manifest, input_mode="unknown")


def test_init_project_writes_input_context_and_legacy_defaults_to_reference(tmp_path: Path) -> None:
    project = init_project(
        "source-led-demo",
        title="Source led",
        pipeline_type="cinematic-fast",
        pipeline_dir=tmp_path,
        input_mode="source_led_template",
        external_reference=False,
        template_prior={
            "present": True,
            "usage": "structural_only",
            "template_pack_ref": "artifacts/template_pack.json",
        },
        owned_source_root="inputs/source/products",
    )
    context = load_input_context(project)
    assert context["input_mode"] == "source_led_template"
    assert context["external_reference"]["present"] is False
    assert context["template_prior"]["usage"] == "structural_only"
    assert context["owned_source_root"] == "inputs/source/products"

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "project.json").write_text(
        json.dumps({"project_id": "legacy", "pipeline_type": "cinematic-fast"}),
        encoding="utf-8",
    )
    assert load_input_context(legacy)["input_mode"] == "reference_driven"


def test_reference_driven_requires_resolvable_external_reference(tmp_path: Path) -> None:
    reference = tmp_path / "reference-demo" / "reference.mp4"
    reference.parent.mkdir()
    reference.write_bytes(b"fixture")
    project = init_project(
        "reference-demo", title="Reference", pipeline_type="cinematic-fast",
        pipeline_dir=tmp_path, input_mode="reference_driven",
        external_reference={"present": True, "paths": ["reference.mp4"]},
    )
    assert load_input_context(project)["external_reference"]["paths"] == ["reference.mp4"]
    with pytest.raises(ValueError, match="resolvable"):
        init_project(
            "bad-reference", title="Bad", pipeline_type="cinematic-fast",
            pipeline_dir=tmp_path, input_mode="reference_driven",
            external_reference={"present": True, "paths": ["missing.mp4"]},
        )


def test_legacy_init_project_is_idempotent_without_reference_paths(tmp_path: Path) -> None:
    project = init_project(
        "legacy-repeat", title="Legacy", pipeline_type="cinematic-fast", pipeline_dir=tmp_path
    )
    init_project(
        "legacy-repeat", title="Legacy again", pipeline_type="cinematic-fast", pipeline_dir=tmp_path
    )
    assert load_input_context(project)["legacy_compat"] is True


def test_explicit_mode_promotes_legacy_marker_and_enforces_reference_path(tmp_path: Path) -> None:
    project = init_project(
        "legacy-promote", title="Legacy", pipeline_type="cinematic-fast", pipeline_dir=tmp_path
    )
    reference = project / "reference.mp4"
    reference.write_bytes(b"fixture")
    init_project(
        "legacy-promote", title="Promoted", pipeline_type="cinematic-fast", pipeline_dir=tmp_path,
        input_mode="reference_driven",
        external_reference={"present": True, "paths": ["reference.mp4"]},
    )
    marker = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert "input_mode_legacy_compat" not in marker
    reference.unlink()
    with pytest.raises(PipelineManifestError, match="not resolvable"):
        load_input_context(project)


def test_source_led_template_requires_template_prior(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="require a template prior"):
        init_project(
            "no-template", title="No template", pipeline_type="cinematic-fast",
            pipeline_dir=tmp_path, input_mode="source_led_template", external_reference=False,
        )
    with pytest.raises(ValueError, match="template prior"):
        init_project(
            "empty-template", title="Empty template", pipeline_type="cinematic-fast",
            pipeline_dir=tmp_path, input_mode="source_led_template",
            external_reference=False, template_prior={},
        )
    with pytest.raises(ValueError, match="template_pack_ref"):
        init_project(
            "missing-template-ref", title="Missing ref", pipeline_type="cinematic-fast",
            pipeline_dir=tmp_path, input_mode="source_led_template",
            external_reference=False,
            template_prior={"present": True, "usage": "structural_only"},
        )


def test_checkpoint_input_mode_must_match_project_marker(tmp_path: Path) -> None:
    project = init_project(
        "mode-mismatch", title="Mismatch", pipeline_type="cinematic-fast",
        pipeline_dir=tmp_path, input_mode="source_led", external_reference=False,
    )
    checkpoint = {
        "version": "1.0", "project_id": "mode-mismatch",
        "pipeline_type": "cinematic-fast", "input_mode": "reference_driven",
        "stage": "research", "status": "failed",
        "timestamp": "2026-09-03T00:00:00Z", "artifacts": {},
    }
    with pytest.raises(CheckpointValidationError, match="does not match project.json"):
        validate_checkpoint(checkpoint, project_dir=project)


def test_source_led_scene_checkpoint_does_not_require_reference_duration(tmp_path: Path) -> None:
    project = init_project(
        "source-led-scene",
        title="Source led scene",
        pipeline_type="cinematic-fast",
        pipeline_dir=tmp_path,
        input_mode="source_led",
        external_reference=False,
    )
    # The mode contract is checked before the legacy reference validator.  A
    # source-led project must not attempt to read this reference artifact.
    # Invalid structure is enough to reach mode validation; importantly the
    # failure must not be the reference-duration error.
    checkpoint = {
        "version": "1.0",
        "project_id": "source-led-scene",
        "pipeline_type": "cinematic-fast",
        "input_mode": "source_led",
        "stage": "scene_plan",
        "status": "awaiting_human",
        "timestamp": "2026-09-03T00:00:00Z",
        "artifacts": {},
    }
    with pytest.raises(Exception) as exc_info:
        validate_checkpoint(checkpoint, project_dir=project)
    assert "reference video requires finite duration" not in str(exc_info.value)


def test_source_led_scene_mapping_rejects_direct_reference_evidence() -> None:
    from lib.checkpoint import _validate_source_led_scene_mapping

    with pytest.raises(ValueError, match="direct_segment"):
        _validate_source_led_scene_mapping(
            {
                "scenes": [{"id": "s1", "shot_intent": "proof", "start_seconds": 0, "end_seconds": 1}],
                "metadata": {"reference_media_usage": "not_applicable", "source_mapping": [{"scene_id": "s1", "source_path": "inputs/source/a.mp4", "reference_evidence": {"mode": "direct_segment"}}]},
            },
            source_media_review={"files": [{"path": "inputs/source/a.mp4", "reviewed": True}]},
        )


def test_source_led_checkpoint_rejects_missing_mode_specific_research_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_project(
        "source-led-missing", title="Missing", pipeline_type="cinematic-fast",
        pipeline_dir=tmp_path, input_mode="source_led", external_reference=False,
    )
    monkeypatch.setattr("lib.checkpoint.get_pipeline_stages", lambda pipeline_type: ["scene_plan"])
    from lib.checkpoint import _enforce_stage_prerequisites
    with pytest.raises(CheckpointValidationError, match="reference_source_matrix"):
        _enforce_stage_prerequisites(
            tmp_path, "source-led-missing", "cinematic-fast", "scene_plan", "completed"
        )
