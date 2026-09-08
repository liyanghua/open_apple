"""Unit tests for lib.template_fork (template run 复用共享 research 的 main-chain 播种)。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lib.checkpoint import get_next_stage, read_checkpoint, validate_checkpoint
from lib.template_fork import (
    adapt_shared_research_artifact,
    fork_template_run,
    shared_research_artifact_names,
    shared_research_refs,
)

# 真实共享研究源：schema 有效的研究制品 + analysis/ 证据帧，fork 会原样复制并重建信封。
REAL_SOURCE = Path(__file__).resolve().parents[2] / "projects/table-mat-mix-v8"
RESEARCH_ARTIFACTS = (
    "research_brief", "video_analysis_brief", "source_media_review", "media_index",
    "reference_fingerprint", "research_breakdown", "reference_source_matrix",
    "research_synthesis", "research_scorecard", "caption_style_fingerprint",
)


def _copy_source(tmp_path: Path) -> Path:
    """复制真实 v8 研究源到 tmp，作为共享研究源项目（schema 有效）。"""
    src = tmp_path / "research-src"
    (src / "artifacts").mkdir(parents=True)
    for name in RESEARCH_ARTIFACTS:
        f = REAL_SOURCE / "artifacts" / f"{name}.json"
        if f.is_file():
            shutil.copyfile(f, src / "artifacts" / f"{name}.json")
    analysis = REAL_SOURCE / "analysis"
    if analysis.is_dir():
        shutil.copytree(analysis, src / "analysis", dirs_exist_ok=True)
    return src


def test_fork_seeds_completed_research_and_starts_at_proposal(tmp_path: Path):
    src = _copy_source(tmp_path)
    refs = shared_research_refs(src)
    assert refs and all(r.get("artifact_sha256") for r in refs)
    run_id = "template-run-test"
    project_dir = fork_template_run(run_id, source_project_dir=src, pipeline_dir=tmp_path)
    cp = read_checkpoint(tmp_path, run_id, "research")
    assert cp is not None and cp.get("status") == "completed"
    validate_checkpoint(cp, project_dir=project_dir)
    assert get_next_stage(tmp_path, run_id, "cinematic-fast") == "proposal"
    assert (project_dir / "artifacts" / "media_index.json").is_file()


def test_fork_is_idempotent(tmp_path: Path):
    src = _copy_source(tmp_path)
    run_id = "template-run-idem"
    for _ in range(2):
        fork_template_run(run_id, source_project_dir=src, pipeline_dir=tmp_path)
    cp = read_checkpoint(tmp_path, run_id, "research")
    assert cp.get("status") == "completed"
    assert get_next_stage(tmp_path, run_id, "cinematic-fast") == "proposal"


def test_shared_research_refs_are_content_addressed(tmp_path: Path):
    src = _copy_source(tmp_path)
    refs = shared_research_refs(src)
    assert {r["name"] for r in refs} == set(RESEARCH_ARTIFACTS)
    assert all(len(r["artifact_sha256"]) == 64 for r in refs)


def test_source_led_fork_uses_checkpoint_artifacts_instead_of_legacy_reference_list(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-led-research"
    artifacts = source / "artifacts"
    artifacts.mkdir(parents=True)
    names = (
        "research_brief",
        "source_media_review",
        "media_index",
        "source_semantic_index",
        "reference_source_matrix",
        "research_breakdown",
        "research_synthesis",
        "research_scorecard",
        "caption_style_fingerprint",
        "product_page_capture",
        "product_asset_ledger",
        "product_facts",
    )
    for offset, name in enumerate(names):
        digest = f"{offset + 1:064x}"
        (artifacts / f"{name}.json").write_text(
            json.dumps({"artifact_sha256": digest}), encoding="utf-8"
        )
    (source / "checkpoint_research.json").write_text(
        json.dumps({"artifacts": {name: {} for name in names}}), encoding="utf-8"
    )

    assert shared_research_artifact_names(source) == names
    refs = shared_research_refs(source)
    assert {item["name"] for item in refs} == set(names)
    assert "video_analysis_brief" not in {item["name"] for item in refs}
    assert "reference_fingerprint" not in {item["name"] for item in refs}


def test_source_led_template_fork_adapts_evidence_mode_without_faking_reference() -> None:
    index = adapt_shared_research_artifact(
        "source_semantic_index",
        {"input_mode": "source_led", "entries": []},
        target_input_mode="source_led_template",
    )
    matrix = adapt_shared_research_artifact(
        "reference_source_matrix",
        {
            "matrix_mode": "source_led",
            "rows": [{"reference_scene_id": None, "reference_time_range": None}],
        },
        target_input_mode="source_led_template",
    )

    assert index["input_mode"] == "source_led_template"
    assert matrix["matrix_mode"] == "source_led_template"
    assert matrix["rows"][0]["reference_scene_id"] is None
    assert matrix["rows"][0]["reference_time_range"] is None
