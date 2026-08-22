from __future__ import annotations

from lib.sample_execution_trace import build_sample_execution_trace, write_sample_execution_trace
from schemas.artifacts import validate_artifact


def _artifacts() -> dict:
    return {
        "reference_fingerprint": {
            "abstract_structure": {"beat_order": ["冲突", "证明"]},
        },
        "creative_control_plan": {
            "sections": {
                "content_direction": {"summary": "真实动作证明产品价值"},
            },
        },
        "script": {
            "sections": [{"id": "hook", "label": "开场", "text": "先看真实动作", "start_seconds": 0, "end_seconds": 2}],
        },
        "shot_execution_plan": {
            "plan_version": 3,
            "shots": [
                {
                    "id": "shot-01",
                    "order": 1,
                    "purpose": "建立冲突",
                    "duration_seconds": 2,
                    "subject_action": "刮擦桌垫",
                    "screen_copy": "防刮",
                    "reference_mechanisms": ["首秒动作"],
                    "source_selection": {
                        "path": "inputs/source/scratch.mp4",
                        "start_seconds": 1,
                        "end_seconds": 3,
                    },
                },
                {
                    "id": "shot-02",
                    "order": 2,
                    "purpose": "展示结果",
                    "duration_seconds": 3,
                    "subject_action": "擦净桌面",
                    "screen_copy": "一擦即净",
                    "reference_mechanisms": ["动作后给出结果"],
                    "source_selection": {
                        "path": "inputs/source/wipe.mp4",
                        "start_seconds": 0,
                        "end_seconds": 3,
                    },
                },
            ],
        },
        "sample_report": {
            "window": {"startFrame": 0, "endFrameExclusive": 60},
        },
        "final_props": {
            "fps": 30,
            "shots": [
                {
                    "id": "shot-01",
                    "start_seconds": 0,
                    "end_seconds": 2,
                    "source_path": "inputs/source/scratch.mp4",
                    "source_in_seconds": 1,
                    "source_out_seconds": 3,
                    "screen_copy": "防刮",
                },
                {
                    "id": "shot-02",
                    "start_seconds": 2,
                    "end_seconds": 5,
                    "source_path": "inputs/source/wipe.mp4",
                    "source_in_seconds": 0,
                    "source_out_seconds": 3,
                    "screen_copy": "一擦即净",
                },
            ],
        },
    }


def test_trace_distinguishes_executed_and_not_in_sample() -> None:
    trace = build_sample_execution_trace("table-mat", _artifacts())

    assert trace["summary"] == {
        "planned_shot_count": 2,
        "included_shot_count": 1,
        "status_counts": {"executed": 1, "partial": 0, "added": 0, "not_in_sample": 1},
        "new_content_count": 0,
    }
    assert trace["shots"][0]["status"] == "executed"
    assert trace["shots"][1]["status"] == "not_in_sample"
    assert trace["shots"][1]["sample_window"]["included"] is False


def test_trace_marks_unplanned_actual_shot_as_added() -> None:
    artifacts = _artifacts()
    artifacts["final_props"]["shots"].append({
        "id": "shot-extra",
        "start_seconds": 1,
        "end_seconds": 1.5,
        "source_path": "inputs/source/extra.mp4",
    })

    trace = build_sample_execution_trace("table-mat", artifacts)

    added = next(item for item in trace["shots"] if item["shot_id"] == "shot-extra")
    assert added["status"] == "added"
    assert added["deviation"]["reason"] == "样片中出现了锁定方案之外的镜头"


def test_trace_is_registered_as_a_valid_artifact() -> None:
    trace = build_sample_execution_trace("table-mat", _artifacts())

    validate_artifact("sample_execution_trace", trace)


def test_trace_reads_remotion_scenes_and_footage_map() -> None:
    artifacts = _artifacts()
    artifacts["final_props"] = {
        "fps": 30,
        "footage": {"shot_01": "assets/video/shot-01-proxy.mp4"},
        "scenes": [{
            "id": "shot-01", "footageKey": "shot_01", "fromFrame": 0,
            "toFrameExclusive": 60, "sourceInSeconds": 1, "sourceOutSeconds": 3,
        }],
    }

    trace = build_sample_execution_trace("table-mat", artifacts)

    shot = trace["shots"][0]
    assert shot["status"] == "executed"
    assert shot["actual_execution"]["source_path"] == "assets/video/shot-01-proxy.mp4"


