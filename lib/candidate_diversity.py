"""Pure candidate diversity planning, fingerprinting, and gating.

Deterministic: the same inputs produce the same fingerprints across restarts
(JSON is canonicalized with sorted keys before hashing). Diversity starts in
planning — a candidate must change at least three dimensions relative to the
batch baseline and at least three structural shots relative to each sibling;
an opening-only change is rejected. Shared source media alone is not a failure.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

DIMENSION_KEYS: tuple[str, ...] = (
    "hook_type",
    "narrative_structure",
    "visual_grammar",
    "pacing_profile",
    "evidence_strategy",
    "asset_strategy",
)

MIN_CHANGED_DIMENSIONS = 3
MIN_STRUCTURAL_SHOTS = 3
OPENING_WINDOW = {"start_seconds": 0, "end_seconds": 3}

# The default catalogue is intentionally small and opinionated.  It gives a
# new batch a legible creative spread before an operator approves any paid
# asset or sample work.  Values are strings because they are carried into
# proposal/script prompts as human-readable creative intent.
DEFAULT_VARIANT_STRATEGIES: tuple[dict[str, Any], ...] = (
    {
        "strategy_id": "result_first",
        "hook_type": "result_first",
        "narrative_structure": "result-proof-cta",
        "visual_grammar": "hero-product-macro",
        "pacing_profile": "steady-reveal",
        "evidence_strategy": "proof_after_claim",
        "asset_strategy": "product_detail_led",
        "shot_types": ("shot_order", "source_window", "evidence_role"),
    },
    {
        "strategy_id": "problem_first",
        "hook_type": "problem_first",
        "narrative_structure": "problem-tension-solution",
        "visual_grammar": "contrast-before-after",
        "pacing_profile": "tension-release",
        "evidence_strategy": "pain_point_then_proof",
        "asset_strategy": "context_to_product",
        "shot_types": ("source_window", "duration", "asset_role"),
    },
    {
        "strategy_id": "evidence_first",
        "hook_type": "evidence_first",
        "narrative_structure": "claim-evidence-explanation",
        "visual_grammar": "demonstration-led",
        "pacing_profile": "measured-proof",
        "evidence_strategy": "evidence_first",
        "asset_strategy": "demonstration_led",
        "shot_types": ("evidence_role", "shot_order", "caption_layout"),
    },
    {
        "strategy_id": "high_density",
        "hook_type": "high_density",
        "narrative_structure": "rapid-benefit-stack",
        "visual_grammar": "editorial-collage",
        "pacing_profile": "high_density",
        "evidence_strategy": "multi_fact_stack",
        "asset_strategy": "coverage_breadth",
        "shot_types": ("duration", "shot_order", "visual_grammar"),
    },
    {
        "strategy_id": "product_craft",
        "hook_type": "product_craft",
        "narrative_structure": "craft-detail-payoff",
        "visual_grammar": "material-and-light",
        "pacing_profile": "premium-breathing-room",
        "evidence_strategy": "quality_detail_proof",
        "asset_strategy": "craft_detail_led",
        "shot_types": ("source_window", "visual_grammar", "asset_role"),
    },
)

_DEFAULT_BASELINE = {
    "hook_type": "baseline_hook",
    "narrative_structure": "baseline_structure",
    "visual_grammar": "baseline_visual",
    "pacing_profile": "baseline_pacing",
    "evidence_strategy": "baseline_evidence",
    "asset_strategy": "baseline_assets",
}


def default_variant_strategy(
    candidate_index: int = 0, direction: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return a stable default strategy, honoring an explicit hook direction."""
    direction = direction if isinstance(direction, Mapping) else {}
    requested = str(direction.get("hook") or direction.get("hook_type") or "").strip()
    for strategy in DEFAULT_VARIANT_STRATEGIES:
        if requested == strategy["strategy_id"]:
            return dict(strategy)
    return dict(DEFAULT_VARIANT_STRATEGIES[int(candidate_index) % len(DEFAULT_VARIANT_STRATEGIES)])


