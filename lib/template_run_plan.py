"""单条模板适配计划（template_run_plan）builder + pilot 选择。

一条模板 → 一条自有视频的不可变适配契约。``slot_bindings`` 把模板的每个 slot 绑定到
自有素材（owned）或生成素材（generate）；没有绑定的 slot（unbound）不能进入 paid assets。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

DEFAULT_ADAPTATION_POLICIES = ("proof-first", "pain-first", "story")


def load_template_for_run_plan(run_plan: Mapping[str, Any], *, pack_path: Path | None = None) -> dict[str, Any] | None:
    """Load the canonical template for a run plan when one is registered locally."""
    template_id = str(run_plan.get("template_id") or "").strip()
    if not template_id:
        return None
    path = pack_path or Path(__file__).resolve().parents[1] / "projects/template-pack-library/artifacts/template_pack.json"
    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return next((t for t in pack.get("templates", [])
                 if isinstance(t, Mapping) and str(t.get("template_id") or "") == template_id), None)


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
    if template is None and str(run_plan.get("template_id") or "").strip():
        template = load_template_for_run_plan(run_plan)
        if template is None:
            blockers.append("template_run_plan 引用的模板未在权威 template_pack 中注册，禁止付费生成")
    known_slot_ids = set()
    if template is not None:
        known_slot_ids = {str(s.get("slot_id")) for s in (template.get("slots") or []) if isinstance(s, Mapping)}
        bound_slot_ids = [str(b.get("slot_id") or "") for b in bindings if isinstance(b, Mapping)]
        if len(bound_slot_ids) != len(set(bound_slot_ids)):
            blockers.append("template_run_plan 存在重复 slot binding，禁止付费生成")
        missing = sorted(known_slot_ids - set(bound_slot_ids))
        if missing:
            blockers.append(f"template_run_plan 缺少 {len(missing)} 个模板 slot 的绑定（{', '.join(missing[:3])}...），禁止付费生成")
        if str(run_plan.get("template_id") or "") != str(template.get("template_id") or ""):
            blockers.append("template_run_plan.template_id 与加载模板不一致，禁止付费生成")
    # 标定策略 C：未标定模板直接阻断（关键词回退判定不可信，禁止付费生成）。
    try:
        from lib.template_source_match import is_template_calibrated

        if template is not None and not is_template_calibrated(str(template.get("template_id") or "")):
            blockers.append("模板动作域未标定，禁止付费生成——请先运行 scripts/calibrate_template.py 完成标定（VLM/人工）后再起片")
    except Exception as exc:
        blockers.append(f"标定状态判定异常（fail-closed）：{exc}")
    # P0-2b：素材容量判定 fail-closed（评审 P0-1）——
    #   · 判定器异常 → blocker（不得静默放行进入付费资产阶段）；
    #   · MARK_GAP → blocker（缺口禁止付费）；
    #   · COMPRESS → 必须携带经校验的压缩计划，否则禁止继续生成。
    try:
        from lib.template_source_match import capacity_verdict

        comp = run_plan.get("compression")
        template_id = str((template or {}).get("template_id") or run_plan.get("template_id") or "")
        if template_id.endswith("-c1") and not isinstance(comp, Mapping):
            blockers.append("压缩变体必须携带完整 compression 契约，禁止仅凭 -c1 命名放行")
        if isinstance(comp, Mapping):
            _check_compression_plan(comp, run_plan, template, blockers)
        verdict = capacity_verdict(template) if template is not None else None
        if verdict:
            if verdict.get("verdict") == "MARK_GAP":
                blockers.append("素材容量缺口（MARK_GAP）：" + "; ".join(verdict.get("reasons") or []) + "——需补素材或压缩后重评")
            elif verdict.get("verdict") == "COMPRESS" and not isinstance(comp, Mapping):
                blockers.append("素材容量不足（COMPRESS）：" + "; ".join(verdict.get("reasons") or []) +
                                "——必须提供已批准且 all_hard_ok=true 的压缩计划")
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


def _check_compression_plan(comp: Mapping[str, Any], run_plan: Mapping[str, Any],
                            template: Mapping[str, Any] | None, blockers: list[str]) -> None:
    """Validate the compressed subset against the exact template being executed."""
    if (not comp.get("all_hard_ok") or not comp.get("h1_ok") or not comp.get("h2_ok")
            or not comp.get("h3_ok") or not comp.get("h4_ok") or not comp.get("capacity_ok")):
        blockers.append("压缩计划硬约束未全部通过，禁止付费生成")
    if not comp.get("dur_ok") or not (15.0 <= float(comp.get("total_s") or 0.0) <= 60.0):
        blockers.append("压缩计划时长未满足 [15,60]s，禁止付费生成")
    base_template_id = str(comp.get("base_template_id") or "")
    if base_template_id != str(comp.get("base_ref") or "").removeprefix("template:"):
        blockers.append("压缩计划 base_template_id/base_ref 不一致")
    kept_ids = [str(x) for x in comp.get("kept_slot_ids") or []]
    kept_ordinals = [int(x) for x in comp.get("kept_ordinals") or [] if isinstance(x, int) or str(x).isdigit()]
    if len(kept_ids) != len(set(kept_ids)) or len(kept_ordinals) != len(set(kept_ordinals)):
        blockers.append("压缩计划保留 slot 重复")
    validation_template = template
    if base_template_id and template is not None and base_template_id != str(template.get("template_id") or ""):
        validation_template = load_template_for_run_plan({"template_id": base_template_id})
        if validation_template is None:
            blockers.append("压缩计划 base_template_id 未在权威 template_pack 注册")
    if validation_template is not None:
        slots = [s for s in validation_template.get("slots") or [] if isinstance(s, Mapping)]
        known_ids = {str(s.get("slot_id") or "") for s in slots}
        known_ordinals = {int(s.get("ordinal") or i) for i, s in enumerate(slots, 1)}
        if not kept_ids or not set(kept_ids) <= known_ids:
            blockers.append("压缩计划 kept_slot_ids 不是当前模板的子集")
        if not kept_ordinals or not set(kept_ordinals) <= known_ordinals:
            blockers.append("压缩计划 kept_ordinals 不是当前模板的子集")
        if len(kept_ids) != len(kept_ordinals):
            blockers.append("压缩计划 kept_slot_ids/kept_ordinals 数量不一致")
        expected_ids = {
            int(s.get("ordinal") or i): str(s.get("slot_id") or "")
            for i, s in enumerate(slots, 1)
        }
        if any(expected_ids.get(ordinal) != slot_id
               for ordinal, slot_id in zip(kept_ordinals, kept_ids)):
            blockers.append("压缩计划 kept_slot_ids 与 kept_ordinals 映射不一致")
        refs = comp.get("base_section_refs")
        if not isinstance(refs, list) or len(refs) != len(kept_ids) or not all(str(ref).strip() for ref in refs):
            blockers.append("压缩计划 base_section_refs 不完整")
    if template is not None and base_template_id != str(template.get("template_id") or ""):
        current_ids = {str(s.get("slot_id") or "") for s in template.get("slots") or [] if isinstance(s, Mapping)}
        if current_ids != set(kept_ids):
            blockers.append("压缩变体模板 slots 未与 kept_slot_ids 完整对齐")
    if not isinstance(comp.get("input_hash"), str) or len(comp["input_hash"]) != 64:
        blockers.append("压缩计划 input_hash 非法")


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
