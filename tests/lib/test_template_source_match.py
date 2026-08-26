"""Unit tests for lib.template_source_match (模板 slot → 自有素材，no-dup + consistency)."""

from __future__ import annotations

from lib.template_run_plan import create_template_run
from lib.template_source_match import (
    best_action,
    build_source_mappings,
    match_run_plan,
    resolve_matrix_grounding,
)

_SLOTS = [
    {"slot_id": f"s{i}", "ordinal": i, "duration_s": 2.0,
     "shot_language": {"shot_size": "近景", "camera_movement": "固定"},
     "visual_content": "KEEP HAPPY HOLIDAY", "overlay_text": "KEEP HAPPY HOLIDAY",
     "scene": "室内/桌面", "caption_treatment": "subtitle",
     "dialogue": "透明软玻璃桌垫，贴合桌面，防水防油易清洁"} for i in range(1, 9)
]
_SLOTS[5] = {**_SLOTS[5], "overlay_text": "防水油 克洗易清洁"}
_SLOTS[6] = {**_SLOTS[6], "overlay_text": "耐磨"}


def _make_run():
    template = {"template_id": "sheet-test", "slots": _SLOTS}
    return create_template_run(template, template_pack_ref={"artifact_sha256": "a" * 64},
                               product_facts_ref={"artifact_sha256": "b" * 64})


def test_match_run_plan_exact_action_first_then_explicit_reuse():
    """语义不变量（评审 P0-1）：素材动作 == slot 动作；素材不足时**显式复用同动作**，
    绝不拿其他动作的未用素材顶替并谎称"首次匹配"。"""
    from lib.template_source_match import _action_from_stem, _best_action

    run = _make_run()
    assigned = match_run_plan(_SLOTS, run)
    bindings = run["slot_bindings"]
    # assigned 键是 slot_id，值非空
    assert set(assigned) == {s["slot_id"] for s in _SLOTS}
    assert all(v for v in assigned.values())
    # 每个绑定都置为 owned
    assert all(b["source"] == "owned" for b in bindings)
    # 语义对齐：绑定素材动作 == 该 slot 期望动作（不允许错配顶替）
    for slot in _SLOTS:
        expected = _best_action(slot)
        got = _action_from_stem(assigned[slot["slot_id"]])
        assert got == expected, f"{slot['slot_id']}: 期望 {expected} 实得 {got}（错配）"
    # 复用必须显式标注（跨景别强调），不允许"首次分配"的未用错配
    reasons = [b["reason"] for b in bindings]
    assert any("跨景别强调" in r for r in reasons)
    assert all(r for r in reasons)  # 每个绑定都有理由


def test_build_source_mappings_distinct_inpoints_non_overlapping():
    run = _make_run()
    assigned = match_run_plan(_SLOTS, run)
    scenes = [
        {"id": f"scene-{i:03d}", "start_seconds": float((i - 1) * 2.0), "end_seconds": float(i * 2.0)}
        for i in range(1, 9)
    ]
    slot_by_scene = {f"scene-{i:03d}": slot for i, slot in enumerate(_SLOTS, start=1)}
    mappings = build_source_mappings(scenes, slot_by_scene, assigned)
    assert len(mappings) == 8
    # 每个 scene 一条 mapping，scene_id 对齐
    assert {m["scene_id"] for m in mappings} == {s["id"] for s in scenes}
    # 同一素材的 in-point 不重叠
    from collections import defaultdict
    by_clip = defaultdict(list)
    for m in mappings:
        by_clip[m["source_path"]].append((m["source_interval"]["start_seconds"], m["source_interval"]["end_seconds_exclusive"]))
    for clip, ivs in by_clip.items():
        for i in range(len(ivs)):
            for j in range(i + 1, len(ivs)):
                a, b = ivs[i], ivs[j]
                assert a[1] <= b[0] or b[1] <= a[0], f"{clip} windows overlap: {ivs}"
    # 必有 reference_evidence + 4 个 evidence 字段（research 链 grounding 契约）
    for m in mappings:
        assert m["reference_evidence"]["mode"] == "structural_only"
        for field in ("reference_basis", "source_fit", "mapping_reason", "originality_note"):
            assert m.get(field)


def test_source_interval_span_matches_timeline_span():
    """source_interval 长度必须 == timeline span；绝不拉成整段 matrix 区间。"""
    run = _make_run()
    assigned = match_run_plan(_SLOTS, run)
    scenes = [
        {"id": f"scene-{i:03d}", "start_seconds": float((i - 1) * 2.0), "end_seconds": float(i * 2.0)}
        for i in range(1, 9)
    ]
    slot_by_scene = {f"scene-{i:03d}": slot for i, slot in enumerate(_SLOTS, start=1)}
    mappings = build_source_mappings(scenes, slot_by_scene, assigned)
    for m in mappings:
        src_span = m["source_interval"]["end_seconds_exclusive"] - m["source_interval"]["start_seconds"]
        tl_span = m["timeline_interval"]["end_seconds_exclusive"] - m["timeline_interval"]["start_seconds"]
        assert abs(src_span - tl_span) < 0.01, f"{m['scene_id']} source span != timeline span"
        assert m["source_interval"]["start_seconds"] < m["source_interval"]["end_seconds_exclusive"]


