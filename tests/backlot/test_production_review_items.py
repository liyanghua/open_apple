import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from backlot.operator_state import load_operator_state


def write_json(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data), encoding="utf-8")


def fixture_project(root):
    write_json(root, "project.json", {"project_id": root.name, "pipeline_type": "cinematic-fast"})
    items = []
    for slot in ("A01", "A03"):
        video = root / f"renders/{slot}.mp4"
        video.parent.mkdir(exist_ok=True)
        video.write_bytes(slot.encode())
        sha = hashlib.sha256(video.read_bytes()).hexdigest()
        base = f"artifacts/waves/W1/{slot}"
        write_json(root, f"{base}/production_record.json", {
            "content_slot_id": slot,
            "render": {"path": f"renders/{slot}.mp4", "sha256": sha, "seconds": 8},
            "checks": {"technical_hard_gate": True, "alignment": "pass",
                       "video_judge": "scored" if slot == "A03" else "unavailable"},
            "human_review_ref": f"{base}/human_review.json",
        })
        write_json(root, f"{base}/human_review.json", {"status": "pending", "render_sha256": sha})
        items.append({"id": slot, "title": slot, "record_path": f"{base}/production_record.json"})
    write_json(root, "artifacts/production_review_index.json", {"items": items})
    return items


def review_items(root):
    state = load_operator_state(root, permissions=("view", "review"))
    compose = next(s for s in state["stages"] if s["id"] == "compose")
    return compose["editor"]["data"].get("production_reviews", []), state


def test_nested_productions_visible_without_advancing_checkpoints(tmp_path):
    fixture_project(tmp_path)
    before = set(tmp_path.rglob("*"))
    items, state = review_items(tmp_path)
    assert [item["id"] for item in items] == ["A01", "A03"]
    assert items[0]["video_url"].endswith("renders/A01.mp4")
    assert items[0]["judge_label"] == "自动视觉评分未完成，原错误记录保留"
    assert items[0]["technical_label"] == "当前文件技术证据待补齐"
    assert items[1]["judge_label"] == "历史报告有评分；不代替本次完整认证"
    assert all(item["review_status"] == "待审核" for item in items)
    assert state["pending_review"] is None
    assert set(tmp_path.rglob("*")) == before
    assert not list(tmp_path.glob("checkpoint_*.json"))


def test_changed_video_cannot_reuse_old_checks_or_approval(tmp_path):
    fixture_project(tmp_path)
    (tmp_path / "renders/A01.mp4").write_bytes(b"new unreviewed render")
    items, _ = review_items(tmp_path)
    assert len(items) == 2
    assert items[0]["video_url"] is None
    assert items[0]["review_status"] == "文件已变化，请重新提交审核"
    assert items[0]["technical_label"] != "通过"


@pytest.mark.parametrize("bad_path", ["../outside.json", "/tmp/outside.json"])
def test_index_cannot_read_outside_project(tmp_path, bad_path):
    fixture_project(tmp_path)
    write_json(tmp_path, "artifacts/production_review_index.json", {
        "items": [{"id": "unsafe", "record_path": bad_path}]
    })
    assert review_items(tmp_path)[0] == []


def test_notes_bound_to_exact_content_and_render(tmp_path):
    fixture_project(tmp_path)
    sha = hashlib.sha256(b"A01").hexdigest()
    notes = [
        {"note": "通过", "stage": "compose", "version_ref": f"A01@{sha}", "ts": "now"},
        {"note": "old approval", "stage": "compose", "version_ref": "A01@old", "ts": "before"},
    ]
    (tmp_path / "review_notes.jsonl").write_text("\n".join(json.dumps(n) for n in notes))
    items, _ = review_items(tmp_path)
    assert len(items) == 2
    assert [n["note"] for n in items[0]["notes"]] == ["通过"]
    assert items[1]["notes"] == []
    assert items[0]["review_status"] == "待审核"  # A note is not a pipeline gate decision.


def test_frontend_reviews_batch_without_showing_unrelated_single_render(tmp_path):
    fixture_project(tmp_path)
    _, state = review_items(tmp_path)
    module = (Path(__file__).resolve().parents[2] / "backlot/ui/operator/approval_model.js").as_uri()
    script = f"""
      import {{buildApprovalStages}} from {json.dumps(module)};
      const state = {json.dumps(state)};
      const compose = buildApprovalStages(state).find(s => s.stageId === 'compose');
      console.log(JSON.stringify(compose));
    """
    model = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", script], text=True))
    assert [a["id"] for a in model["artifacts"]] == ["production_reviews"]
    assert model["status"] == "成片可审"
    assert "完整流程记录仍待补齐" in model["summary"]
    assert model["review"]["actionable"] is False
