"""Caption style fingerprint builder (Design_Review P1-1).

Derives the reference caption style spec from `research_breakdown` overlay
observations plus manual overrides. Automated extraction seeds what research
already captured (overlay text samples, evidence frames, effect treatment);
exact font metrics (family/size/weight/color) are approximations that must be
confirmed by a human — the artifact is marked `needs_review` until then.
References without captioned overlay text are `not_applicable`. Remotion must
render from this spec only; reference font files and assets are never copied.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def _observations(research_breakdown: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(research_breakdown, Mapping):
        return []
    out: list[Mapping[str, Any]] = []
    for item in [*research_breakdown.get("reference_shots", []), *research_breakdown.get("source_segments", [])]:
        if isinstance(item, Mapping):
            out.append(item)
    return out


def _merge(base: dict[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        elif value is not None:
            merged[key] = value
    return merged


# 中性通用字幕默认（不属于任何特定产品）。花字竖排楷书是独立 profile（见 CAPTION_PROFILES），
# 仅当参考片/设置明确为 calligraphy 时才应用，绝不当全局默认。
DEFAULT_STYLE: dict[str, Any] = {
    "font_family": "Source Han Sans（风格近似，待人工确认）",
    "font_style_approx": "",
    "size_hierarchy": [48, 60],
    "weight": "bold",
    "fill_color": "#FFFFFF",
    "stroke": {"color": "#000000", "width_px": 3},
    "opacity": 1.0,
    "position": "中下 1/3",
    "safe_zone_profile": "douyin_9_16",
    # 评审 #9b：字幕底部偏移的单一数据源。渲染器（CaptionOverlay 的
    # paddingBottom）与 QA（caption_layout 的安全区校验）都必须消费此值，
    # 不得各自硬编码 120/300。
    "bottom_offset_px": 120,
    "max_chars_per_line": 12,
    "line_breaks": "按短语断行",
    "entrance_animation": "整句淡入",
    "emphasis_animation": "无",
    "sync_mode": "follow_visual",
    "vertical": False,
}

# 命名字幕 profile。calligraphy = 参考片竖排书法花字（楷书 + 纯白 + 左上 + 大号）。
# 只有 profile 明确为 calligraphy 时应用，不影响其他任务的通用字幕。
CAPTION_PROFILES: dict[str, dict[str, Any]] = {
    "generic": dict(DEFAULT_STYLE),
    "calligraphy": {
        "font_family": "Ma Shan Zheng",
        "font_style_approx": "楷书书法竖排",
        "size_hierarchy": [104, 120],
        "weight": "bold",
        "fill_color": "#FFFFFF",
        "stroke": {"color": "#000000", "width_px": 0},
        "opacity": 1.0,
        "position": "左上",
        "safe_zone_profile": "douyin_9_16",
        "bottom_offset_px": 120,
        "max_chars_per_line": 12,
        "line_breaks": "逐字竖排",
        "entrance_animation": "整句淡入",
        "emphasis_animation": "无",
        "sync_mode": "follow_visual",
        "vertical": True,
    },
}


def build_caption_style_fingerprint(
    project_id: str,
    research_breakdown: Mapping[str, Any] | None,
    *,
    profile: str = "generic",
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if profile not in CAPTION_PROFILES:
        raise ValueError(f"unknown caption profile {profile!r}; expected one of {sorted(CAPTION_PROFILES)}")
    profile_style = dict(CAPTION_PROFILES[profile])
    observations = _observations(research_breakdown)
    overlay_samples: list[str] = []
    evidence_frames: list[str] = []
    effect_treatment = ""
    for item in observations:
        values = item.get("values") if isinstance(item.get("values"), Mapping) else {}
        overlay = str(values.get("overlay_text") or "").strip()
        if overlay:
            overlay_samples.append(overlay)
        frames = values.get("evidence_frames") or item.get("evidence_frames") or []
        for frame in frames:
            if isinstance(frame, str) and frame not in evidence_frames:
                evidence_frames.append(frame)
        if not effect_treatment and values.get("effect_treatment"):
            effect_treatment = str(values["effect_treatment"])

    if not overlay_samples:
        return {
            "version": "1.0",
            "project_id": project_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "applicability": "not_applicable",
            "profile": profile,
            "source": {"research_breakdown_ref": None, "evidence_frames": [], "overlay_text_samples": []},
            "style": profile_style,
            "binding": {"brand_required_rules": [], "reference_only_rules": []},
            "notes": "参考片未采集到字幕叠字，字幕样式走通用策略",
        }

    style = dict(profile_style)
    if effect_treatment:
        style["entrance_animation"] = effect_treatment
    base: dict[str, Any] = {
        "version": "1.0",
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "applicability": "needs_review",
        "profile": profile,
        "source": {
            "research_breakdown_ref": None,
            "evidence_frames": evidence_frames,
            "overlay_text_samples": overlay_samples[:20],
        },
        "style": style,
        "binding": {"brand_required_rules": [], "reference_only_rules": []},
        "notes": "自动提取了叠字样例与动效描述；字体族/字号/字重/描边为默认近似值，须人工修正后置 applicability=extracted",
    }
    if overrides:
        base = _merge(base, overrides)
    return base


WEIGHT_MAP = {
    "normal": 400,
    "medium": 500,
    "semibold": 600,
    "bold": 700,
    "heavy": 800,
}


def _map_position(position: str) -> str:
    text = str(position or "")
    if "左上" in text or text == "top-left":
        return "topleft"
    if "顶" in text or text == "top":
        return "top"
    if "居" in text or text == "center":
        return "center"
    return "bottom"


def _map_entrance(animation: str) -> str:
    text = str(animation or "")
    if "硬切" in text:
        return "none"
    if "淡" in text or text == "fade":
        return "fade"
    if "滑" in text or text == "slide_up":
        return "slide_up"
    if "无" in text or text in {"none", ""}:
        return "none"
    return "pop"


def to_overlay_spec(style: Mapping[str, Any]) -> dict[str, Any]:
    """Map a caption_style_fingerprint.style to the renderer's CaptionStyleSpec.

    Field names mirror `CaptionStyleSpec` in
    remotion-composer/src/components/SafeCaptionTrack.tsx — keep both in sync.
    """
    stroke = style.get("stroke") if isinstance(style.get("stroke"), Mapping) else {}
    background = style.get("background_bar") if isinstance(style.get("background_bar"), Mapping) else {}
    hierarchy = [float(v) for v in (style.get("size_hierarchy") or []) if isinstance(v, (int, float))]
    return {
        "fontFamily": str(style.get("font_family") or ""),
        "fontSize": float(hierarchy[0]) if hierarchy else None,
        "emphasizeFontSize": float(hierarchy[1]) if len(hierarchy) > 1 else None,
        "fontWeight": WEIGHT_MAP.get(str(style.get("weight") or "bold"), 700),
        "fillColor": str(style.get("fill_color") or "#FFFFFF"),
        "strokeColor": str(stroke.get("color") or "#000000"),
        "strokeWidthPx": float(stroke.get("width_px") or 0),
        "backgroundColor": str(background.get("color") or "") or None,
        "opacity": float(style.get("opacity") if style.get("opacity") is not None else 1.0),
        "position": _map_position(style.get("position") or ""),
        "entranceAnimation": _map_entrance(style.get("entrance_animation") or ""),
        "bottomOffsetPx": float(style.get("bottom_offset_px") if style.get("bottom_offset_px") is not None else 120),
        "vertical": bool(style.get("vertical") or False),
    }
