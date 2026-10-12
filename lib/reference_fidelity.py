"""Validation for strict reference replacement mappings."""
from __future__ import annotations
from typing import Any


def default_fidelity_policy() -> dict[str, Any]:
    """Return the versioned strict-mode contract persisted at Research."""
    return {
        "version": "1.0",
        "mode": "reference_fidelity",
        "locked_dimensions": [
            "beat_order", "shot_order", "shot_duration", "cut_points",
            "voice_cadence", "pause_structure", "caption_timing", "transition_intent",
        ],
        "replaceable_dimensions": [
            "product_identity", "product_claims", "visual_evidence",
            "narration_words", "screen_copy", "logo", "brand_colors", "music",
        ],
        "forbidden_dimensions": [
            "reference_brand", "reference_logo", "reference_watermark",
            "reference_person_identity", "reference_original_pixels", "reference_caption_text",
        ],
        "duration_drift_tolerance_ms": 120,
        "voice_timing_tolerance_ms": 160,
    }


def build_alignment_report(
    *,
    reference_duration_seconds: float,
    target_duration_seconds: float,
    matrix_rows: list[dict[str, Any]],
    voice_segments: list[dict[str, Any]],
    render_inputs: list[str],
    high_risk_claim_ids: set[str] | None = None,
    product_identity_match: bool = True,
    duration_tolerance_ms: int = 120,
    voice_tolerance_ms: int = 160,
) -> dict[str, Any]:
    """Build the strict-mode dual quality gate from canonical artifacts.

    This deliberately evaluates structural fidelity and product truth separately:
    a visually faithful result cannot compensate for an unsupported product claim.
    """
    duration_drift = round((target_duration_seconds - reference_duration_seconds) * 1000)
    matrix_errors = validate_replacement_matrix(
        matrix_rows, high_risk_claim_ids=high_risk_claim_ids
    )
    voice_failures = [
        str(segment.get("segment_id") or index)
        for index, segment in enumerate(voice_segments)
        if abs(int(segment.get("start_drift_ms") or 0)) > voice_tolerance_ms
        or abs(int(segment.get("end_drift_ms") or 0)) > voice_tolerance_ms
    ]
    reference_leak = any(
        str(path).replace("\\", "/").startswith("inputs/reference/")
        for path in render_inputs
    )
    failures: list[str] = []
    if abs(duration_drift) > duration_tolerance_ms:
        failures.append("duration_drift")
    if voice_failures:
        failures.append("voice_timing")
    if reference_leak:
        failures.append("reference_media_in_render")
    if matrix_errors:
        failures.append("replacement_matrix")
    if not product_identity_match:
        failures.append("product_identity")
    fidelity_failures = sum((abs(duration_drift) > duration_tolerance_ms, bool(voice_failures), reference_leak))
    truth_failures = sum((bool(matrix_errors), not product_identity_match))
    fidelity_score = max(0.0, 1.0 - fidelity_failures / 3)
    truth_score = max(0.0, 1.0 - truth_failures / 2)
    return {
        "version": "1.0",
        "status": "pass" if not failures else "fail",
        "hard_gate_failures": failures,
        "reference_fidelity": {
            "score": fidelity_score,
            "duration_drift_ms": duration_drift,
            "voice_segment_failures": voice_failures,
            "reference_media_leak": reference_leak,
        },
        "product_truth": {
            "score": truth_score,
            "identity_match": product_identity_match,
            "matrix_errors": matrix_errors,
        },
    }


def validate_replacement_matrix(rows: list[dict[str, Any]], *, high_risk_claim_ids: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    high_risk_claim_ids = high_risk_claim_ids or set()
    for index, row in enumerate(rows):
        ref = row.get("reference_shot_id")
        target = row.get("target_shot_id")
        if not ref or not target:
            errors.append(f"row {index} requires reference_shot_id and target_shot_id")
        if target in seen:
            errors.append(f"duplicate target_shot_id: {target}")
        seen.add(target)
        claims = set(row.get("claim_ids") or [])
        if not row.get("product_fact_refs") and claims:
            errors.append(f"row {index} claims require product facts")
        if claims & high_risk_claim_ids and not row.get("evidence_row_ids"):
            errors.append(f"row {index} high-risk claims require evidence")
    return errors