def test_trace_writer_persists_canonical_artifact(tmp_path) -> None:
    (tmp_path / "artifacts").mkdir()

    trace = write_sample_execution_trace(str(tmp_path), {"project_id": "table-mat", **_artifacts()})

    saved = (tmp_path / "artifacts" / "sample_execution_trace.json").read_text(encoding="utf-8")
    assert '"semantic_sha256"' in saved
    assert trace["project_id"] == "table-mat"


def _artifacts_with_audio_captions_rules() -> dict:
    artifacts = _artifacts()
    artifacts["creative_control_plan"] = {
        "sections": {
            "content_direction": {"title": "内容方向", "rules": ["主信息固定为透明保护"]},
            "visual_rules": {"title": "视觉规则", "rules": ["字幕只放短词"]},
        }
    }
    artifacts["script"]["voice_performance"] = {"performance_intent": "直接可信"}
    artifacts["script"]["metadata"] = {"caption_policy": "白字深色描边"}
    artifacts["shot_execution_plan"]["shots"][0]["control_rule_refs"] = ["content_direction.rules[0]"]
    artifacts["final_props"]["audio"] = {"mix": {"music": None, "narration": None, "source": "none_selected"}}
    artifacts["final_props"]["captions"] = [{"text": "防刮", "startMs": 0, "endMs": 2000}]
    artifacts["sample_report"]["probe"] = {"duration_seconds": 2.0}
    return artifacts


def test_trace_audio_diff_reports_planned_but_missing_narration() -> None:
    trace = build_sample_execution_trace("table-mat", _artifacts_with_audio_captions_rules())

    audio = trace["audio_diff"]
    assert audio["status"] == "partial"
    assert audio["plan"]["narration_planned"] is True
    assert audio["actual"]["narration_present"] is False
    assert "口播" in audio["summary"]


def test_trace_caption_diff_detects_timing_drift() -> None:
    artifacts = _artifacts_with_audio_captions_rules()
    artifacts["final_props"]["captions"].append({"text": "越界", "startMs": 0, "endMs": 9000})

    trace = build_sample_execution_trace("table-mat", artifacts)

    assert trace["caption_diff"]["actual"]["caption_count"] == 2
    assert trace["caption_diff"]["status"] == "partial"
    assert trace["caption_diff"]["actual"]["timing_drift_detected"] is True


def test_trace_creative_rule_diff_uses_natural_language() -> None:
    trace = build_sample_execution_trace("table-mat", _artifacts_with_audio_captions_rules())

    rules = trace["creative_rule_diff"]["rules"]
    assert any(r["rule"] == "主信息固定为透明保护" for r in rules)
    assert all("rules[" not in r["rule"] for r in rules)
    bound = next(r for r in rules if r["rule"] == "主信息固定为透明保护")
    assert bound["status"] == "bound"
    unbound = next(r for r in rules if r["rule"] == "字幕只放短词")
    assert unbound["status"] == "not_checked"


def test_trace_with_diffs_is_schema_valid() -> None:
    trace = build_sample_execution_trace("table-mat", _artifacts_with_audio_captions_rules())

    validate_artifact("sample_execution_trace", trace)


def test_trace_rejects_unrelated_proxy_path_as_source_mismatch() -> None:
    """评审 #8：路径含 shot 标记与 proxy 子串但词干非规范代理名 → 换源 partial。"""
    artifacts = _artifacts()
    artifacts["final_props"]["shots"][0]["source_path"] = "assets/video/backup-shot-01-proxy-old.mp4"
    trace = build_sample_execution_trace("table-mat", artifacts)
    item = next(i for i in trace["shots"] if i["shot_id"] == "shot-01")
    assert item["status"] == "partial"


def test_trace_accepts_canonical_shot_proxy_naming() -> None:
    artifacts = _artifacts()
    artifacts["final_props"]["shots"][0]["source_path"] = "assets/video/shot-01-proxy.mp4"
    trace = build_sample_execution_trace("table-mat", artifacts)
    item = next(i for i in trace["shots"] if i["shot_id"] == "shot-01")
    assert item["status"] == "executed"


def test_trace_accepts_proxy_preserving_source_stem() -> None:
    artifacts = _artifacts()
    artifacts["final_props"]["shots"][0]["source_path"] = "assets/video/scratch-shot-01-proxy.mp4"
    trace = build_sample_execution_trace("table-mat", artifacts)
    item = next(i for i in trace["shots"] if i["shot_id"] == "shot-01")
    assert item["status"] == "executed"
