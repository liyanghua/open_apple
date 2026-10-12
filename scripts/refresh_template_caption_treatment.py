"""Refresh Taobao selling-point caption props and reopen only the sample gate.

This reuses approved proxy, TTS and BGM assets. It neither calls a media
provider nor changes narration, source selections or the creative lock.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backlot.project_commit import ProjectCommitStore
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import write_checkpoint
from lib.template_caption_refresh import build_refreshed_final_props

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = "cinematic-fast"


def _load(project: Path, name: str) -> dict:
    path = project / "artifacts" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _envelope(name: str, data: dict) -> dict:
    return {
        "name": name,
        "path": f"artifacts/{name}.json",
        "semantic_sha256": data.get("semantic_sha256"),
        "artifact_sha256": data.get("artifact_sha256"),
        "data": data,
    }


def refresh(run: str, *, pipeline_dir: Path = ROOT / "projects") -> dict:
    project = pipeline_dir / run
    final_props = _load(project, "final_props")
    script = _load(project, "script")
    shot_plan = _load(project, "shot_execution_plan")
    lock = _load(project, "production_lock")
    output = (lock.get("locked_values") or {}).get("output") or {}
    profile = str(output.get("profile") or "social_vertical_1080p30")
    refreshed = build_refreshed_final_props(
        project,
        existing_final_props=final_props,
        script=script,
        shot_plan=shot_plan,
        profile=profile,
    )
    with ProjectCommitStore(project).transaction(
        action={"action_id": f"refresh-caption-treatment-{run}"}
    ) as sink:
        refreshed_env = write_artifact_atomic(
            "artifacts/final_props.json", "final_props", refreshed,
            project_dir=project, sink=sink,
        )
        for name in (
            "final_qa_sample", "l1a_sample", "sample_report",
            "sample_execution_trace", "caption_policy_revision",
            "evaluation_report.sample",
        ):
            sink.stage_delete(f"artifacts/{name}.json")
        asset_manifest = _load(project, "asset_manifest")
        render_plan = _load(project, "render_plan")
        artifacts = {
            "asset_manifest": _envelope("asset_manifest", asset_manifest),
            "final_props": refreshed_env,
            "render_plan": _envelope("render_plan", render_plan),
        }
        write_checkpoint(
            pipeline_dir, run, "sample", "in_progress", artifacts,
            pipeline_type=PIPELINE,
            next_action={
                "summary": "以现有代理、口播和 BGM 重渲淘宝 3:4 样片；花字已改为左上竖排并使用精简卖点文案，随后重跑 sample QA。",
                "verb": "resume_render",
                "context_refs": [
                    "artifacts/final_props.json", "artifacts/render_plan.json",
                    "assets/audio", "assets/music",
                ],
            },
            sink=sink,
        )
    return refreshed_env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    env = refresh(args.run)
    print(f"{args.run}: refreshed final_props {env['artifact_sha256'][:12]}")


if __name__ == "__main__":
    main()
