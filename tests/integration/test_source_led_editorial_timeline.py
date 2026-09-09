from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.base_tool import ToolResult


def _fixture(tmp_path: Path) -> Path:
    project = tmp_path / "silver-ion-towel"
    (project / "artifacts").mkdir(parents=True)
    (project / "renders").mkdir()
    (project / "renders/final.mp4").write_bytes(b"old-delivery")
    timeline = {
        "version": "1.0", "timeline_id": "timeline-1", "base_generation_id": "generation-000000", "base_edit_revision": "edit-000000",
        "source_artifact_hashes": {"edit_decisions": "a" * 64, "final_props": "b" * 64, "asset_manifest": "c" * 64, "coverage_matrix": "d" * 64, "product_facts": "e" * 64},
        "profile": {"profile_id": "taobao-detail-3-4", "aspect_ratio": "3:4", "width": 1080, "height": 1440, "fps": 30, "render_runtime": "remotion", "safe_zone": "taobao_detail_3_4"},
        "tracks": [
            {"id": "video", "kind": "video", "clips": [{"id": "clip-1", "asset_id": "asset-1", "source_sha256": "a" * 64, "source_in_seconds": 0, "source_out_seconds": 1, "start_seconds": 0, "fact_scope": {"claim_ids": ["claim-1"], "shot_id": "shot-1", "visual_requirement_id": "visual-1", "allowed_source_classes": ["owned_source"]}}]},
            {"id": "narration", "kind": "narration", "clips": []}, {"id": "music", "kind": "music", "clips": []},
            {"id": "text", "kind": "text", "clips": [{"id": "text-1", "text": "吸水速干", "start_seconds": 0, "end_seconds": 1, "style_token": "taobao_selling_point_v1", "position": "top_center", "claim_ids": ["claim-1"]}]},
            {"id": "subtitle", "kind": "subtitle", "clips": [{"id": "subtitle-1", "text": "吸水速干", "start_seconds": 0, "end_seconds": 1, "style_token": "taobao_subtitle_v1", "position": "bottom_center", "claim_ids": ["claim-1"], "original_text_sha256": "a" * 64}]},
        ],
    }
    (project / "project.json").write_text(json.dumps({"project_id": project.name}), encoding="utf-8")
    (project / "artifacts/editorial_timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
    from lib.cache_keys import canonical_digest
    catalogue = {"version": "1.0", "project_id": project.name, "candidate_id": project.name, "timeline_id": "timeline-1", "base_generation_id": "generation-000000", "base_edit_revision": "edit-000000", "timeline_hash": canonical_digest(timeline), "source_artifact_hashes": dict(timeline["source_artifact_hashes"]), "assets": [{"asset_id": "asset-2", "candidate_id": project.name, "project_id": project.name, "source_sha256": "b" * 64, "media_kind": "video", "role": "video", "source_class": "owned_source", "claim_ids": ["claim-1"], "visual_requirement_id": "visual-1", "valid_range": {"start_seconds": 0, "end_seconds": 2}, "fact_scope": {"claim_ids": ["claim-1"], "shot_id": "shot-1", "visual_requirement_id": "visual-1", "allowed_source_classes": ["owned_source"]}}]}
    catalogue["catalogue_hash"] = canonical_digest(catalogue)
    (project / "operator/editorial").mkdir(parents=True)
    (project / "operator/editorial/asset-catalogue.json").write_text(json.dumps(catalogue), encoding="utf-8")
    return project


class _Compose:
    def execute(self, inputs):
        Path(inputs["output_path"]).write_bytes(b"rendered-" + inputs["profile"].encode())
        return ToolResult(success=True, data={})


class _Gate:
    def execute(self, inputs):
        Path(inputs["output_path"]).write_text(json.dumps({"status": "pass"}), encoding="utf-8")
        return ToolResult(success=True, data={"status": "pass"})


def test_source_led_editorial_preview_final_promote_preserves_old_delivery(tmp_path: Path) -> None:
    from backlot.editorial_sessions import EditorialSessionService
    from backlot.openreel_bridge import actions_to_delta
    from lib.editorial_executor import EditorialRenderExecutor

    project = _fixture(tmp_path)
    service = EditorialSessionService(project, actor_id="operator-a")
    session = service.create_session(idempotency_key="open-1")
    delta = actions_to_delta(session, [{"type": "clip/replace", "params": {"clipId": "clip-1", "assetId": "asset-2", "inPoint": 0, "outPoint": 1}}, {"type": "clip/split", "params": {"clipId": "clip-1", "time": 0.5}}, {"type": "caption/timing", "params": {"clipId": "subtitle-1", "start": 0.1, "end": 0.8}}], idempotency_key="delta-1")
    session = service.save_draft(session["session_id"], delta, idempotency_key="delta-1")
    def evaluate(**kwargs):
        return [{"clip_id": item["clip_id"], "shot_id": "shot-1", "scene_id": "shot-1", "match": "yes", "action_match": "pass", "result_support": "pass", "narration_caption_match": "pass", "crop_completeness": "pass", "product_identity_match": "pass", "status": "pass", "reason_codes": []} for item in kwargs["fact_bindings"]]
    executor = EditorialRenderExecutor(project, video_compose=_Compose(), technical_validator=_Gate(), final_qa=_Gate(), timeline_adapter=lambda timeline, **_: timeline, probe_runner=lambda _: {"duration": 1}, frame_sampler=lambda *_: [{"timestamp_seconds": 0}], alignment_evaluator=evaluate)
    fact_bindings = [{"clip_id": clip["id"], "shot_id": "shot-1", "claim_ids": ["claim-1"], "visual_requirement_id": "visual-1"} for track in session["timeline"]["tracks"] if track["kind"] == "video" for clip in track["clips"]]
    common = dict(timeline=session["timeline"], asset_catalogue=session["asset_catalogue"], asset_manifest={"assets": []}, product_facts_hash="e" * 64, script_hash="b" * 64, output_probe=None, frame_samples=None, fact_bindings=fact_bindings, visual_requirements=[{"id": "visual-1"}])
    preview = executor.render_preview(revision=session["revision_id"], **common)
    assert preview["status"] == "pass", preview.get("error")
    session = service.record_preview(session["session_id"], {"report_path": f"operator/editorial/versions/{session['revision_id']}/preview-execution_report.json"})
    session = service.approve_preview(session["session_id"], output_sha256=preview["output_sha256"])
    session = service.request_final(session["session_id"])
    final = executor.render_final(revision=session["revision_id"], **common)
    assert final["status"] == "pass"
    session = service.record_final(session["session_id"], {"report_path": f"operator/editorial/versions/{session['revision_id']}/final-execution_report.json"})
    session = service.promote(session["session_id"])
    assert session["status"] == "promoted"
    assert (project / "renders/final.mp4").read_bytes() == b"old-delivery"
    assert (project / "operator/current-delivery.json").is_file()
