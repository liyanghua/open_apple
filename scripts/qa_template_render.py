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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def qa(run: str) -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    project = ROOT / "projects" / run
    from lib.caption_layout import layout_captions
    from lib.sample_payload import build_sample_render_payload
    from scripts.render_template_sample import build_payload

    runtime = build_sample_render_payload(build_payload(project))
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
    boxes = layout_captions(cues, width=1080, height=1920, bottom_margin=300)
    caption_spec = {"captions": cues, "computed_boxes": boxes, "props_hash": prop_hash}
    declaration = {"caption_render_mode": "remotion_overlay",
                   "caption_source": "script.json#sections[].narration",
                   "safe_zone_profile": "douyin_9_16"}

    from tools.tool_registry import registry

    registry.discover()
    qa_tool = registry._tools["final_qa"]
    qa_result = qa_tool.execute({
        "mode": "full",
        "input_path": str(project / "renders/sample-v1.mp4"),
        "expected_profile": "social_vertical_1080p30",
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
    shutil.copy2(project / "renders/sample-v1.mp4", final)

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
        "expected_profile": "social_vertical_1080p30",
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
        "input_path": str(project / "renders/sample-v1.mp4"), "scope": "sample",
        "subject_ref": {"name": "sample_video", "path": "renders/sample-v1.mp4"},
        "subject_version": "1.0", "subject_hash": _sha256(project / "renders/sample-v1.mp4"),
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
            "sample_path": "renders/sample-v1.mp4",
            "sample_sha256": _file_sha(project / "renders/sample-v1.mp4"),
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
