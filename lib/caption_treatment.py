"""逐镜花字 treatment → caption_recipe_intent 应用层（独立于 43 条模板库）。

分两层（参考 Reference_Library_Driven_Generation_Plan §2.1）：
- ``caption_treatment``：参考/模板"用了什么表现方式"（fade_in/subtitle/animated/…）。
- ``caption_recipe_intent``：自有镜头"为什么需要这种字幕意图"（hook/proof/label/reveal）。

规则：优选自有镜头的 ``shot_intent``/``narrative_role``；只有没有显式意图时，
才回退到参考 treatment 映射，且必须记录 ``derived_from: template_treatment`` +
``fallback_used: true``——不能在验收中声称"与参考花字列一致"就代表语义正确。
"""
from __future__ import annotations

from typing import Any

# 参考/模板花字处理枚举（对齐 xlsx「特效」列规范化结果）。
CAPTION_TREATMENTS: tuple[str, ...] = (
    "fade_in", "subtitle", "animated", "static", "fade_out", "none", "unknown",
)

# 自有镜头可用的 caption_recipe_intent。
CAPTION_RECIPE_INTENTS: tuple[str, ...] = ("hook", "proof", "label", "reveal")

# 参考 treatment → 建议的 recipe intent（仅 fallback 用）。
CAPTION_TREATMENT_TO_INTENT: dict[str, str] = {
    "animated": "hook",     # 动效花字 → 关键词高亮钩子
    "fade_in": "reveal",    # 淡入 → 柔和揭示
    "subtitle": "label",    # 普通字幕 → 极简标签
    "static": "label",      # 有字无动画 → 极简标签
    "fade_out": "label",    # 淡出 → 极简标签
    "none": "label",        # 无处理 → 极简标签
    "unknown": "label",     # 未知 → 极简标签（人工复核）
}


def caption_treatment_to_intent(treatment: str) -> str:
    """参考 treatment → 建议 recipe intent（未识别回退 label）。"""
    key = str(treatment or "").strip().lower()
    return CAPTION_TREATMENT_TO_INTENT.get(key, "label")


def resolve_caption_recipe_intent(
    own_caption_intent: str | None,
    reference_treatment: str | None,
) -> dict[str, Any]:
    """解析镜头 caption_recipe_intent：自有意图优先，参考 treatment 仅 fallback。

    返回 ``{recipe_intent, derived_from, fallback_used}``：
    - derived_from=``shot_intent`` 且 fallback_used=False：显式自有意图；
    - derived_from=``template_treatment`` 且 fallback_used=True：参考 treatment 回退。
    """
    own = str(own_caption_intent or "").strip().lower()
    if own in CAPTION_RECIPE_INTENTS:
        return {"recipe_intent": own, "derived_from": "shot_intent", "fallback_used": False}
    return {
        "recipe_intent": caption_treatment_to_intent(reference_treatment),
        "derived_from": "template_treatment",
        "fallback_used": True,
    }
