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


def per_dimension_stats(goldset: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """每维度相关性统计（评审缺口 #6）：{dimension_id: tier 分布与总数}。

    只统计 pointwise 中有数值分数的维度；n>=100 的维度才计入发布门槛。
    """
    stats: dict[str, dict[str, int]] = {}
    for sample in goldset.get("samples", []):
        if not isinstance(sample, Mapping):
            continue
        labels = sample.get("labels") if isinstance(sample.get("labels"), Mapping) else {}
        pointwise = labels.get("pointwise") if isinstance(labels.get("pointwise"), Mapping) else {}
        tier = str(sample.get("tier") or "unknown")
        for dim, value in pointwise.items():
            if not isinstance(value, (int, float)):
                continue
            entry = stats.setdefault(
                str(dim),
                {"total": 0, "gold": 0, "silver": 0, "bad": 0, "hard_negative": 0},
            )
            entry["total"] += 1
            if tier in entry:
                entry[tier] += 1
    return stats


def _annotator_labels(
    goldset: Mapping[str, Any], annotator_id: str
) -> dict[str, str]:
    """该标注者的 pointwise 分数离散化：>=8 pass / <8 fail（用于 kappa）。"""
    labels: dict[str, str] = {}
    for sample in goldset.get("samples", []):
        if not isinstance(sample, Mapping):
            continue
        annotators = sample.get("annotators") or []
        if not any(
            isinstance(item, Mapping) and item.get("annotator_id") == annotator_id
            for item in annotators
        ):
            continue
        pointwise = (
            sample.get("labels", {}).get("pointwise")
            if isinstance(sample.get("labels"), Mapping) else None
        )
        if not isinstance(pointwise, Mapping):
            continue
        for dim, value in pointwise.items():
            if isinstance(value, (int, float)):
                labels[f"{sample['sample_id']}:{dim}"] = "pass" if float(value) >= 8.0 else "fail"
    return labels


def calibration_report(
    goldset: Mapping[str, Any],
    *,
    annotator_a: str = "human",
    annotator_b: str | None = None,
    min_samples_per_dimension: int = 100,
    min_kappa: float = 0.6,
) -> dict[str, Any]:
    """校准报告：每维样本统计 + 双人 kappa + 发布门槛判定。

    releasable = 每个维度 n >= min_samples_per_dimension 且（无双人标注或
    kappa >= min_kappa）。校准不足时 optimization 只能跑 shadow mode。
    """
    stats = per_dimension_stats(goldset)
    dimensions: dict[str, dict[str, Any]] = {}
    for dim in sorted(stats):
        counts = stats[dim]
        dimensions[dim] = {
            "total": counts["total"],
            "gold": counts["gold"],
            "silver": counts["silver"],
            "bad": counts["bad"],
            "hard_negative": counts["hard_negative"],
            "sufficient": counts["total"] >= min_samples_per_dimension,
        }
    kappa: float | None = None
    kappa_note = "未配置双人标注"
    if annotator_b:
        a_labels = _annotator_labels(goldset, annotator_a)
        b_labels = _annotator_labels(goldset, annotator_b)
        if a_labels and b_labels:
            kappa = cohens_kappa(a_labels, b_labels)
            kappa_note = f"cohens kappa（{annotator_a} vs {annotator_b}）"
        else:
            kappa_note = "双人标注数据不足，无法计算 kappa"
    sufficient = bool(dimensions) and all(
        item["sufficient"] for item in dimensions.values()
    )
    kappa_ok = kappa is not None and float(kappa) >= min_kappa
    double_annotated = kappa is not None
    return {
        "judge_version": goldset.get("judge_version"),
        "rubric_version": goldset.get("rubric_version"),
        "min_samples_per_dimension": min_samples_per_dimension,
        "min_kappa": min_kappa,
        "sample_count": len(goldset.get("samples") or []),
        "dimensions": dimensions,
        "kappa": kappa,
        "kappa_note": kappa_note,
        "sufficient": sufficient,
        "kappa_ok": kappa_ok,
        "double_annotated": double_annotated,
        # 发布门槛：每维 n 达标 + 双人标注 + kappa 达标（judge-calibration skill）
        "releasable": sufficient and double_annotated and kappa_ok,
    }


def is_judge_releasable(
    goldset: Mapping[str, Any],
    *,
    annotator_a: str = "human",
    annotator_b: str | None = None,
    min_samples_per_dimension: int = 100,
    min_kappa: float = 0.6,
) -> tuple[bool, dict[str, Any]]:
    """judge 是否允许进入生产自动门禁。返回 (releasable, calibration_report)。"""
    report = calibration_report(
        goldset,
        annotator_a=annotator_a,
        annotator_b=annotator_b,
        min_samples_per_dimension=min_samples_per_dimension,
        min_kappa=min_kappa,
    )
    return report["releasable"], report


def assert_judge_releasable(
    goldset: Mapping[str, Any],
    *,
    annotator_a: str = "human",
    annotator_b: str | None = None,
    min_samples_per_dimension: int = 100,
    min_kappa: float = 0.6,
) -> None:
    """发布前阻断（评审缺口 #6）：校准不足时禁止启用生产自动门禁。"""
    releasable, report = is_judge_releasable(
        goldset,
        annotator_a=annotator_a,
        annotator_b=annotator_b,
        min_samples_per_dimension=min_samples_per_dimension,
        min_kappa=min_kappa,
    )
    if not releasable:
        raise ValueError(
            "judge 校准不足，禁止进入生产自动门禁（只能 shadow mode）："
            f"sufficient={report['sufficient']}, kappa_ok={report['kappa_ok']}, "
            f"sample_count={report['sample_count']}"
        )


def _seal(goldset: dict[str, Any]) -> dict[str, Any]:
    sealed = attach_hashes(goldset)
    validate_artifact("gold_sample", sealed)
    return sealed
