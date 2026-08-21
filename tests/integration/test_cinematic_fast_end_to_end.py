from __future__ import annotations

import copy
import json
from pathlib import Path

from lib.approval_groups import approve_bundle, build_approval_bundle, reconcile_bundle
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import init_project, write_checkpoint
from lib.pipeline_loader import load_pipeline
from backlot.project_commit import ProjectCommitStore
from tests.contracts.test_fastline_artifact_contracts import (
    FASTLINE_ARTIFACTS,
    valid_artifact,
)
from tests.contracts.test_phase0_contracts import sample_artifact


PROJECT_ID = "cinematic-fast-e2e"
PIPELINE = "cinematic-fast"
REFERENCE_PATH = "inputs/reference/viral-reference.mp4"
REFERENCE_FRAME = "artifacts/reference-frames/frame-001.jpg"
REFERENCE_AUDIO = "artifacts/reference-audio/reference.wav"
REFERENCE_HASH = "f" * 64


class FakePaidProviders:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_tts(self) -> None:
        self.calls.append("tts")

    def generate_music(self) -> None:
        self.calls.append("music")


class FakeRemotionAdapter:
    def __init__(self) -> None:
        self.sample_calls = 0
        self.full_render_calls = 0
        self.full_qa_calls = 0

    def render_sample(self) -> None:
        self.sample_calls += 1

    def render_full_and_qa(self) -> None:
        self.full_render_calls += 1
        self.full_qa_calls += 1


def _source_media_review() -> dict:
    return {
        "version": "1.0",
        "files": [
            {
                "path": "inputs/source/product-a.mp4",
                "media_type": "video",
                "reviewed": True,
                "technical_probe": {"duration_seconds": 8, "resolution": "1080x1920", "fps": 30},
                "content_summary": "Product wipe test",
                "representative_frames": ["artifacts/source-frames/product-a.jpg"],
                "best_ranges": [{"start_seconds": 0, "end_seconds": 8}],
                "usable_audio": False,
                "quality_risks": [],
                "usable_for": ["proof beat"],
            },
            {
                "path": "inputs/source/product-b.mp4",
                "media_type": "video",
                "reviewed": True,
                "technical_probe": {"duration_seconds": 10, "resolution": "1080x1920", "fps": 30},
                "content_summary": "Product overview",
                "representative_frames": ["artifacts/source-frames/product-b.jpg"],
                "best_ranges": [{"start_seconds": 1, "end_seconds": 9}],
                "usable_audio": False,
                "quality_risks": [],
                "usable_for": ["opening and closing"],
            },
        ],
        "summary": "Two inspected vertical product clips with no usable production audio",
        "planning_implications": ["Use source clips for every realized visual"],
    }


def _final_review() -> dict:
    return {
        "version": "2.0",
        "output_path": "renders/final.mp4",
        "status": "pass",
        "checks": {
            "technical_probe": {"valid_container": True, "duration_seconds": 30, "resolution": "1080x1920", "fps": 30, "has_audio": True, "codec": "h264", "issues": []},
            "visual_spotcheck": {"frames_sampled": 4, "frame_paths": ["q1.jpg", "q2.jpg", "q3.jpg", "q4.jpg"], "black_frames_detected": False, "broken_overlays": False, "missing_assets": False, "unreadable_text": False, "issues": []},
            "audio_spotcheck": {"narration_present": True, "music_present": True, "unexpected_silence": False, "clipping_detected": False, "mix_intelligible": True, "issues": []},
            "promise_preservation": {"delivery_promise_honored": True, "render_runtime_used": "remotion", "runtime_swap_detected": False, "silent_downgrade_detected": False, "issues": []},
            "subtitle_check": {"subtitles_expected": True, "subtitles_present": True, "coverage_ratio": 1, "timing_drift_detected": False, "issues": []},
            "media_integrity": {"black_frames": 0, "freeze_frames": 0},
            "audio_loudness": {"peak_dbfs": -1, "integrated_lufs": -14},
            "caption_render": {
                "declared": True,
                "caption_render_mode": "remotion_overlay",
                "caption_source": "artifacts/final_props.json#captions",
                "safe_zone_profile": "douyin_9_16",
                "pixels_rendered": True,
                "safe_zone_passed": True,
                "computed_boxes": [],
                "props_hash": "a" * 64,
            },
        },
        "issues_found": [],
        "recommended_action": "present_to_user",
    }


