"""Semantic quality gates for the Research stage."""

from __future__ import annotations

from typing import Any, Mapping


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
