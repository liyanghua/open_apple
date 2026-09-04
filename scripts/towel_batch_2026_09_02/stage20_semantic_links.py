"""阶段 2.0：按 VLM 标注的动作域为素材建立语义符号链接（product_<产品>-<动作域>-<n>.MP4）。

产物：<project>/inputs/source/video/product/*.MP4（符号链接）+ analysis/semantic_map.json。
语义 stem 供 slot→素材绑定与 scene_plan source_path 使用。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
PRODUCTS = [
    ("maojin-yinlizi", "银离子毛巾"),
    ("maojin-tiansi", "天丝莱赛尔毛巾"),
    ("maojin-chenxu", "沉序毛巾"),
    ("yujin-chenxu", "沉序浴巾"),
]


def main() -> int:
    for pid, pname in PRODUCTS:
        project = PROJECTS / pid
        mi = json.loads((project / "artifacts" / "media_index.json").read_text(encoding="utf-8"))
        ann_dir = project / "analysis" / "annotations"
        product_dir = project / "inputs" / "source" / "video" / "product"
        product_dir.mkdir(parents=True, exist_ok=True)

        # sha → annotation；path → sha
        ann = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in ann_dir.glob("*.json")}
        domain_count: dict[str, int] = defaultdict(int)
        semantic_map = {}
        for entry in mi["entries"]:
            raw_path = Path(entry["path"]).resolve()
            sha = entry["fingerprint"]["content_sha256"]
            a = ann.get(sha, {})
            domain = str(a.get("action_domain") or "其他")
            domain_count[domain] += 1
            n = domain_count[domain]
            stem = f"product_{pname}-{domain}" + ("" if n == 1 else f"-{n}")
            link = product_dir / f"{stem}.MP4"
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(raw_path)
            semantic_map[stem] = {
                "sha": sha,
                "raw": entry["path"],
                "domain": domain,
                "subject": a.get("subject", ""),
                "shot_size": a.get("shot_size", ""),
                "camera_movement": a.get("camera_movement", ""),
                "usable": a.get("usable", "fully"),
                "quality_note": a.get("quality_note", ""),
                "text_on_screen": a.get("text_on_screen", ""),
                "duration_seconds": entry["probe"]["duration_seconds"],
            }
        out = project / "analysis" / "semantic_map.json"
        out.write_text(json.dumps(semantic_map, ensure_ascii=False, indent=1), encoding="utf-8")
        by_domain = defaultdict(list)
        for stem, meta in semantic_map.items():
            by_domain[meta["domain"]].append((stem, meta["duration_seconds"]))
        print(f"[{pid}] {len(semantic_map)} semantic links")
        for d, items in sorted(by_domain.items()):
            secs = sum(x[1] for x in items)
            print(f"   {d}: {len(items)} clips / {secs:.1f}s  {', '.join(x[0].split('-')[-1] for x in items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
