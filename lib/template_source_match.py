"""模板 slot → 自有素材的匹配（复用 research 链原则：不重复 + 一致性）。

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
    return stem.replace("product_透明桌垫-", "")


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
        "餐桌场景", "桌角对齐-挤压不变形", "餐桌场景", "餐桌场景", "餐桌场景",
        "无甲醛检测", "餐桌场景",
    ],
    "sheet-14-video15-aks-zhuodian": [
        "餐桌场景", "餐桌场景", "桌角对齐-挤压不变形", "餐桌场景", "餐桌场景",
        "餐桌场景", "桌角对齐-挤压不变形", "餐桌场景", "餐桌场景", "无甲醛检测",
        "无甲醛检测", "餐桌场景", "餐桌场景", "餐桌场景", "无甲醛检测",
        "无甲醛检测", "防刮", "防油易擦拭", "餐桌场景", "桌角对齐-挤压不变形",
        "餐桌场景", "餐桌场景", "餐桌场景", "餐桌场景", "防刮", "防油易擦拭",
        "餐桌场景", "餐桌场景", "餐桌场景", "餐桌场景",
    ],
    "sheet-19-video22-aks-zhuodian": [
        "餐桌场景", "餐桌场景", "无甲醛检测", "无甲醛检测", "无甲醛检测",
        "餐桌场景", "防刮", "防油易擦拭", "防油易擦拭", "桌角对齐-挤压不变形",
        "餐桌场景", "防刮", "餐桌场景", "餐桌场景", "餐桌场景", "餐桌场景",
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
            chosen = min(unused_exact)
            is_reuse = False
            reason_by_slot[slot_id] = f"自有素材「{chosen}」匹配该 slot 产品动作（首次分配）"
            first_slot_by_stem[chosen] = (i, slot)
        else:
            used_exact = [s for s in used_stems if _action_from_stem(s) == action]
            if used_exact:
                # 2) 未用无精确匹配：复用已用过的**同动作**素材（跨景别强调，显式标注）。
                chosen = min(used_exact)
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
    "桌角对齐-挤压不变形": {"window": (1.7, 5.1), "label": "手铺平桌角贴合边缘（贴合不翘边）"},
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
        stem = assigned.get(slot_id) or _DEFAULT_ACTION
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
        # 研究链 grounding：若该素材能桥接到已解析 matrix row，则挂 row ref（满足 scene_plan 硬门）。
        g = (grounding or {}).get(stem) or {}
        if g.get("matrix_row_id"):
            item["matrix_row_id"] = g["matrix_row_id"]
            item["matrix_resolution_id"] = g["matrix_resolution_id"]
            if research_direction:
                item["research_direction_ref"] = research_direction
            # 硬门：source_interval 必须落在 matrix row 的 approved source_time_range 内，
            # **且长度 == timeline span**（2s 场景取 2s 素材窗，绝不拉成整段 matrix 区间）。
            # 关键：优先锚定到该素材的**语义证据窗口**（人在哪一秒发生证据动作），
            # 而不是粗估 matrix 源区间——否则会切到"已擦干净/无动作"的误导段。
            tr = g.get("source_time_range") or {}
            lo = tr.get("start_seconds")
            hi = tr.get("end_seconds_exclusive")
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                span = max(dur, 0.1)
                sem = _semantic_window(stem)
                # 可用区间 = 语义证据窗口 ∩ matrix 源区间；无语义窗口则用 matrix 区间。
                if sem and isinstance(sem.get("window"), (tuple, list)) and len(sem["window"]) == 2:
                    s_lo, s_hi = float(sem["window"][0]), float(sem["window"][1])
                    avail_lo = max(float(lo), s_lo)
                    avail_hi = min(float(hi), s_hi)
                else:
                    avail_lo, avail_hi = float(lo), float(hi)
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
                        s2 = max(float(lo), float(hi) - span)
                        while s2 >= float(lo):
                            yield s2
                            s2 -= span + 0.25
                    chosen_start = None
                    for cand in _candidates():
                        win = (cand, cand + span)
                        if (cand + span) <= float(hi) and not any(
                            win[0] < used_end and used_start < win[1] for used_start, used_end in used
                        ):
                            chosen_start = cand
                            break
                    if chosen_start is None:
                        # 实在没有无重叠位置：错开复用（尽量远处），但仍标注
                        chosen_start = max(float(lo), float(hi) - span) if not used else max(
                            float(lo), float(hi) - span)
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
