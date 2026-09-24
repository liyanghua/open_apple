"""Deterministic batch-level candidate differentiation and deduplication.

The scorer is dependency-free and reproducible. Metrics are advisory: declared
creative axes and exact asset overlap cannot replace individual human review.
Controlled experiments must be preregistered and compared to their baseline.
"""

from __future__ import annotations

import re
import math
import json
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import zip_longest
from typing import Any, Iterable, Mapping, Sequence

from lib.artifact_hashing import attach_hashes, verify_hashes
from schemas.artifacts import validate_artifact

ACTION_THRESHOLD = 0.80
COPY_THRESHOLD = 0.85
BEAT_THRESHOLD = 0.15
THRESHOLDS = {
    "action_jaccard": ACTION_THRESHOLD,
    "copy_ngram_dice": COPY_THRESHOLD,
    "beat_duration_delta": BEAT_THRESHOLD,
}

_TOKEN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]|[a-z0-9]+")


@dataclass(frozen=True)
class CandidateSignature:
    candidate_id: str
    product_id: str
    hook_pattern: str = ""
    primary_action_keys: tuple[str, ...] = ()
    action_keys: tuple[str, ...] = ()
    copy_text: str = ""
    beat_durations: tuple[float, ...] = ()
    beat_order: tuple[str, ...] = ()
    scene_context: str = ""
    pacing_curve: str = ""
    caption_strategy: str = ""
    audio_strategy: str = ""
    forbidden_repeats: tuple[str, ...] = ()
    matrix_row_refs: tuple[str, ...] = ()
    sibling_similarity_budget: float = ACTION_THRESHOLD
    narrative_structure: str = ""
    evidence_keys: tuple[str, ...] = ()
    experiment_family_id: str = ""
    baseline_candidate_id: str = ""
    preregistered_variable: str = ""
    registration_ref: str = ""
    media_segment_ids: tuple[str, ...] = ()
    first_three_seconds_sha256: str = ""
    keyframe_sha256s: tuple[str, ...] = ()
    allowed_changed_fields: tuple[str, ...] = ()


def normalize_copy(value: str | None) -> str:
    """NFKC/lower/punctuation-normalized copy with stable whitespace."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    # Keep Chinese/Latin/digits and turn everything else into whitespace.
    text = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"[_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _copy_tokens(value: str | None) -> list[str]:
    return _TOKEN_RE.findall(normalize_copy(value))


def _ngrams(value: str | None) -> set[tuple[str, str]]:
    tokens = _copy_tokens(value)
    return set(zip(tokens, tokens[1:]))


def copy_ngram_dice(a: str | None, b: str | None) -> float:
    """Dice coefficient over adjacent Chinese-character/Latin-number 2-grams."""
    left, right = _ngrams(a), _ngrams(b)
    if not left and not right:
        return 0.0
    return 2.0 * len(left & right) / (len(left) + len(right))


def action_jaccard(a: Iterable[str] | None, b: Iterable[str] | None) -> float:
    left, right = set(str(x) for x in (a or ())), set(str(x) for x in (b or ()))
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _normalized_beats(beats: Sequence[float] | None) -> list[float]:
    values = [max(0.0, float(value)) for value in (beats or ())]
    total = sum(values)
    return [value / total for value in values] if total > 0 else []


def beat_duration_delta(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    """L1 delta between each candidate's normalized beat duration vectors."""
    left, right = _normalized_beats(a), _normalized_beats(b)
    return sum(abs(x - y) for x, y in zip_longest(left, right, fillvalue=0.0)) / max(sum(left), sum(right), 1.0)