def build_default_variant_plan(
    batch_id: str,
    candidate_id: str,
    candidate_index: int = 0,
    *,
    baseline_ref: Mapping[str, Any] | None = None,
    direction: Mapping[str, Any] | None = None,
    variant_revision: int = 1,
    index: int | None = None,
) -> dict[str, Any]:
    """Build the deterministic plan used by a new candidate before production.

    ``index`` is accepted as a compatibility alias for callers that use the
    batch position terminology.  The result is intentionally awaiting human
    approval; the creative-lock bundle is the approval authority.
    """
    if index is not None:
        candidate_index = index
    strategy = default_variant_strategy(candidate_index, direction)
    baseline = dict(baseline_ref or {"name": "research_synthesis", "path": "artifacts/research_synthesis.json"})
    dimensions = {
        key: {
            "value": str(strategy[key]),
            "baseline_value": str(_DEFAULT_BASELINE[key]),
            "changed": str(strategy[key]) != str(_DEFAULT_BASELINE[key]),
            "rationale": f"默认差异策略 {strategy['strategy_id']}：{key} 发生明确变化",
        }
        for key in DIMENSION_KEYS
    }
    ranges = ((0, 3), (3, 7), (7, 12))
    shot_differences = [
        {
            "shot_id": f"s{i + 1}",
            "difference_type": strategy["shot_types"][i],
            "evidence_class": "structural",
            "evidence_ref": {
                "kind": "default_variant_strategy",
                "path": f"variant-strategies/{strategy['strategy_id']}/shot-{i + 1}",
            },
            "time_range": {"start_seconds": start, "end_seconds": end},
        }
        for i, (start, end) in enumerate(ranges)
    ]
    shot_differences.append({
        "shot_id": "s4",
        "difference_type": "visual_grammar",
        "evidence_class": "visual",
        "evidence_ref": {
            "kind": "default_variant_strategy",
            "path": f"variant-strategies/{strategy['strategy_id']}/visual-grammar",
        },
        "time_range": {"start_seconds": 3, "end_seconds": 7},
    })
    return build_variant_plan(
        batch_id=batch_id,
        candidate_id=candidate_id,
        variant_revision=variant_revision,
        baseline_ref=baseline,
        dimensions=dimensions,
        shot_differences=shot_differences,
        opening_only_change=False,
        provenance={
            "author": "candidate-diversity-producer",
            "strategy_id": strategy["strategy_id"],
            "generated_by": "build_default_variant_plan",
        },
        approval_status="awaiting_human",
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _dim(dimensions: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = dimensions.get(key) if isinstance(dimensions, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def changed_dimension_count(dimensions: Mapping[str, Any]) -> int:
    """Number of the six variation dimensions marked changed=true."""
    return sum(1 for key in DIMENSION_KEYS if _dim(dimensions, key).get("changed"))


def compute_difference_fingerprint(
    dimensions: Mapping[str, Any], shot_differences: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Deterministic structure/visual/timing hashes and counts.

    structure_hash/visual_hash are the source of truth for pairwise structural
    comparison; timing_hash captures shot order/duration/time ranges.
    """
    rows = list(shot_differences or [])
    structural = [
        {"shot_id": r.get("shot_id"), "difference_type": r.get("difference_type"),
         "evidence_ref": r.get("evidence_ref")}
        for r in rows if r.get("evidence_class") == "structural"
    ]
    visual = [
        {"shot_id": r.get("shot_id"), "difference_type": r.get("difference_type")}
        for r in rows if r.get("evidence_class") == "visual"
    ]
    timing = [
        {"shot_id": r.get("shot_id"), "difference_type": r.get("difference_type"),
         "time_range": r.get("time_range")}
        for r in rows
    ]
    return {
        "structure_hash": _sha256(structural),
        "visual_hash": _sha256(visual),
        "timing_hash": _sha256(timing),
        "changed_dimension_count": changed_dimension_count(dimensions),
        "structural_shot_count": len(structural),
    }


def build_variant_plan(
    *,
    batch_id: str,
    candidate_id: str,
    variant_revision: int,
    baseline_ref: Mapping[str, Any],
    dimensions: Mapping[str, Any],
    shot_differences: Sequence[Mapping[str, Any]],
    opening_only_change: bool = False,
    provenance: Mapping[str, Any] | None = None,
    approval_status: str = "awaiting_human",
) -> dict[str, Any]:
    """Assemble a candidate_variant_plan with a computed fingerprint."""
    return {
        "version": "1.0",
        "batch_id": batch_id,
        "candidate_id": candidate_id,
        "variant_revision": variant_revision,
        "baseline_ref": dict(baseline_ref),
        "dimensions": dict(dimensions),
        "shot_differences": [dict(row) for row in shot_differences],
        "difference_fingerprint": compute_difference_fingerprint(dimensions, shot_differences),
        "opening_window": dict(OPENING_WINDOW),
        "opening_only_change": bool(opening_only_change),
        "provenance": dict(provenance or {}),
        "approval_status": approval_status,
    }


def compare_candidate_pair(
    plan_a: Mapping[str, Any], plan_b: Mapping[str, Any]
) -> dict[str, Any]:
    """Pairwise diversity result (the authoritative gate for selection).

    Passes only when the symmetric dimension difference count is >= 3, the
    structural shot difference count is >= 3, and neither plan is an
    opening-only change.
    """
    dims_a = plan_a.get("dimensions") if isinstance(plan_a.get("dimensions"), Mapping) else {}
    dims_b = plan_b.get("dimensions") if isinstance(plan_b.get("dimensions"), Mapping) else {}
    changed_dims = sum(
        1 for key in DIMENSION_KEYS
        if _dim(dims_a, key).get("value") != _dim(dims_b, key).get("value")
    )
    shots_a = plan_a.get("shot_differences") if isinstance(plan_a.get("shot_differences"), list) else []
    shots_b = plan_b.get("shot_differences") if isinstance(plan_b.get("shot_differences"), list) else []
    def structural_signature(row: Mapping[str, Any]) -> str:
        return _canonical({
            "shot_id": row.get("shot_id"),
            "difference_type": row.get("difference_type"),
            "evidence_ref": row.get("evidence_ref"),
        })

    structural_a = {structural_signature(r) for r in shots_a if r.get("evidence_class") == "structural"}
    structural_b = {structural_signature(r) for r in shots_b if r.get("evidence_class") == "structural"}
    # Count changed structural slots, rather than the intersection of IDs.
    # Identical s1/s2/s3 plans therefore score 0; three wholly different shots
    # score 3 and satisfy the minimum.
    structural_common = max(len(structural_a - structural_b), len(structural_b - structural_a))

    fp_a = plan_a.get("difference_fingerprint") if isinstance(plan_a.get("difference_fingerprint"), Mapping) else {}
    fp_b = plan_b.get("difference_fingerprint") if isinstance(plan_b.get("difference_fingerprint"), Mapping) else {}
    visual_identical = fp_a.get("visual_hash") == fp_b.get("visual_hash")
    passes = (
        changed_dims >= MIN_CHANGED_DIMENSIONS
        and structural_common >= MIN_STRUCTURAL_SHOTS
        and not bool(plan_a.get("opening_only_change"))
        and not bool(plan_b.get("opening_only_change"))
    )
    return {
        "candidate_a": str(plan_a.get("candidate_id") or ""),
        "candidate_b": str(plan_b.get("candidate_id") or ""),
        "changed_dimensions": changed_dims,
        "structural_shot_count": structural_common,
        "visual_risk": "high" if visual_identical else "low",
        "passes": passes,
    }


def assert_candidate_variant_ready(plan: Mapping[str, Any] | None) -> list[str]:
    """Structural diversity precondition (empty result = ready).

    Returns the blocking structural failures for a candidate variant plan.
    Callers enforce the rollout mode: ``hard_gate`` rejects on failures (and
    blocks paid calls), ``warning`` records a warning and continues. Missing
    plan is always a structural failure.
    """
    if not isinstance(plan, Mapping):
        return ["缺少候选差异计划（candidate_variant_plan）"]
    return selection_diversity_failures(plan, [])["structural_failures"]


def selection_diversity_failures(
    plan: Mapping[str, Any], sibling_plans: Sequence[Mapping[str, Any]]
) -> dict[str, list[str]]:
    """Hard diversity checks for selection, split by class.

    Returns separate ``structural_failures`` (blocking) and
    ``visual_similarity_warnings`` (advisory) so the gate can surface them
    distinctly and the UI never collapses them into one opaque message.
    """
    structural_failures: list[str] = []
    visual_similarity_warnings: list[str] = []

    if changed_dimension_count(plan.get("dimensions")) < MIN_CHANGED_DIMENSIONS:
        structural_failures.append("至少需变更三个差异维度")
    if bool(plan.get("opening_only_change")):
        structural_failures.append("仅改变前三秒（opening_only_change），不构成候选差异")
    rows = plan.get("shot_differences") if isinstance(plan.get("shot_differences"), list) else []
    computed_fp = compute_difference_fingerprint(
        plan.get("dimensions") if isinstance(plan.get("dimensions"), Mapping) else {},
        rows,
    )
    fp = plan.get("difference_fingerprint") if isinstance(plan.get("difference_fingerprint"), Mapping) else {}
    if any(fp.get(key) != computed_fp[key] for key in computed_fp):
        structural_failures.append("差异指纹与维度/镜头证据不一致")
    if computed_fp["structural_shot_count"] < MIN_STRUCTURAL_SHOTS:
        structural_failures.append("结构镜头差异少于三个")

    visual_hash = fp.get("visual_hash")
    for sibling in sibling_plans:
        sibling_fp = sibling.get("difference_fingerprint") if isinstance(sibling.get("difference_fingerprint"), Mapping) else {}
        if visual_hash and sibling_fp.get("visual_hash") == visual_hash:
            visual_similarity_warnings.append(
                f"与候选 {sibling.get('candidate_id')} 视觉指纹一致（需人工复核是否同质化）"
            )
            break
    return {
        "structural_failures": structural_failures,
        "visual_similarity_warnings": visual_similarity_warnings,
    }
