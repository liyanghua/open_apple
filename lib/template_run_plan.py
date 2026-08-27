"""单条模板适配计划（template_run_plan）builder + pilot 选择。

一条模板 → 一条自有视频的不可变适配契约。``slot_bindings`` 把模板的每个 slot 绑定到
自有素材（owned）或生成素材（generate）；没有绑定的 slot（unbound）不能进入 paid assets。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

DEFAULT_ADAPTATION_POLICIES = ("proof-first", "pain-first", "story")


def _run_id() -> str:
    return f"template-run-{uuid.uuid4().hex[:12]}"


def create_template_run(
    template: Mapping[str, Any],
    *,
    template_pack_ref: Mapping[str, Any],
    product_facts_ref: Mapping[str, Any],
    adaptation_policy: str = "proof-first",
) -> dict[str, Any]:
    """由模板创建 template_run_plan（slot_bindings 初始为 require-binding 的 unbound）。"""
    template_id = str(template.get("template_id") or "")
    if not template_id:
        raise ValueError("template_run_plan requires template_id")
    bindings: list[dict[str, Any]] = []
    for slot in (template.get("slots") or []):
        if not isinstance(slot, Mapping):
            continue
        bindings.append({
            "slot_id": str(slot.get("slot_id") or ""),
            "source": "unbound",
            "source_media_id": None,
            "asset_type": None,
            "reason": "待绑定自有素材或生成素材",
        })
    return {
        "version": "1.0",
        "run_id": _run_id(),
        "template_id": template_id,
        "template_pack_ref": dict(template_pack_ref),
        "product_facts_ref": dict(product_facts_ref),
        "adaptation_policy": adaptation_policy,
        "slot_bindings": bindings,
        "caption_policy": {"reference_text": "analysis_only", "copy_reference_caption": False},
        "status": "awaiting_human",
    }


def bind_slot(
    run: Mapping[str, Any],
    slot_id: str,
    *,
    source: str,
    source_media_id: str | None = None,
    asset_type: str | None = None,
    reason: str,
) -> dict[str, Any]:
    """把某个 slot 绑定到自有或生成素材；返回更新后的 run（不可变复制）。"""
    if source not in {"owned", "generate", "unbound"}:
        raise ValueError(f"invalid slot source {source!r}")
    updated = dict(run)
    bindings = [dict(b) for b in run.get("slot_bindings") or []]
    for b in bindings:
        if b["slot_id"] == slot_id:
            b["source"] = source
            b["source_media_id"] = source_media_id
            b["asset_type"] = asset_type
            b["reason"] = reason
            break
    else:
        raise ValueError(f"slot_id {slot_id!r} not found in run")
    updated["slot_bindings"] = bindings
    return updated


def check_template_run_plan_ready(
    run_plan: Mapping[str, Any],
    template: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """fail-closed：template_run_plan 是否可进入 paid assets（代码硬门，非描述）。

    必须全部满足才 ready=True，否则返回 blockers：
    - status 必须是 ``approved``（awaiting_human/未决 = 未就绪）；
    - slot_bindings 非空；
    - 每个 binding：source ∈ {owned, generate, unbound}，slot_id 非空；
      owned 必须带 source_media_id，generate 必须带 asset_type，unbound 不允许；
    - caption_policy.copy_reference_caption 必须为 false；
    - 若提供 template：每个 binding 的 slot_id 必须是模板的已知 slot。
    """
    blockers: list[str] = []
    status = str(run_plan.get("status") or "").strip()
    if status != "approved":
        blockers.append(f"template_run_plan 未批准（status={status or '未决'}），禁止付费生成")
    bindings = run_plan.get("slot_bindings") or []
    if not bindings:
        blockers.append("template_run_plan slot_bindings 为空，禁止付费生成")
    known_slot_ids = set()
    if template is not None:
        known_slot_ids = {str(s.get("slot_id")) for s in (template.get("slots") or []) if isinstance(s, Mapping)}
    # P0-2b：素材容量判定 fail-closed（评审 P0-1）——
    #   · 判定器异常 → blocker（不得静默放行进入付费资产阶段）；
    #   · MARK_GAP → blocker（缺口禁止付费）；
    #   · COMPRESS → 原始模板 blocker（必须改用压缩变体 -c1/已批准压缩计划，否则禁止继续生成）。
    try:
        from lib.template_source_match import capacity_verdict

        verdict = capacity_verdict(template) if template is not None else None
        if verdict:
            tid = str(template.get("template_id") or "")
            if verdict.get("verdict") == "MARK_GAP":
                blockers.append("素材容量缺口（MARK_GAP）：" + "; ".join(verdict.get("reasons") or []) + "——需补素材或压缩后重评")
            elif verdict.get("verdict") == "COMPRESS" and not tid.endswith("-c1"):
                blockers.append("素材容量不足（COMPRESS）：" + "; ".join(verdict.get("reasons") or []) +
                                "——必须以压缩变体（-c1）或已批准压缩计划运行，禁止原始计划继续生成")
    except Exception as exc:
        blockers.append(f"素材容量判定器异常（fail-closed，禁止付费生成）：{exc}")
    unbound_slots: list[str] = []
    for b in bindings:
        if not isinstance(b, Mapping):
            blockers.append("slot_binding 必须为对象")
            continue
        slot_id = str(b.get("slot_id") or "")
        source = str(b.get("source") or "").strip()
        if not slot_id:
            blockers.append("存在空 slot_id 的绑定")
        if source not in {"owned", "generate", "unbound"}:
            blockers.append(f"slot {slot_id}: 非法 source {source!r}")
        if template is not None and slot_id and slot_id not in known_slot_ids:
            blockers.append(f"slot {slot_id}: 不是模板已知 slot")
        if source == "unbound":
            unbound_slots.append(slot_id)
        if source == "owned" and not str(b.get("source_media_id") or "").strip():
            blockers.append(f"slot {slot_id}: owned 必须带 source_media_id")
        if source == "generate" and not str(b.get("asset_type") or "").strip():
            blockers.append(f"slot {slot_id}: generate 必须带 asset_type")
    if unbound_slots:
        preview = ", ".join(unbound_slots[:3])
        blockers.append(f"{len(unbound_slots)} 个 slot 未绑定素材（{preview}...），禁止付费生成")
    if (run_plan.get("caption_policy") or {}).get("copy_reference_caption"):
        blockers.append("禁止复制参考花字/字幕（copy_reference_caption 必须为 false）")
    return {"ready": not blockers, "unbound_slots": unbound_slots, "blockers": blockers}


def is_slot_paid_allowed(run_plan: Mapping[str, Any], slot_id: str, template: Mapping[str, Any] | None = None) -> bool:
    """该 slot 是否允许付费生成：status 已批准 + 该 slot 已绑定（非 unbound）+ 未复制参考。"""
    if str(run_plan.get("status") or "").strip() != "approved":
        return False
    if (run_plan.get("caption_policy") or {}).get("copy_reference_caption"):
        return False
    for b in run_plan.get("slot_bindings") or []:
        if isinstance(b, Mapping) and str(b.get("slot_id")) == slot_id:
            source = str(b.get("source") or "")
            if source == "unbound":
                return False
            if source == "owned" and not str(b.get("source_media_id") or "").strip():
                return False
            if source == "generate" and not str(b.get("asset_type") or "").strip():
                return False
            return source in {"owned", "generate"}
    return False  # slot 未在计划中 -> 不允许


def select_pilot(templates: list[Mapping[str, Any]], n: int = 8) -> list[str]:
    """选 n 条覆盖不同 archetype/花字 treatment/素材缺口/规模 的 pilot template_id。

    优先保证：关键 treatment（fade_in/fade_out/animated/subtitle/none/static）至少各 1 条；
    再按 slot 规模（小/中/大）分摊；最后填充到 n。结果保留可追溯（template_id 列表）。
    """
    if n <= 0:
        return []
    ts = [t for t in templates if isinstance(t, Mapping)]
    template_ids = [str(t.get("template_id") or "") for t in ts if t.get("template_id")]

    def treatments(t):
        return {s.get("caption_treatment") for s in t.get("slots") or [] if isinstance(s, Mapping)}

    def slot_bucket(t):
        cnt = len(t.get("slots") or [])
        return "small" if cnt <= 8 else "medium" if cnt <= 14 else "large"

    chosen: list[str] = []
    chosen_set: set[str] = set()

    def _pick(score_fn):
        cands = [t for t in ts if str(t.get("template_id")) not in chosen_set]
        if not cands:
            return
        best = max(cands, key=score_fn)
        chosen.append(str(best["template_id"]))
        chosen_set.add(str(best["template_id"]))

    # 1) 关键 treatment 各 1 条
    for treatment in ("fade_in", "fade_out", "animated", "subtitle", "none", "static"):
        _pick(lambda t, tr=treatment: (1 if tr in treatments(t) else 0, len(t.get("slots") or [])))
    # 2) 不同 slot 规模各 1 条
    for bucket in ("small", "medium", "large"):
        _pick(lambda t, b=bucket: (1 if slot_bucket(t) == b else 0, len(t.get("slots") or [])))
    # 3) 填充到 n（按 treatment 覆盖 + 规模衡量的启发式）
    while len(chosen) < n:
        cands = [t for t in ts if str(t.get("template_id")) not in chosen_set]
        if not cands:
            break
        best = max(cands, key=lambda t: (len(treatments(t)), len(t.get("slots") or [])))
        chosen.append(str(best["template_id"]))
        chosen_set.add(str(best["template_id"]))
    return chosen[:n]
