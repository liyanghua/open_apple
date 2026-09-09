"""模板 run 的 post-render QA：final_qa full + L1a(sample/final) + final.mp4 交付拷贝。

像素级字幕证据（props_hash/computed_boxes）由渲染契约重派生（.remotion_props.json 是瞬态，
会被渲染器 finally 清理），帧级证据由 sample 门抽查人工确认。

用法：python -m scripts.qa_template_render --run <run>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def editorial_execution_report(project_dir: str | Path, *, revision: str,
                               timeline: dict, asset_catalogue: dict,
                               asset_manifest: dict, script_hash: str,
                               product_facts_hash: str, fact_bindings: list,
                               visual_requirements: list, kind: str = "preview") -> dict:
    """Run the server-owned editorial executor for a versioned render.

    This helper is intentionally thin: unlike the legacy template QA path it
    never accepts client QA flags or output paths and always writes under the
    immutable operator/editorial version directory.
    """
    from lib.editorial_executor import EditorialRenderExecutor
    from tools.tool_registry import registry
    registry.discover()
    executor = EditorialRenderExecutor(
        project_dir,
        video_compose=registry.get("video_compose"),
        technical_validator=registry.get("technical_validator"),
        final_qa=registry.get("final_qa"),
    )
    method = executor.render_final if kind == "final" else executor.render_preview
    return method(
        revision=revision, timeline=timeline, asset_catalogue=asset_catalogue,
        asset_manifest=asset_manifest, script_hash=script_hash,
        product_facts_hash=product_facts_hash, fact_bindings=fact_bindings,
        visual_requirements=visual_requirements, output_probe=None,
        frame_samples=None,
    )


def _load(project: Path, name: str) -> dict | None:
    f = project / "artifacts" / f"{name}.json"
    if not f.is_file():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_qa_profile(project: Path) -> tuple[str, str]:
    lock = _load(project, "production_lock") or {}
    output = (lock.get("locked_values") or {}).get("output") or {}
    profile = str(output.get("profile") or "social_vertical_1080p30")
    platform = str((lock.get("locked_values") or {}).get("platform") or "douyin")
    safe_zone = "taobao_detail_3_4" if platform == "taobao" or "3_4" in profile else "douyin_9_16"
    return profile, safe_zone


def resolve_sample_qa_profile(full_profile: str) -> str:
    """Return the matching 0.5x profile for the approved sample render."""
    mapping = {
        "social_vertical_3_4_2160p30": "social_vertical_3_4_sample_540p30",
        "social_vertical_3_4_1080p30": "social_vertical_3_4_sample_540p30",
        "social_vertical_1080p30": "social_vertical_sample_540p30",
    }
    return mapping.get(full_profile, "social_vertical_sample_540p30")


def _media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def qa(run: str) -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    project = ROOT / "projects" / run
    from lib.caption_layout import layout_captions
    from lib.sample_payload import build_sample_render_payload
    from scripts.render_template_sample import build_payload

    runtime = build_sample_render_payload(build_payload(project))
    qa_profile, safe_zone_profile = resolve_qa_profile(project)
    cues = runtime.get("narrationSubtitles") or []
    caption_contract = {
        key: runtime[key]
        for key in ("captions", "narrationSubtitles", "captionStyle", "captionRecipes",
                    "transitionRecipes", "captionWordsPerPage", "caption_render_mode",
                    "caption_source")
        if key in runtime
    }
    prop_hash = hashlib.sha256(
        json.dumps(caption_contract, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    from lib.media_profiles import get_profile
    profile_dims = get_profile(qa_profile)

    def caption_inputs(profile_name: str) -> tuple[dict, dict]:
        dims = get_profile(profile_name)
        bottom_offset = round(dims.height * 0.15625)
        boxes = layout_captions(cues, width=dims.width, height=dims.height,
                                bottom_margin=bottom_offset)
        spec = {"captions": cues, "computed_boxes": boxes, "props_hash": prop_hash}
        declaration = {"caption_render_mode": "remotion_overlay",
                       "caption_source": "script.json#sections[].narration",
                       "safe_zone_profile": safe_zone_profile,
                       "bottom_offset_px": bottom_offset}
        return spec, declaration

    caption_spec, declaration = caption_inputs(qa_profile)

    full = project / "renders/final.mp4"
    if not full.is_file():
        full = project / "renders/sample-v1.mp4"
    sample = project / "renders/sample-v1-540x960.mp4"
    if not sample.is_file():
        sample = project / "renders/sample-v1.mp4"

    from tools.tool_registry import registry

    registry.discover()
    qa_tool = registry._tools["final_qa"]
    qa_result = qa_tool.execute({
        "mode": "full",
        "input_path": str(full),
        "expected_profile": qa_profile,
        "caption_declaration": declaration,
        "caption_spec": caption_spec,
        "output_path": str(project / "artifacts/final_qa_full.json"),
    })
    qa_file = _load(project, "final_qa_full")
    if not qa_result.success or not qa_file or str(qa_file.get("status") or "") != "pass":
        raise SystemExit(
            f"{run}: final_qa 未通过（success={qa_result.success}, status="
            f"{qa_file.get('status') if qa_file else '缺失'}）——禁止交付为 final.mp4（评审 P0-3）")

    final = project / "renders/final.mp4"
    if not final.is_file():
        shutil.copy2(full, final)

    script = _load(project, "script")
    shot_plan = _load(project, "shot_execution_plan")
    final_props = _load(project, "final_props")
    text_sources, shot_map, cursor = [], [], 0.0
    for shot in sorted(shot_plan.get("shots", []), key=lambda s: s.get("order", 0)):
        text = " ".join(filter(None, [shot.get("narration") or "", shot.get("screen_copy") or ""])).strip()
        if text:
            text_sources.append({"source": "shot_copy", "shot_id": shot["id"], "text": text})
        shot_map.append({"shot_id": shot["id"], "start_s": cursor,
                         "end_s": cursor + float(shot.get("duration_seconds", 0))})
        cursor += float(shot.get("duration_seconds", 0))
    caps = final_props.get("captions") or []
    if caps:
        text_sources.append({"source": "captions", "text": " ".join(c.get("text", "") for c in caps)})

    validator = registry._tools["technical_validator"]
    common = {
        "project_id": run, "project_dir": str(project),
        "expected_profile": qa_profile,
        "expected_duration_s": float(script.get("total_duration_seconds", 0)),
        "duration_tolerance_s": 0.5,
        "text_sources": text_sources, "shot_map": shot_map,
        "caption_declaration": declaration, "caption_spec": caption_spec,
    }
    l1a_final = validator.execute({
        **common,
        "input_path": str(final), "scope": "final",
        "subject_ref": {"name": "final_video", "path": "renders/final.mp4"},
        "subject_version": "1.0", "subject_hash": _sha256(final),
        "output_path": str(project / "artifacts/l1a_final.json"),
    })
    l1a_sample = validator.execute({
        **common,
        "input_path": str(sample), "scope": "sample",
        "subject_ref": {"name": "sample_video", "path": sample.relative_to(project).as_posix()},
        "subject_version": "1.0", "subject_hash": _sha256(sample),
        "expected_profile": resolve_sample_qa_profile(qa_profile),
        "expected_duration_s": _media_duration(sample),
        "caption_declaration": caption_inputs(resolve_sample_qa_profile(qa_profile))[1],
        "caption_spec": caption_inputs(resolve_sample_qa_profile(qa_profile))[0],
        "output_path": str(project / "artifacts/l1a_sample.json"),
    })
    for label, result in (("l1a_final", l1a_final), ("l1a_sample", l1a_sample)):
        status = (result.data or {}).get("status")
        if not result.success or status != "pass":
            raise SystemExit(
                f"{run}: {label} 未通过（success={result.success}, status={status}）"
                f"——禁止进入 sample/compose 门（评审 P0-3）")

    # 交付证书（评审 P0-2）：把不可变媒体快照 + 输入/QA 制品 hash 绑定为 certified delivery version。
    from datetime import datetime, timezone

    def _file_sha(path: Path) -> str:
        import hashlib as _h

        h = _h.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    certificate = {
        "version": "1.0",
        "project_id": run,
        "certified_at": datetime.now(timezone.utc).isoformat(),
        "media": {
            "final_path": "renders/final.mp4",
            "final_sha256": _file_sha(final),
            "sample_path": sample.relative_to(project).as_posix(),
            "sample_sha256": _file_sha(sample),
        },
        "source_hashes": {
            name: _file_sha(project / "artifacts" / f"{name}.json")
            for name in ("final_props", "script", "asset_manifest", "scene_plan",
                         "edit_decisions", "render_plan")
        },
        "qa_refs": {
            "final_qa_full": _file_sha(project / "artifacts/final_qa_full.json"),
            "l1a_final": _file_sha(project / "artifacts/l1a_final.json"),
            "l1a_sample": _file_sha(project / "artifacts/l1a_sample.json"),
        },
        "gates": {"final_qa": "pass", "l1a_final": "pass", "l1a_sample": "pass"},
    }
    from lib.artifact_io import write_artifact_atomic
    from backlot.project_commit import ProjectCommitStore

    with ProjectCommitStore(project).transaction(action={"action_id": f"certify-{run}"}) as sink:
        cert_env = write_artifact_atomic("artifacts/delivery_certificate.json", "delivery_certificate",
                                         certificate, project_dir=project, sink=sink)
    return {"final_qa": qa_result.success, "l1a_final": (l1a_final.data or {}).get("status"),
            "l1a_sample": (l1a_sample.data or {}).get("status"),
            "final_qa_error": qa_result.error, "l1a_error": l1a_final.error,
            "certified": cert_env.get("artifact_sha256", "")[:12]}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="template-run-sheet-05-video5-aks-zhuodian")
    args = p.parse_args()
    print(qa(args.run))


if __name__ == "__main__":
    main()