def _artifact(name: str) -> dict:
    if name == "creative_control_plan":
        sections = {
            section_id: {
                "title": section_id,
                "summary": "已确认的制作约束",
                "rules": ["按总控单执行"],
                "evidence_refs": [],
                "industry_notes": [],
            }
            for section_id in (
                "content_direction",
                "story_pacing",
                "visual_rules",
                "fact_continuity",
                "originality_boundary",
            )
        }
        return {
            "version": "1.0",
            "project_id": PROJECT_ID,
            "created_at": "2026-08-17T00:00:00+00:00",
            "producer": "proposal-director-test",
            "input_hashes": {"proposal_packet": "a" * 64},
            "plan_id": "creative-control-cinematic-fast-e2e",
            "plan_version": 1,
            "status": "approved",
            "selected_direction_id": "direction-1",
            "sections": sections,
            "section_reviews": {key: "approved" for key in sections},
            "feedback": {},
            "locked_at": "2026-08-17T00:00:00+00:00",
            "locked_by": "tester",
        }
    if name in FASTLINE_ARTIFACTS:
        value = copy.deepcopy(valid_artifact(name))
        value["project_id"] = PROJECT_ID
        if name == "reference_fingerprint":
            value.update(
                content_sha256=REFERENCE_HASH,
                analysis_depth="deep",
                canonical_request={"path": REFERENCE_PATH, "depth": "deep"},
                abstract_structure={"semantic_hash": "e" * 64, "beats": 3},
            )
        elif name == "media_index":
            value["entries"][0]["path"] = "inputs/source/product-a.mp4"
        elif name == "reference_source_matrix":
            value["rows"][0]["reference_time_range"] = {"start_seconds": 0, "end_seconds_exclusive": 5}
            value["rows"][0]["source_time_range"] = {"start_seconds": 0, "end_seconds_exclusive": 10}
        return value
    if name == "source_media_review":
        return _source_media_review()
    if name == "final_review":
        return _final_review()
    if name == "decision_log":
        return {
            "version": "1.0",
            "project_id": PROJECT_ID,
            "decisions": [
                {
                    "decision_id": "runtime-1",
                    "stage": "proposal",
                    "category": "render_runtime_selection",
                    "subject": "composition runtime",
                    "options_considered": [
                        {"option_id": "remotion", "label": "Remotion", "score": 1, "reason": "source-led"},
                        {"option_id": "hyperframes", "label": "HyperFrames", "score": 0, "reason": "unavailable", "rejected_because": "runtime unavailable"},
                    ],
                    "selected": "remotion",
                    "reason": "source-led montage",
                    "user_visible": True,
                    "user_approved": True,
                }
            ],
        }
    value = copy.deepcopy(sample_artifact(name))
    if name == "video_analysis_brief":
        value["source"] = {
            "type": "local_file",
            "local_path": REFERENCE_PATH,
            "duration_seconds": 30,
        }
        value["metadata"] = {
            "representative_frame": REFERENCE_FRAME,
            "audio_path": REFERENCE_AUDIO,
        }
    elif name == "proposal_packet":
        for concept in value["concept_options"]:
            concept["research_direction_refs"] = ["direction-1"]
            concept["matrix_row_refs"] = ["matrix-1"]
            concept["fingerprint_rule_refs"] = ["proof-pair"]
    elif name == "scene_plan":
        value["scenes"][0]["shot_intent"] = "Show the owned product proof beat"
        value["metadata"] = {
            "reference_media_usage": "analysis_only",
            "source_mapping": [{
                "scene_id": "scene-1",
                "reference_evidence": {
                    "mode": "direct_segment",
                    "reference_scene_id": "reference-1",
                    "reference_interval": {
                        "start_seconds": 0,
                        "end_seconds_exclusive": 5,
                    },
                    "mechanism": "Action and result proof",
                    "rationale": "Use the hook structure for the product proof beat",
                },
                "source_path": "inputs/source/product-b.mp4",
                "source_interval": {
                    "start_seconds": 0,
                    "end_seconds_exclusive": 10,
                },
                "timeline_interval": {
                    "start_seconds": 0,
                    "end_seconds_exclusive": 10,
                },
                "reference_basis": "Reference pairs product action with result",
                "source_fit": "Owned overview clip covers the complete beat",
                "mapping_reason": "The clip establishes the product proof intent",
                "originality_note": "Only the abstract proof structure is reused",
                "matrix_row_id": "matrix-1",
                "matrix_resolution_id": "accept",
                "research_direction_ref": "direction-1",
            }],
        }
    elif name == "asset_manifest":
        value["assets"] = [
            {
                "id": "source-a",
                "type": "video",
                "path": "assets/video/product-a.mp4",
                "source_tool": "media_proxy",
                "scene_id": "scene-1",
            },
            {
                "id": "narration",
                "type": "audio",
                "path": "assets/audio/narration.wav",
                "source_tool": "fake_tts",
                "scene_id": "scene-1",
            },
        ]
    elif name == "edit_decisions":
        value["render_runtime"] = "remotion"
    elif name == "render_report":
        value["outputs"][0].update(path="renders/final.mp4", resolution="1080x1920", duration_seconds=30)
        value.update(render_mode="full", remotion_invoked=True)
    return value


