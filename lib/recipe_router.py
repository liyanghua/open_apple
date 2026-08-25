"""Runtime-agnostic caption / transition recipe router (P2).

把「语义 intent」路由到「canonical recipe」，再按所选 runtime 做能力检查与回退。
Recipe 是 runtime 无关的规范；每个 recipe 声明它支持的 runtime 集合。路由规则：

    intent -> canonical recipe (偏好顺序) -> runtime adapter (能力检查) -> fallback

这样渲染器（Remotion / HyperFrames / FFmpeg）只消费 recipe_id + 参数，不把
「花字怎么做 / 转场怎么做」写死在某一套渲染器里；运营可预览 + 替换 recipe。
"""
from __future__ import annotations

from typing import Any, Mapping

RUNTIMES = ("remotion", "hyperframes", "ffmpeg")

# recipe_id -> {description, runtimes}。runtimes 是能力声明。
CAPTION_RECIPES: dict[str, dict[str, Any]] = {
    "proof-punch": {
        "description": "证据冲击：大字强调 + 短促入场，用于证明镜头",
        "runtimes": ("remotion", "hyperframes"),
    },
    "reveal-pop-soft": {
        "description": "柔和揭示：淡入 + 轻弹，用于揭晓/结果",
        "runtimes": ("remotion", "hyperframes", "ffmpeg"),
    },
    "keyword-highlight": {
        "description": "关键词高亮：逐词强调，用于钩子/痛点",
        "runtimes": ("remotion",),
    },
    "clean-minimal-label": {
        "description": "极简标签：静态角标/短词，全 runtime 兜底",
        "runtimes": ("remotion", "hyperframes", "ffmpeg"),
    },
}

TRANSITION_RECIPES: dict[str, dict[str, Any]] = {
    "hard-cut-clean": {
        "description": "干净硬切，全 runtime 兜底",
        "runtimes": ("remotion", "hyperframes", "ffmpeg"),
    },
    "impact-cut": {
        "description": "冲击切：微缩放 + 闪，用于冲突/钩子转折",
        "runtimes": ("remotion", "hyperframes"),
    },
    "action-match": {
        "description": "动作匹配切：上下镜动作方向衔接",
        "runtimes": ("remotion", "hyperframes", "ffmpeg"),
    },
    "flash-proof": {
        "description": "闪白证明切：证明镜头前的强调转场",
        "runtimes": ("remotion", "hyperframes"),
    },
}

# intent -> 偏好 recipe 顺序（先到先用；后面的是 fallback）。
CAPTION_INTENTS: dict[str, list[str]] = {
    "proof": ["proof-punch", "reveal-pop-soft", "clean-minimal-label"],
    "label": ["clean-minimal-label", "reveal-pop-soft"],
    "hook": ["keyword-highlight", "proof-punch", "clean-minimal-label"],
    "reveal": ["reveal-pop-soft", "clean-minimal-label"],
}

TRANSITION_INTENTS: dict[str, list[str]] = {
    "impact": ["impact-cut", "hard-cut-clean"],
    "action_match": ["action-match", "hard-cut-clean"],
    "proof": ["flash-proof", "impact-cut", "hard-cut-clean"],
    "soft": ["action-match", "hard-cut-clean"],
}


def _route(intent: str, runtime: str, intents: dict[str, list[str]], recipes: dict[str, dict[str, Any]], base_recipe: str) -> dict[str, Any]:
    runtime = runtime.lower()
    if runtime not in RUNTIMES:
        raise ValueError(f"unknown runtime {runtime!r}; expected one of {RUNTIMES}")
    candidates = intents.get(intent)
    if not candidates:
        raise ValueError(f"unknown intent {intent!r}; expected one of {sorted(intents)}")
    for index, recipe_id in enumerate(candidates):
        recipe = recipes[recipe_id]
        if runtime in recipe["runtimes"]:
            return {
                "intent": intent,
                "recipe_id": recipe_id,
                "recipe": recipe,
                "runtime": runtime,
                "fallback_used": index > 0,
            }
    # 所有偏好都不支持该 runtime → 兜底基础 recipe（应始终支持全部 runtime）
    return {
        "intent": intent,
        "recipe_id": base_recipe,
        "recipe": recipes[base_recipe],
        "runtime": runtime,
        "fallback_used": True,
    }


