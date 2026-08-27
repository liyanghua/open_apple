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
    if with_cert:
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

    res = backlot_client.get("/api/v2/overview/videos")
    assert res.status_code == 200
    data = res.json()
    assert data["total_runs"] == 2
    assert data["scored_count"] == 1
    assert len(data["slim_runs"]) == 2
    assert len(data["gates"]) >= 5
    ranked = [r["run"] for r in data["slim_runs"]]
    assert ranked[0] == "template-run-a"  # 有证书 + 有评分 → 排前
    # 只读：不触发 judge（无 l3_advisory 的 run 只是未评分，不写文件）
    assert not (projects_root / "template-run-b" / "artifacts" / "l3_advisory.json").exists()


def test_overview_page_served(backlot_client, projects_root, monkeypatch):
    monkeypatch.setattr(export_mod, "PROJECTS", projects_root)
    _make_fake_run(projects_root, "template-run-a")
    res = backlot_client.get("/overview/")
    assert res.status_code == 200
    assert "历史成片总览" in res.text
