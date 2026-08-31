"""历史成片总览：只读 API + 页面（auth_mode=test 下走 TestClient）。"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.export_top_videos as export_mod


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_fake_run(root: Path, run: str, *, with_cert: bool = True, with_l3: bool = True,
                   template_id: str = "sheet-01-video1-aks-zhuodian") -> Path:
    proj = root / run
    (proj / "artifacts").mkdir(parents=True)
    (proj / "renders").mkdir(parents=True)
    (proj / "renders" / "final.mp4").write_bytes(b"fake-media")
    _write(proj / "artifacts" / "template_run_plan.json",
           {"status": "approved", "template_id": template_id})
    _write(proj / "artifacts" / "l1a_final.json", {
        "status": "pass", "hard_gate": {"checks": [
            {"id": "l1a_sensitive", "status": "pass", "message": ""},
            {"id": "l1a_subtitle_bounds", "status": "pass", "message": ""},
            {"id": "l1a_black_frames", "status": "pass", "message": ""},
            {"id": "l1a_freeze", "status": "pass", "message": ""},
            {"id": "l1a_loudness", "status": "pass",
             "evidence": {"integrated_lufs": -14.2, "true_peak_dbtp": -4.5}},
            {"id": "l1a_duration", "status": "pass", "message": ""},
            {"id": "l1a_resolution", "status": "pass", "message": ""},
        ]}})
    _write(proj / "artifacts" / "final_qa_full.json", {
        "status": "pass", "checks": {"technical_probe": {
            "resolution": "1080x1920", "duration_seconds": 40.0, "has_audio": True}}})
    _write(proj / "artifacts" / "script.json", {
        "version": "1.0", "total_duration_seconds": 40.0,
        "sections": [{"id": "sec-001", "narration": "x", "start_seconds": 0.0}]})
    _write(proj / "artifacts" / "edit_decisions.json", {
        "version": "1.0",
        "cuts": [{"id": f"shot-{i:02d}", "transition_in": "dissolve"} for i in range(1, 9)]})
    _write(proj / "artifacts" / "asset_manifest.json",
           {"version": "1.0", "total_cost_usd": 0.0, "assets": []})
    _write(proj / "artifacts" / "publish_log.json", {
        "version": "1.0", "entries": [{"timestamp": "2026-08-26T00:00:00+00:00"}]})
    _write(proj / "checkpoint_publish.json", {"status": "completed"})
    _write(proj / "checkpoint_sample.json", {"status": "completed", "human_approved": True})
    (proj / "assets" / "audio").mkdir(parents=True)
    (proj / "assets" / "audio" / "narration-s001.mp3").write_bytes(b"x")
    (proj / "assets" / "audio" / "sample-mix.mp3").write_bytes(b"x")
    _write(proj / "artifacts" / "scene_plan.json", {"version": "1.0", "metadata": {"source_mapping": [
        {"scene_id": "scene-001", "template_slot_ref": "s1", "source_path": "projects/x/product.MP4",
         "source_interval": {"start_seconds": 0.0, "end_seconds_exclusive": 2.0},
         "timeline_interval": {"start_seconds": 0.0, "end_seconds_exclusive": 2.0}}],
        "template_slot_ref": {}}})
    _write(proj / "artifacts" / "delivery_certificate.json", {"version": "1.0"})
    if with_l3:
        _write(proj / "artifacts" / "l3_advisory.json", {
            "media_sha256": "x" * 64, "rubric_version": "l3-v1.0", "model": "qwen-vl-max",
            "seeds": [42, 7, 2026], "dimensions": {"hook_clarity": 8.0, "visual_hierarchy": 9.0,
                                                    "rhythm": 8.5, "shot_quality": 9.0,
                                                    "story_coherence": 8.5, "audio_quality": 8.0,
                                                    "text_readability": 9.0,
                                                    "product_presence": 8.0},
            "summary": "测试摘要"})
    return proj


def test_overview_api_readonly(backlot_client, projects_root, monkeypatch):
    monkeypatch.setattr(export_mod, "PROJECTS", projects_root)
    _make_fake_run(projects_root, "template-run-a")
    _make_fake_run(projects_root, "template-run-b", with_cert=False, with_l3=False)
    # 进行中 run：plan 已批，停在素材门等待确认
    inflight = projects_root / "template-run-c"
    (inflight / "artifacts").mkdir(parents=True)
    _write(inflight / "artifacts" / "template_run_plan.json",
           {"status": "approved", "template_id": "sheet-01-video1-aks-zhuodian"})
    _write(inflight / "checkpoint_research.json", {"status": "completed"})
    _write(inflight / "checkpoint_assets.json", {
        "status": "awaiting_human",
        "set_at": "2026-08-28T05:00:15+00:00",
        "next_action": {"summary": "资产就绪", "set_at": "2026-08-28T05:00:15+00:00"},
    })
    # 占位 run：已建位未启动（无 checkpoint，plan 待批）
    scaffold = projects_root / "template-run-d"
    (scaffold / "artifacts").mkdir(parents=True)
    _write(scaffold / "artifacts" / "template_run_plan.json",
           {"status": "awaiting_human", "template_id": "sheet-01-video1-aks-zhuodian"})

    res = backlot_client.get("/api/v2/overview/videos")
    assert res.status_code == 200
    data = res.json()
    assert data["total_runs"] == 2
    assert data["scored_count"] == 1
    # 强校验字段（语义一致 / 画面重复 / 口播覆盖）
    top = data["slim_runs"][0]
    assert "semantic" in top and "reuse" in top and "audio" in top
    assert top.get("release") in {"official", "superseded", "baseline"}
    assert top["audio"]["coverage_ok"] is True
    assert isinstance(top["reuse"]["hard_pass"], bool)
    assert len(data["slim_runs"]) == 2
    assert len(data["gates"]) >= 5
    ranked = [r["run"] for r in data["slim_runs"]]
    assert ranked[0] == "template-run-a"  # 有证书 + 有评分 → 排前
    # 只读：不触发 judge（无 l3_advisory 的 run 只是未评分，不写文件）
    assert not (projects_root / "template-run-b" / "artifacts" / "l3_advisory.json").exists()
    # 整体报告：只读聚合，进行中/待推进/占位分类正确
    br = data["batch_report"]
    assert br["published"] == 2 and br["scored"] == 1
    assert br["certificated"] == 2
    assert br["l1a_pass"] == 2
    assert set(br["tiers"]) <= {"推荐", "达标", "观察", "未评分"}
    assert br["l3_avg"] == 8.5
    assert "pool" in br and "produced" in br and "inflight" in br and "notes" in br
    runs = [i["run"] for i in br["inflight"]]
    assert "template-run-c" in runs
    item = next(i for i in br["inflight"] if i["run"] == "template-run-c")
    assert item["phase"] == "running" and item["status_label"] == "等待确认"
    assert item["stage_label"] == "确认制作准备"
    assert item["since"] == "2026-08-28 13:00"
    assert br["scaffolds"] == 1
    # 动态口径：无写死的过期说明（证书状态已全部绑定，不再出现 sheet-01/04 硬编码）
    assert "sheet-01/04" not in " ".join(data["methodology"]["known_limits"])


def test_overview_page_served(backlot_client, projects_root, monkeypatch):
    monkeypatch.setattr(export_mod, "PROJECTS", projects_root)
    _make_fake_run(projects_root, "template-run-a")
    res = backlot_client.get("/overview/")
    assert res.status_code == 200
    assert "历史成片总览" in res.text
