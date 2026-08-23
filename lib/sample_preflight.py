"""Cheap, deterministic checks that run before a sample render starts."""

from __future__ import annotations

from typing import Any, Mapping


def validate_sample_inputs(artifacts: Mapping[str, Any]) -> dict[str, Any]:
    """Return business-readable preflight issues without invoking render tools."""
    issues: list[str] = []
    for name in ("shot_execution_plan", "final_props", "sample_report"):
        if not isinstance(artifacts.get(name), Mapping):
            issues.append(f"缺少{name}产物")

    report = artifacts.get("sample_report") if isinstance(artifacts.get("sample_report"), Mapping) else {}
    window = report.get("window") if isinstance(report.get("window"), Mapping) else {}
    start = window.get("startFrame")
    end = window.get("endFrameExclusive")
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        issues.append("样片窗口无效")
    elif end - start < 300 or end - start > 450:
        issues.append("样片窗口应为 10-15 秒")

    props = artifacts.get("final_props") if isinstance(artifacts.get("final_props"), Mapping) else {}
    fps = props.get("fps")
    if not isinstance(fps, (int, float)) or fps <= 0:
        issues.append("时间轴缺少有效帧率")
    scenes = props.get("scenes") or props.get("shots") or props.get("timeline")
    if not isinstance(scenes, list) or not scenes:
        issues.append("时间轴没有可执行镜头")

    # When full final_props are present, reject the timeline failures before a
    # renderer is invoked. Legacy lightweight callers may omit frame/source
    # details and retain the basic checks above.
    if isinstance(props.get("scenes"), list) and props.get("scenes"):
        first = props["scenes"][0]
        if isinstance(first, Mapping) and "fromFrame" in first:
            from lib.sample_payload import build_sample_render_payload

            payload = artifacts.get("sample_payload")
            if not isinstance(payload, Mapping):
                payload = {
                    "final_props": props,
                    "asset_manifest": artifacts.get("asset_manifest") or {},
                }
            try:
                build_sample_render_payload(payload)
            except ValueError as exc:
                issues.append(str(exc))

    # P1: 字幕完整性（caption_integrity）——cations 非空、无空文案、首条覆盖开场。
    captions = props.get("captions") if isinstance(props.get("captions"), list) else []
    if not captions:
        issues.append("字幕缺失（无 captions）")
    else:
        for cap in captions:
            if isinstance(cap, Mapping) and not str(cap.get("text") or cap.get("word") or "").strip():
                issues.append("字幕存在空文案项")
                break
        first_caption = captions[0] if isinstance(captions[0], Mapping) else {}
        if ((first_caption.get("startMs") if first_caption.get("startMs") is not None else 0) or 0) > 1000:
            issues.append("字幕未覆盖开场（首条字幕起始 > 1s）")

    # P1: 开场对齐（opening_alignment）——首镜头须有屏显文案。
    sep = artifacts.get("shot_execution_plan") if isinstance(artifacts.get("shot_execution_plan"), Mapping) else {}
    sep_shots = sep.get("shots") if isinstance(sep.get("shots"), list) else []
    opening = next((s for s in sep_shots if str(s.get("id") or "").endswith("01")), sep_shots[0] if sep_shots else None)
    opening_copy = ((opening or {}).get("screen_copy") or "").strip() if opening else ""
    if not opening_copy:
        issues.append("开场镜头无屏显文案（开场对齐缺失，钩子不可读）")

    # P1: 候选差异度（candidate_divergence）——给定候选 variant 与兄弟变体时校验。
    variant = str(artifacts.get("candidate_variant") or "")
    sibling_variants = [str(v) for v in (artifacts.get("sibling_variants") or []) if isinstance(v, str)]
    if artifacts.get("candidate_variant") is not None:
        issues.extend(check_candidate_divergence(variant, sibling_variants))

    # 差异度结构硬门：候选差异计划（candidate_variant_plan）结构失败在渲染前阻塞。
    variant_plan = artifacts.get("candidate_variant_plan")
    diversity_mode = str(artifacts.get("diversity_mode") or "warning")
    if variant_plan is None and diversity_mode == "hard_gate":
        issues.append("差异度不足：缺少候选差异计划（candidate_variant_plan）")
    elif variant_plan is not None:
        from lib.candidate_diversity import assert_candidate_variant_ready
        for item in assert_candidate_variant_ready(variant_plan if isinstance(variant_plan, Mapping) else None):
            issues.append(f"差异度不足：{item}")

    return {"ok": not issues, "issues": issues}


def check_candidate_divergence(variant: str, sibling_variants: list[str]) -> list[str]:
    """P1: 候选差异度（禁同质化候选打头）。

    ``variant`` 为当前候选的差异化标识（如钩子），``sibling_variants`` 为其它候选的差异标识。
    空 variant 或与其它候选完全一致 → 返回失败原因。
    """
    issues: list[str] = []
    if not str(variant or "").strip():
        issues.append("候选无差异度（variant 为空）")
    elif sibling_variants and len({variant, *sibling_variants}) == 1:
        issues.append("候选与其它候选同质化（无差异度）")
    return issues
