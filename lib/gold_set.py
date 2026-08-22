"""Gold sample set and judge calibration statistics (Design_Review P2).

Four tiers (Gold / Silver / Bad / Hard Negative), leakage-free Group Split,
Cohen's kappa for annotator agreement, bootstrap confidence intervals, and
replay scoring for judge version governance. Pure functions — the caller
injects the judge callable so replay stays deterministic in tests and auditable
in production.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact

TIERS = ("gold", "silver", "bad", "hard_negative")
SPLITS = ("train", "dev", "test")


def create_gold_set(
    goldset_id: str,
    *,
    project_id: str = "default",
    judge_version: str,
    rubric_version: str,
) -> dict[str, Any]:
    goldset = {
        "version": "1.0",
        "goldset_id": goldset_id,
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "judge_version": judge_version,
        "rubric_version": rubric_version,
        "samples": [],
    }
    return _seal(goldset)


def add_sample(
    goldset: Mapping[str, Any],
    *,
    sample_id: str,
    video_ref: Mapping[str, Any],
    tier: str,
    group_key: str,
    labels: Mapping[str, Any] | None = None,
    annotator_id: str = "human",
    split: str | None = None,
) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}")
    if split not in (None, *SPLITS):
        raise ValueError(f"split must be one of {SPLITS} or None")
    if any(item["sample_id"] == sample_id for item in goldset["samples"]):
        raise ValueError(f"duplicate sample_id {sample_id!r}")
    labels = dict(labels or {})
    failure_tags = list(labels.get("failure_tags") or [])
    if tier == "hard_negative" and not failure_tags:
        raise ValueError("hard_negative samples must carry failure_tags")
    normalized = {
        "sample_id": sample_id,
        "video_ref": {"path": str(video_ref["path"]),
                      **({"artifact_sha256": str(video_ref["artifact_sha256"])} if video_ref.get("artifact_sha256") else {})},
        "tier": tier,
        "group_key": str(group_key),
        "labels": {
            "pointwise": dict(labels.get("pointwise") or {}),
            "pairwise_refs": list(labels.get("pairwise_refs") or []),
            "claims_qa": list(labels.get("claims_qa") or []),
            "failure_tags": failure_tags,
            "expert_reason": str(labels.get("expert_reason") or ""),
            "human_adoption": labels.get("human_adoption"),
            "online_outcome": labels.get("online_outcome"),
        },
        "annotators": [{"annotator_id": str(annotator_id), "role": "primary",
                        "annotated_at": datetime.now(timezone.utc).isoformat()}],
        "split": split,
    }
    updated = dict(goldset)
    updated["samples"] = [*goldset["samples"], normalized]
    return _seal(updated)


def assign_group_split(
    goldset: Mapping[str, Any],
    *,
    seed: int = 20260822,
    ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
) -> dict[str, Any]:
    """Deterministic Group Split: whole group_key lands in one split only."""
    train_ratio, dev_ratio, _ = ratios
    groups = sorted({item["group_key"] for item in goldset["samples"]})
    rng = random.Random(seed)
    rng.shuffle(groups)
    group_split: dict[str, str] = {}
    train_end = int(math.ceil(len(groups) * train_ratio))
    dev_end = train_end + int(math.ceil(len(groups) * dev_ratio))
    for index, group in enumerate(groups):
        group_split[group] = "train" if index < train_end else "dev" if index < dev_end else "test"
    updated = dict(goldset)
    updated["samples"] = [
        {**item, "split": group_split[item["group_key"]]}
        for item in goldset["samples"]
    ]
    return _seal(updated)


def cohens_kappa(annotator_a: Mapping[str, str], annotator_b: Mapping[str, str]) -> float:
    """Cohen's kappa over shared sample ids with categorical labels."""
    keys = sorted(set(annotator_a) & set(annotator_b))
    if not keys:
        return 0.0
    n = len(keys)
    counts: dict[tuple[str, str], int] = {}
    a_margin: dict[str, int] = {}
    b_margin: dict[str, int] = {}
    for key in keys:
        pair = (str(annotator_a[key]), str(annotator_b[key]))
        counts[pair] = counts.get(pair, 0) + 1
        a_margin[pair[0]] = a_margin.get(pair[0], 0) + 1
        b_margin[pair[1]] = b_margin.get(pair[1], 0) + 1
    po = sum(counts[(label, label)] for label in set(a_margin) & set(b_margin)) / n
    pe = sum((a_margin[label] / n) * (b_margin[label] / n) for label in set(a_margin) | set(b_margin) if label in a_margin and label in b_margin)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def bootstrap_ci(values: list[float], *, seed: int = 0, iterations: int = 2000, alpha: float = 0.05) -> dict[str, float]:
    """Mean and percentile bootstrap confidence interval."""
    if not values:
        return {"mean": float("nan"), "low": float("nan"), "high": float("nan")}
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(iterations):
        sample = [rng.choice(values) for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    low_index = int(iterations * alpha / 2)
    high_index = int(iterations * (1 - alpha / 2)) - 1
    return {
        "mean": sum(values) / len(values),
        "low": means[low_index],
        "high": means[high_index],
    }


def replay_score(
    goldset: Mapping[str, Any],
    *,
    judge_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    judge_version: str,
    rubric_version: str,
    score_key: str = "score",
) -> dict[str, Any]:
    """Replay a judge over the gold set and report drift vs stored labels.

    `judge_fn` receives a sample dict and returns a mapping with at least
    `score_key` (0-10). The replay report flags degradation when a stored-pass
    sample now scores as fail — the hard-gate regression signal.
    """
    rows = []
    hard_gate_failures_increased = 0
    score_deltas: list[float] = []
    for sample in goldset["samples"]:
        judge_result = judge_fn(dict(sample))
        judge_score = float(judge_result.get(score_key, 0) or 0)
        stored_scores = [v for v in sample["labels"]["pointwise"].values() if isinstance(v, (int, float))]
        stored = (sum(stored_scores) / len(stored_scores)) if stored_scores else None
        delta = (judge_score - stored) if stored is not None else None
        stored_pass = sample["tier"] in {"gold", "silver"}
        judge_fail = judge_result.get("pass") is False or judge_score < 6.0
        if stored_pass and judge_fail:
            hard_gate_failures_increased += 1
        if delta is not None:
            score_deltas.append(delta)
        rows.append({
            "sample_id": sample["sample_id"],
            "tier": sample["tier"],
            "stored_mean_score": stored,
            "judge_score": judge_score,
            "delta": delta,
        })
    return {
        "version": "1.0",
        "goldset_id": goldset["goldset_id"],
        "judge_version": judge_version,
        "rubric_version": rubric_version,
        "replayed_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(rows),
        "score_delta_bootstrap": bootstrap_ci(score_deltas) if score_deltas else None,
        "hard_gate_failure_increase": hard_gate_failures_increased,
        "degradation_flags": {
            "hard_gate_failure_increase": hard_gate_failures_increased > 0,
            "grounding_drop": None,
        },
        "rows": rows,
    }


def _seal(goldset: dict[str, Any]) -> dict[str, Any]:
    sealed = attach_hashes(goldset)
    validate_artifact("gold_sample", sealed)
    return sealed
