"""Semantic quality gates for the Research stage."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Mapping

# 评审 P2 B3：research 制品引用的派生证据目录前缀。复用研究（跨项目复制
# 制品）时必须连同这些派生文件一起迁移，否则审核台切片黑屏且后续阶段
# 校验失真。范围保持克制：只校验 analysis/ 派生证据（v8 迁移事故的根因），
# 用户自有素材（inputs/）与制品文件（artifacts/）不在此门内。
_DERIVED_PREFIXES = ("analysis/",)


def _iter_evidence_paths(value: Any) -> Iterator[str]:
    """Yield candidate project-relative evidence paths referenced anywhere."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"evidence_frames", "evidence_refs"} and isinstance(child, list):
                for item in child:
                    if isinstance(item, str):
                        yield item
            else:
                yield from _iter_evidence_paths(child)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_evidence_paths(item)


def validate_research_derived_files(
    project_dir: str | Path, research_artifacts: Mapping[str, Any]
) -> None:
    """Reject a completed Research stage whose derived evidence files are missing.

    research_breakdown / reference_source_matrix / caption_style_fingerprint
    reference derived evidence frames (analysis/**). If the artifacts were
    copied from another project without their derived files, this gate fails
    before the research checkpoint can complete.
    """
    missing: list[str] = []
    seen: set[str] = set()
    for artifact in research_artifacts.values():
        for raw in _iter_evidence_paths(artifact):
            text = str(raw).strip().replace("\\", "/")
            if not text or text.startswith(("http://", "https://", "data:")):
                continue
            if not text.startswith(_DERIVED_PREFIXES):
                continue
            if text in seen:
                continue
            seen.add(text)
            if not (Path(project_dir) / text).is_file():
                missing.append(text)
    if missing:
        raise ValueError(
            "research 制品引用的派生证据文件缺失（复用研究时须连同 analysis/ "
            "派生文件一起迁移）："
            + "、".join(missing[:10])
            + ("…" if len(missing) > 10 else "")
        )


def validate_research_completion(scorecard: Mapping[str, Any]) -> None:
    """Reject a completed Research stage when quality gates still fail."""
    failures = [str(value).strip() for value in scorecard.get("hard_failures", []) if str(value).strip()]
    score = scorecard.get("score")
    max_score = scorecard.get("max_score")
    if not isinstance(score, (int, float)) or max_score != 10 or score < 8:
        raise ValueError("研究检查至少 8/10 才能进入方案")
    if scorecard.get("status") != "pass" or failures:
        detail = "；".join(failures) or "研究检查未通过"
        raise ValueError(detail)


def validate_proposal_research_handoff(
    proposal: Mapping[str, Any],
    synthesis: Mapping[str, Any],
    matrix: Mapping[str, Any],
) -> None:
    """Ensure every concept remains traceable to the approved Research output."""
    direction_ids = {
        item.get("direction_id")
        for item in synthesis.get("differentiation_directions", [])
        if isinstance(item, Mapping)
    }
    matrix_ids = {
        item.get("matrix_row_id")
        for item in matrix.get("rows", [])
        if isinstance(item, Mapping)
    }
    for concept in proposal.get("concept_options", []):
        if not isinstance(concept, Mapping):
            raise ValueError("proposal concept must be an object")
        direction_refs = concept.get("research_direction_refs")
        matrix_refs = concept.get("matrix_row_refs")
        fingerprint_refs = concept.get("fingerprint_rule_refs")
        if not isinstance(direction_refs, list) or not direction_refs:
            raise ValueError("proposal concept requires research_direction_refs")
        if not isinstance(matrix_refs, list) or not matrix_refs:
            raise ValueError("proposal concept requires matrix_row_refs")
        if not isinstance(fingerprint_refs, list) or not fingerprint_refs:
            raise ValueError("proposal concept requires fingerprint_rule_refs")
        unknown_directions = set(direction_refs) - direction_ids
        if unknown_directions:
            raise ValueError(
                f"proposal concept references unknown research direction: {sorted(unknown_directions)}"
            )
        unknown_rows = set(matrix_refs) - matrix_ids
        if unknown_rows:
            raise ValueError(
                f"proposal concept references unknown research matrix row: {sorted(unknown_rows)}"
            )