def _coerce_signature(value: CandidateSignature | Mapping[str, Any]) -> CandidateSignature:
    if isinstance(value, CandidateSignature):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("candidate signature must be CandidateSignature or mapping")
    required = {
        "candidate_id", "product_id", "hook_pattern", "primary_action_keys",
        "action_keys", "copy_text", "beat_durations", "beat_order",
        "scene_context", "pacing_curve", "caption_strategy", "audio_strategy",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"candidate signature missing required fields: {', '.join(missing)}")
    def seq(*keys: str) -> tuple[str, ...]:
        for key in keys:
            raw = value.get(key)
            if raw is not None:
                if isinstance(raw, str):
                    return (raw,)
                return tuple(str(item) for item in raw)
        return ()
    beats = value.get("beat_durations", value.get("normalized_beats", value.get("beats", ())))
    if not isinstance(beats, (list, tuple)) or any(
        isinstance(item, bool) or not isinstance(item, (int, float))
        or not math.isfinite(item) or item < 0 for item in beats
    ):
        raise ValueError("candidate beat_durations must be finite non-negative numbers")
    return CandidateSignature(
        candidate_id=str(value.get("candidate_id") or value.get("id") or ""),
        product_id=str(value.get("product_id") or ""),
        hook_pattern=str(value.get("hook_pattern") or value.get("hook") or ""),
        primary_action_keys=seq("primary_action_keys", "primary_actions"),
        action_keys=seq("action_keys", "actions"),
        copy_text=str(value.get("copy_text") or value.get("screen_copy") or value.get("narration") or value.get("copy") or ""),
        beat_durations=tuple(float(item) for item in (beats or ())),
        beat_order=seq("beat_order"),
        scene_context=str(value.get("scene_context") or ""),
        pacing_curve=str(value.get("pacing_curve") or ""),
        caption_strategy=str(value.get("caption_strategy") or ""),
        audio_strategy=str(value.get("audio_strategy") or ""),
        forbidden_repeats=seq("forbidden_repeats"),
        matrix_row_refs=seq("matrix_row_refs"),
        sibling_similarity_budget=float(value.get("sibling_similarity_budget", ACTION_THRESHOLD)),
        narrative_structure=str(value.get("narrative_structure") or ""),
        evidence_keys=seq("evidence_keys"),
        experiment_family_id=str(value.get("experiment_family_id") or ""),
        baseline_candidate_id=str(value.get("baseline_candidate_id") or ""),
        preregistered_variable=str(value.get("preregistered_variable") or ""),
        registration_ref=str(value.get("registration_ref") or ""),
        media_segment_ids=seq("media_segment_ids"),
        first_three_seconds_sha256=str(value.get("first_three_seconds_sha256") or ""),
        keyframe_sha256s=seq("keyframe_sha256s"),
        allowed_changed_fields=seq("allowed_changed_fields"),
    )


def _axis_values(item: CandidateSignature) -> dict[str, Any]:
    return {
        "hook_pattern": item.hook_pattern, "scene_context": item.scene_context,
        "action_sequence": tuple(item.action_keys),
        "narrative_structure": item.narrative_structure or tuple(item.beat_order),
        "evidence_keys": tuple(item.evidence_keys),
    }


def _axes(a: CandidateSignature, b: CandidateSignature, *, cross_product: bool = False) -> list[str]:
    # Product names, type size, colour, caption/audio style and pacing are not
    # substantive creative axes. Missing values do not prove a difference.
    left, right = _axis_values(a), _axis_values(b)
    return [name for name in left if left[name] and right[name] and left[name] != right[name]]


def _experiment_key(item: CandidateSignature) -> tuple[str, ...] | None:
    values = (item.experiment_family_id, item.baseline_candidate_id, item.preregistered_variable, item.registration_ref)
    valid_axes = {"hook_pattern", "scene_context", "action_sequence", "narrative_structure", "evidence_keys"}
    return values if all(values) and item.preregistered_variable in valid_axes else None


def _experiment_control_changes(a: CandidateSignature, b: CandidateSignature) -> list[str]:
    """Preregistration names the exact fields one variable may change.

    Changing one effective axis does not authorize unrelated narration, audio,
    timing or presentation changes. Optional field allowances must agree with
    the baseline and stay within that variable's declared implementation.
    """
    required = {
        "hook_pattern": {"hook_pattern"}, "scene_context": {"scene_context"},
        "action_sequence": {"action_keys", "primary_action_keys"},
        "narrative_structure": {"narrative_structure", "beat_order"},
        "evidence_keys": {"evidence_keys", "primary_action_keys"},
    }
    related = {
        "hook_pattern": {"copy_text", "first_three_seconds_sha256", "media_segment_ids", "keyframe_sha256s"},
        "scene_context": {"media_segment_ids", "keyframe_sha256s"},
        "action_sequence": {"media_segment_ids", "keyframe_sha256s"},
        "narrative_structure": {"copy_text", "beat_durations"},
        "evidence_keys": {"copy_text", "media_segment_ids", "keyframe_sha256s"},
    }
    variable = a.preregistered_variable
    allowed = required.get(variable, set())
    requested = set(a.allowed_changed_fields)
    if requested != set(b.allowed_changed_fields) or not requested <= allowed | related.get(variable, set()):
        return ["registration_field_allowances_mismatch"]
    allowed = allowed | requested
    controls = (
        "product_id", "hook_pattern", "primary_action_keys", "action_keys", "copy_text",
        "beat_durations", "beat_order", "scene_context", "pacing_curve", "caption_strategy",
        "audio_strategy", "narrative_structure", "evidence_keys", "media_segment_ids",
        "first_three_seconds_sha256", "keyframe_sha256s",
    )
    return [key for key in controls if key not in allowed and getattr(a, key) != getattr(b, key)]


