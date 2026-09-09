"""Approved silver-ion towel script-variant definitions.

This module only builds deterministic structural variants.  It never edits
product facts or invents evidence: every slot keeps its original evidence row
and source binding while the order and beat durations change.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


VARIANT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "variant_id": "result_first",
        "label": "吸水结果先行",
        "hook": "先看到连续倒水后的湿润范围，再解释材质与日常使用",
        "row_order": (1, 2, 3, 4, 5, 6, 7, 8, 9),
        "durations": (7.2, 3.0, 3.0, 3.0, 3.0, 2.6, 3.0, 2.3, 3.0),
        "pacing_curve": "result-proof-cta",
        "evidence_strategy": "result_before_explanation",
    },
    {
        "variant_id": "texture_first",
        "label": "材质证据先行",
        "hook": "先看毛圈纹理、轻抚与轻揉，再落到吸水结果",
        "row_order": (2, 3, 4, 5, 1, 6, 7, 8, 9),
        "durations": (3.0, 3.0, 3.0, 3.0, 7.2, 2.6, 3.0, 2.3, 3.0),
        "pacing_curve": "texture-proof-payoff",
        "evidence_strategy": "material_before_result",
    },
    {
        "variant_id": "daily_seed",
        "label": "日常场景种草",
        "hook": "从取下、洁面、挂放进入真实日常，再补足材质与吸水",
        "row_order": (7, 6, 8, 3, 4, 5, 1, 2, 9),
        "durations": (3.0, 2.6, 2.3, 3.0, 3.0, 3.0, 7.2, 3.0, 3.0),
        "pacing_curve": "daily-touch-proof",
        "evidence_strategy": "daily_use_before_claim",
    },
    {
        "variant_id": "high_density",
        "label": "高密度卖点串联",
        "hook": "以更密集的动作切换快速串联吸水、触感、厚度与使用",
        "row_order": (1, 3, 2, 4, 6, 5, 7, 8, 9),
        "durations": (6.0, 4.0, 2.0, 2.0, 4.5, 3.0, 3.0, 2.0, 3.6),
        "pacing_curve": "high-density-benefit-stack",
        "evidence_strategy": "one_fact_per_cut",
    },
)


def _row_for_slot(slot: Mapping[str, Any], binding: Mapping[str, Any]) -> int:
    ids = list(binding.get("evidence_row_ids") or [])
    if not ids:
        raise ValueError(f"slot {slot.get('slot_id')} has no evidence_row_ids")
    suffix = str(ids[0]).rsplit("-", 1)[-1]
    try:
        return int(suffix)
    except ValueError as exc:
        raise ValueError(f"unsupported evidence row id {ids[0]!r}") from exc


def build_variant_definition(
    base_template: Mapping[str, Any],
    base_run_plan: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a reordered local template pack item and its approved run plan."""
    row_order = tuple(int(value) for value in spec["row_order"])
    durations = tuple(float(value) for value in spec["durations"])
    if len(row_order) != len(durations):
        raise ValueError("row_order and durations must have equal length")

    slots_by_row: dict[int, dict[str, Any]] = {}
    bindings_by_slot = {
        str(binding.get("slot_id") or ""): binding
        for binding in base_run_plan.get("slot_bindings") or []
        if isinstance(binding, Mapping)
    }
    for slot in base_template.get("slots") or []:
        slot_copy = deepcopy(dict(slot))
        binding = bindings_by_slot.get(str(slot_copy.get("slot_id") or ""))
        if binding is None:
            raise ValueError(f"missing binding for slot {slot_copy.get('slot_id')!r}")
        slots_by_row[_row_for_slot(slot_copy, binding)] = slot_copy
    if set(row_order) != set(slots_by_row):
        raise ValueError("variant row_order must cover exactly the base evidence rows")

    variant_id = str(spec["variant_id"])
    slots: list[dict[str, Any]] = []
    for row, duration in zip(row_order, durations):
        slot = deepcopy(slots_by_row[row])
        slot["ordinal"] = len(slots) + 1
        slot["duration_s"] = duration
        slots.append(slot)

    run_plan = deepcopy(dict(base_run_plan))
    run_plan["template_id"] = f"yinlizi-{variant_id}"
    run_plan["status"] = "approved"
    run_plan["adaptation_policy"] = str(spec["evidence_strategy"])
    run_plan["slot_bindings"] = [
        deepcopy(bindings_by_slot[str(slot["slot_id"])]) for slot in slots
    ]
    run_plan.pop("semantic_sha256", None)
    run_plan.pop("artifact_sha256", None)

    template = deepcopy(dict(base_template))
    template["template_id"] = f"yinlizi-{variant_id}"
    template["sheet_name"] = f"银离子毛巾 {spec['label']}"
    template["archetype"] = "proof-first"
    template["slots"] = slots
    return {
        "variant_id": variant_id,
        "label": str(spec["label"]),
        "hook": str(spec["hook"]),
        "row_order": list(row_order),
        "template": template,
        "run_plan": run_plan,
    }


__all__ = ["VARIANT_SPECS", "build_variant_definition"]
