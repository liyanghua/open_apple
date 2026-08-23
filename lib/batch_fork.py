"""Candidate project forking (Autoresearch §4：一次研究 → 5 个候选项目).

Candidates share one research pass (facts, evidence, media inventory,
originality boundary) and fork only on hook/pacing/packaging/audience/
duration. This module creates each candidate's independent project workspace
and seeds it with the shared research artifacts + their derived analysis
files, then writes a `completed` research checkpoint so the candidate's own
pipeline starts at proposal. Concurrency stays agent-driven (max_parallel is
declared in the batch and enforced by the optimize-director runbook); Python
only persists and validates.

The batch is an index — it never carries full candidate content.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from lib.artifact_io import write_artifact_atomic
from lib.candidate_diversity import build_default_variant_plan
from lib.checkpoint import init_project, write_checkpoint
from schemas.artifacts import validate_artifact

# 共享研究的制品 + 派生文件（analysis/ 证据帧必须一起复制，B3 门会校验）。
SHARED_RESEARCH_ARTIFACTS = (
    "research_brief",
    "video_analysis_brief",
    "source_media_review",
    "media_index",
    "reference_fingerprint",
    "research_breakdown",
    "reference_source_matrix",
    "research_synthesis",
    "research_scorecard",
    "caption_style_fingerprint",
)

RESEARCH_CHECKPOINT_ARTIFACTS = SHARED_RESEARCH_ARTIFACTS


def fork_candidate_project(
    candidate: Mapping[str, Any],
    *,
    source_project_dir: Path,
    pipeline_dir: Path,
    baseline_ref: Mapping[str, Any] | None = None,
    candidate_index: int = 0,
) -> Path:
    """Create one candidate project seeded with the shared research pass.

    Returns the candidate project directory. Idempotent: re-running refreshes
    the shared research copies in place (same content = same hashes).
    """
    candidate_id = str(candidate["candidate_id"])
    source_project_id = source_project_dir.name
    project_dir = init_project(
        candidate_id,
        title=f"{candidate_id} {str(candidate.get('label') or '')}".strip(),
        pipeline_type="cinematic-fast",
        pipeline_dir=pipeline_dir,
    )

    # 1) 复制共享研究制品文件（原样内容；信封由本函数重建）。
    for name in SHARED_RESEARCH_ARTIFACTS:
        source = source_project_dir / "artifacts" / f"{name}.json"
        if not source.is_file():
            continue
        target = project_dir / "artifacts" / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    # 2) 复制派生的 analysis/ 证据文件（B3：research 派生文件完整性）。
    analysis_source = source_project_dir / "analysis"
    if analysis_source.is_dir():
        shutil.copytree(
            analysis_source,
            project_dir / "analysis",
            dirs_exist_ok=True,
        )

    # 3) 用复制后的内容重建信封并写 research 检查点（completed，research 无门禁）。
    envelopes: dict[str, dict[str, Any]] = {}
    for name in RESEARCH_CHECKPOINT_ARTIFACTS:
        path = project_dir / "artifacts" / f"{name}.json"
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        envelopes[name] = write_artifact_atomic(
            f"artifacts/{name}.json", name, data, project_dir=project_dir
        )
    write_checkpoint(
        pipeline_dir,
        candidate_id,
        "research",
        "completed",
        envelopes,
        pipeline_type="cinematic-fast",
        next_action=None,
    )

    # 4) Materialize the default variant contract before proposal/assets.  A
    # user-authored plan is preserved on restart; a newly forked candidate gets
    # a deterministic awaiting_human plan that the creative-lock bundle can
    # present alongside the other creative inputs.
    variant_path = project_dir / "artifacts" / "candidate_variant_plan.json"
    if variant_path.is_file():
        existing = json.loads(variant_path.read_text(encoding="utf-8"))
        validate_artifact("candidate_variant_plan", existing)
    else:
        plan = build_default_variant_plan(
            str(candidate.get("batch_id") or ""),
            candidate_id,
            candidate_index,
            baseline_ref=baseline_ref,
            direction=candidate.get("direction"),
        )
        write_artifact_atomic(
            "artifacts/candidate_variant_plan.json",
            "candidate_variant_plan",
            plan,
            project_dir=project_dir,
        )

    # 5) 候选元数据写入 project.json（batch 索引之外的可追溯性）。
    marker_path = project_dir / "project.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["candidate"] = {
        "candidate_id": candidate_id,
        "batch_id": str(candidate.get("batch_id") or ""),
        "parent_candidate_id": candidate.get("parent_candidate_id"),
        "iteration": candidate.get("iteration"),
        "direction": dict(candidate.get("direction") or {}),
        "source_research_project": source_project_id,
    }
    marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return project_dir


def fork_candidate_projects(
    batch: Mapping[str, Any],
    *,
    source_project_dir: Path,
    pipeline_dir: Path,
) -> dict[str, Path]:
    """Fork every candidate in the batch; returns {candidate_id: project_dir}."""
    created: dict[str, Path] = {}
    baseline_ref = next(
        (dict(ref) for ref in (batch.get("shared_research") or {}).get("refs", [])
         if isinstance(ref, Mapping)),
        None,
    )
    for candidate_index, candidate in enumerate(batch.get("candidates", [])):
        if not isinstance(candidate, Mapping):
            continue
        project_dir = fork_candidate_project(
            dict(candidate, batch_id=batch.get("batch_id", "")),
            source_project_dir=source_project_dir,
            pipeline_dir=pipeline_dir,
            baseline_ref=baseline_ref,
            candidate_index=candidate_index,
        )
        created[str(candidate["candidate_id"])] = project_dir
    return created