def _validate_signature(item: CandidateSignature) -> None:
    for name in ("candidate_id", "product_id", "hook_pattern", "scene_context", "pacing_curve", "caption_strategy", "audio_strategy"):
        if not str(getattr(item, name)).strip():
            raise ValueError(f"candidate {name} must be non-empty")
    for name in ("primary_action_keys", "action_keys", "beat_order"):
        values = getattr(item, name)
        if not values or any(not str(value).strip() for value in values):
            raise ValueError(f"candidate {name} must contain non-empty values")
    if not item.copy_text.strip():
        raise ValueError("candidate copy_text must be non-empty")
    if not item.beat_durations:
        raise ValueError("candidate beat_durations must be non-empty")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in item.beat_durations):
        raise ValueError("candidate beat_durations must be finite non-negative numbers")
    if isinstance(item.sibling_similarity_budget, bool) or not math.isfinite(item.sibling_similarity_budget) or not 0 <= item.sibling_similarity_budget <= 1:
        raise ValueError("sibling_similarity_budget must be between 0 and 1")


def compare_candidates(
    a: CandidateSignature | Mapping[str, Any],
    b: CandidateSignature | Mapping[str, Any],
    *,
    scope: str | None = None,
) -> dict[str, Any]:
    """Compare substantive axes, preserving existing metric thresholds as advice."""
    left, right = _coerce_signature(a), _coerce_signature(b)
    same_product = bool(left.product_id and left.product_id == right.product_id)
    scope = scope or ("same_product" if same_product else "cross_product")
    cross_product = scope == "cross_product"
    similarity_budget = min(left.sibling_similarity_budget, right.sibling_similarity_budget)
    if cross_product:
        action = action_jaccard(left.primary_action_keys, right.primary_action_keys)
        copy = None
        beat = None
        compared_axes = ["hook_pattern", "primary_action_keys"]
        high = left.hook_pattern == right.hook_pattern and action >= similarity_budget
    else:
        action = action_jaccard(left.action_keys, right.action_keys)
        copy = copy_ngram_dice(left.copy_text, right.copy_text)
        beat = beat_duration_delta(left.beat_durations, right.beat_durations)
        compared_axes = ["action_keys", "copy_text", "beat_durations"]
        high = action >= similarity_budget and copy >= COPY_THRESHOLD and beat <= BEAT_THRESHOLD
    differing_axes = _axes(left, right, cross_product=cross_product)
    experiment = _experiment_key(left)
    controlled = bool(experiment and experiment == _experiment_key(right))
    direct_baseline = controlled and left.baseline_candidate_id in {left.candidate_id, right.candidate_id}
    unregistered_changes = _experiment_control_changes(left, right) if controlled else []
    if controlled:
        raw_left, raw_right = _axis_values(left), _axis_values(right)
        all_changed = [key for key in raw_left if raw_left[key] != raw_right[key]]
        primary_fixed = left.primary_action_keys == right.primary_action_keys or left.preregistered_variable in {"action_sequence", "evidence_keys"}
        status = "controlled_experiment" if direct_baseline and same_product and primary_fixed and not unregistered_changes and all_changed == [left.preregistered_variable] else "needs_redesign"
    elif high:
        status = "high_similarity"
    elif len(differing_axes) < 3:
        status = "needs_redesign"
    else:
        status = "distinct"
    segment_overlap = action_jaccard(left.media_segment_ids, right.media_segment_ids) if left.media_segment_ids and right.media_segment_ids else None
    opening_repeated = left.first_three_seconds_sha256 == right.first_three_seconds_sha256 if left.first_three_seconds_sha256 and right.first_three_seconds_sha256 else None
    keyframe_overlap = action_jaccard(left.keyframe_sha256s, right.keyframe_sha256s) if left.keyframe_sha256s and right.keyframe_sha256s else None
    warnings = []
    if high:
        warnings.append("metric_high_similarity")
    if segment_overlap is not None and segment_overlap >= ACTION_THRESHOLD:
        warnings.append("media_segment_overlap")
    if opening_repeated:
        warnings.append("first_three_seconds_repeated")
    if keyframe_overlap is not None and keyframe_overlap > 0:
        warnings.append("keyframe_overlap")
    if controlled and not direct_baseline:
        warnings.append("baseline_comparison_required")
    result: dict[str, Any] = {
        "candidate_a": left.candidate_id,
        "candidate_b": right.candidate_id,
        "product_a": left.product_id,
        "product_b": right.product_id,
        "scope": scope,
        "compared_axes": compared_axes,
        "differing_axes": differing_axes,
        "action_jaccard": round(action, 6),
        "copy_ngram_dice": None if copy is None else round(copy, 6),
        "beat_duration_delta": None if beat is None else round(beat, 6),
        "sibling_similarity_budget": similarity_budget,
        "status": status,
        "effective_differing_axes": differing_axes,
        "minimum_effective_axes": 1 if controlled else 3,
        "baseline_candidate_id": left.baseline_candidate_id if controlled else None,
        "experiment_family_id": left.experiment_family_id if controlled else None,
        "media_segment_overlap": segment_overlap,
        "first_three_seconds_repeated": opening_repeated,
        "keyframe_overlap": keyframe_overlap,
        "warning_fields": warnings,
        "advisory_only": True,
        "human_review_required": True,
        "unregistered_changed_fields": unregistered_changes,
    }
    return result


