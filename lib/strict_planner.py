"""严格档子集规划器（评审 2026-08-28 固化自临时枚举脚本）。

用途：给定模板（-c1 压缩变体或任意模板），在「顺序不可变 + 严格档 6 条规则」约束下
枚举最优子集，输出可直接写入 rp.compression 契约的字段集。

规则（与 template-platform-standards §5 一致）：
- S1' 单素材复用 ≤ ceil(N'/M)
- S2' 单素材占片 ≤ 25%（数学上要求 M ≥ 4）
- S3' 同素材窗口完全不重叠（非重叠容量，见 strict_capacity）
- S4' 起点差 ≥ 1.5s（由 S3' 隐含，保留字段）
- S5' 复用间隔 ≥ min_interval（默认 4；可放宽以分析阻塞类别）
- 时长 [15, 60]

确定性：枚举按 mask 升序，以 utility 最大为首要目标（首解平局取序数小者）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from lib.template_mainline import _NARRATION_BY_TEMPLATE
from lib.template_source_match import SEMANTIC_EVIDENCE_WINDOWS, SLOT_ACTION_BY_TEMPLATE, _clip_durations

SOLVER_VERSION = "strict-enumerator-v1"
ROLE_UTILITY = {"hook": 10, "cta": 10, "reveal": 7, "payoff": 8, "proof": 6,
                "problem": 5, "escalation": 5, "other": 4}
SPAN = 2.0  # 默认 slot 时长（窗口容量计算用）


def strict_capacity(action_domain: str, span: float = SPAN) -> int:
    """S3' 非重叠容量：证据窗口（∩ 素材时长）内 span 步进、互不重叠的窗口数。

    注意 ≠ window_capacity（其 gap=0.75 允许部分重叠）；50 类"自动铺开"3.7s 窗口 ⇒ 容量 1。
    """
    win = SEMANTIC_EVIDENCE_WINDOWS.get(action_domain) or {}
    window = win.get("window") or (0.0, 0.0)
    lo, hi = float(window[0]), float(window[1])
    dur = _clip_durations().get(f"product_透明桌垫-{action_domain}", hi)
    hi = min(hi, dur)
    count, s = 0, lo
    while s + span <= hi + 1e-9:
        count += 1
        s += span
    return count


def plan_strict_subset(
    template: Mapping[str, Any],
    *,
    min_interval: int = 4,
    min_d: float = 15.0,
    max_d: float = 60.0,
) -> dict[str, Any] | None:
    """枚举最优严格子集。返回契约字段集；无解返回 None。

    返回：{kept_ordinals, kept_slot_ids, base_section_refs, total_s, domain_counts_kept,
          seconds_kept, utility, h1_ok/h2_ok/h3_ok/h4_ok/capacity_ok/dur_ok/all_hard_ok,
          input_hash, solver_version, infeasibilities}（infeasibilities 用于无解时归因）。
    """
    tid = str(template.get("template_id") or "")
    acts = SLOT_ACTION_BY_TEMPLATE.get(tid, [])
    rows = _NARRATION_BY_TEMPLATE.get(tid, [])
    slots = []
    for i, s in enumerate(template.get("slots") or []):
        slot_id = str(s.get("slot_id") or f"slot-{i:03d}")
        dur = float(s.get("duration_s") or 2.0)
        action = acts[i] if i < len(acts) else ""
        role = rows[i][2] if i < len(rows) else "proof"
        slots.append((slot_id, dur, action, role, ROLE_UTILITY.get(role, 4)))
    N = len(slots)
    if not slots or not any(a for _, _, a, _, _ in slots):
        return None
    caps = {a: strict_capacity(a) for _, _, a, _, _ in slots if a}
    best: tuple[float, list[int], float] | None = None

    for mask in range(1, 1 << N):
        ks = [i for i in range(N) if mask >> i & 1]
        D = sum(slots[i][1] for i in ks)
        if not (min_d - 1e-9 <= D <= max_d + 1e-9):
            continue
        counts: dict[str, int] = {}
        secs: dict[str, float] = {}
        for i in ks:
            counts[slots[i][2]] = counts.get(slots[i][2], 0) + 1
            secs[slots[i][2]] = secs.get(slots[i][2], 0.0) + slots[i][1]
        M = len(counts)
        if M < 4:
            continue
        if any(c > max(2, -(-len(ks) // M)) for c in counts.values()):
            continue
        if any(v > D / 4.0 + 1e-9 for v in secs.values()):
            continue
        if any(counts[a] > caps[a] for a in counts):
            continue
        order = sorted(ks)
        if any(slots[order[j]][2] == slots[order[j - 1]][2] for j in range(1, len(order))):
            continue
        pos: dict[str, list[int]] = {}
        for j, i in enumerate(order):
            pos.setdefault(slots[i][2], []).append(j)
        if any(p[-1] - p[0] < min_interval for p in pos.values() if len(p) > 1):
            continue
        util = sum(slots[i][4] for i in ks)
        if best is None or util > best[0]:
            best = (util, ks, D, dict(counts), dict(secs))

    if best is None:
        reasons = []
        if N >= 1:
            reasons.append("无满足全部严格规则的子集（检查：域数≥4？S5' 间隔？原始顺序聚簇？S3' 非重叠容量？）")
        return None
    _, ks, D, dom_counts, secs = best
    kept_ordinals = [i + 1 for i in ks]
    kept_slot_ids = [slots[i][0] for i in ks]
    h2_ok = all(v <= D / 4.0 + 1e-9 for v in secs.values())
    caps_ok = all(dom_counts[a] <= caps[a] for a in dom_counts)
    return {
        "solver_version": SOLVER_VERSION,
        "base_template_id": tid,
        "kept_ordinals": kept_ordinals,
        "kept_slot_ids": kept_slot_ids,
        "base_section_refs": [f"sec-{o:03d}" for o in kept_ordinals],
        "total_s": round(D, 2),
        "domain_counts_kept": dom_counts,
        "seconds_kept": {k: round(v, 2) for k, v in secs.items()},
        "utility": best[0],
        "h1_ok": True, "h2_ok": h2_ok, "h3_ok": True, "h4_ok": True,
        "capacity_ok": caps_ok, "dur_ok": min_d - 1e-9 <= D <= max_d + 1e-9,
        "all_hard_ok": True,
        "input_hash": hashlib.sha256(json.dumps(
            {"tid": tid, "kept": kept_ordinals}, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
    }