def route_caption(intent: str, runtime: str) -> dict[str, Any]:
    """caption intent -> canonical recipe（含 runtime 能力检查与回退）。"""
    return _route(intent, runtime, CAPTION_INTENTS, CAPTION_RECIPES, "clean-minimal-label")


def route_transition(intent: str, runtime: str) -> dict[str, Any]:
    """transition intent -> canonical recipe（含 runtime 能力检查与回退）。"""
    return _route(intent, runtime, TRANSITION_INTENTS, TRANSITION_RECIPES, "hard-cut-clean")


def recipe_capabilities(runtime: str) -> dict[str, list[str]]:
    """某 runtime 支持的 recipe 清单（运营预览/替换入口）。"""
    runtime = runtime.lower()
    if runtime not in RUNTIMES:
        raise ValueError(f"unknown runtime {runtime!r}")
    return {
        "runtime": runtime,
        "caption_recipes": [rid for rid, r in CAPTION_RECIPES.items() if runtime in r["runtimes"]],
        "transition_recipes": [rid for rid, r in TRANSITION_RECIPES.items() if runtime in r["runtimes"]],
    }


# recipe_id -> 渲染级规格（runtime adapter 的"recipe 落地"层）。
# 渲染器只消费这些字段；不把 recipe 语义写死在某一套渲染组件里。
CAPTION_RENDER_SPECS: dict[str, dict[str, Any]] = {
    "proof-punch": {"entrance": "pop", "emphasis": "scale", "energy": "high"},
    "reveal-pop-soft": {"entrance": "fade", "emphasis": "none", "energy": "low"},
    "keyword-highlight": {"entrance": "pop", "emphasis": "underline", "energy": "high"},
    "clean-minimal-label": {"entrance": "none", "emphasis": "none", "energy": "low"},
}

TRANSITION_RENDER_SPECS: dict[str, dict[str, Any]] = {
    "hard-cut-clean": {"type": "cut", "duration_frames": 0},
    "impact-cut": {"type": "impact", "scale": 1.06, "flash": 0.15, "duration_frames": 5},
    "action-match": {"type": "fade", "duration_frames": 6},
    "flash-proof": {"type": "flash", "flash_seconds": 0.12, "duration_frames": 4},
}


def caption_render_spec(intent: str, runtime: str) -> dict[str, Any]:
    """caption intent → 渲染级规格（含 recipe_id + fallback 标记）。"""
    routed = route_caption(intent, runtime)
    spec = dict(CAPTION_RENDER_SPECS[routed["recipe_id"]])
    spec.update({"recipe_id": routed["recipe_id"], "fallback_used": routed["fallback_used"]})
    return spec


def transition_render_spec(intent: str, runtime: str) -> dict[str, Any]:
    """transition intent → 渲染级规格（含 recipe_id + fallback 标记）。"""
    routed = route_transition(intent, runtime)
    spec = dict(TRANSITION_RENDER_SPECS[routed["recipe_id"]])
    spec.update({"recipe_id": routed["recipe_id"], "fallback_used": routed["fallback_used"]})
    return spec


def scene_recipe_specs(scene_plan: Mapping[str, Any], runtime: str) -> dict[str, dict[str, Any]]:
    """从 scene_plan 的每镜 recipe intent 派生渲染级规格（按 scene_id 索引）。"""
    scenes = scene_plan.get("scenes") if isinstance(scene_plan, Mapping) else None
    caption_by_scene: dict[str, Any] = {}
    transition_by_scene: dict[str, Any] = {}
    if isinstance(scenes, list):
        for scene in scenes:
            if not isinstance(scene, Mapping):
                continue
            sid = scene.get("id")
            if not sid:
                continue
            ci = scene.get("caption_recipe_intent")
            ti = scene.get("transition_recipe_intent")
            if ci:
                caption_by_scene[str(sid)] = caption_render_spec(str(ci), runtime)
            if ti:
                transition_by_scene[str(sid)] = transition_render_spec(str(ti), runtime)
    return {"caption_recipes": caption_by_scene, "transition_recipes": transition_by_scene}