def _caption_policy_revision() -> dict:
    """Minimal approved caption treatment the sample stage now produces (manifest v2 contract)."""
    return {
        "version": "1.0",
        "project_id": PROJECT_ID,
        "created_at": "2026-08-17T00:00:00+00:00",
        "producer": "sample-director-test",
        "input_hashes": {"production_lock": "a" * 64, "scene_plan": "b" * 64},
        "semantic_sha256": "c" * 64,
        "artifact_sha256": "d" * 64,
        "revision_id": "caprev-1",
        "revision_version": 1,
        "base_production_lock_artifact_sha256": "e" * 64,
        "caption_treatments": [
            {
                "scene_id": "scene-1",
                "caption_id": "cap-1",
                "action": "retain",
                "review": "approved",
                "interval": {"start_seconds": 0.0, "end_seconds": 8.0},
                "reason": "approved source caption",
            }
        ],
        "authorization": {
            "source": "approval_record",
            "actor": "tester",
            "timestamp": "2026-08-17T00:00:00+00:00",
            "evidence_ref": "operator/reviews/sample.json",
        },
        "decision_revision_id": "drev-1",
        "change_impact": {
            "render_route": "full_render",
            "reopen_creative": False,
            "reopen_sample": True,
            "changed_fields": ["caption_policy_revision"],
        },
        "status": "approved_for_sample_revision",
    }


def _envelopes(project: Path, names: list[str], overrides: dict[str, dict] | None = None) -> dict:
    result = {}
    for name in names:
        data = copy.deepcopy((overrides or {}).get(name, _artifact(name)))
        result[name] = write_artifact_atomic(
            f"artifacts/{name}.json", name, data, project_dir=project
        )
    return result


def _checkpoint(root: Path, stage: str, status: str, artifacts: dict, **kwargs) -> Path:
    kwargs.setdefault("pipeline_type", PIPELINE)
    if status in {"awaiting_human", "in_progress"} and "next_action" not in kwargs:
        kwargs["next_action"] = {
            "summary": f"E2E 恢复:{stage} 阶段",
            "verb": "await_user" if status == "awaiting_human" else "run_stage",
            "context_refs": [f"checkpoint_{stage}.json"],
        }
    return write_checkpoint(
        root,
        PROJECT_ID,
        stage,
        status,
        artifacts,
        **kwargs,
    )


def test_research_artifacts_and_checkpoint_commit_in_one_generation(tmp_path: Path) -> None:
    project = init_project(PROJECT_ID, title="Atomic Research", pipeline_type=PIPELINE, pipeline_dir=tmp_path)
    store = ProjectCommitStore(project)
    store.initialize()
    names = [
        "research_brief", "video_analysis_brief", "source_media_review", "media_index",
        "reference_fingerprint", "research_breakdown", "reference_source_matrix",
        "research_synthesis", "research_scorecard",
    ]
    with store.transaction(action={"action_id": "research-complete"}) as sink:
        envelopes = {
            name: write_artifact_atomic(
                f"artifacts/{name}.json", name, copy.deepcopy(_artifact(name)),
                project_dir=project, sink=sink,
            )
            for name in names
        }
        write_checkpoint(
            tmp_path, PROJECT_ID, "research", "completed", envelopes,
            pipeline_type=PIPELINE, sink=sink,
        )
        assert not (project / "checkpoint_research.json").exists()
    assert (project / "checkpoint_research.json").exists()
    assert all((project / f"artifacts/{name}.json").exists() for name in names)


