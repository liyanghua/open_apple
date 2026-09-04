"""毛巾批量混剪 2026-09-02 — 阶段 1：素材接入 + 规范媒体分析（本地，零付费调用）。

对 4 个产品目录执行：
  - init_project 建研究根项目（cinematic-fast）
  - 符号链接接入原始素材到 inputs/source/video/raw/（不复制 4K 源片，省磁盘）
  - build_media_index：ffprobe + scene_detect + 每片 4 帧，落 analysis/media/<sha>/towel-2026-09-02/
  - review_source_media：规范 source_media_review 制品（禁用转写：源片为现场环境音，不需 ASR）

Agent 仍是创作者；本脚本只负责按 canonical 构建器落盘分析产物。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import init_project
from lib.media_index import build_media_index
from lib.source_media_review import review_source_media
from tools.tool_registry import registry

SOURCE_ROOT = Path("/Users/yichen/Desktop/抖音短视频/花花公子视频集合/2026_09_02_银离子毛巾")
ANALYSIS_VERSION = "towel-2026-09-02"

PRODUCTS = [
    {"id": "maojin-yinlizi", "title": "银离子毛巾 素材研究", "dir": "银离子毛巾"},
    {"id": "maojin-tiansi", "title": "天丝莱赛尔毛巾 素材研究", "dir": "天丝莱赛尔毛巾"},
    {"id": "maojin-chenxu", "title": "沉序毛巾 素材研究", "dir": "沉序毛巾"},
    {"id": "yujin-chenxu", "title": "沉序浴巾 素材研究", "dir": "沉序浴巾"},
]


class _NoTranscribeRegistry:
    """绕过转写（现场环境音无需 ASR），其余工具照常。"""

    def __init__(self, real):
        self._real = real

    def get(self, name):
        if name == "transcriber":
            return None
        return self._real.get(name)

    def __getattr__(self, item):
        return getattr(self._real, item)


def link_raw_media(project_dir: Path, source_dir: Path) -> list[Path]:
    raw_dir = project_dir / "inputs" / "source" / "video" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    links: list[Path] = []
    for src in sorted(source_dir.glob("*.MP4")):
        dst = raw_dir / src.name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
        links.append(dst)
    return links


def main() -> int:
    registry.discover()
    print(f"[registry] analysis tools discovered: "
          f"{sum(1 for c in registry.provider_menu_summary()['capabilities'] if c['capability']=='analysis')} families")
    for product in PRODUCTS:
        source_dir = SOURCE_ROOT / product["dir"]
        if not source_dir.is_dir():
            print(f"[skip] {product['id']}: source dir missing {source_dir}")
            continue
        project_dir = init_project(
            product["id"], title=product["title"], pipeline_type="cinematic-fast",
            input_mode="source_led_template",
            template_prior={"present": True, "usage": "structural_only"},
            owned_source_root="inputs/source",
        )
        links = link_raw_media(project_dir, source_dir)
        print(f"[{product['id']}] linked {len(links)} clips -> {project_dir}")

        data = build_media_index(
            links,
            project_dir=project_dir,
            registry=registry,
            analysis_version=ANALYSIS_VERSION,
        )
        entries = data.get("entries", [])
        bad = [e for e in entries if e.get("quality_risks")]
        print(f"[{product['id']}] media_index: {len(entries)} entries, "
              f"{len(bad)} with quality_risks")

        smr = review_source_media(
            links,
            context={"pipeline_type": "cinematic-fast", "project_dir": str(project_dir)},
            tool_registry=_NoTranscribeRegistry(registry),
            media_index=data,
        )
        write_artifact_atomic(
            "artifacts/source_media_review.json",
            "source_media_review",
            smr,
            project_dir=project_dir,
        )
        print(f"[{product['id']}] source_media_review: {len(smr.get('files', []))} files reviewed")
    print("[done] stage 1 analysis complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