def build_differentiation_plan(
    batch_id: str,
    candidates: Sequence[CandidateSignature | Mapping[str, Any]],
    *,
    research_refs: Sequence[Mapping[str, Any]] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    signatures = [_coerce_signature(item) for item in candidates]
    if not signatures:
        raise ValueError("differentiation_plan requires at least one candidate")
    for item in signatures:
        _validate_signature(item)
    candidate_ids = [item.candidate_id for item in signatures]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate_id values must be unique")
    comparisons: list[dict[str, Any]] = []
    by_id = {item.candidate_id: item for item in signatures}
    warnings = sorted({f"missing_experiment_baseline:{item.baseline_candidate_id}" for item in signatures
                       if _experiment_key(item) and item.baseline_candidate_id not in by_id})
    for index, left in enumerate(signatures):
        for right in signatures[index + 1 :]:
            key = _experiment_key(left)
            if key and key == _experiment_key(right):
                baseline = by_id.get(left.baseline_candidate_id)
                if baseline and baseline not in (left, right):
                    # Each variant is compared to the registered baseline,
                    # never to a sibling that already accumulated a change.
                    continue
                if baseline is right:
                    comparisons.append(compare_candidates(right, left))
                    continue
            same = left.product_id == right.product_id
            comparisons.append(compare_candidates(left, right, scope="same_product" if same else "cross_product"))
    plan = {
        "version": "1.0",
        "batch_id": str(batch_id),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "research_refs": [dict(ref) for ref in (research_refs or ())],
        "thresholds": dict(THRESHOLDS),
        "candidate_signatures": [
            {**{key: list(value) if isinstance(value, tuple) else value for key, value in asdict(item).items()}, "copy_text": normalize_copy(item.copy_text)}
            for item in signatures
        ],
        "sibling_comparisons": comparisons,
        "warnings": warnings,
        "status": "needs_redesign" if warnings or any(row["status"] in {"high_similarity", "needs_redesign"} for row in comparisons) else "pass",
    }
    sealed = attach_hashes(plan)
    validate_artifact("differentiation_plan", sealed)
    return sealed


def build_dedup_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    comparisons = [dict(row) for row in (plan.get("sibling_comparisons") or []) if isinstance(row, Mapping)]
    return {
        "thresholds": dict(plan.get("thresholds") or THRESHOLDS),
        "comparisons": comparisons,
        "status": "needs_redesign" if plan.get("warnings") or any(row.get("status") in {"high_similarity", "needs_redesign"} for row in comparisons) else "pass",
    }


def validate_batch_plan_owner(project_dir, batch: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the persisted plan addressed by a batch root's sole ref."""
    from pathlib import Path
    root = Path(project_dir).resolve()
    ref = batch.get("differentiation_plan_ref")
    if not isinstance(ref, Mapping) or ref.get("name") != "differentiation_plan":
        raise ValueError("batch root requires differentiation_plan_ref")
    raw_path = str(ref.get("path") or "")
    if not raw_path.startswith("artifacts/") or Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
        raise ValueError("invalid differentiation_plan_ref path")
    path = (root / raw_path).resolve()
    try:
        path.relative_to((root / "artifacts").resolve())
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("cannot read differentiation plan owner artifact") from exc
    validate_artifact("differentiation_plan", plan)
    if not verify_hashes(plan).valid or plan.get("artifact_sha256") != ref.get("artifact_sha256"):
        raise ValueError("differentiation plan owner hash mismatch")
    if str(plan.get("batch_id") or "") != str(batch.get("batch_id") or ""):
        raise ValueError("differentiation plan owner batch_id mismatch")
    return plan


__all__ = [
    "ACTION_THRESHOLD", "COPY_THRESHOLD", "BEAT_THRESHOLD", "THRESHOLDS",
    "CandidateSignature", "normalize_copy", "copy_ngram_dice", "action_jaccard",
    "beat_duration_delta", "compare_candidates", "build_differentiation_plan",
    "build_dedup_summary",
    "validate_batch_plan_owner",
]
