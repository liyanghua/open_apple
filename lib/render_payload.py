"""Deterministic Remotion render-payload assembler (固化债：render_payload assembler).

The agent used to hand-assemble the render payload from approved artifacts on
every run. This module is the single place that derives the render-payload-only
fields (caption_style / audio.mix / caption words-per-page) from the approved
artifacts so batch runs never hand-write five payloads:

    final_props           → composition props（时间线唯一来源）
    caption_style_fingerprint → captionStyle（to_overlay_spec，含 bottomOffsetPx）
    asset_plan/audio.mix  → audio.mix
    edit_decisions        → caption_words_per_page 等渲染参数透传

`caption_style` 是 render-payload-only 派生字段：绝不写入 canonical
`edit_decisions`；指纹 not_applicable 时省略，走渲染器默认。
"""

from __future__ import annotations

from typing import Any, Mapping


def build_render_payload(
    *,
    final_props: Mapping[str, Any],
    caption_fingerprint: Mapping[str, Any] | None = None,
    audio_mix: Mapping[str, Any] | None = None,
    edit_decisions: Mapping[str, Any] | None = None,
    scene_plan: Mapping[str, Any] | None = None,
    render_runtime: str = "remotion",
) -> dict[str, Any]:
    """Assemble the render payload deterministically from approved artifacts."""
    payload: dict[str, Any] = dict(final_props)

    if caption_fingerprint:
        from lib.caption_style import to_overlay_spec

        applicability = str(caption_fingerprint.get("applicability") or "")
        style = caption_fingerprint.get("style")
        if applicability in {"extracted", "needs_review"} and isinstance(style, Mapping):
            payload["captionStyle"] = to_overlay_spec(style)
        # not_applicable → 省略 captionStyle，渲染器走默认。

    if audio_mix:
        payload.setdefault("audio", {})
        audio = payload["audio"]
        if isinstance(audio, Mapping):
            audio["mix"] = dict(audio_mix)

    decisions = edit_decisions if isinstance(edit_decisions, Mapping) else {}
    for key in ("caption_words_per_page", "words_per_page"):
        value = decisions.get(key)
        if value is not None:
            payload["captionWordsPerPage"] = int(value)
            break

    # P2：scene_plan 的 caption/transition recipe intent → 渲染级规格（runtime 无关）。
    # 渲染器按 scene_id 查 captionRecipes/transitionRecipes 落地花字/转场效果。
    if scene_plan:
        from lib.recipe_router import scene_recipe_specs

        specs = scene_recipe_specs(scene_plan, render_runtime)
        if specs["caption_recipes"]:
            payload["captionRecipes"] = specs["caption_recipes"]
        if specs["transition_recipes"]:
            payload["transitionRecipes"] = specs["transition_recipes"]

    return payload
