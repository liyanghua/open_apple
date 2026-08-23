"""批级聚合状态契约测试（Batch_Workbench_Aggregate_State_Event_Contract §6）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backlot import state as state_mod
from backlot.operator_state import load_operator_state
from lib.candidate_batch import create_candidate_batch


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _child(root: Path, project_id: str, *, script_pending=False, with_sample=True, corrupt=False) -> None:
    child = root / project_id
    (child / "artifacts").mkdir(parents=True, exist_ok=True)
    (child / "renders").mkdir(parents=True, exist_ok=True)
    if corrupt:
        _write(child / "project.json", {"broken": True})
        return
    _write(child / "project.json", {"project_id": project_id, "title": project_id, "pipeline_type": "cinematic-fast"})
    if script_pending:
        _write(child / "checkpoint_script.json", {
            "version": "1.0", "project_id": project_id, "pipeline_type": "cinematic-fast",
            "stage": "script", "status": "awaiting_human",
            "timestamp": "2026-08-23T00:00:00+00:00", "artifacts": {},
        })
    if with_sample:
        _write(child / "artifacts" / "evaluation_report.sample.json", {
            "scope": "sample", "status": "revise", "recommended_action": "repair",
            "judge_version": "technical_validator-0.1.0",
            "hard_gate": {"checks": []},
            "creative_advisory": {"scored": False, "dimensions": [], "summary": "未运行"},
        })
        _write(child / "artifacts" / "sample_execution_trace.json", {
            "audio_diff": {
                "plan": {"narration_planned": True, "music_planned": True},
                "actual": {"narration_present": True, "music_present": True, "original_sound": True, "source": "mix"},
                "status": "executed",
            },
            "summary": {"status_counts": {}},
        })
        (child / "renders" / "sample-v1.mp4").write_bytes(b"fake")


def _batch_root(tmp_path: Path, n: int = 2, statuses=None) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    batch_dir = root / "batch-mix-001"
    (batch_dir / "artifacts").mkdir(parents=True)
    _write(batch_dir / "project.json", {
        "project_id": "batch-mix-001", "title": "透明桌垫批量混剪", "pipeline_type": "cinematic-fast",
    })
    statuses = statuses or ["sampled", "in_progress"][:n]
    candidates = [
        {"candidate_id": f"cand-{i:02d}", "label": f"方向 {i}", "project_id": f"cand-{i:02d}",
         "direction": {"hook": f"direction-{i}"}, "status": statuses[i - 1] if i - 1 < len(statuses) else "planned"}
        for i in range(1, n + 1)
    ]
    batch = create_candidate_batch(
        "mix-001",
        shared_research_refs=[{"name": "research_brief", "path": "artifacts/research_brief.json"}],
        candidates=candidates,
        source_media_refs=["inputs/source/video-01.mp4"],
        budget={"max_cost_usd": 30.0, "max_retries_per_candidate": 2},
        max_candidates=max(n, 5),
    )
    _write(batch_dir / "artifacts" / "candidate_batch.json", batch)
    return batch_dir


@pytest.fixture
def batch_project(tmp_path, monkeypatch):
    batch_dir = _batch_root(tmp_path)
    root = tmp_path / "projects"
    _child(root, "cand-01", script_pending=True)
    _child(root, "cand-02", with_sample=False)
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    return batch_dir


def _data(state):
    return state["workspace"]["editor"]["data"]


def test_batch_review_contract_shape(batch_project: Path):
    data = _data(load_operator_state(batch_project))
    assert data["schema_version"] == "1.0"
    assert data["kind"] == "batch_review"
    assert data["batch_id"] == "mix-001"
    assert len(data["aggregate_revision"]) == 64
    assert data["consistency"] == "stable"
    assert data["phase"] in {"building", "sampling", "scoring", "selection", "editing", "publishing", "completed", "blocked"}
    assert data["phase_reason"]
    assert [item["phase"] for item in data["rail"]] == ["building", "sampling", "scoring", "selection", "editing", "publishing"]
    assert len(data["candidates"]) == 2
    for view in data["candidates"]:
        assert view["candidate_phase"] in {"planned", "forking", "sampling", "sampled", "evaluating",
                                           "evaluated", "selected", "editing", "composed", "published",
                                           "failed", "missing", "corrupt"}
        assert view["stage_states"] is not None
        assert view["pending_reviews"] is not None
        assert "sample_url" in view["media"]
    assert data["budget"]["source"] in {"cost_tracker", "candidate_batch"}
    assert data["concurrency"]["max_parallel"] == 3
    assert data["selection"]["eligible_candidate_ids"] == []


def test_candidate_view_carries_evaluation_and_audio(batch_project: Path):
    data = _data(load_operator_state(batch_project))
    views = {c["candidate_id"]: c for c in data["candidates"]}
    first = views["cand-01"]
    assert first["status"] == "sampled"
    assert first["score"]["evaluation"]["status"] == "revise"
    assert first["media"]["sample_url"] is not None
    tracks = {t["kind"]: t for t in first["media"]["audio_tracks"]}
    assert tracks["narration"]["state"] == "present"
    second = views["cand-02"]
    assert second["score"]["evaluation"] is None
    assert second["media"]["sample_url"] is None
    assert all(t["state"] == "not_planned" for t in second["media"]["audio_tracks"])


def test_script_gate_lists_awaiting_candidates(batch_project: Path):
    state = load_operator_state(batch_project)
    review = state["pending_review"]
    assert review is not None
    assert review["kind"] == "batch_gate"
    assert review["gate"] == "script"
    assert [c["candidate_id"] for c in review["candidates"]] == ["cand-01"]


def test_matrix_sizes_1_2_5_10(tmp_path, monkeypatch):
    for n in (1, 2, 5, 10):
        base = tmp_path / f"n{n}"
        base.mkdir()
        batch_dir = _batch_root(base, n=n)
        root = batch_dir.parent
        monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
        data = _data(load_operator_state(batch_dir))
        assert len(data["candidates"]) == n  # 不出现固定 5 列
        assert len(data["rail"]) == 6


def test_all_failed_candidates_block(tmp_path, monkeypatch):
    batch_dir = _batch_root(tmp_path, n=2, statuses=["failed", "failed"])
    root = batch_dir.parent
    _child(root, "cand-01", with_sample=False)
    _child(root, "cand-02", with_sample=False)
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    data = _data(load_operator_state(batch_dir))
    assert data["phase"] == "blocked"
    assert "没有可选候选" in data["phase_reason"]


def test_missing_and_corrupt_candidates_degrade(tmp_path, monkeypatch):
    batch_dir = _batch_root(tmp_path, n=2)
    root = batch_dir.parent
    _child(root, "cand-01", with_sample=False)  # 正常
    _child(root, "cand-02", with_sample=False, corrupt=True)  # project.json 损坏
    # cand-02 的 batch 条目指向 cand-02；再删掉 cand-01 的 project.json 模拟缺失？用第三个场景分开测。
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    data = _data(load_operator_state(batch_dir))
    views = {c["candidate_id"]: c for c in data["candidates"]}
    assert views["cand-02"]["candidate_phase"] == "corrupt"
    assert any(w["code"] == "candidate_corrupt" for w in data["warnings"])
    assert data["consistency"] in {"degraded", "unstable"}


def test_missing_candidate_project_degrades(tmp_path, monkeypatch):
    batch_dir = _batch_root(tmp_path, n=2)
    root = batch_dir.parent
    _child(root, "cand-01", with_sample=False)  # cand-02 目录不创建 → missing
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    data = _data(load_operator_state(batch_dir))
    views = {c["candidate_id"]: c for c in data["candidates"]}
    assert views["cand-02"]["candidate_phase"] == "missing"
    assert any(w["code"] == "candidate_missing" for w in data["warnings"])
    assert data["consistency"] == "degraded"


def test_budget_mismatch_degrades(tmp_path, monkeypatch):
    batch_dir = _batch_root(tmp_path, n=2)
    root = batch_dir.parent
    _child(root, "cand-01", with_sample=False)
    _child(root, "cand-02", with_sample=False)
    # 候选索引合计 > cost_tracker（board cost 不存在 → source=candidate_batch 无冲突）；
    # 注入 tracker 不一致：候选成本 0，tracker 显示 5.0 → 不一致。
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    import backlot.batch_state as bs
    original = bs.load_board_state

    def fake_board(child_dir):
        board = original(child_dir)
        board["cost"] = {"total_spent_usd": 5.0}
        return board

    monkeypatch.setattr(bs, "load_board_state", fake_board)
    # 但 batch 根 board 的 cost 也来自 load_board_state（batch_state 只对子项目调用）；
    # 批根 cost 在 operator_state 传入的 board 上。直接调 build：
    from backlot.operator_state import load_operator_state as los

    board_root = load_operator_state(batch_dir)  # 正常路径
    # 批根 board 没有 cost → 用 monkeypatch 直接测 batch_state.build：
    from backlot.state import load_board_state as real_load
    board = real_load(batch_dir)
    board["_project_dir"] = batch_dir
    board["cost"] = {"total_spent_usd": 5.0}  # tracker 与索引 0 不一致
    from backlot.batch_state import build_batch_review_data
    data = build_batch_review_data(board, board["artifacts"]["candidate_batch"])
    assert data["consistency"] == "degraded"
    assert any(w["code"] == "budget_mismatch" for w in data["warnings"])
    assert data["budget"]["spent_usd"] == 5.0  # 以 tracker 为准
    assert data["budget"]["source"] == "cost_tracker"


def test_phase_rollback_changes_aggregate_revision(tmp_path, monkeypatch):
    batch_dir = _batch_root(tmp_path, n=2, statuses=["evaluated", "evaluated"])
    root = batch_dir.parent
    _child(root, "cand-01", with_sample=False)
    _child(root, "cand-02", with_sample=False)
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    first = _data(load_operator_state(batch_dir))
    assert first["phase"] == "selection"
    # retry/rework：把 cand-01 打回 in_progress → 相位回退 sampling，revision 变化
    batch_path = batch_dir / "artifacts" / "candidate_batch.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    for item in batch["candidates"]:
        if item["candidate_id"] == "cand-01":
            item["status"] = "in_progress"
    _write(batch_path, batch)
    second = _data(load_operator_state(batch_dir))
    assert second["phase"] == "sampling"
    assert second["aggregate_revision"] != first["aggregate_revision"]


def test_unstable_when_child_changes_during_read(tmp_path, monkeypatch):
    batch_dir = _batch_root(tmp_path, n=1, statuses=["sampled"])
    root = batch_dir.parent
    _child(root, "cand-01", with_sample=False)
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    import backlot.batch_state as bs

    calls = {"count": 0}
    original_snapshot = bs.child_snapshot

    def flaky_snapshot(project_dir, child_dir):
        calls["count"] += 1
        snapshot = original_snapshot(project_dir, child_dir)
        if calls["count"] >= 2:
            # 读取期间子项目变化：revision 输入改变
            snapshot["child_revision"] = (snapshot.get("child_revision") or "a" * 64)[::-1]
        return snapshot

    monkeypatch.setattr(bs, "child_snapshot", flaky_snapshot)
    from backlot.state import load_board_state as real_load
    board = real_load(batch_dir)
    board["_project_dir"] = batch_dir
    data = bs.build_batch_review_data(board, board["artifacts"]["candidate_batch"])
    assert data["consistency"] == "unstable"