def test_evidence_window_anchors_oil_shot_off_clean_table():
    """proof 镜头 in-point 必须落在语义证据窗口，而不是 matrix 区间尾部（已擦干净段）。"""
    from lib.template_source_match import SEMANTIC_EVIDENCE_WINDOWS, _semantic_window
    # 防油证据窗口应排除"已擦干净"的尾部（>8s）
    assert _semantic_window("product_透明桌垫-防油易擦拭")["window"] == (0.5, 8.0)
    # 场景 1 绑定防油 → in-point 必须落在该窗口内
    sem = SEMANTIC_EVIDENCE_WINDOWS["防油易擦拭"]
    lo, hi = sem["window"]
    slot = {"slot_id": "s-a", "duration_s": 2.0, "shot_language": {"shot_size": "近景", "camera_movement": "固定"},
            "visual_content": "防油", "overlay_text": "防油易擦拭", "scene": "室内/桌面", "caption_treatment": "subtitle",
            "dialogue": "防油防水易清洁"}
    from lib.template_run_plan import create_template_run
    run = create_template_run({"template_id": "t", "slots": [slot]},
                              template_pack_ref={"artifact_sha256": "a" * 64}, product_facts_ref={"artifact_sha256": "b" * 64})
    assigned = match_run_plan([slot], run)
    scene = {"id": "scene-001", "start_seconds": 0.0, "end_seconds": 2.0}
    grounding = {"product_透明桌垫-防油易擦拭": {
        "matrix_row_id": "matrix-04", "matrix_resolution_id": "accept",
        "source_time_range": {"start_seconds": 3.2, "end_seconds_exclusive": 10.8}}}
    mappings = build_source_mappings(
        [scene], {scene["id"]: slot}, assigned, grounding=grounding)
    iv = mappings[0]["source_interval"]
    assert lo <= iv["start_seconds"] < hi, f"oil shot in-point {iv} outside semantic window ({lo},{hi})"


def test_material_reuse_records_explicit_shot_size_reason():
    """素材不足复用时，bindings 的 reason 必须显式标注"跨景别强调"，不许静默复用。"""
    slots = [
        {"slot_id": f"s{i}", "ordinal": i, "duration_s": 2.0,
         "shot_language": {"shot_size": "全景" if i == 1 else "近景" if i == 2 else "特写", "camera_movement": "固定"},
         "visual_content": "防油", "overlay_text": "防油", "scene": "室内", "caption_treatment": "subtitle",
         "dialogue": "防油防水"} for i in range(1, 9)
    ]
    from lib.template_run_plan import create_template_run
    run = create_template_run({"template_id": "t8", "slots": slots},
                              template_pack_ref={"artifact_sha256": "a" * 64}, product_facts_ref={"artifact_sha256": "b" * 64})
    # 覆盖素材池：_clip_stems 读真实 v8。删除多余素材不现实，直接断言复用 reason 含"跨景别强调"。
    match_run_plan(slots, run)
    reuse_reasons = [b["reason"] for b in run["slot_bindings"] if "跨景别强调" in str(b.get("reason") or "")]
    assert reuse_reasons, "8 slot / 6 素材下必须有显式复用标注"
    # 每个复用 reason 都提及景别差异
    for r in reuse_reasons:
        assert "景别" in r and "复用" in r


def test_matcher_still_resolves_best_action_by_overlay():
    # 槽位 7 的 overlay 是"耐磨"，应优先 → 防刮
    action = best_action(_SLOTS[6])
    assert action.startswith("防刮")


def test_resolve_matrix_grounding_bridges_by_frames():
    # 构造 source_review 与 matrix，用 representative_frames ∩ evidence_frames 建立 grounding。
    frame_src = "analysis/source/abc/frame_0001.jpg"
    src = {"files": [
        {"path": "projects/x/video/product_透明桌垫-无甲醛检测.MP4",
         "representative_frames": [frame_src], "reviewed": True},
        {"path": "projects/x/video/product_透明桌垫-防刮.MP4",
         "representative_frames": ["analysis/source/def/frame_0001.jpg"], "reviewed": True},
    ]}
    matrix = {"rows": [
        {"matrix_row_id": "matrix-01", "resolution": "accept", "source_media_id": "s1",
         "evidence_frames": [frame_src],
         "source_time_range": {"start_seconds": 0.0, "end_seconds_exclusive": 8.01}},
        {"matrix_row_id": "matrix-02", "resolution": "pending", "source_media_id": None,
         "evidence_frames": [], "source_time_range": None},
    ]}
    g = resolve_matrix_grounding(src, matrix)
    # 无甲醛检测 → matrix-01（帧桥接）；防刮 无 overlap → 不纳入；pending row 忽略。
    assert g["product_透明桌垫-无甲醛检测"]["matrix_row_id"] == "matrix-01"
    assert g["product_透明桌垫-无甲醛检测"]["matrix_resolution_id"] == "accept"
    assert "product_透明桌垫-防刮" not in g
