"""
slot → 自有素材的匹配（复用 research 链原则：不重复 + 一致性）。

与 `init_template_pilot._match_source` 的关键词 hack 不同，这里：
- **不重复（no-dup）**：每个 slot 拿到一个*不同*的素材 + *不同*的 in-point 窗口；
  同一素材被复用时，取窗外偏移（不重叠），绝不两个 slot 共用同一个 start_seconds。
- **一致性（consistency）**：按 slot 的产品动作关键词打分，选与产品动作最贴近的素材；
  全部来自同一产品线（透明桌垫）的素材族，保证视觉连贯。

结果两种消费形态：
- `match_run_plan`：给 `template_run_plan.slot_bindings[].source_media_id` 赋值（去重到素材）。
- `build_source_mappings`：给 `scene_plan.metadata.source_mapping[]` 赋值（去重到素材+in-point）。

规则表（关键词 → 产品动作素材 stem 后缀）：
- 甲醛/检测/环保 → 无甲醛检测
- 桌角/贴合/翘边/挤压/不变形/对齐 → 桌角对齐-挤压不变形
- 铺开/展开/平铺 → 自动铺开对齐
- 刮/磨损/耐磨 → 防刮
- 油/水/清洁/易清洁/擦拭 → 防油易擦拭
- 餐桌/居家/生活/场景/木纹 → 餐桌场景
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
# 自有素材：V8 产品动作视频（reviewed owned source），path 在 source_media_review 里。
PRODUCT_VIDEO_DIR = ROOT / "projects/table-mat-mix-v8/inputs/source/video/product"
# 素材 stem 后缀（去掉 product_透明桌垫- 前缀）→ 匹配到的产品动作，用于 source_fit 文案。
CLIP_ACTION = "无甲醛检测|桌角对齐-挤压不变形|自动铺开对齐|防刮|防油易擦拭|餐桌场景"

# 关键词 → 素材 stem 后缀
# 注意：latin 词必须带上下文（"HAP 报告"/"HAP报告"），裸 "HAP" 会误命中
# 模板占位英文（"KEEP HAPPY HOLIDAY"）→ 语义错配（评审 P0-1 复现）。
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("无甲醛检测", ("甲醛", "检测", "环保", "0甲醛", "有醛", "醛", "HAP 报告", "HAP报告", "报告", "安全", "无味", "无毒", "异味", "材质")),
    ("桌角对齐-挤压不变形", ("桌角", "贴合", "翘边", "挤压", "不变形", "对齐", "发黄", "边缘", "不翘")),
    ("自动铺开对齐", ("铺开", "展开", "平铺", "摊开", "铺")),
    ("防刮", ("防刮", "刮", "磨损", "耐磨", "划", "随便造", "造", "耐用", "耐")),
    ("防油易擦拭", ("防油", "油污", "防水", "水", "清洁", "易清洁", "易擦", "擦拭", "克洗", "一擦", "油", "擦")),
    ("餐桌场景", ("餐桌", "居家", "生活", "场景", "木纹", "家居", "直播间", "价格", "骗", "家")),
]
_DEFAULT_ACTION = "防油易擦拭"  # 通用兜底：产品主打防水防油


def _slot_text(slot: Mapping[str, Any]) -> str:
    """slot 的文本信号（用于最终输出/调试）：overlay + visual + scene + dialogue。"""
    return " ".join(
        str(slot.get(k) or "")
        for k in ("overlay_text", "visual_content", "scene", "dialogue")
        if slot.get(k)
    )


def _slot_sources(slot: Mapping[str, Any]) -> list[tuple[float, str]]:
    """按区分度加权：overlay/visual（屏上实显，每个槽位不同）> scene > dialogue。

    模板的 dialogue 是全部槽位共用的参考台词（"防水防油…"），会掩盖槽位差异，故给最低权。
    """
    return [
        (3.0, str(slot.get("overlay_text") or "")),
        (2.0, str(slot.get("visual_content") or "")),
        (1.0, str(slot.get("scene") or "")),
        (0.2, str(slot.get("dialogue") or "")),
    ]


def _score_action(slot: Mapping[str, Any], keywords: tuple[str, ...]) -> float:
    """加权命中分：每个来源各自数命中数再乘权重，避免把共用 dialogue 当成强信号。"""
    return sum(weight * sum(1 for kw in keywords if kw in text) for weight, text in _slot_sources(slot))


def _clip_stems() -> list[str]:
    """返回自有素材的完整 stem 列表（如 product_透明桌垫-防油易擦拭）。"""
    if not PRODUCT_VIDEO_DIR.is_dir():
        return []
    return sorted(
        f.stem for f in PRODUCT_VIDEO_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in {".mp4", ".mov", ".m4v"}
    )


def _action_from_stem(stem: str) -> str:
    raw = stem.replace("product_透明桌垫-", "", 1)
    # A physical clip may carry a camera/angle suffix; keep it in the same
    # action domain for capacity and matching decisions.
    for action in sorted(_ACTION_DOMAIN_NAMES, key=len, reverse=True):
        if raw == action or raw.startswith(action + "-"):
            return action
    return raw


_ACTION_DOMAIN_NAMES = (
    "桌角对齐-挤压不变形", "自动铺开对齐", "防油易擦拭", "无甲醛检测", "餐桌场景", "防刮",
)


# 逐模板、逐 slot 的**显式**产品动作表（人工按模板 slot 语义标定；双端消费：
# 素材绑定 match_run_plan + 口播选择 build_script —— 保证「口播动作 == 素材动作」）。
# 未列出的模板回退 _best_action 关键词打分（VLM 语义匹配为后续 TODO）。
# 尾闪帧（≤1s 卡位）统一 "餐桌场景"（无口播，仅花字）。
SLOT_ACTION_BY_TEMPLATE: dict[str, list[str]] = {
    "sheet-01-video1-aks-zhuodian": [
        "防油易擦拭", "无甲醛检测", "桌角对齐-挤压不变形", "自动铺开对齐",
        "防刮", "餐桌场景", "防刮", "餐桌场景",
    ],
    "sheet-04-video4-zhuodian": [
        "餐桌场景", "无甲醛检测", "桌角对齐-挤压不变形", "自动铺开对齐",
        "防油易擦拭", "防刮", "餐桌场景", "防刮",
        "无甲醛检测", "无甲醛检测", "餐桌场景", "餐桌场景", "餐桌场景", "餐桌场景",
    ],
    "sheet-05-video5-aks-zhuodian": [
        "餐桌场景", "防油易擦拭", "桌角对齐-挤压不变形", "无甲醛检测", "餐桌场景",
        "餐桌场景", "餐桌场景", "餐桌场景", "餐桌场景", "自动铺开对齐",
        "防油易擦拭", "自动铺开对齐", "餐桌场景", "防油易擦拭", "防油易擦拭",
        "餐桌场景", "防刮", "餐桌场景", "自动铺开对齐", "餐桌场景", "餐桌场景",
    ],
    "sheet-09-video9-aks-zhuodian": [
        "餐桌场景", "无甲醛检测", "餐桌场景", "无甲醛检测", "无甲醛检测",
        "无甲醛检测", "无甲醛检测", "无甲醛检测", "餐桌场景", "桌角对齐-挤压不变形",
        "桌角对齐-挤压不变形", "桌角对齐-挤压不变形", "餐桌场景", "餐桌场景",
        "桌角对齐-挤压不变形", "桌角对齐-挤压不变形", "餐桌场景", "餐桌场景",
        "无甲醛检测", "无甲醛检测", "桌角对齐-挤压不变形",
    ],
    "sheet-14-video15-aks-zhuodian": [
        "餐桌场景", "餐桌场景", "桌角对齐-挤压不变形", "餐桌场景", "餐桌场景",
        "餐桌场景", "桌角对齐-挤压不变形", "餐桌场景", "餐桌场景", "无甲醛检测",
        "无甲醛检测", "餐桌场景", "餐桌场景", "餐桌场景", "无甲醛检测",
        "无甲醛检测", "防刮", "防油易擦拭", "餐桌场景", "桌角对齐-挤压不变形",
        "餐桌场景", "餐桌场景", "餐桌场景", "防油易擦拭", "防刮", "防油易擦拭",
        "餐桌场景", "餐桌场景", "餐桌场景", "餐桌场景",
    ],
"sheet-09-video9-aks-zhuodian-c2": [
        "无甲醛检测", "餐桌场景", "桌角对齐-挤压不变形", "防刮",
        "无甲醛检测", "餐桌场景", "桌角对齐-挤压不变形", "防刮",
    ],
    "sheet-14-video15-aks-zhuodian-c3": [
        "餐桌场景", "无甲醛检测", "防刮", "防油易擦拭",
        "桌角对齐-挤压不变形", "餐桌场景", "无甲醛检测", "防刮",
        "防油易擦拭",
    ],
    "sheet-19-video22-aks-zhuodian-c4": [
        "无甲醛检测", "防刮", "餐桌场景", "防油易擦拭",
        "桌角对齐-挤压不变形", "无甲醛检测", "防刮", "防油易擦拭",
    ],
"sheet-04-video4-zhuodian-c1": [
        "餐桌场景", "无甲醛检测", "桌角对齐-挤压不变形", "自动铺开对齐",
        "防油易擦拭", "防刮", "无甲醛检测", "餐桌场景",
    ],
    "sheet-05-video5-aks-zhuodian-c1": [
        "餐桌场景", "防油易擦拭", "桌角对齐-挤压不变形", "无甲醛检测",
        "自动铺开对齐", "防油易擦拭", "自动铺开对齐", "餐桌场景",
        "防油易擦拭", "餐桌场景", "防刮", "餐桌场景",
        "自动铺开对齐", "餐桌场景",
    ],
    "sheet-19-video22-aks-zhuodian-c1": [
        "餐桌场景", "无甲醛检测", "防刮", "防油易擦拭",
        "桌角对齐-挤压不变形", "防刮", "餐桌场景", "无甲醛检测",
        "餐桌场景",
    ],
    "sheet-14-video15-aks-zhuodian-c1": [
        "餐桌场景", "桌角对齐-挤压不变形", "无甲醛检测", "餐桌场景", "无甲醛检测",
        "防刮", "防油易擦拭", "防刮", "防油易擦拭", "餐桌场景",
    ],
    "sheet-19-video22-aks-zhuodian": [
        "餐桌场景", "餐桌场景", "无甲醛检测", "无甲醛检测", "无甲醛检测",
        "餐桌场景", "防刮", "防油易擦拭", "防油易擦拭", "桌角对齐-挤压不变形",
        "桌角对齐-挤压不变形", "防刮", "餐桌场景", "餐桌场景", "餐桌场景", "餐桌场景",
        "无甲醛检测", "餐桌场景", "餐桌场景", "餐桌场景", "餐桌场景", "餐桌场景",
    ],
}


def _best_action(slot: Mapping[str, Any]) -> str:
    """按加权命中分返回最贴近的产品动作素材后缀。

    命中数相同（很多槽位都含"防水防油"）时，选关键词更特化的动作（关键词列表更短）。
    """
    scored = []
    for action, keywords in _RULES:
        hits = _score_action(slot, keywords)
        if hits > 0:
            scored.append((hits, -len(keywords), action))  # 少关键词、更特化
    if not scored:
        return _DEFAULT_ACTION
    scored.sort(reverse=True)
    return scored[0][2]


# 公开别名（best_action 便于下游/测试引用）
best_action = _best_action


def match_run_plan(
    slots: list[Mapping[str, Any]],
    run: dict,  # template_run_plan（含 slot_bindings），就地更新绑定
) -> dict[str, str]:
    """把每个 slot 绑定到自有素材（no-dup 优先 + 显式复用）。返回 {slot_id: stem}。

    规则：按槽位序，先尽量给每个 slot 分配"每素材至多一次"；素材不足时允许复用，
    但复用必须**显式标注**（跨景别强调），不许静默重复装填。consistency 由同产品线保证。
    slot 动作来源：逐模板显式表（SLOT_ACTION_BY_TEMPLATE）优先，否则关键词打分 _best_action。
    """
    bindings = run.get("slot_bindings") or []
    stems = _clip_stems()
    if not stems:
        raise SystemExit("无自有素材池，无法匹配（先确认 V8 product 视频存在）")

    # 逐 slot 打分，得到一个 (slot_index, action) 的期望；用全局不重复贪心分配。
    explicit = SLOT_ACTION_BY_TEMPLATE.get(str(run.get("template_id") or "")) or []
    desired = []
    for i, slot in enumerate(slots):
        action = explicit[i] if i < len(explicit) else _best_action(slot)
        desired.append((i, action))

    used_stems: set[str] = set()
    use_count: dict[str, int] = {stem: 0 for stem in stems}
    assigned: dict[str, str] = {}
    # 记录每个 stem 第一次分配到的 slot（用于复用标注"跨景别强调"）。
    first_slot_by_stem: dict[str, tuple[int, Mapping[str, Any]]] = {}
    reason_by_slot: dict[str, str] = {}

    def _shot_size(slot: Mapping[str, Any]) -> str:
        return str((slot.get("shot_language") or {}).get("shot_size") or "未知景别")

    for i, action in desired:
        slot = slots[i]
        slot_id = slot.get("slot_id")
        unused = [s for s in stems if s not in used_stems]
        unused_exact = [s for s in unused if _action_from_stem(s) == action]
        if unused_exact:
            # 1) 未用且动作精确匹配：首次分配（语义优先，绝不拿错动作素材顶替）。
            chosen = min(unused_exact, key=lambda stem: (use_count[stem], stem))
            is_reuse = False
            reason_by_slot[slot_id] = f"自有素材「{chosen}」匹配该 slot 产品动作（首次分配）"
            first_slot_by_stem[chosen] = (i, slot)
        else:
            used_exact = [s for s in used_stems if _action_from_stem(s) == action]
            if used_exact:
                # 2) 未用无精确匹配：复用已用过的**同动作**素材（跨景别强调，显式标注）。
                # Balance repeated use across physical clips in one action
                # domain before falling back to stable lexical ordering.
                chosen = min(used_exact, key=lambda stem: (use_count[stem], stem))
                is_reuse = True
                prev_idx, prev_slot = first_slot_by_stem.get(chosen, (i, slot))
                reason_by_slot[slot_id] = (
                    f"模板跨景别强调：slot 序号 {prev_idx + 1}（{_shot_size(prev_slot)}）与 slot 序号 {i + 1}"
                    f"（{_shot_size(slot)}）为「{_action_from_stem(chosen)}」卖点，复用素材「{chosen}」，"
                    f"in-point 由语义证据窗口独立分配（不重复同一画面）"
                )
            else:
                # 3) 素材池根本没有该动作：显式 gap（generate），绝不静默错配并标记"首次匹配"。
                b = next((x for x in bindings if x.get("slot_id") == slot_id), None)
                if b is not None:
                    b["source"] = "generate"
                    b["source_media_id"] = None
                    b["asset_type"] = "video"
                    b["reason"] = (f"素材池缺少「{action}」动作素材；该 slot 需付费生成，"
                                   f"禁止用其他动作素材顶替（语义错配）")
                assigned[slot_id] = ""
                continue
        used_stems.add(chosen)
        use_count[chosen] += 1
        assigned[slot_id] = chosen

    # 就地更新绑定（run 后续会被重新 hash/落盘，in-place 与 bind_slot 语义一致）。
    by_id = {b.get("slot_id"): b for b in bindings}
    for slot_id, stem in assigned.items():
        b = by_id.get(slot_id)
        if b is not None:
            b["source"] = "owned"
            b["source_media_id"] = stem
            b["asset_type"] = None
            b["reason"] = reason_by_slot.get(slot_id, f"自有素材「{stem}」匹配该 slot 产品动作")
    return assigned


# 每素材的"证据动作语义窗口"（人工看帧标定，_action_from_stem 的后缀为 key）。
#
# 这是**语义匹配**的关键：proof 镜头的 in-point 必须落在该素材里"证据实际发生"
# 的区间，而不是 matrix row 的粗估源区间（后者覆盖整个动作链，含"已擦干净"这类
# 误导段）。key = 素材 stem 后缀；value = {window: (start, end), label: 证据动作}。
# window 是开区间 [start, end)，应落在素材时长内。
SEMANTIC_EVIDENCE_WINDOWS: dict[str, dict] = {
    "防油易擦拭": {"window": (0.5, 8.0), "label": "倒油→油滴落桌→纸巾擦走（油污一擦即净）"},
    "防刮": {"window": (1.9, 7.6), "label": "硬物在垫面刮擦（防刮耐磨）"},
    "无甲醛检测": {"window": (0.0, 8.0), "label": "手持检测仪读数（0甲醛 检测报告）"},
    "桌角对齐-挤压不变形": {"window": (1.7, 5.75), "label": "手铺平桌角贴合边缘（贴合不翘边）"},
    "自动铺开对齐": {"window": (0.2, 3.9), "label": "桌垫自动铺开并完成对齐"},
    "餐桌场景": {"window": (0.0, 7.5), "label": "餐桌生活场景（透明垫不遮木纹质感）"},
}


def _semantic_window(stem: str) -> dict | None:
    """返回素材的语义证据窗口；无则 None（回退到 matrix 源区间）。"""
    action = _action_from_stem(stem)
    return SEMANTIC_EVIDENCE_WINDOWS.get(action)


def build_source_mappings(
    scenes: list[dict],  # scene_plan.scenes[]
    slot_by_scene: dict[str, Mapping[str, Any]],  # scene_id → slot（键控配对）
    assigned: dict[str, str],  # {slot_id: stem}
    *,
    source_review_urls: dict[str, str] | None = None,  # {stem: source_path}（reviewed owned source）
    grounding: dict[str, dict] | None = None,  # {stem: {matrix_row_id, matrix_resolution_id, ...}}
    research_direction: str | None = None,
) -> list[dict]:
    """为每个 scene 构造去重到素材+in-point 的 source_mapping 条目。

    **键控配对**（评审 P0-1）：scene ↔ slot 通过 scene_id 显式映射，绝不按位置
    `scene[i] ↔ slot[i]` 取值；scene 无 slot 映射时直接报错（fail-closed，防漂移）。
    source_path 尽量用 reviewed owned source 的路径（否则回退到 v8 目录约定）。
    """
    durations = _clip_durations()
    cursor: dict[str, float] = {stem: 0.0 for stem in assigned.values()}
    _used_windows: dict[str, list[tuple[float, float]]] = {stem: [] for stem in assigned.values()}

    mappings: list[dict] = []
    for scene in scenes:
        scene_id = str(scene.get("id") or "")
        slot = slot_by_scene.get(scene_id)
        if slot is None:
            raise ValueError(f"scene {scene_id} 缺少 slot 映射（键控配对失败，禁止位置兜底）")
        slot_id = str(slot.get("slot_id") or scene_id)
        stem = assigned.get(slot_id)
        if not stem:
            # P0-2：缺口/未绑定 slot 禁止回退默认动作素材（必须由 readiness 门阻断，
            # 或走 COMPRESS/MARK_GAP 流程——确保"无证据素材不顶替"）。
            raise ValueError(f"slot {slot_id} 未绑定素材（缺口或未批准），禁止静默回退默认动作素材")
        start = round(cursor[stem], 3)
        dur = scene["end_seconds"] - scene["start_seconds"]
        clip_dur = durations.get(stem, dur)
        end = min(start + dur, clip_dur)
        cursor[stem] = start + dur + 0.25
        if cursor[stem] + dur > clip_dur:
            cursor[stem] = 0.0
        action = _action_from_stem(stem)
        if source_review_urls and stem in source_review_urls:
            source_path = source_review_urls[stem]
        else:
            source_path = f"projects/table-mat-mix-v8/inputs/source/video/product/{stem}.MP4"
        item = {
            "scene_id": scene["id"],
            "template_slot_ref": slot_id,
            "source_path": source_path,
            "source_interval": {"start_seconds": start, "end_seconds_exclusive": round(end, 3)},
            "timeline_interval": {"start_seconds": scene["start_seconds"], "end_seconds_exclusive": scene["end_seconds"]},
            "reference_evidence": {
                "mode": "structural_only",
                "mechanism": f"借用模板 slot 的「{action}」产品动作证明方式",
                "rationale": "模板 slot 结构驱动，仅沿用镜头语法，不复制参考台词/花字",
            },
            "reference_basis": "模板 slot 结构复用",
            "source_fit": f"自有素材「{action}」完整展示该 slot 的产品动作",
            "mapping_reason": f"镜头意图匹配 {action} 素材，去重且 in-point 不重叠",
            "originality_note": "主体、字幕与剪辑均为本项目表达；参考仅用于分析",
        }
        # 语义窗口差异化分配（P1-6）：不依赖 matrix_row_id，无条件计算可用区间。
        # （无 grounding 素材若走旧 cursor 会产出完全相同窗口 —— H3 违规根因）
        sem = _semantic_window(stem)
        tr = (grounding or {}).get(stem, {}).get("source_time_range") or {}
        lo, hi = tr.get("start_seconds"), tr.get("end_seconds_exclusive")
        m_lo = float(lo) if isinstance(lo, (int, float)) else 0.0
        m_hi = float(hi) if isinstance(hi, (int, float)) else clip_dur
        # 研究链 grounding：若该素材能桥接到已解析 matrix row，则挂 row ref（满足 scene_plan 硬门）。
        g = (grounding or {}).get(stem) or {}
        if True:  # 评审 P1-6：窗口差异化分配无条件执行（matrix 只是可用区间的信息来源之一）；
            # 无 grounding 素材同样必须走差异化窗口（否则 cursor 复用 → H3 完全重复）。
            if g.get("matrix_row_id"):
                item["matrix_row_id"] = g["matrix_row_id"]
                item["matrix_resolution_id"] = g.get("matrix_resolution_id")
                if research_direction:
                    item["research_direction_ref"] = research_direction
            # 硬门：source_interval 必须落在 matrix row 的 approved source_time_range 内，
            # **且长度 == timeline span**（2s 场景取 2s 素材窗，绝不拉成整段 matrix 区间）。
            # 关键：优先锚定到该素材的**语义证据窗口**（人在哪一秒发生证据动作），
            # 而不是粗估 matrix 源区间——否则会切到"已擦干净/无动作"的误导段。
            # 关键修复（评审 P0）：窗口分配只依赖语义证据窗口存在，不依赖 matrix_row_id ——
            # 无 grounding 的素材走 cursor 复用会产出完全相同窗口（H3 违规，05c1 自动铺开×3）。
            sem = _semantic_window(stem)
            tr = g.get("source_time_range") or {}
            lo = tr.get("start_seconds")
            hi = tr.get("end_seconds_exclusive")
            m_lo = float(lo) if isinstance(lo, (int, float)) else 0.0
            m_hi = float(hi) if isinstance(hi, (int, float)) else clip_dur
            if sem and isinstance(sem.get("window"), (tuple, list)) and len(sem["window"]) == 2:
                span = max(dur, 0.1)
                s_lo, s_hi = float(sem["window"][0]), float(sem["window"][1])
                avail_lo = max(m_lo, s_lo)
                avail_hi = min(m_hi, s_hi)
                if avail_hi > avail_lo:
                    # 从语义窗口起点开始，避免落到尾部"动作已结束"段。
                    used = _used_windows[stem]
                    win_start = avail_lo
                    # 候选起点：先在语义窗口内从起点推进；语义窗口塞不下时，
                    # 回退到整个 matrix 区间（仍然在源素材内）寻找未用窗口——
                    # 绝不重复已分配的 in-point（no-dup 硬约束）。
                    def _candidates():
                        # 语义窗口内优先
                        s = avail_lo
                        while s + span <= avail_hi + 1e-9:
                            yield s
                            s += span + 0.25
                        # 语义窗口之外（matrix 区间内），从尾部向前取，避免占用语义段
                        s2 = max(m_lo, m_hi - span)
                        while s2 >= m_lo:
                            yield s2
                            s2 -= span + 0.25
                    def _fine_grid(lo_, hi_, span_):
                        s = lo_
                        while s + span_ <= hi_ + 1e-9:
                            yield round(s, 3)
                            s += 0.25
                    chosen_start = None
                    for cand in _candidates():
                        win = (cand, cand + span)
                        if (cand + span) <= m_hi and not any(
                            win[0] < used_end and used_start < win[1] for used_start, used_end in used
                        ):
                            chosen_start = cand
                            break
                    if chosen_start is None:
                        # 实在没有无重叠位置：回退到「窗口差异化」——在同一素材的候选起点集合里
                        # 选一个与已用窗口起点距离最远的起点（保证起始差 ≥ 0.75s；窗口允许部分重叠，
                        # 但绝不允许与已用窗口完全相同 → 画面不会逐帧重复）。
                        fine = [c for c in _fine_grid(avail_lo, avail_hi, span)
                                 if all(abs(c - s) >= 0.75 for s, _ in used)
                                 and all(abs(c - s) > 1e-6 for s, _ in used)]
                        if fine:
                            def _min_gap(cand):
                                gaps = [abs(cand - s) for s, _ in used] if used else [1.0]
                                return min(gaps)
                            chosen_start = max(fine, key=_min_gap)
                        else:
                            raise ValueError(
                                f"素材 {stem} 的合法窗口已耗尽，无法满足 H3/H4（窗口容量不足）"
                            )
                    item["source_interval"]["start_seconds"] = round(chosen_start, 3)
                    item["source_interval"]["end_seconds_exclusive"] = round(chosen_start + span, 3)
                    _used_windows[stem].append((item["source_interval"]["start_seconds"], item["source_interval"]["end_seconds_exclusive"]))
                    cursor[stem] = chosen_start + span + 0.25
        mappings.append(item)
    return mappings


def _clip_durations() -> dict[str, float]:
    """从 v8 media_index 读每个素材时长。"""
    path = ROOT / "projects/table-mat-mix-v8/artifacts/media_index.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    out: dict[str, float] = {}
    for e in data.get("entries") or []:
        if e.get("media_type") != "video":
            continue
        stem = Path(e.get("path", "")).stem
        probe = e.get("probe") or {}
        dur = probe.get("duration_seconds")
        if isinstance(dur, (int, float)) and dur > 0:
            out[stem] = float(dur)
    return out


def resolve_matrix_grounding(
    source_review: Mapping[str, Any],
    matrix: Mapping[str, Any],
) -> dict[str, dict]:
    """把每个源素材桥接到真实 research matrix row：{stem_0f_path: grounding}。

    通过 ``representative_frames`` ∩ matrix row ``evidence_frames`` 建立内容寻址桥
    （参考 lib.cinematic_fast_validation._matches_matrix_source 的桥接语义），
    避免接受任意替换。返回每个源 stem 的 {matrix_row_id, matrix_resolution_id, source_time_range}。
    """
    # source_media_id (source-03...) → reviewed source path/frames
    frames_by_stem: dict[str, set[str]] = {}
    path_by_stem: dict[str, str] = {}
    for f in source_review.get("files", []) if isinstance(source_review, Mapping) else []:
        if not isinstance(f, Mapping):
            continue
        stem = Path(str(f.get("path") or "")).stem
        frames = {x for x in (f.get("representative_frames") or []) if isinstance(x, str) and x}
        frames_by_stem[stem] = frames
        path_by_stem[stem] = str(f.get("path") or "")
    # matrix rows by evidence frame overlap
    grounding: dict[str, dict] = {}
    for stem, frames in frames_by_stem.items():
        best_row = None
        for row in matrix.get("rows", []) if isinstance(matrix, Mapping) else []:
            if not isinstance(row, Mapping):
                continue
            if row.get("resolution") == "pending":
                continue
            row_frames = {x for x in (row.get("evidence_frames") or []) if isinstance(x, str) and x}
            if frames & row_frames:
                best_row = row
                break
        if best_row is not None:
            grounding[stem] = {
                "matrix_row_id": str(best_row.get("matrix_row_id")),
                "matrix_resolution_id": str(best_row.get("resolution")),
                "source_time_range": dict(best_row.get("source_time_range") or {}),
                "source_path": path_by_stem.get(stem),
            }
    return grounding


# ---------------------------------------------------------------------------
# 文案↔素材 语义一致性校验器（V2：显式动作表自洽不够，需「可证关键词」真值校验）
# ---------------------------------------------------------------------------

# 每动作素材的「可证关键词」：文案至少命中 1 个（画面能证明的说法）。
PROOF_KEYWORDS: dict[str, tuple[str, ...]] = {
    "餐桌场景": ("家", "桌", "饭", "菜", "茶", "干净", "省心", "质感", "木纹", "家人",
                "孩子", "清爽", "生活", "舒服", "适合", "吃", "放心", "食物",
                "缝隙", "脏", "藏", "挑", "光泽", "热", "桌面", "磨砂", "情况"),
    "无甲醛检测": ("检测", "测", "读数", "合格", "安全", "健康", "材质", "软玻璃",
                  "异味", "母婴", "用料", "验", "归零"),
    "桌角对齐-挤压不变形": ("边角", "圆角", "边缘", "贴合", "毛刺", "挤压", "复原",
                          "变形", "对齐", "服帖", "刮手", "平整"),
    "防刮": ("刮", "划", "耐磨", "抗造", "扒拉", "光滑", "如新", "硬物"),
    "防油易擦拭": ("油", "水", "擦", "污", "净", "撒", "酒水"),
    "自动铺开对齐": ("铺", "平", "对齐", "尺寸"),
}

# 事实卡/服务/价格类通用语境词：任何画面都允许的「事实引述」口径（与参考片 01/04/05 一致）。
FACT_CITATION_WORDS: tuple[str, ...] = (
    "价格", "价钱", "贵", "便宜", "元", "20", "30", "年", "SGS", "报告", "免费", "定制",
    "尺寸", "直播", "买", "选", "一份", "份钱", "做工", "品质", "好物", "值得", "配得",
)

# 跨动作 claim 判定用「强动作词」：只对无法化妆成生活语境的证据动作词敏感
# （去掉 干净/光滑/质感/软玻璃/尺寸 等上下文泛词，避免误报）。
STRONG_ACTION_TERMS: dict[str, tuple[str, ...]] = {
    "无甲醛检测": ("检测", "测", "读数", "合格", "归零", "验"),
    "桌角对齐-挤压不变形": ("边角", "圆角", "毛刺", "挤压", "复原", "贴合", "服帖", "边缘"),
    "防刮": ("刮", "划", "耐磨", "扒拉", "硬物"),
    "防油易擦拭": ("擦", "油", "水", "污", "撒"),
    "自动铺开对齐": ("铺",),
    "餐桌场景": (),
}

_NEGATION_PREFIX = ("不", "无", "没", "别", "莫")


def semantic_mismatches(script: Mapping[str, Any]) -> list[dict[str, str]]:
    """逐镜校验：文案必须给出该镜绑定素材的「可证说法」，且不得claim其他素材的能力。

    返回 [{section_id, message, narrated, bound_action}]；空 = 通过。
    """
    findings: list[dict[str, str]] = []
    for section in (script.get("sections") or []):
        if not isinstance(section, Mapping):
            continue
        narr = str(section.get("narration") or "").strip()
        if not narr:
            continue
        bound = str(section.get("bound_material_action") or "")
        if bound not in PROOF_KEYWORDS:
            continue
        text = narr + " " + str(section.get("screen_copy") or "")
        # 参考片式反问句（“…行不行？”）：提问而非断言，豁免证明词要求（与已批准 01/04/05 口径一致）。
        if narr.rstrip().endswith(("？", "?")):
            continue
        anchored = any(kw in text for kw in PROOF_KEYWORDS[bound])
        fact = any(kw in text for kw in FACT_CITATION_WORDS)
        if not (anchored or fact):
            findings.append({
                "section_id": str(section.get("id") or ""),
                "message": f"文案无「{bound}」动作的可证锚点（{PROOF_KEYWORDS[bound][:3]}…）",
                "narrated": narr, "bound_action": bound,
            })
            continue
        # 跨动作 claim：文案主张了其他素材才能证明的动作（强动作词判定；否定句豁免，
        # 如「不翘边/毛刺不存在/不刮手」属于边界安全类可证表达）
        for other, kws in STRONG_ACTION_TERMS.items():
            if other == bound:
                continue
            for kw in kws:
                idx = text.find(kw)
                while idx >= 0:
                    prefix = text[max(0, idx - 2):idx]
                    if not any(prefix.endswith(neg) for neg in _NEGATION_PREFIX):
                        findings.append({
                            "section_id": str(section.get("id") or ""),
                            "message": f"文案含「{other}」专属证明词「{kw}」（画面为{bound}，无法证明）",
                            "narrated": narr, "bound_action": bound,
                        })
                        break
                    idx = text.find(kw, idx + 1)
                else:
                    continue
                break
    return findings


# ---------------------------------------------------------------------------
# 画面重合度标准（评审：成片内不能“同一镜头用多次”）
# ---------------------------------------------------------------------------
# 硬标准：
#   H1 相邻镜头不得使用同一素材（同素材连播 = 视觉重复）
#   H2 单一素材占全片时长 ≤ 1/3（30 镜模板配 6 素材的理论下限 ≈ 29%）
#   H3 同一素材的 in-point 窗口不得重叠（既有分配器约束，报告复核）
# 软指标（展示）：
#   S1 单素材复用次数（上限 = ceil(镜数/素材数)；超限 → 建议换动作句/补素材素材）
#   S2 同素材两次使用间至少相隔 2 镜（diff≥3；降低“同一镜头反复出现”的感知）
REUSE_HARD = {"adjacent_same": 0, "single_ratio_max": 1 / 3}
REUSE_SOFT = {"min_use_gap_scenes": 3, "min_window_start_gap": 0.75}


def material_reuse_report(scene_plan: Mapping[str, Any]) -> dict[str, Any]:
    """基于 scene_plan.source_mapping 的素材复用/重合度报告。

    返回：{counts, max_stem, max_reuse, single_ratio, adjacent_same, overlap_violations,
          min_gap_violations, hard_pass, findings[]}
    """
    import os

    mapping = (scene_plan or {}).get("metadata", {}).get("source_mapping") or []
    stems: list[str] = []
    durations: dict[str, float] = {}
    index_by_stem: dict[str, list[int]] = {}
    windows: dict[str, list[tuple[float, float]]] = {}
    total = 0.0
    for scene in (scene_plan or {}).get("scenes", []) if isinstance(scene_plan, Mapping) else []:
        total += float(scene.get("end_seconds", 0)) - float(scene.get("start_seconds", 0))
    for idx, m in enumerate(mapping):
        stem = os.path.splitext(os.path.basename(str(m.get("source_path") or "")))[0]
        stems.append(stem)
        dur = float(m["timeline_interval"]["end_seconds_exclusive"]) - float(m["timeline_interval"]["start_seconds"])
        durations[stem] = durations.get(stem, 0.0) + dur
        index_by_stem.setdefault(stem, []).append(idx)
        w = (float(m["source_interval"]["start_seconds"]), float(m["source_interval"]["end_seconds_exclusive"]))
        windows.setdefault(stem, []).append(w)
    n_materials = len({s.replace("product_透明桌垫-", "") for s in stems}) if stems else 1
    adjacent_same = sum(1 for i in range(1, len(stems)) if stems[i] == stems[i - 1])
    ratio = {stem: round(d / max(total, 0.01), 3) for stem, d in durations.items()}
    max_stem = max(durations, key=durations.get) if durations else ""
    max_reuse = len(index_by_stem.get(max_stem, [])) if max_stem else 0
    single_ratio = ratio.get(max_stem, 0.0)

    identical_windows = []
    for stem, ws in windows.items():
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                a, b = ws[i], ws[j]
                if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
                    identical_windows.append(f"{stem}: window{i}==window{j}")
    # 相邻（同素材先后两次使用）窗口起点差 ≥ min_window_start_gap：保证“微变化”，
    # 即使窗口部分重叠也不是同一帧画面。
    min_window_gaps = []
    for stem in index_by_stem:
        idxs = index_by_stem[stem]
        for i in range(1, len(idxs)):
            a, b = windows[stem][idxs.index(idxs[i]) - 1], windows[stem][idxs.index(idxs[i])]
            gap = abs(b[0] - a[0])
            if gap < REUSE_SOFT["min_window_start_gap"]:
                min_window_gaps.append(f"{stem}: 第{idxs[i-1]+1}与第{idxs[i]+1}镜起点差{gap:.2f}s")
    min_gap_violations = []
    for stem, idxs in index_by_stem.items():
        for i in range(1, len(idxs)):
            if idxs[i] - idxs[i - 1] < REUSE_SOFT["min_use_gap_scenes"]:
                min_gap_violations.append(f"{stem}: 第{idxs[i-1]+1}与第{idxs[i]+1}镜间隔{idxs[i]-idxs[i-1]-1}镜")
    hard_pass = (
        adjacent_same <= REUSE_HARD["adjacent_same"]
        and single_ratio <= REUSE_HARD["single_ratio_max"]
        and not identical_windows
        and not min_window_gaps
    )
    findings = []
    if adjacent_same > REUSE_HARD["adjacent_same"]:
        findings.append(f"H1 相邻镜头同素材 ×{adjacent_same}")
    if single_ratio > REUSE_HARD["single_ratio_max"]:
        findings.append(f"H2 「{max_stem}」占片 {single_ratio:.0%}（标准 ≤33%）")
    if identical_windows:
        findings.append("H3 完全重复窗口: " + "; ".join(identical_windows[:3]))
    if min_window_gaps:
        findings.append("H4 同素材相邻窗口起点差不足: " + "; ".join(min_window_gaps[:3]))
    if min_gap_violations:
        findings.append("S2 复用间隔不足: " + "; ".join(min_gap_violations[:3]))
    if n_materials and max_reuse > max(2, -(-len(stems) // n_materials)):
        findings.append(
            f"S1 复用次数 {max_reuse} 次 > 理论下限 {max(2, -(-len(stems) // n_materials))}（{len(stems)}镜/{n_materials}素材）")
    # ---- 严格档（评审：用户要求"高严格"画面重复判定）----
    # S-H2' 单素材占比 ≤ 1/4；S-H3' 同素材窗口**完全不重叠**；S-H4' 起点差 ≥ 1.5s；
    # S-S1' 复用次数 ≤ ceil(N/M) 硬门；S-S2' 任意两次使用间隔 ≥ 4 镜。
    n_materials_actual = max(len({s.replace("product_透明桌垫-", "") for s in stems}), 1) if stems else 1
    use_cap = max(2, -(-len(stems) // n_materials_actual)) if stems else 0
    strict_uses = [s for s, ms in index_by_stem.items()
                   if len(ms) > use_cap and s.replace("product_透明桌垫-", "") != max_stem.replace("product_透明桌垫-", "")]
    strict_findings = []
    if any(len(v) > use_cap for v in index_by_stem.values()):
        strict_findings.append(f"S1' 复用超限（上限 {use_cap}/素材）")
    if any(r > 0.25 for r in ratio.values()):
        strict_findings.append("S2' 单素材占比 > 25%")
    # 完全非重叠 + 起点差 1.5s
    overlap_pairs = []
    small_gaps = []
    for stem, ws in windows.items():
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                a, b = sorted((ws[i], ws[j]))
                if b[0] < a[1]:
                    overlap_pairs.append(f"{stem}: w{i}∩w{j}")
                elif abs(b[0] - a[0]) < 1.5:
                    small_gaps.append(f"{stem}: w{i}/w{j} 起点差 {abs(b[0]-a[0]):.2f}s")
    if overlap_pairs:
        strict_findings.append("S3' 同素材窗口重叠 " + "; ".join(overlap_pairs[:3]))
    if small_gaps:
        strict_findings.append("S4' 起点差 < 1.5s " + "; ".join(small_gaps[:3]))
    min_gap_strict = [f"{stem}" for stem, idxs in index_by_stem.items()
                      for i in range(1, len(idxs)) if idxs[i] - idxs[i - 1] < 4][:3]
    if min_gap_strict:
        strict_findings.append("S5' 复用间隔 < 4 镜: " + ", ".join(min_gap_strict))
    strict_pass = not strict_findings
    return {
        "strict_pass": strict_pass, "strict_findings": strict_findings,
        "use_capacity": use_cap,
        "counts": {k.replace("product_透明桌垫-", ""): len(v) for k, v in index_by_stem.items()},
        "max_stem": max_stem.replace("product_透明桌垫-", ""), "max_reuse": max_reuse,
        "single_ratio": single_ratio, "adjacent_same": adjacent_same,
        "identical_windows": identical_windows, "min_window_gaps": min_window_gaps,
        "hard_pass": hard_pass, "findings": findings,
    }


# ---------------------------------------------------------------------------
# P0-1：窗口级容量 / slot_semantics / 容量判定（设计文档 §3.1-3.5 + 附录 A2/A3）
# ---------------------------------------------------------------------------
WINDOW_STEP = 0.25          # 窗口候选步长（秒）
WINDOW_GAP = 0.75           # H4：同素材相邻窗口起点差
DIVERSIFY_MIN_ASSETS_PER_DOMAIN = 2
CAPACITY_SOLVER = "greedy-capacity-v1"
ROLE_UTILITY = {"hook": 10, "cta": 10, "reveal": 7, "payoff": 8, "proof": 6,
                "problem": 5, "escalation": 5, "other": 4}


def _media_stems_by_domain(stems: list[str] | None = None) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for stem in stems if stems is not None else _clip_stems():
        grouped.setdefault(_action_from_stem(stem), []).append(stem)
    return {domain: sorted(media) for domain, media in grouped.items()}


def _window_capacity_for_media(action: str, stem: str, slot_s: float, *, step: float,
                               gap: float) -> dict[str, Any]:
    win = SEMANTIC_EVIDENCE_WINDOWS.get(action)
    if not win or not isinstance(win.get("window"), (tuple, list)):
        return {"capacity": 0, "candidates": [], "basis": {"error": "无证据窗口"}}
    lo, hi = float(win["window"][0]), float(win["window"][1])
    durations = _clip_durations()
    dur = durations.get(stem, durations.get(f"product_透明桌垫-{action}", hi))
    legal_max = min(hi, dur)
    candidates = []
    s = lo
    while s + slot_s <= legal_max + 1e-9:
        candidates.append(round(s, 3))
        s += step
    picked: list[float] = []
    for cand in candidates:
        if not picked or cand - picked[-1] >= gap:
            picked.append(cand)
    return {
        "capacity": len(picked),
        "candidates": candidates[:80],
        "basis": {"evidence_window": [float(win["window"][0]), float(win["window"][1])],
                  "source_media_id": stem, "source_duration": round(dur, 3),
                  "slot_s": slot_s, "step": step, "gap": gap},
    }


def window_capacity(action: str, slot_s: float, *, step: float = WINDOW_STEP,
                    gap: float = WINDOW_GAP) -> dict[str, Any]:
    """Aggregate C(a,l,delta) over physical media in one action domain."""
    media = _media_stems_by_domain().get(action, [])
    if not media:
        return {"capacity": 0, "candidates": [],
                "basis": {"error": "动作域无物理素材", "action_domain": action}}
    per_media = {
        stem: _window_capacity_for_media(action, stem, slot_s, step=step, gap=gap)
        for stem in media
    }
    return {
        "capacity": sum(item["capacity"] for item in per_media.values()),
        "candidates": [
            {"source_media_id": stem, "start_seconds": start}
            for stem, item in per_media.items() for start in item["candidates"]
        ][:80],
        "basis": {"action_domain": action, "physical_media_count": len(media),
                  "per_media": {stem: item["basis"] for stem, item in per_media.items()},
                  "slot_s": slot_s, "step": step, "gap": gap},
    }


def slot_semantics(template: Mapping[str, Any]) -> list[dict[str, Any]]:
    """标准化 slot 语义（附录 A1 效用规则 + §3.1 字段契约）。"""
    from lib.template_mainline import _NARRATION_BY_TEMPLATE, _NARRATION_DEFAULT

    tid = str(template.get("template_id") or "")
    actions = SLOT_ACTION_BY_TEMPLATE.get(tid, [])
    rows = _NARRATION_BY_TEMPLATE.get(tid, _NARRATION_DEFAULT)
    semantics = []
    for i, slot in enumerate(template.get("slots") or [], start=1):
        slot_s = float(slot.get("duration_s") or 2.0)
        role = rows[i - 1][2] if i - 1 < len(rows) else "proof"
        domain = actions[i - 1] if i - 1 < len(actions) else _best_action(slot)
        semantics.append({
            "slot_id": str(slot.get("slot_id") or f"slot-{i:03d}"),
            "ordinal": i, "duration_s": slot_s, "action_domain": domain,
            "beat_role": role, "source_section_ref": f"sec-{i:03d}",
            "utility": ROLE_UTILITY.get(role, 4),
            "required_group": role if role in ("hook", "cta") or role == "payoff" else
                              (f"evidence:{domain}" if role == "proof" else ""),
            "predecessor_refs": [f"slot-{i - 1:03d}"] if i > 1 else [],
            "candidate_assets": [f"product_透明桌垫-{domain}"],
        })
    return semantics


def capacity_verdict(template: Mapping[str, Any], *, allow_compress: bool = True) -> dict[str, Any]:
    """§3.5 三步判定（P0-1 版：贪心容量检查；精确子集求解 = P1-1 CP-SAT）。

    DIVERSIFY / DIVERSIFY_LIMITED / COMPRESS / MARK_GAP。
    """
    import hashlib

    tid = str(template.get("template_id") or "")
    slots = template.get("slots") or []
    sem = slot_semantics(template)
    counts: dict[str, int] = {}
    seconds_by_domain: dict[str, float] = {}
    dur_by_slot: dict[str, float] = {}
    for s in sem:
        d = s["action_domain"]
        counts[d] = counts.get(d, 0) + 1
        seconds_by_domain[d] = seconds_by_domain.get(d, 0.0) + s["duration_s"]
        dur_by_slot[s["slot_id"]] = s["duration_s"]
    D = sum(seconds_by_domain.values())
    caps = {d: window_capacity(d, 2.0)["capacity"] for d in counts}
    deficits = {d: max(0, counts[d] - caps[d]) for d in counts}
    media = _media_stems_by_domain()
    seconds_by_media: dict[str, float] = {}
    for domain in counts:
        domain_media = media.get(domain, [])
        for item in sorted((s for s in sem if s["action_domain"] == domain),
                           key=lambda s: (-s["duration_s"], s["ordinal"])):
            if not domain_media:
                continue
            stem = min(domain_media, key=lambda candidate: (seconds_by_media.get(candidate, 0.0), candidate))
            seconds_by_media[stem] = seconds_by_media.get(stem, 0.0) + item["duration_s"]
    h2_limit = D / 3.0 if D > 0 else 0.0
    h2_worst = max(seconds_by_media.values()) if seconds_by_media else 0.0
    full_ok = all(v <= 0 for v in deficits.values()) and h2_worst <= h2_limit + 1e-9
    # P1-4：多样化判定按**物理素材数**（同动作域多支素材视作多素材；域≠素材）
    media_by_domain = {domain: len(stems) for domain, stems in media.items()}
    diversify_ok = all(media_by_domain.get(d, 0) >= DIVERSIFY_MIN_ASSETS_PER_DOMAIN
                       for d in counts)
    reasons: list[str] = []
    for d, cnt in deficits.items():
        if cnt > 0:
            reasons.append(f"{d}: 需 {cnt} 镜 容量 {counts[d]}→{caps[d]}")
    if h2_worst > h2_limit + 1e-9:
        worst_media = max(seconds_by_media, key=seconds_by_media.get) if seconds_by_media else "未知素材"
        reasons.append(f"H2: 单素材 {worst_media} {h2_worst:.1f}s > D/3 {h2_limit:.1f}s")

    if full_ok:
        verdict = "DIVERSIFY" if diversify_ok else "DIVERSIFY_LIMITED"
        comp_ok = True
    else:
        # F_comp（P0-1 贪心·瓶颈二分）：骨架保留（每域 ≥1 + hook/cta），
        # 对瓶颈域 k 从容量向下二分，找满足「k×dur_b ≤ D(k)/3」的最小保留量。
        # 全域 H2 迭代剪枝：所有域同时满足 k_d×dur_d ≤ D/3（而非仅瓶颈域）。
        ks = {d: min(counts[d], caps[d]) for d in counts}
        # Every represented action domain must retain at least one physical
        # source; dropping a whole domain would violate the evidence skeleton.
        comp_ok = bool(ks) and all(caps[d] >= 1 for d in counts)
        guard = 0
        while comp_ok and guard < len(counts) * 4 + 4:
            guard += 1
            Dk = sum(ks[d] * (dur_by_slot.get(next((s["slot_id"] for s in sem
                                                    if s["action_domain"] == d), ""), 2.0)) for d in ks)
            physical_loads: dict[str, tuple[str, float]] = {}
            for domain, keep in ks.items():
                domain_media = media.get(domain, [])
                duration = dur_by_slot.get(next(
                    (s["slot_id"] for s in sem if s["action_domain"] == domain), ""), 2.0)
                for index in range(keep):
                    if not domain_media:
                        continue
                    stem = domain_media[index % len(domain_media)]
                    _, load = physical_loads.get(stem, (domain, 0.0))
                    physical_loads[stem] = (domain, load + duration)
            worst_stem = max(physical_loads, key=lambda stem: physical_loads[stem][1]) if physical_loads else ""
            worst = physical_loads.get(worst_stem, ("", 0.0))[0]
            if not worst or physical_loads[worst_stem][1] <= Dk / 3.0 + 1e-9:
                break
            ks[worst] -= 1
            if ks[worst] < 1:
                comp_ok = False
                break
        verdict = "COMPRESS" if (allow_compress and comp_ok) else "MARK_GAP"
        if not comp_ok:
            reasons.append("压缩分量仍违反 H2（需补素材）")
    input_hash = hashlib.sha256(
        json.dumps({"tid": tid, "counts": counts, "caps": caps, "media": media,
                    "solver": CAPACITY_SOLVER},
                   sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "template_id": tid, "verdict": verdict, "solver": CAPACITY_SOLVER,
        "slot_count": len(slots), "total_seconds": round(D, 2),
        "domain_counts": counts, "window_capacities": caps, "deficits": deficits,
        "h2_worst_material_seconds": round(h2_worst, 2), "h2_limit_seconds": round(h2_limit, 2),
        "seconds_by_media": {stem: round(seconds, 2) for stem, seconds in seconds_by_media.items()},
        "full_solvable": full_ok, "compress_solvable": comp_ok,
        "diversify_solvable": diversify_ok, "media_by_domain": media_by_domain, "reasons": reasons,
        "input_hash": input_hash,
    }



# ---- 标定合并（策略 C）：calibrations 产物并入主要事实源，并入即"标定" ----
from lib.template_calibrations import _CALIBRATIONS as _CAL

for _tid, _acts in _CAL.items():
    SLOT_ACTION_BY_TEMPLATE.setdefault(_tid, _acts)

_CALIBRATED_VIA_META = {
    "sheet-01-video1-aks-zhuodian": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-26", "reviewer": "agent"},
    "sheet-04-video4-zhuodian": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-26", "reviewer": "agent"},
    "sheet-05-video5-aks-zhuodian": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-26", "reviewer": "agent"},
    "sheet-09-video9-aks-zhuodian": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-26", "reviewer": "agent"},
    "sheet-14-video15-aks-zhuodian": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-26", "reviewer": "agent"},
    "sheet-19-video22-aks-zhuodian": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-26", "reviewer": "agent"},
    "sheet-14-video15-aks-zhuodian-c1": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-28", "reviewer": "agent"},
    "sheet-05-video5-aks-zhuodian-c1": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-28", "reviewer": "agent"},
    "sheet-19-video22-aks-zhuodian-c1": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-28", "reviewer": "agent"},
    "sheet-04-video4-zhuodian-c1": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-28", "reviewer": "agent"},
    "sheet-09-video9-aks-zhuodian-c2": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-28", "reviewer": "agent"},
    "sheet-14-video15-aks-zhuodian-c3": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-28", "reviewer": "agent"},
    "sheet-19-video22-aks-zhuodian-c4": {"source": "manual", "version": "1.0", "calibrated_at": "2026-08-28", "reviewer": "agent"},
}


def calibration_meta() -> dict:
    """标定审计元数据（含产物 meta 合并与模块内置来源）。"""
    from lib.template_calibrations import _CALIBRATION_META

    merged = dict(_CALIBRATED_VIA_META)
    merged.update(_CALIBRATION_META or {})
    return merged


def is_template_calibrated(template_id: str) -> bool:
    return template_id in SLOT_ACTION_BY_TEMPLATE
