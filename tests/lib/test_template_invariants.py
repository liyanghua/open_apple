"""跨阶段不变量测试（评审 P0/P1 回归护栏）。

覆盖五条跨阶段契约：
1. source_mapping → narration：口播动作 key == 绑定素材动作 key（语义对齐）
2. TTS 输出 → mix 输入：三位命名契约 + 缺口播文件即阻断
3. scene recipe → cut id：recipe key 必须与渲染 cut.id 一致
4. QA/L1a 失败 → 禁止发布：verify_publish_gates 硬门
5. 输入内容变化 → 禁止复用旧 proxy/mix（内容 hash 幂等 sidecar 校验）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _make_run():
    from lib.template_run_plan import create_template_run

    slots = [
        {"slot_id": f"s{i}", "ordinal": i, "duration_s": 2.0,
         "shot_language": {"shot_size": "近景", "camera_movement": "固定"},
         "visual_content": "KEEP HAPPY HOLIDAY", "overlay_text": "KEEP HAPPY HOLIDAY",
         "scene": "室内/桌面", "caption_treatment": "subtitle",
         "dialogue": "透明软玻璃桌垫，贴合桌面，防水防油易清洁"} for i in range(1, 9)
    ]
    slots[5] = {**slots[5], "overlay_text": "防水油 克洗易清洁"}
    slots[6] = {**slots[6], "overlay_text": "防刮耐磨"}
    template = {"template_id": "sheet-test", "slots": slots}
    run = create_template_run(template, template_pack_ref={"artifact_sha256": "a" * 64},
                              product_facts_ref={"artifact_sha256": "b" * 64})
    return template, run


def test_match_run_plan_semantic_alignment_and_hap_false_positive_guard():
    """不变量 1a：素材动作 == slot 期望动作；"KEEP HAPPY HOLIDAY" 不得被 "HAP" 误命中。"""
    from lib.template_source_match import _action_from_stem, _best_action, match_run_plan

    template, run = _make_run()
    assigned = match_run_plan(template["slots"], run)
    for slot in template["slots"]:
        expected = _best_action(slot)
        stem = assigned[slot["slot_id"]]
        assert _action_from_stem(stem) == expected, f"{slot['slot_id']}: {expected} != {stem}"
    # 占位英文不产生 无甲醛 误匹配
    assert assigned["s1"] == "product_透明桌垫-防油易擦拭"


def test_build_script_narration_aligns_with_bound_material(tmp_path: Path):
    """不变量 1b：build_script 按绑定素材动作挑文案（narration_action_key == bound_material_action）。"""
    from lib.template_mainline import _bound_action, build_script
    from lib.template_source_match import build_source_mappings, match_run_plan

    template, run = _make_run()
    assigned = match_run_plan(template["slots"], run)
    scenes = [
        {"id": f"scene-{i:03d}", "start_seconds": float((i - 1) * 2.0), "end_seconds": float(i * 2.0)}
        for i in range(1, 9)
    ]
    slot_by_scene = {f"scene-{i:03d}": slot for i, slot in enumerate(template["slots"], start=1)}
    mapping = build_source_mappings(scenes, slot_by_scene, assigned)
    sp = {"scenes": scenes, "metadata": {"source_mapping": mapping}}
    from backlot.project_commit import ProjectCommitStore

    proj = tmp_path / "run-script"
    from lib.template_mainline import build_script

    with ProjectCommitStore(proj).transaction(action={"action_id": "invariant-script"}) as sink:
        script_env = build_script(proj, template, sp, {}, {}, approved=True, sink=sink)
    script = script_env["data"]
    for sec in script["sections"]:
        if not str(sec.get("narration") or "").strip():
            continue
        assert sec["narration_material_aligned"] is True, f"{sec['id']} 文案与素材动作错位"
        assert sec["narration_action_key"] == sec["bound_material_action"], sec["id"]
        assert sec["narration_action_key"] == _bound_action(sp, scenes[int(sec["id"].split("-")[1]) - 1])


def test_tts_naming_contract_and_mix_track_resolution():
    """不变量 2：TTS 三位命名 = mix 使用的命名；缺文件阻断混音（评审 P0-2）。"""
    from scripts.gen_template_audio import narration_filename, narration_meta_filename
    from scripts.prep_template_media import _build_mix_tracks

    assert narration_filename("sec-005") == "narration-s005.mp3"
    assert narration_filename("sec-21") == "narration-s021.mp3"
    assert narration_meta_filename("sec-005") == "narration-s005.mp3.json"

    audio_dir = Path(__import__("tempfile").mkdtemp())
    (audio_dir / "narration-s001.mp3").write_bytes(b"x")
    script = {"sections": [
        {"id": "sec-001", "narration": "测试口播", "start_seconds": 0.0},
        {"id": "sec-002", "narration": "第二句必须存在", "start_seconds": 2.0},
    ]}
    with pytest.raises(RuntimeError, match="narration-s002"):
        _build_mix_tracks(audio_dir, script, Path("/tmp/bgm.mp3"))


def test_recipe_keys_remapped_to_cut_ids():
    """不变量 3：scene_plan 的 recipe（scene-NNN）必须重映射到渲染 cut.id（shot-NN）。"""
    from lib.sample_payload import build_sample_render_payload

    payload_in = {
        "final_props": {
            "fps": 30, "durationInFrames": 120,
            "scenes": [
                {"id": "shot-01", "assetId": "proxy-01", "footageKey": "k",
                 "fromFrame": 0, "toFrameExclusive": 60,
                 "sourceInSeconds": 0.0, "sourceOutSeconds": 2.0},
                {"id": "shot-02", "assetId": "proxy-02", "footageKey": "k2",
                 "fromFrame": 60, "toFrameExclusive": 120,
                 "sourceInSeconds": 0.0, "sourceOutSeconds": 2.0},
            ],
            "footage": {"k": "a.mp4", "k2": "b.mp4"},
            "audio": {"mix": {"narration": {"path": "assets/audio/sample-mix.mp3"}}},
        },
        "asset_manifest": {"assets": [
            {"id": "proxy-01", "path": "a.mp4", "duration_seconds": 2.0},
            {"id": "proxy-02", "path": "b.mp4", "duration_seconds": 2.0},
        ]},
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
        "scene_plan": {"scenes": [
            {"id": "scene-001", "transition_recipe_intent": "proof",
             "caption_recipe_intent": "hook"},
            {"id": "scene-002", "transition_recipe_intent": "action_match",
             "caption_recipe_intent": "proof"},
        ]},
    }
    result = build_sample_render_payload(payload_in)
    assert set(result["transitionRecipes"]) == {"shot-01", "shot-02"}
    assert set(result["captionRecipes"]) == {"shot-01", "shot-02"}
    assert result["transitionRecipes"]["shot-01"]["type"] == "flash"
    assert result["transitionRecipes"]["shot-02"]["type"] == "dissolve"
    # 所有 recipe key 必须命中 cut id（渲染器按 cut.id 查询）
    cut_ids = {c["id"] for c in result["cuts"]}
    assert set(result["transitionRecipes"]) <= cut_ids


def test_publish_gates_block_failed_l1a(tmp_path: Path):
    """不变量 4：final_qa/l1a_final 失败或缺失 → verify_publish_gates 阻断发布。"""
    proj = tmp_path / "run"
    (proj / "artifacts").mkdir(parents=True)
    (proj / "artifacts" / "l1a_final.json").write_text(
        json.dumps({"status": "revise"}), encoding="utf-8")
    (proj / "artifacts" / "final_qa_full.json").write_text(
        json.dumps({"status": "pass"}), encoding="utf-8")
    (proj / "checkpoint_sample.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8")
    (proj / "checkpoint_compose.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8")
    from scripts.publish_template_run import verify_publish_gates

    with pytest.raises(SystemExit, match="发布阻断"):
        verify_publish_gates(proj, "run")
    (proj / "artifacts" / "l1a_final.json").write_text(
        json.dumps({"status": "pass"}), encoding="utf-8")
    # 证书缺失 → 阻断；补齐证书（含媒体/制品 hash）→ 放行；媒体被改 → 阻断（不可变版本绑定）
    (proj / "renders").mkdir(exist_ok=True)
    (proj / "renders" / "final.mp4").write_bytes(b"final-bytes")
    (proj / "renders" / "sample-v1.mp4").write_bytes(b"sample-bytes")
    for name in ("final_props", "script", "asset_manifest", "scene_plan",
                 "edit_decisions", "render_plan", "l1a_sample"):
        (proj / "artifacts" / f"{name}.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (proj / "artifacts" / "final_qa_full.json").write_text(
        json.dumps({"status": "pass"}), encoding="utf-8")
    (proj / "artifacts" / "l1a_final.json").write_text(
        json.dumps({"status": "pass"}), encoding="utf-8")

    def _sha(path):
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(SystemExit, match="delivery_certificate"):
        verify_publish_gates(proj, "run")
    (proj / "artifacts" / "delivery_certificate.json").write_text(json.dumps({
        "version": "1.0", "project_id": "run",
        "certified_at": "2026-01-01T00:00:00+00:00",
        "media": {"final_path": "renders/final.mp4",
                  "final_sha256": _sha(proj / "renders" / "final.mp4"),
                  "sample_path": "renders/sample-v1.mp4",
                  "sample_sha256": _sha(proj / "renders" / "sample-v1.mp4")},
        "source_hashes": {n: _sha(proj / "artifacts" / f"{n}.json")
                          for n in ("final_props", "script", "asset_manifest", "scene_plan",
                                    "edit_decisions", "render_plan")},
        "qa_refs": {n: _sha(proj / "artifacts" / f"{n}.json")
                    for n in ("final_qa_full", "l1a_final", "l1a_sample")},
        "gates": {"final_qa": "pass", "l1a_final": "pass", "l1a_sample": "pass"},
    }), encoding="utf-8")
    assert verify_publish_gates(proj, "run")["compose"] == "completed"
    (proj / "renders" / "final.mp4").write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="hash 不一致"):
        verify_publish_gates(proj, "run")


def test_sidecar_content_hash_invalidates_reuse(tmp_path: Path):
    """不变量 5：输入内容 hash 变化 → sidecar 失效 → 必须重新生成（评审 P1-5）。"""
    from scripts.prep_template_media import _sidecar_valid

    sidecar = tmp_path / "out.mp4.prep.json"
    expected = {"source_sha256": "a" * 64, "src_in": 0.0, "duration": 2.0, "out_sha256": "b" * 64}
    sidecar.write_text(json.dumps(expected), encoding="utf-8")
    assert _sidecar_valid(sidecar, expected) is True
    # 源内容变化（source_sha256 变化）→ 失效
    changed = dict(expected, source_sha256="c" * 64)
    assert _sidecar_valid(sidecar, changed) is False
    # 裁剪时长变化 → 失效
    changed = dict(expected, duration=3.0)
    assert _sidecar_valid(sidecar, changed) is False


def test_run_plan_not_auto_approved_for_assets(tmp_path: Path, monkeypatch):
    """不变量 6（评审 P1-8）：advance_to_assets 不允许把未批准 run_plan 自动置为 approved。"""
    import sys

    sys.path.insert(0, str(ROOT))
    import lib.template_mainline as tml

    # 令 scene_plan 视为已完成，跳过 advance_run_full，直接命中 run_plan 批准硬门。
    monkeypatch.setattr("lib.checkpoint.get_completed_stages", lambda *a, **k: ["scene_plan"])
    proj = tmp_path / "template-run-x"
    (proj / "artifacts").mkdir(parents=True)
    (proj / "artifacts" / "template_run_plan.json").write_text(
        json.dumps({"status": "awaiting_human", "template_id": "sheet-01-video1-aks-zhuodian"}),
        encoding="utf-8")
    # 未批准 → 必须阻断，且不得把 status 自动改成 approved
    with pytest.raises(SystemExit, match="未批准"):
        tml.advance_to_assets("template-run-x", pipeline_dir=tmp_path)
    rp = json.loads((proj / "artifacts" / "template_run_plan.json").read_text(encoding="utf-8"))
    assert rp["status"] == "awaiting_human"

def test_shot_plan_drift_detected_and_edit_decisions_carry_transitions():
    """不变量 7（评审 P0-1/P1-1）：shot_plan 漂移可检出；edit_decisions 携带非 cut 转场 token。"""
    from lib.template_assets import shot_plan_drift
    from lib.template_render import build_edit_decisions

    template, run = _make_run()
    from lib.template_source_match import build_source_mappings, match_run_plan

    assigned = match_run_plan(template["slots"], run)
    scenes = [
        {"id": f"scene-{i:03d}", "start_seconds": float((i - 1) * 2.0),
         "end_seconds": float(i * 2.0), "template_slot_ref": f"s{i}",
         "description": f"slot {i} 动作",
         "transition_recipe_intent": "proof" if i == 2 else None}
        for i in range(1, 9)
    ]
    slot_by_scene = {f"scene-{i:03d}": template["slots"][i - 1] for i in range(1, 9)}
    mapping = build_source_mappings(scenes, slot_by_scene, assigned)
    sp = {"scenes": scenes, "metadata": {"source_mapping": mapping}}
    script = {"sections": [
        {"id": f"sec-{i:03d}", "narration": f"口播{i}", "screen_copy": f"花字{i}",
         "start_seconds": float((i - 1) * 2.0), "end_seconds": float(i * 2.0),
         "beat_role": "proof"} for i in range(1, 9)
    ]}
    # 陈旧 shot_plan（旧文案）→ 漂移检出
    stale_shots = [{"id": f"shot-{i:02d}", "order": i, "scene_id": f"scene-{i:03d}",
                    "template_slot_ref": f"s{i}", "duration_seconds": 2.0,
                    "narration": "旧文案", "screen_copy": "",
                    "setting": "室内/桌面", "purpose": "x"} for i in range(1, 9)]
    drift = shot_plan_drift(Path("."), template, sp, script, {"shots": stale_shots})
    assert len(drift) >= 8
    # 当前 shot_plan（键控一致）→ 无漂移
    fresh = [dict(stale_shots[i - 1], narration=f"口播{i}", screen_copy=f"花字{i}",
                  purpose=f"slot {i} 动作") for i in range(1, 9)]
    assert shot_plan_drift(Path("."), template, sp, script, {"shots": fresh}) == []
    # edit_decisions 携带非 cut 转场（scene-002 = proof → flash）
    ed = build_edit_decisions(Path("projects/x"), fresh, scene_plan=sp)
    tokens = {c["id"]: c["transition_in"] for c in ed["cuts"]}
    assert tokens["shot-02"] == "flash"
    assert sum(1 for t in tokens.values() if t != "cut") >= 1


def test_tts_lock_binds_voice_and_rate(tmp_path: Path):
    """不变量 8（评审 P1-2）：TTS 缓存锁定 文案+voice+resource+format+rate，任一变化即失效。"""
    import json as _json

    from scripts.gen_template_audio import _text_sha, _tts_lock_valid

    sha = _text_sha("测试文案")
    lock = tmp_path / "narration-s001.mp3.lock.json"
    lock.write_text(_json.dumps({
        "text_sha": sha, "speech_rate": 0,
        "voice_id": "zh_female_vv_uranus_bigtts", "resource_id": "seed-tts-2.0",
        "format": "mp3"}), encoding="utf-8")
    assert _tts_lock_valid(lock, "测试文案", speech_rate=0) is True
    assert _tts_lock_valid(lock, "不同文案", speech_rate=0) is False      # 文案变化
    assert _tts_lock_valid(lock, "测试文案", speech_rate=10) is False     # rate 变化
    lock.write_text(_json.dumps({
        "text_sha": sha, "speech_rate": 0,
        "voice_id": "其他声线", "resource_id": "seed-tts-2.0",
        "format": "mp3"}), encoding="utf-8")
    assert _tts_lock_valid(lock, "测试文案", speech_rate=0) is False      # voice 变化


def test_bgm_source_lock_binds_prompt(tmp_path: Path):
    """不变量 9（评审 P1-2）：BGM 源复用必须绑定 prompt/model/instrumental 锁。"""
    import json as _json

    from scripts.prep_template_media import _sidecar_valid

    lock = tmp_path / "bgm-source.lock.json"
    expected = {"prompt_sha256": "p" * 64, "model": "V4_5", "instrumental": True}
    lock.write_text(_json.dumps(expected), encoding="utf-8")
    assert _sidecar_valid(lock, expected) is True
    assert _sidecar_valid(lock, dict(expected, model="V5")) is False
    assert _sidecar_valid(lock, dict(expected, prompt_sha256="q" * 64)) is False


def test_semantic_validator_catches_cross_claims_and_all_template_tables_clean():
    """不变量 10：文案↔素材语义真值校验。

    a) 语义校验器必须能抓到「画面无法证明」的跨动作 claim 与无锚点文案；
    b) 六张模板文案表 × 显式动作表 合成校验 = 0 findings（防手改再错）。
    """
    from lib.template_mainline import _NARRATION_BY_TEMPLATE, _NARRATION_DEFAULT
    from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE, semantic_mismatches

    # a) 反例：餐桌场景画面配「刮擦/耐磨」→ 必被抓
    bad = {"sections": [
        {"id": "sec-001", "narration": "耐磨防刮，久用如新。", "screen_copy": "耐磨",
         "bound_material_action": "餐桌场景"},
        {"id": "sec-002", "narration": "检测仪归零，材料干净。", "screen_copy": "检测",
         "bound_material_action": "餐桌场景"},
    ]}
    assert len(semantic_mismatches(bad)) >= 2

    # b) 全部 6 张表：合成 sections 校验
    for tid, rows in list(_NARRATION_BY_TEMPLATE.items()) + [("sheet-01-video1-aks-zhuodian", _NARRATION_DEFAULT)]:
        actions = SLOT_ACTION_BY_TEMPLATE.get(tid, [])
        assert len(rows) == len(actions), f"{tid} 表行数与动作表不一致"
        sections = []
        for i, row in enumerate(rows, start=1):
            sections.append({
                "id": f"sec-{i:03d}", "narration": row[0] or "", "screen_copy": row[1],
                "bound_material_action": actions[i - 1],
            })
        findings = semantic_mismatches({"sections": sections})
        assert not findings, f"{tid} 语义不一致: {findings[:3]}"


def test_material_reuse_standard_detects_duplicate_shots():
    """不变量 11：画面重合度标准（评审——成片不能“同一镜头用多次”）。

    H1 相邻同素材 / H2 单素材占比 / H3 完全重复窗口 / H4 同素材相邻窗口起点差，
    任一违反 → hard_pass=False；标准与判定函数同时锁定。
    """
    from lib.template_source_match import REUSE_HARD, material_reuse_report

    assert REUSE_HARD["adjacent_same"] == 0 and abs(REUSE_HARD["single_ratio_max"] - 1 / 3) < 1e-9

    def plan(seq, windows):
        scenes = []
        mapping = []
        cursor = 0.0
        for i, stem in enumerate(seq, start=1):
            scenes.append({"id": f"scene-{i:03d}", "start_seconds": cursor, "end_seconds": cursor + 2.0})
            mapping.append({
                "scene_id": f"scene-{i:03d}", "template_slot_ref": f"s{i}",
                "source_path": f"projects/x/product_透明桌垫-{stem}.MP4",
                "source_interval": {"start_seconds": windows[i - 1][0],
                                   "end_seconds_exclusive": windows[i - 1][1]},
                "timeline_interval": {"start_seconds": cursor, "end_seconds_exclusive": cursor + 2.0},
            })
            cursor += 2.0
        return {"scenes": scenes, "metadata": {"source_mapping": mapping}}

    good = plan(["防油易擦拭", "防刮", "无甲醛检测"], [(0.0, 2.0), (1.9, 3.9), (0.0, 2.0)])
    assert material_reuse_report(good)["hard_pass"] is True
    # H1：相邻同素材
    bad1 = plan(["防刮", "防刮", "无甲醛检测"], [(0.0, 2.0), (2.25, 4.25), (0.0, 2.0)])
    assert material_reuse_report(bad1)["hard_pass"] is False
    assert any("H1" in f for f in material_reuse_report(bad1)["findings"])
    # H3：完全相同窗口
    bad2 = plan(["防刮", "无甲醛检测", "防刮"], [(0.0, 2.0), (0.0, 2.0), (0.0, 2.0)])
    assert any("H3" in f for f in material_reuse_report(bad2)["findings"])
    # H4：同素材相邻窗口起点差 < 0.75s
    bad3 = plan(["防刮", "无甲醛检测", "防刮"], [(0.0, 2.0), (0.0, 2.0), (0.3, 2.3)])
    assert any("H4" in f for f in material_reuse_report(bad3)["findings"])


def test_capacity_verdict_three_branches():
    """不变量 12：素材容量判定（设计 §3.5 / 附录 A2-A3）。

    DIVERSIFY_LIMITED（全量可行但池每域单支）/ COMPRESS（可删镜达标）/ MARK_GAP（删镜仍不可行）。
    """
    from lib.template_source_match import capacity_verdict

    def tmpl(domains):
        return {"template_id": "sheet-test", "slots": [
            {"slot_id": f"s{i}", "ordinal": i, "duration_s": 2.0, "scene": "室内/桌面",
             "shot_language": {"shot_size": "近景", "camera_movement": "固定"},
             "dialogue": "透明软玻璃桌垫", "caption_treatment": "subtitle"}
            for i in range(1, len(domains) + 1)],
        "__domains": domains}

    def run(t, domain_override):
        return t

    # 自定义 domains：直接构造带 __domains 并在调用前打补丁太重——用真实 SLOT_ACTION 打表最小模板。
    from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE

    # 6 域各 1：全量可行（每域 ≤ 容量、单素材 2s ≤ 12/3）→ 池每域 1 支 → LIMITED
    t_limited = tmpl(["防油易擦拭", "无甲醛检测", "桌角对齐-挤压不变形",
                      "防刮", "自动铺开对齐", "餐桌场景"])
    SLOT_ACTION_BY_TEMPLATE["sheet-test"] = t_limited["__domains"]
    v = capacity_verdict(t_limited)
    assert v["verdict"] == "DIVERSIFY_LIMITED" and v["full_solvable"] is True

    # 三域各减至 1 时全域 H2 可过（D=6：2 ≤ 6/3）→ COMPRESS（全域剪枝：防油/无甲醛各减 1）
    t_compress = tmpl(["防油易擦拭", "防油易擦拭", "无甲醛检测", "桌角对齐-挤压不变形"])
    SLOT_ACTION_BY_TEMPLATE["sheet-test"] = t_compress["__domains"]
    v = capacity_verdict(t_compress)
    assert v["verdict"] == "COMPRESS", v

    # 餐桌 2 镜 + 无甲醛 1：压缩到 1 镜仍 2s > (2+2)/3 → MARK_GAP
    t_gap = tmpl(["餐桌场景", "餐桌场景", "无甲醛检测"])
    SLOT_ACTION_BY_TEMPLATE["sheet-test"] = t_gap["__domains"]
    v = capacity_verdict(t_gap)
    assert v["verdict"] == "MARK_GAP", v

    del SLOT_ACTION_BY_TEMPLATE["sheet-test"]


def test_capacity_readiness_failclosed_and_compress_blocks_original():
    """不变量 13（评审 P0-1）：容量门 fail-closed——判定器异常 blocker；COMPRESS 阻断原始模板、放行 -c1。"""
    from lib.template_run_plan import check_template_run_plan_ready
    import json as _json

    pack = _json.loads((ROOT / "projects/template-pack-library/artifacts/template_pack.json").read_text())
    t14 = next(t for t in pack["templates"] if t["template_id"] == "sheet-14-video15-aks-zhuodian")
    t14c1 = next(t for t in pack["templates"] if t["template_id"] == "sheet-14-video15-aks-zhuodian-c1")
    base = {"status": "approved", "slot_bindings": [
        {"slot_id": s["slot_id"], "source": "owned", "source_media_id": "x"} for s in t14["slots"]]}

    r_orig = check_template_run_plan_ready(dict(base), template=t14)
    assert any("COMPRESS" in b for b in r_orig["blockers"]), f"原始模板应被 COMPRESS 阻断: {r_orig['blockers'][:2]}"
    # -c1 压缩变体必须携带可回溯的压缩契约后放行
    from lib.template_compression import compression_plan_for_subset
    kept = json.loads((ROOT / "docs/reports/export/compression-candidates-2026-08-27.json").read_text())["sheet-14-video15-aks-zhuodian"][0]["kept_ordinals"]
    compression = compression_plan_for_subset(t14, kept)
    r_c1 = check_template_run_plan_ready({**base, "template_id": t14c1["template_id"], "compression": compression}, template=t14c1)
    assert not any("COMPRESS" in b or "MARK_GAP" in b for b in r_c1["blockers"])
    # 判定器异常 → fail-closed blocker
    import lib.template_run_plan as rpmod

    orig = rpmod.check_template_run_plan_ready
    def boom(*a, **k):
        raise RuntimeError("capacity crash")
    import lib.template_source_match as sm
    cap_orig = sm.capacity_verdict
    sm.capacity_verdict = boom
    try:
        r = check_template_run_plan_ready(dict(base), template=t14)
    finally:
        sm.capacity_verdict = cap_orig
    assert any("异常" in b for b in r["blockers"])


def test_compressor_skeleton_protected_and_real_slot_ids():
    """不变量 14（评审 P0-2a/P1-5）：骨架（每域首镜）不可删；kept_slot_ids 使用真实 slot id。"""
    from lib.template_compression import compress_candidate
    from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE

    def tmpl(domains):
        return {"template_id": "sheet-test-x", "slots": [
            {"slot_id": f"sheet-test-x-slot-{i:03d}", "ordinal": i, "duration_s": 2.0,
             "shot_language": {"shot_size": "近景"}, "scene": "室内/桌面",
             "dialogue": "x", "caption_treatment": "subtitle"} for i in range(1, len(domains) + 1)]}

    t = tmpl(["防油易擦拭", "防油易擦拭", "防油易擦拭"])
    SLOT_ACTION_BY_TEMPLATE["sheet-test-x"] = ["防油易擦拭"] * 3
    from lib.template_mainline import _NARRATION_BY_TEMPLATE
    _NARRATION_BY_TEMPLATE["sheet-test-x"] = [
        ("a", "a", "hook"), ("b", "b", "proof"), ("c", "c", "cta")]
    c = compress_candidate(t)
    SLOT_ACTION_BY_TEMPLATE.pop("sheet-test-x", None)
    _NARRATION_BY_TEMPLATE.pop("sheet-test-x", None)
    assert c["kept_slot_ids"][0] == "sheet-test-x-slot-001"  # 真实 id，非 slot-001 伪造
    assert 1 in c["kept_ordinals"] and 3 in c["kept_ordinals"]  # 首/尾骨架保留
    assert c["base_template_id"] == "sheet-test-x"
    assert len(c["base_section_refs"]) == len(c["kept_slot_ids"])
    assert c["h3_ok"] is True and c["h4_ok"] is True


def test_compressor_h1_uses_physical_media_not_action_domain(monkeypatch):
    import lib.template_source_match as source_match
    from lib.template_compression import compress_candidate
    from lib.template_source_match import SLOT_ACTION_BY_TEMPLATE

    template = {"template_id": "sheet-test-physical", "slots": [
        {"slot_id": f"physical-slot-{i}", "ordinal": i, "duration_s": 2.0,
         "visual_content": "防油易擦拭"} for i in range(1, 4)
    ]}
    SLOT_ACTION_BY_TEMPLATE[template["template_id"]] = ["防油易擦拭"] * 3
    monkeypatch.setattr(source_match, "_clip_stems", lambda: [
        "product_透明桌垫-防油易擦拭", "product_透明桌垫-防油易擦拭-俯拍",
    ])
    try:
        result = compress_candidate(template)
    finally:
        SLOT_ACTION_BY_TEMPLATE.pop(template["template_id"], None)
    assert result["h1_ok"] is True


def test_no_grounding_still_distinct_windows():
    """不变量 15（评审 P1-6）：无 grounding 时窗口分配仍差异化（不得 H3 重复）。"""
    from lib.template_source_match import build_source_mappings

    scenes = [{"id": f"scene-{i:03d}", "start_seconds": 2.0 * (i - 1), "end_seconds": 2.0 * i,
               "template_slot_ref": f"s{i}"} for i in range(1, 4)]
    slot_by_scene = {f"scene-{i:03d}": {"slot_id": f"s{i}"} for i in range(1, 4)}
    assigned = {f"s{i}": "product_透明桌垫-自动铺开对齐" for i in range(1, 4)}
    m = build_source_mappings(scenes, slot_by_scene, assigned, grounding={})
    starts = [x["source_interval"]["start_seconds"] for x in m]
    assert len(set(round(s, 2) for s in starts)) == len(starts), f"无 grounding 仍出现重复窗口: {starts}"


def test_strict_planner_subset_and_capacity():
    """不变量 16：严格档子集规划器（固化的枚举器）——非重叠容量 + 最优子集 + 无解归因。

    复现已验证事实：05c1 子集 [1,2,3,4,5,6,8,11]/16.0s；15c1/19c1 在 S5'=4 下无解（换序阻塞）；
    S3' 非重叠容量：自动铺开=1（3.7s 窗口容不下两个 2s 非重叠窗）。
    """
    import json as _json
    from lib.strict_planner import plan_strict_subset, strict_capacity

    assert strict_capacity("自动铺开对齐") == 1
    assert strict_capacity("桌角对齐-挤压不变形") == 2
    pack = _json.loads((ROOT / "projects/template-pack-library/artifacts/template_pack.json").read_text())

    t05 = next(t for t in pack["templates"] if t["template_id"] == "sheet-05-video5-aks-zhuodian-c1")
    p = plan_strict_subset(t05)
    assert p and p["kept_ordinals"] == [1, 2, 3, 4, 5, 6, 8, 11]
    assert p["all_hard_ok"] and p["h2_ok"] and p["capacity_ok"]
    assert abs(p["total_s"] - 16.0) < 1e-6

    t15 = next(t for t in pack["templates"] if t["template_id"] == "sheet-14-video15-aks-zhuodian-c1")
    assert plan_strict_subset(t15) is None  # S5'=4 + 原始顺序聚簇 → 换序阻塞（已归档）

    t09c2 = next(t for t in pack["templates"] if t["template_id"] == "sheet-09-video9-aks-zhuodian-c2")
    p2 = plan_strict_subset(t09c2)
    assert p2 and len(p2["kept_ordinals"]) == 8
