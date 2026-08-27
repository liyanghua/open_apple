"""模板压缩器（设计 §6 / 附录 A1-A3）：保留序不变、只删镜；输出满足 H1-H4 的 slot 子集候选。

确定性规则（无 CP-SAT，N≤30 时贪心+收敛即可）：
- 骨架强制保留：首镜（hook）、尾镜（cta）、每个出现过的证据域首镜、payoff 域首镜；
- 违规删减优先级：容量（域需≤窗口容量）→ H2（单素材秒 ≤ D/3）→ H1（最终序列相邻不同域）；
- 每次删「违规域/相邻对中效用最低（utility 小、idx 靠后）」的候选（骨架除外）；
- 目标时长：可选 target_s，达标删除后若仍超 → 继续删最低效用非骨架行；
  若骨架最短长度仍 > target → 返回最小骨架解并标注 infeasible_target。

输出：{solver_version, kept_slot_ids, kept_durations, total_s, domain_counts_kept,
      h1_ok, h2_max_material_s, h2_limit_s, capacity_ok, dropped[{slot_id, reason}],
      infeasible_target, base_ref, input_hash}
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE, slot_semantics, window_capacity

SOLVER = "greedy-drop-v1"


def _h1_pairs(order: list[int]) -> list[tuple[int, int]]:
    return [(order[i], order[i - 1]) for i in range(1, len(order))]


def _violations(sem: list[dict], kept_idx: set[int], chars: dict[str, float], caps: dict[str, int]) -> dict:
    """返回违规项：容量缺口域 / H2 超限域 / H1 相邻对。"""
    kept = [s for s in sem if s["ordinal"] in kept_idx]
    order = [s["ordinal"] for s in kept]
    counts: dict[str, int] = {}
    secs: dict[str, float] = {}
    for s in kept:
        counts[s["action_domain"]] = counts.get(s["action_domain"], 0) + 1
        secs[s["action_domain"]] = secs.get(s["action_domain"], 0.0) + s["duration_s"]
    D = sum(secs.values())
    h1 = [(a, b) for a, b in _h1_pairs(order)
          if sem[a - 1]["action_domain"] == sem[b - 1]["action_domain"]]
    capacity_bad = [d for d in counts if counts[d] > caps.get(d, 0)]
    h2_bad = [d for d in secs if D > 0 and secs[d] > D / 3.0 + 1e-9]
    return {"counts": counts, "secs": secs, "D": D, "h1": h1,
            "capacity_bad": capacity_bad, "h2_bad": h2_bad}


def compress_candidate(template: Mapping[str, Any], *, target_s: float | None = None) -> dict | None:
    sem = slot_semantics(template)
    slots = sem
    ordinals = [s["ordinal"] for s in sem]
    # 骨架：首/尾 + 每域首镜 + payoff 域首镜
    skeleton: set[int] = set()
    if ordinals:
        skeleton.add(ordinals[0])
        skeleton.add(ordinals[-1])
    seen: set[str] = set()
    payoff_seen = False
    for s in sem:
        d = s["action_domain"]
        if d not in seen:
            seen.add(d)
            skeleton.add(s["ordinal"])
        if s["beat_role"] == "payoff" and not payoff_seen:
            skeleton.add(s["ordinal"])
            payoff_seen = True

    caps = {d: window_capacity(d, 2.0)["capacity"] for d in seen}
    kept: set[int] = set(ordinals)

    def _drop_pick(kept_set: set[int], *, target_shrink: bool = False):
        """按 容量 → H2 → H1 分组的单调优先级删减（避免各违规组互相干扰导致过度删减）。"""
        v = _violations(sem, kept_set, {}, caps)
        eligible = [s for s in sem if s["ordinal"] in kept_set
                    and s["ordinal"] not in skeleton]  # P1-5：排除完整骨架（每域首镜+payoff 首）
        groups: list[list] = []
        if v["capacity_bad"]:
            groups.append([s for s in eligible if s["action_domain"] in set(v["capacity_bad"])])
        if v["h2_bad"]:
            h2doms = set(v["h2_bad"])
            groups.append([s for s in eligible if s["action_domain"] in h2doms])
        if v["h1"]:
            pairs = {i for pair in v["h1"] for i in pair}
            groups.append([s for s in eligible if s["ordinal"] in pairs])
        if target_shrink and not groups:
            groups.append(eligible)  # 目标时长收缩兜底：最低效用
        for cands in groups:
            if not cands:
                continue
            cands.sort(key=lambda s: (s["utility"], -s["ordinal"]))
            return cands[0]["ordinal"]
        return None

    for _ in range(len(sem) + 1):
        v = _violations(sem, kept, {}, caps)
        if not (v["capacity_bad"] or v["h2_bad"] or v["h1"]):
            break
        if target_s is not None and v["D"] <= target_s + 1e-9:
            break  # 目标时长优先：硬门由目标收缩阶段继续处理，避免过度收缩
        pick = _drop_pick(kept)
        if pick is None:
            break
        kept.remove(pick)
    # 目标时长收缩
    if target_s is not None:
        for _ in range(len(sem) + 1):
            v = _violations(sem, kept, {}, caps)
            if v["D"] <= target_s + 1e-9 and not (v["capacity_bad"] or v["h2_bad"] or v["h1"]):
                break
            pick = _drop_pick(kept, target_shrink=True)
            if pick is None:
                break
            kept.remove(pick)

    final = _violations(sem, kept, {}, caps)
    infeasible_target = bool(target_s is not None and final["D"] > target_s + 1e-9)
    dur_ok = 15.0 - 1e-9 <= final["D"] <= 60.0 + 1e-9  # P1-7：业务时长硬门 [15,60]
    kept_dur = [s["duration_s"] for s in sem if s["ordinal"] in kept]
    dropped = [{"slot_id": s["slot_id"], "ordinal": s["ordinal"], "reason": "压缩删除",
                "utility": s["utility"]} for s in sem if s["ordinal"] not in kept]
    input_hash = hashlib.sha256(json.dumps(
        {"tid": template.get("template_id"), "kept": sorted(kept), "target": target_s,
         "solver": SOLVER}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {
        "solver_version": SOLVER, "template_id": str(template.get("template_id") or ""),
        "base_ref": f"template:{template.get('template_id')}",
        "kept_slot_ids": [s["slot_id"] for s in sem if s["ordinal"] in kept],  # P0-2a：真实 slot id
        "kept_ordinals": sorted(kept), "kept_durations": kept_dur,
        "total_s": round(sum(kept_dur), 2),
        "domain_counts_kept": final["counts"], "secs_kept": {k: round(v, 2) for k, v in final["secs"].items()},
        "h1_ok": not final["h1"], "h2_max_material_s": round(max(final["secs"].values()) if final["secs"] else 0, 2),
        "h2_limit_s": round(final["D"] / 3.0, 2), "capacity_ok": not final["capacity_bad"],
        "dur_ok": dur_ok,
        "all_hard_ok": not final["h1"] and not final["h2_bad"] and not final["capacity_bad"] and dur_ok
                      and not infeasible_target,
        "dropped": dropped, "infeasible_target": infeasible_target, "input_hash": input_hash,
    }



def _honest_flags(sem, kept, caps):
    """P1-7：h1/capacity/duration 分别独立判定（不再把域计数误报成 H1 通过）。"""
    kept_s = [s for s in sem if s["ordinal"] in kept]
    order = [s["ordinal"] for s in kept_s]
    counts, secs = {}, {}
    for s in kept_s:
        counts[s["action_domain"]] = counts.get(s["action_domain"], 0) + 1
        secs[s["action_domain"]] = secs.get(s["action_domain"], 0.0) + s["duration_s"]
    D = sum(secs.values())
    h1 = all(sem[a - 1]["action_domain"] != sem[b - 1]["action_domain"]
             for a, b in zip(order, order[1:]))
    cap = all(counts.get(d, 0) <= caps.get(d, 0) for d in counts)
    h2 = all(D <= 0 or secs[d] <= D / 3.0 + 1e-9 for d in secs)
    dur = 15.0 - 1e-9 <= D <= 60.0 + 1e-9
    return h1, (h1 and cap and h2 and dur), cap, dur


def compress_candidate_bottomup(template: Mapping[str, Any], *, target_s: float | None = None) -> dict | None:
    """自底向上压缩（替代纯贪心收缩）：按效用降序加入 slot，满足容量/H2/H1 且有目标时长。

    解决 09 类「多域需对称收缩」场景（top-down 收缩会把 D 缩到 6s 以下产生 H2 边际冲突）。
    """
    from lib.template_source_match import window_capacity

    sem = slot_semantics(template)
    ordinals = [s["ordinal"] for s in sem]
    seen = {s["action_domain"] for s in sem}
    caps = {d: window_capacity(d, 2.0)["capacity"] for d in seen}

    def check(kept_set: set[int]) -> tuple[bool, dict]:
        kept = [s for s in sem if s["ordinal"] in kept_set]
        order = [s["ordinal"] for s in kept]
        counts: dict[str, int] = {}
        secs: dict[str, float] = {}
        for s in kept:
            counts[s["action_domain"]] = counts.get(s["action_domain"], 0) + 1
            secs[s["action_domain"]] = secs.get(s["action_domain"], 0.0) + s["duration_s"]
        D = sum(secs.values())
        h1 = [(a, b) for a, b in zip(order, order[1:])
              if sem[a - 1]["action_domain"] == sem[b - 1]["action_domain"]]
        ok = (not h1 and all(counts.get(d, 0) <= caps.get(d, 0) for d in counts)
              and all(D <= 0 or secs[d] <= D / 3.0 + 1e-9 for d in secs))
        return ok, {"D": D, "counts": counts, "secs": secs}

    # 两阶段：grow（仅校验容量）+ repair（H2 删超载域 → H1 断相邻冲突）
    skeleton = {ordinals[0], ordinals[-1]} | {
        next(s["ordinal"] for s in sem if s["action_domain"] == d) for d in seen}
    kept = set(skeleton)
    ordered = sorted(sem, key=lambda s: (s["utility"], s["ordinal"]), reverse=True)
    for s in ordered:
        if s["ordinal"] in kept:
            continue
        cand = kept | {s["ordinal"]}
        _, info = check(cand)
        counts = info["counts"]
        if all(counts.get(d, 0) <= caps.get(d, 0) for d in counts) and                 (target_s is None or info["D"] <= target_s + 1e-9):
            kept = cand
    # 阶段2：时长下限增长（D < 15s 或目标）——只加容量允许的最低占比域（临时容忍 H2 超标）
    floor_s = max(15.0, target_s or 0.0)
    for _ in range(len(sem) + 2):
        _, info = check(kept)
        if info["D"] >= floor_s - 1e-9:
            break
        low = sorted(seen, key=lambda d: info["counts"].get(d, 0))
        added = False
        for d in low:
            cands = [s for s in sem if s["ordinal"] not in kept and s["action_domain"] == d]
            if not cands:
                continue
            _, info2 = check(kept | {cands[0]["ordinal"]})
            if info2["counts"].get(d, 0) <= caps.get(d, 0):
                kept.add(cands[0]["ordinal"]); added = True
                break
        if not added:
            break
    # 阶段3：平衡修复（H2 超标 → 从最重域删一镜 + 从最轻域补一镜；可加尽止）
    for _ in range(len(sem) + 4):
        ok, info = check(kept)
        if ok or info["D"] <= 0:
            break
        secs = info["secs"]
        if all(secs[d] <= info["D"] / 3.0 + 1e-9 for d in secs):
            break
        worst = max(secs, key=lambda d: secs[d])
        best = min(seen, key=lambda d: secs.get(d, 0.0))
        drop = [s["ordinal"] for s in sem if s["ordinal"] in kept
                and s["action_domain"] == worst and s["ordinal"] not in skeleton]
        add = [s["ordinal"] for s in sem if s["ordinal"] not in kept and s["action_domain"] == best]
        if drop and add:
            _, info_add = check(kept - {drop[0]} | {add[0]})
            if info_add["counts"].get(best, 0) <= caps.get(best, 0):
                kept.discard(drop[0]); kept.add(add[0])
                continue
        # 无交换余地 → 只删（否则保持现状退出）
        if drop:
            kept.discard(drop[0])
            continue
        break
    # repair：H1 断相邻（删后镜，域首镜保留）+ 容量兜底
    for _ in range(len(sem) + 2):
        ok, info = check(kept)
        if ok:
            break
        kept_in_order = [s["ordinal"] for s in sem if s["ordinal"] in kept]
        drop = None
        for a, b in zip(kept_in_order, kept_in_order[1:]):
            if sem[a - 1]["action_domain"] == sem[b - 1]["action_domain"]:
                cands = [s for s in sem if s["ordinal"] == b and s["ordinal"] not in skeleton]
                if cands:
                    drop = b
                else:
                    cands = [s for s in sem if s["ordinal"] == a and s["ordinal"] not in skeleton]
                    drop = cands[0]["ordinal"] if cands else None
                if drop:
                    break
        if drop is None:
            break
        kept.discard(drop)
    ok, info = check(kept)
    kept_dur = [s["duration_s"] for s in sem if s["ordinal"] in kept]
    dropped = [{"slot_id": s["slot_id"], "ordinal": s["ordinal"]} for s in sem if s["ordinal"] not in kept]
    (h1_ok, _h2_ok, cap_ok, dur_ok) = _honest_flags(sem, kept, caps)
    return {
        "solver_version": SOLVER + "-bottomup", "template_id": str(template.get("template_id") or ""),
        "kept_ordinals": sorted(kept), "kept_durations": kept_dur,
        "total_s": round(sum(kept_dur), 2), "domain_counts_kept": info["counts"],
        "h1_ok": h1_ok, "h2_max_material_s": round(max(info["secs"].values()) if info["secs"] else 0, 2),
        "h2_limit_s": round(info["D"] / 3.0, 2), "capacity_ok": cap_ok, "dur_ok": dur_ok,
        "all_hard_ok": h1_ok and cap_ok and dur_ok and _h2_ok, "dropped": dropped,
    }
