"""模板 run 的 sample 渲染：video_compose operation=render（两层字幕，主链路）。

--mode full   → renders/sample-v1.mp4（1080x1920，render_plan mode=full）
--mode quick  → render-gradient sample 层：450 帧 540x960（assets/sample/sample-<key>.mp4，
                再复制到 renders/sample-v1-540x960.mp4 供 sample 门展示）

sample_payload 携带 final_props/asset_manifest/scene_plan/caption_style_fingerprint/script，
由 build_sample_render_payload 派生 narrationSubtitles（底部口播轨）+ captionStyle（左上书法花字）。

用法：
  python -m scripts.render_template_sample --run <run> --mode full
  python -m scripts.render_template_sample --run <run> --mode quick
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = "cinematic-fast"


def _load(project: Path, name: str) -> dict:
    import json

    return json.loads((project / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))


def build_payload(project: Path) -> dict:
    pp = _load(project, "proposal_packet")
    plan = pp.get("production_plan") or pp
    return {
        "final_props": _load(project, "final_props"),
        "asset_manifest": _load(project, "asset_manifest"),
        "scene_plan": _load(project, "scene_plan"),
        "caption_style_fingerprint": _load(project, "caption_style_fingerprint"),
        "script": _load(project, "script"),
        "render_runtime": plan.get("render_runtime") or "remotion",
        "renderer_family": plan.get("renderer_family") or "product-reveal",
    }


def render(run: str, mode: str) -> dict:
    project = ROOT / "projects" / run
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.tool_registry import registry

    payload = build_payload(project)
    registry.discover()
    vc = registry._tools["video_compose"]
    if mode == "full":
        total_frames = int(payload["final_props"].get("durationInFrames") or 0)
        timeout_ms = max(300000, int(total_frames * 900))
        result = vc.execute({
            "operation": "render",
            "sample_payload": payload,
            "asset_manifest": payload["asset_manifest"],
            "output_path": str(project / "renders/sample-v1.mp4"),
            "profile": "social_vertical_1080p30",
            "project_dir": str(project),
            "remotion_timeout_ms": timeout_ms,
        })
    else:
        fp = payload["final_props"]
        total_frames = int(fp.get("durationInFrames") or 0)
        render_plan = {"mode": "sample", "profile": "tiktok",
                       "sample": {"startFrame": 0, "endFrameExclusive": 450,
                                  "scale": 0.5, "qaMode": "quick"}}
        result = vc.execute({
            "operation": "render",
            "sample_payload": payload,
            "asset_manifest": payload["asset_manifest"],
            "render_plan": render_plan,
            "project_dir": str(project),
            "remotion_timeout_ms": 900000,
        })
        if result.success:
            staged = Path((result.data or {}).get("output", ""))
            if staged.is_file():
                shutil.copy2(staged, project / "renders/sample-v1-540x960.mp4")
    return {"success": result.success, "error": result.error, "data": result.data}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="template-run-sheet-05-video5-aks-zhuodian")
    p.add_argument("--mode", choices=["full", "quick"], default="full")
    args = p.parse_args()
    r = render(args.run, args.mode)
    print(f"== {args.mode} success:", r["success"], "| error:", r["error"])
    if r["success"]:
        print("== final_review_status:", (r["data"] or {}).get("final_review_status"))


if __name__ == "__main__":
    main()
