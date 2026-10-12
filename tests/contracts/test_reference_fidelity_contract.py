from pathlib import Path

import pytest

from lib.checkpoint import init_project
from lib.pipeline_loader import get_stage_produces, get_stage_required_artifacts, load_input_context, load_pipeline


def test_cinematic_fast_accepts_reference_fidelity_mode():
    manifest = load_pipeline("cinematic-fast")
    assert "reference_fidelity" in manifest["mode_requirements"]
    assert {"reference_timeline", "fidelity_policy"} <= set(
        get_stage_produces(manifest, "research", input_mode="reference_fidelity")
    )
    assert {"voice_alignment_report", "reference_alignment_report"} <= set(
        get_stage_produces(manifest, "sample", input_mode="reference_fidelity")
    )
    assert "replacement_matrix" in get_stage_required_artifacts(
        manifest, "compose", input_mode="reference_fidelity"
    )


def test_strict_mode_requires_resolvable_analysis_only_reference(tmp_path):
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"fixture")
    project = init_project(
        "strict-demo",
        title="严格复刻",
        pipeline_type="cinematic-fast",
        pipeline_dir=tmp_path / "projects",
        input_mode="reference_fidelity",
        external_reference={"present": True, "paths": [str(reference)], "usage": "analysis_only"},
    )
    context = load_input_context(project)
    assert context["input_mode"] == "reference_fidelity"


def test_strict_mode_rejects_non_analysis_reference(tmp_path):
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="analysis_only"):
        init_project(
            "strict-invalid",
            title="严格复刻",
            pipeline_type="cinematic-fast",
            pipeline_dir=tmp_path / "projects",
            input_mode="reference_fidelity",
            external_reference={"present": True, "paths": [str(reference)], "usage": "render"},
        )
