"""阶段 1.5 准备：把每段素材的 4 帧拼成 2x2 接触表（contact sheet），供 VLM/人工语义标注。

输入：analysis/media/<sha>/towel-2026-09-02/frames/frame_000{1..4}.jpg（2160x4096 竖幅）
输出：analysis/contact_sheets/<sha>.jpg（1080x2048）+ sheets_manifest.json

本地 ffmpeg，零付费。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
PRODUCTS = ["maojin-yinlizi", "maojin-tiansi", "maojin-chenxu", "yujin-chenxu"]
ANALYSIS_VERSION = "towel-2026-09-02"
CELL_W, CELL_H = 540, 1024  # 每帧缩放尺寸（竖幅 2160x4096 -> 540x1024）


def build_sheet(frames: list[Path], out: Path) -> bool:
    if len(frames) != 4:
        return False
    filters = []
    for i, f in enumerate(frames):
        filters.append(f"[{i}]scale={CELL_W}:{CELL_H}[v{i}]")
    filters.append("[v0][v1]hstack[top]")
    filters.append("[v2][v3]hstack[bottom]")
    filters.append("[top][bottom]vstack[out]")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for f in frames:
        cmd += ["-i", str(f)]
    cmd += ["-filter_complex", ";".join(filters), "-map", "[out]", "-frames:v", "1", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return proc.returncode == 0 and out.is_file()


def main() -> int:
    total = 0
    for pid in PRODUCTS:
        project = PROJECTS / pid
        media_root = project / "analysis" / "media"
        if not media_root.is_dir():
            print(f"[skip] {pid}: no analysis yet")
            continue
        sheets_dir = project / "analysis" / "contact_sheets"
        sheets_dir.mkdir(parents=True, exist_ok=True)
        manifest = {}
        for sha_dir in sorted(media_root.iterdir()):
            frames = sorted((sha_dir / ANALYSIS_VERSION / "frames").glob("frame_*.jpg"))
            if len(frames) != 4:
                continue
            out = sheets_dir / f"{sha_dir.name}.jpg"
            if out.is_file():
                continue
            if build_sheet(frames, out):
                record = json.loads((sha_dir / ANALYSIS_VERSION / "record.json").read_text())
                manifest[sha_dir.name] = {
                    "sheet": str(out.relative_to(project)),
                    "duration_seconds": record["entry"]["probe"].get("duration_seconds"),
                }
                total += 1
        mpath = sheets_dir / "sheets_manifest.json"
        mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{pid}] {len(manifest)} sheets -> {mpath}")
    print(f"[done] {total} contact sheets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
