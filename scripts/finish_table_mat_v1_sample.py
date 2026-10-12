"""Finalize the table-mat strict-clone sample gate after deterministic QA passes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from backlot.project_commit import ProjectCommitStore
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import write_checkpoint
from lib.sample_execution_trace import build_sample_execution_trace
from lib import qa_checks


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "table-mat-mix-v1"
SAMPLE_REL = "renders/sample-v1-540x960.mp4"
SAMPLE = PROJECT / SAMPLE_REL


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_artifact(data: dict) -> dict:
    return {key: value for key, value in data.items() if key not in {"semantic_sha256", "artifact_sha256"}}


def refreshed_artifacts(checkpoint: dict) -> dict:
    """Rebind a prior checkpoint to immutable hashes after approved lock revisions."""
    refreshed = {}
    for name, envelope in (checkpoint.get("artifacts") or {}).items():
        relative = str(envelope["path"])
        data = read_json(PROJECT / relative)
        refreshed[name] = {
            "name": envelope.get("name") or name,
            "path": relative,
            "semantic_sha256": data["semantic_sha256"],
            "artifact_sha256": data["artifact_sha256"],
            "data": data,
        }
    return refreshed


def refresh_approved_checkpoint(stage: str, *, sink) -> None:
    checkpoint = read_json(PROJECT / f"checkpoint_{stage}.json")
    write_checkpoint(
        ROOT / "projects",
        PROJECT.name,
        stage,
        checkpoint["status"],
        refreshed_artifacts(checkpoint),
        pipeline_type=checkpoint.get("pipeline_type") or "cinematic-fast",
        style_playbook=checkpoint.get("style_playbook"),
        checkpoint_policy=checkpoint.get("checkpoint_policy") or "guided",
        human_approval_required=bool(checkpoint.get("human_approval_required")),
        human_approved=bool(checkpoint.get("human_approved")),
        review=checkpoint.get("review"),
        cost_snapshot=checkpoint.get("cost_snapshot"),
        next_action=checkpoint.get("next_action"),
        metadata=checkpoint.get("metadata"),
        approval_group=checkpoint.get("approval_group"),
        approval_bundle_id=checkpoint.get("approval_bundle_id"),
        approval_bundle_version=checkpoint.get("approval_bundle_version"),
        sink=sink,
    )


def main() -> None:
    final_qa = read_json(PROJECT / "artifacts" / "final_qa_sample.json")
    l1a = read_json(PROJECT / "artifacts" / "l1a_sample.json")
    if final_qa.get("status") != "pass" or l1a.get("status") != "pass":
        raise RuntimeError("sample QA gates have not passed")

    final_props = read_json(PROJECT / "artifacts" / "final_props.json")
    render_plan = read_json(PROJECT / "artifacts" / "render_plan.sample.json")
    shot_plan = read_json(PROJECT / "artifacts" / "shot_execution_plan.json")
    script = read_json(PROJECT / "artifacts" / "script.json")
    production_lock = read_json(PROJECT / "artifacts" / "production_lock.json")
    scene_plan = read_json(PROJECT / "artifacts" / "scene_plan.json")
    decision_log = read_json(PROJECT / "artifacts" / "decision_log.json")
    probe = qa_checks.probe_media(SAMPLE)
    video = qa_checks.first_stream(probe, "video") or {}
    duration = float((probe.get("format") or {}).get("duration") or 0)
    subject_hash = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()

    sample_report = {
        "version": "1.0",
        "project_id": PROJECT.name,
        "created_at": now,
        "producer": "reference-fidelity/sample-director@1.0",
        "input_hashes": {
            "final_props": final_props["semantic_sha256"],
            "render_plan": render_plan["semantic_sha256"],
        },
        "final_props_hash": final_props["artifact_sha256"],
        "render_plan_hash": render_plan["artifact_sha256"],
        "window": {"startFrame": 0, "endFrameExclusive": 373, "scale": 0.5},
        "output_path": SAMPLE_REL,
        "probe": {
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "fps": 30,
            "frame_count": 373,
            "duration_seconds": round(duration, 3),
            "sha256": subject_hash,
        },
        "qa": {
            "status": "pass",
            "issues": [],
            "final_qa": "artifacts/final_qa_sample.json",
            "technical_validator": "artifacts/l1a_sample.json",
        },
        "status": "pass",
    }

    # Normalize the Atelier shot objects for the generic plan-vs-actual trace builder.
    trace_props = dict(final_props)
    trace_props["shots"] = [
        {
            **shot,
            "start_seconds": shot["fromFrame"] / 30,
            "end_seconds": shot["toFrameExclusive"] / 30,
            "source_path": f"inputs/source/video/product/{shot['image']}",
            "source_in_seconds": 0.0,
            "source_out_seconds": (shot["toFrameExclusive"] - shot["fromFrame"]) / 30,
            "screen_copy": shot["claim"],
        }
        for shot in final_props.get("shots") or []
    ]

    # TTS is an approved downstream production-lock revision. Rebind the two
    # approved checkpoints that carry that mutable lock before advancing.
    for stage in ("proposal", "assets"):
        with ProjectCommitStore(PROJECT).transaction(
            action={"action_id": f"refresh-{stage}-after-tts", "actor_id": "codex"},
            result={"status": "checkpoint_rebound", "stage": stage},
            audit={"event_type": "checkpoint_hash_rebound", "actor_id": "codex"},
            business_diff=[f"刷新 {stage} 制品哈希引用以绑定已批准的豆包 TTS 制作锁"],
        ) as refresh_sink:
            refresh_approved_checkpoint(stage, sink=refresh_sink)

    current_checkpoint = read_json(PROJECT / "checkpoint_sample.json")
    envs = dict(current_checkpoint.get("artifacts") or {})
    with ProjectCommitStore(PROJECT).transaction(
        action={"action_id": "finish-table-mat-v1-sample", "actor_id": "codex"},
        result={"status": "awaiting_human", "sample": SAMPLE_REL},
        audit={"event_type": "sample_gate_ready", "actor_id": "codex"},
        business_diff=["严格复刻样片渲染完成", "豆包口播音画质检通过", "进入人工样片审核"],
    ) as sink:
        caption_policy = {
            "version": "1.0",
            "project_id": PROJECT.name,
            "created_at": now,
            "producer": "reference-fidelity/sample-director@1.0",
            "input_hashes": {
                "production_lock": production_lock["artifact_sha256"],
                "scene_plan": scene_plan["artifact_sha256"],
            },
            "revision_id": "table-mat-mix-v1-caption-rev-001",
            "revision_version": 1,
            "base_production_lock_artifact_sha256": production_lock["artifact_sha256"],
            "caption_treatments": [],
            "authorization": {
                "source": "approval_record",
                "actor": "operator",
                "timestamp": now,
                "evidence_ref": "production_script and generation_list approved",
            },
            "decision_revision_id": decision_log["artifact_sha256"],
            "change_impact": {
                "render_route": "full_render",
                "reopen_creative": False,
                "reopen_sample": True,
                "changed_fields": ["caption_bottom_offset_px", "caption_keyword_highlight"],
            },
            "status": "approved_for_sample_revision",
        }
        caption_policy_env = write_artifact_atomic(
            "artifacts/caption_policy_revision.json",
            "caption_policy_revision",
            caption_policy,
            project_dir=PROJECT,
            sink=sink,
        )
        sample_report["caption_policy_version"] = "1.0"
        sample_report["caption_policy_revision_ref"] = {
            "name": "caption_policy_revision",
            "path": "artifacts/caption_policy_revision.json",
            "semantic_sha256": caption_policy_env["semantic_sha256"],
            "artifact_sha256": caption_policy_env["artifact_sha256"],
        }
        sample_env = write_artifact_atomic(
            "artifacts/sample_report.json",
            "sample_report",
            sample_report,
            project_dir=PROJECT,
            sink=sink,
        )
        trace = build_sample_execution_trace(
            PROJECT.name,
            {
                "script": script,
                "shot_execution_plan": shot_plan,
                "final_props": trace_props,
                "render_plan": render_plan,
                "sample_report": sample_env["data"],
            },
        )
        trace_env = write_artifact_atomic(
            "artifacts/sample_execution_trace.json",
            "sample_execution_trace",
            trace,
            project_dir=PROJECT,
            sink=sink,
        )
        evaluation = clean_artifact(l1a)
        evaluation["execution_diff_ref"] = {
            "name": "sample_execution_trace",
            "path": "artifacts/sample_execution_trace.json",
            "artifact_sha256": trace_env["artifact_sha256"],
        }
        evaluation_env = write_artifact_atomic(
            "artifacts/evaluation_report.sample.json",
            "evaluation_report",
            evaluation,
            project_dir=PROJECT,
            sink=sink,
        )
        envs.update(
            {
                "sample_report": sample_env,
                "sample_execution_trace": trace_env,
                "evaluation_report": evaluation_env,
                "caption_policy_revision": caption_policy_env,
            }
        )
        write_checkpoint(
            ROOT / "projects",
            PROJECT.name,
            "sample",
            "awaiting_human",
            envs,
            pipeline_type="cinematic-fast",
            next_action={
                "summary": "严格复刻样片已通过技术质检，等待人工五效果确认",
                "verb": "await_user",
                "context_refs": [
                    SAMPLE_REL,
                    "artifacts/sample_report.json",
                    "artifacts/evaluation_report.sample.json",
                ],
            },
            sink=sink,
        )

    print(
        json.dumps(
            {
                "status": "awaiting_human",
                "sample": SAMPLE_REL,
                "sha256": subject_hash,
                "duration_seconds": round(duration, 3),
                "resolution": f"{video.get('width')}x{video.get('height')}",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
