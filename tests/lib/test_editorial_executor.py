import hashlib
import json
from pathlib import Path

from tools.base_tool import ToolResult
from lib.cache_keys import canonical_digest


class _Compose:
    def execute(self, inputs):
        Path(inputs["output_path"]).write_bytes(b"rendered-editorial-video")
        return ToolResult(success=True, data={"output_path": inputs["output_path"]})


class _QA:
    def __init__(self, status="pass"):
        self.status = status

    def execute(self, inputs):
        if inputs.get("scope") is not None:
            assert inputs["scope"] in {"sample", "final"}
        payload = {"status": self.status, "subject_hash": inputs.get("subject_hash")}
        Path(inputs["output_path"]).write_text(json.dumps(payload), encoding="utf-8")
        return ToolResult(success=self.status == "pass", data=payload)


def _timeline():
    timeline = {
        "base_generation_id": "generation-1",
        "profile": {"render_runtime": "remotion", "width": 1080, "height": 1440, "fps": 30},
        "tracks": [{"id": "video-main", "kind": "video", "clips": [{
            "id": "video-1", "fact_scope": {"shot_id": "shot-1",
            "claim_ids": ["claim-1"], "visual_requirement_id": "visual-1"}
        }]}],
    }
    return {**timeline, "timeline_hash": canonical_digest(timeline)}


def test_executor_writes_versioned_preview_and_preserves_delivery(tmp_path: Path):
    from lib.editorial_executor import EditorialRenderExecutor

    current = tmp_path / "renders" / "final.mp4"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"current-delivery")
    executor = EditorialRenderExecutor(tmp_path, video_compose=_Compose(),
                                       technical_validator=_QA(), final_qa=_QA(),
                                       timeline_adapter=lambda timeline, **_: timeline,
        alignment_evaluator=lambda **_: [{"clip_id": "video-1", "shot_id": "shot-1", "scene_id": "scene-1", "match": "yes", "action_match": "pass", "result_support": "pass", "narration_caption_match": "pass", "crop_completeness": "pass", "product_identity_match": "pass", "status": "pass", "reason_codes": []}],
                                       probe_runner=lambda _: {"duration_seconds": 1.0},
                                       frame_sampler=lambda *_: [{"timestamp_seconds": 0.0}])
    result = executor.render_preview(
        revision="rev-001", timeline=_timeline(), asset_catalogue={"assets": []},
        asset_manifest={"assets": []}, product_facts_hash="c" * 64,
        script_hash="b" * 64,
        output_probe={"duration_seconds": 1.0}, frame_samples=[{"timestamp_seconds": 0}],
        fact_bindings=[{"clip_id": "video-1", "shot_id": "shot-1", "claim_ids": ["claim-1"],
                        "visual_requirement_id": "visual-1"}],
        visual_requirements=[{"id": "visual-1"}],
    )
    output = tmp_path / "operator/editorial/versions/rev-001/preview.mp4"
    assert result["status"] == "pass"
    assert output.is_file()
    assert result["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert current.read_bytes() == b"current-delivery"
    assert (output.parent / "preview-execution_report.json").is_file()


def test_executor_rejects_stale_baseline_and_qa_failure_without_touching_delivery(tmp_path: Path):
    from lib.editorial_executor import EditorialRenderExecutor

    current = tmp_path / "renders" / "final.mp4"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"current-delivery")
    executor = EditorialRenderExecutor(tmp_path, video_compose=_Compose(),
                                       technical_validator=_QA("fail"), final_qa=_QA(),
                                       timeline_adapter=lambda timeline, **_: timeline)
    result = executor.render_final(
        revision="rev-002", timeline=_timeline(), asset_catalogue={"assets": []},
        asset_manifest={"assets": []}, product_facts_hash="c" * 64,
        script_hash="b" * 64,
        output_probe={"duration_seconds": 1.0}, frame_samples=[{"timestamp_seconds": 0}],
        fact_bindings=[], visual_requirements=[],
        baseline_alignment={"status": "pass"},
    )
    assert result["status"] == "failed"
    assert current.read_bytes() == b"current-delivery"
    assert not (tmp_path / "renders/final.mp4").read_bytes() == b"rendered-editorial-video"


def test_executor_rejects_unsafe_revision_before_creating_version(tmp_path: Path):
    from lib.editorial_executor import EditorialRenderExecutor

    executor = EditorialRenderExecutor(tmp_path, video_compose=_Compose(),
                                       technical_validator=_QA(), final_qa=_QA())
    try:
        executor.render_preview(
            revision="../../renders", timeline=_timeline(), asset_catalogue={},
            asset_manifest={}, product_facts_hash="c" * 64, script_hash="b" * 64,
            output_probe=None, frame_samples=None, fact_bindings=[],
            visual_requirements=[],
        )
    except ValueError as exc:
        assert "safe version identifier" in str(exc)
    else:
        raise AssertionError("unsafe revision was accepted")
    assert not (tmp_path / "operator").exists()


def test_executor_default_alignment_and_l1a_receive_server_owned_inputs(tmp_path: Path):
    from lib.editorial_executor import EditorialRenderExecutor

    class CaptureQA(_QA):
        def execute(self, inputs):
            assert "expected_facts" in inputs
            assert "text_sources" in inputs
            assert "caption_declaration" in inputs
            assert "caption_spec" in inputs
            assert "shot_map" in inputs
            return super().execute(inputs)

    executor = EditorialRenderExecutor(tmp_path, video_compose=_Compose(),
        technical_validator=CaptureQA(), final_qa=_QA(),
        timeline_adapter=lambda timeline, **_: timeline,
        probe_runner=lambda _: {"duration_seconds": 1},
        frame_sampler=lambda *_: [{"timestamp_seconds": 0}],
    )
    result = executor.render_preview(
        revision="rev-inputs", timeline=_timeline(), asset_catalogue={}, asset_manifest={},
        product_facts_hash="c" * 64, script_hash="b" * 64,
        output_probe=None, frame_samples=None,
        fact_bindings=[{"clip_id": "video-1", "shot_id": "shot-1", "claim_ids": ["claim-1"], "visual_requirement_id": "visual-1"}],
        visual_requirements=[{"id": "visual-1"}],
    )
    assert result["status"] == "pass"