def test_cinematic_fast_end_to_end_has_exactly_two_gates_and_no_reference_reuse(tmp_path: Path):
    project = init_project(PROJECT_ID, title="Fastline E2E", pipeline_type=PIPELINE, pipeline_dir=tmp_path)
    manifest = load_pipeline(PIPELINE)
    awaiting_human_stages: list[str] = []
    providers = FakePaidProviders()
    remotion = FakeRemotionAdapter()

    _checkpoint(tmp_path, "research", "completed", _envelopes(project, [
        "research_brief", "video_analysis_brief", "source_media_review", "media_index",
        "reference_fingerprint", "research_breakdown", "reference_source_matrix",
        "research_synthesis", "research_scorecard",
    ]))
    _checkpoint(
        tmp_path,
        "proposal",
        "completed",
        _envelopes(project, ["proposal_packet", "creative_control_plan", "decision_log"]),
    )
    _checkpoint(tmp_path, "script", "completed", _envelopes(project, ["script"]))
    _checkpoint(tmp_path, "scene_plan", "completed", _envelopes(project, ["scene_plan"]))

    asset_inputs = _envelopes(project, ["asset_plan", "production_lock"])
    _checkpoint(tmp_path, "assets", "in_progress", asset_inputs, approval_group="creative_lock")
    assert providers.calls == []

    bundle = build_approval_bundle(project, manifest, "creative_lock")
    bundle_envelope = _envelopes(project, ["approval_bundle"], {"approval_bundle": bundle})["approval_bundle"]
    assets_artifacts = {**asset_inputs, "approval_bundle": bundle_envelope}
    _checkpoint(
        tmp_path,
        "assets",
        "awaiting_human",
        assets_artifacts,
        approval_group="creative_lock",
        approval_bundle_id=bundle["bundle_id"],
        approval_bundle_version=bundle["bundle_version"],
    )
    awaiting_human_stages.append("assets")

    approved_path = approve_bundle(project, bundle["bundle_id"], approved_by="tester")
    approved_bundle = json.loads(approved_path.read_text(encoding="utf-8"))
    approved_envelope = _envelopes(project, ["approval_bundle"], {"approval_bundle": approved_bundle})["approval_bundle"]
    _checkpoint(
        tmp_path,
        "assets",
        "completed",
        {**asset_inputs, "approval_bundle": approved_envelope},
        human_approved=True,
        approval_group="creative_lock",
        approval_bundle_id=bundle["bundle_id"],
        approval_bundle_version=bundle["bundle_version"],
    )
    terminal = json.loads((project / "checkpoint_assets.json").read_text(encoding="utf-8"))
    assert reconcile_bundle(project, terminal)["status"] == "approved"

    providers.generate_tts()
    providers.generate_music()
    remotion.render_sample()
    sample_artifacts = _envelopes(
        project,
        ["asset_manifest", "final_props", "render_plan", "sample_report"],
        {"caption_policy_revision": _caption_policy_revision()},
    )
    sample_artifacts["caption_policy_revision"] = write_artifact_atomic(
        "artifacts/caption_policy_revision.json",
        "caption_policy_revision",
        _caption_policy_revision(),
        project_dir=project,
    )
    _checkpoint(tmp_path, "sample", "awaiting_human", sample_artifacts)
    awaiting_human_stages.append("sample")
    _checkpoint(tmp_path, "sample", "completed", sample_artifacts, human_approved=True)

    _checkpoint(tmp_path, "edit", "completed", _envelopes(project, ["edit_decisions", "change_impact"]))
    remotion.render_full_and_qa()
    _checkpoint(tmp_path, "compose", "completed", _envelopes(project, ["render_report", "final_review"]))
    _checkpoint(tmp_path, "publish", "completed", _envelopes(project, ["publish_log"]))

    assert awaiting_human_stages == ["assets", "sample"]
    assert providers.calls == ["tts", "music"]
    assert remotion.sample_calls == 1
    assert remotion.full_render_calls == 1
    assert remotion.full_qa_calls == 1

    realized = json.dumps(
        {
            "asset_manifest": sample_artifacts["asset_manifest"]["data"],
            "final_props": sample_artifacts["final_props"]["data"],
            "render_inputs": sample_artifacts["render_plan"]["data"],
        },
        sort_keys=True,
    )
    for forbidden in (REFERENCE_PATH, REFERENCE_FRAME, REFERENCE_AUDIO, REFERENCE_HASH):
        assert forbidden not in realized
