"""Narrow, auditable corrections for a failed sample render revision."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes
from lib.artifact_io import scoped_artifact_path, write_artifact_atomic
from lib.sample_preflight import validate_sample_inputs


def _persist_artifact(
    project_dir: Path, name: str, value: Mapping[str, Any], *, scope: str | None = None
) -> dict[str, Any]:
    """Write a canonical artifact with refreshed integrity hashes.

    ``repair_source_windows`` only mutates an in-memory copy; if a repair is
    actually needed the canonical artifact must be rewritten too, otherwise the
    next build hits the same constraint and the board shows stale content.
    """
    hashed = attach_hashes(dict(value))
    relative = (
        scoped_artifact_path(project_dir, name, scope).relative_to(project_dir).as_posix()
        if scope
        else f"artifacts/{name}.json"
    )
    store = ProjectCommitStore(project_dir)
    with store.transaction(
        action={"action_id": f"sample-recovery-{name}", "type": "sample_recovery"},
        result={"status": "committed", "artifact": name},
        audit={"event_type": "sample_recovery", "actor_id": "system"},
    ) as sink:
        write_artifact_atomic(
            relative, name, hashed, project_dir=project_dir, sink=sink
        )
    return hashed


def repair_source_windows(final_props: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Extend only source-window metadata that cannot cover its own scene.

    This does not alter output timing, source selection start points, or any
    audio setting. It makes the canonical source end explicit when a prior
    producer rounded it below the already-approved scene duration.
    """
    repaired = copy.deepcopy(dict(final_props))
    fps = repaired.get("fps")
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise ValueError("final_props requires a positive fps")
    scenes = repaired.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("final_props requires scenes")
    changes: list[dict[str, Any]] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("final_props scene must be an object")
        start = scene.get("fromFrame")
        end = scene.get("toFrameExclusive")
        source_in = scene.get("sourceInSeconds", 0)
        source_out = scene.get("sourceOutSeconds")
        if not all(isinstance(value, (int, float)) for value in (start, end, source_in, source_out)):
            raise ValueError("final_props scene timing must be numeric")
        required_out = round(float(source_in) + (float(end) - float(start)) / float(fps), 6)
        if float(source_out) + 1e-6 < required_out:
            scene["sourceOutSeconds"] = required_out
            changes.append({"scene_id": str(scene.get("id") or ""), "source_out_seconds": required_out})
    return repaired, changes


def build_reuse_assets_sample_input(project_dir: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Load existing artifacts and prepare a no-generation sample render input."""
    project_dir = Path(project_dir)
    artifacts = project_dir / "artifacts"
    final_props = json.loads((artifacts / "final_props.json").read_text(encoding="utf-8"))
    asset_manifest = json.loads((artifacts / "asset_manifest.json").read_text(encoding="utf-8"))
    render_plan = json.loads(
        (artifacts / "render_plan.sample.json").read_text(encoding="utf-8")
        if (artifacts / "render_plan.sample.json").exists()
        else (artifacts / "render_plan.json").read_text(encoding="utf-8")
    )
    proposal = json.loads((artifacts / "proposal_packet.json").read_text(encoding="utf-8"))
    repaired_props, changes = repair_source_windows(final_props)
    if changes:
        # Persist the repaired canonical final_props so a later build does not
        # fail the same source-window constraint. Keep render_plan's timeline
        # hash in step only when that field exists.
        repaired_props = _persist_artifact(project_dir, "final_props", repaired_props)
        if render_plan.get("final_props_hash") is not None:
            render_plan = _persist_artifact(
                project_dir, "render_plan",
                {**render_plan, "final_props_hash": repaired_props.get("semantic_sha256")},
                scope="sample" if (artifacts / "render_plan.sample.json").exists() else None,
            )
        # Artifact writes are transactional; refresh checkpoint references after
        # the generation commits so they no longer point at stale hashes.
        try:
            from lib.checkpoint import refresh_checkpoint_envelopes

            marker = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
            refresh_checkpoint_envelopes(
                project_dir.parent,
                project_dir.name,
                pipeline_type=marker.get("pipeline_type"),
            )
        except (OSError, json.JSONDecodeError, ValueError):
            # The sample input remains usable; a later checkpoint validation
            # surfaces any unresolved envelope drift explicitly.
            pass
    # P1-6: 渲染 runtime/家族须来自锁定值，而非硬编码 remotion/explainer-data。
    render_runtime = "remotion"
    renderer_family = "explainer-data"
    lock_path = artifacts / "production_lock.json"
    if lock_path.exists():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lv = lock.get("locked_values") if isinstance(lock.get("locked_values"), Mapping) else {}
            render_runtime = str(lv.get("render_runtime") or render_runtime)
        except (OSError, json.JSONDecodeError):
            pass
    proposal_path = artifacts / "proposal_packet.json"
    if proposal_path.exists():
        try:
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            pp = proposal.get("production_plan") if isinstance(proposal.get("production_plan"), Mapping) else {}
            render_runtime = str(pp.get("render_runtime") or render_runtime)
            renderer_family = str(pp.get("renderer_family") or renderer_family)
        except (OSError, json.JSONDecodeError):
            pass
    # P2/P1 修复：恢复路径必须带 scene_plan（recipe 意图）与 caption_style_fingerprint（花字）。
    # 分别读取：文件存在但解析失败 = 损坏，应显式失败；不静默吞掉并降级渲染。
    def _load_json_if_exists(name: str) -> dict[str, Any] | None:
        p = artifacts / name
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"恢复失败：{name} 损坏（{exc}），请修复后重试") from exc
        return data if isinstance(data, dict) else None

    scene_plan = _load_json_if_exists("scene_plan.json")
    csf = _load_json_if_exists("caption_style_fingerprint.json")
    script = _load_json_if_exists("script.json")
    payload = {
        "final_props": repaired_props,
        "asset_manifest": asset_manifest,
        "render_runtime": render_runtime,
        "renderer_family": renderer_family,
    }
    if isinstance(scene_plan, dict):
        payload["scene_plan"] = scene_plan
    if isinstance(csf, dict):
        payload["caption_style_fingerprint"] = csf
    if isinstance(script, dict):
        # 双层字幕：底部口播字幕轨由 script.narration 逐句派生。
        payload["script"] = script
    preflight = validate_sample_inputs({
        "shot_execution_plan": json.loads((artifacts / "shot_execution_plan.json").read_text(encoding="utf-8")),
        "final_props": repaired_props,
        "sample_report": {"window": render_plan["sample"]},
        "asset_manifest": asset_manifest,
        "sample_payload": payload,
    })
    if not preflight["ok"]:
        raise ValueError("sample preflight failed: " + "; ".join(preflight["issues"]))
    return {
        "operation": "render",
        "project_dir": str(project_dir),
        "output_path": str(project_dir / "renders" / "sample-v1.mp4"),
        "sample_payload": payload,
        "render_plan": render_plan,
        "proposal_packet": proposal,
    }, repaired_props, changes
