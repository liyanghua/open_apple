"""显式迁移：为历史项目补建门 review（修正 3 的唯一写路径之一）。

仅应在「读取路径已去写副作用」后用于存量数据迁移：
遍历 operator-managed 且当前门即将确认但缺对应 review 的项目，
调用 ensure_script/assets/sample_review_for_checkpoint()。
新项目不应依赖本脚本——写 checkpoint 的事务必须同事务创建 review。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="补建门 review（显式迁移）")
    ap.add_argument("--projects-dir", default=str(ROOT / "projects"))
    args = ap.parse_args()
    projects_root = Path(args.projects_dir)
    done = skipped = missing_after = 0
    for proj in sorted(projects_root.iterdir()):
        if not proj.is_dir() or not (proj / "operator" / "operator-managed").exists():
            continue
        checkpoint = None
        for stage, key in (("script", "checkpoint_script.json"), ("assets", "checkpoint_assets.json"),
                           ("sample", "checkpoint_sample.json")):
            path = proj / key
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("status") != "awaiting_human":
                continue
            checkpoint = (stage, path)
            break
        if checkpoint is None:
            continue
        from backlot.operator_reviews import ReviewService

        stage, _ = checkpoint
        svc = ReviewService(proj)
        fn = {"script": svc.ensure_script_review_for_checkpoint,
              "assets": svc.ensure_assets_review_for_checkpoint,
              "sample": svc.ensure_sample_review_for_checkpoint}[stage]
        try:
            created = fn()
        except Exception as exc:
            print(f"  [FAIL] {proj.name}: {exc}")
            missing_after += 1
            continue
        if created:
            done += 1
            print(f"  [{stage}] {proj.name}: review 已补建")
        else:
            skipped += 1
    print(f"迁移完成：补建 {done}，跳过 {skipped}，异常 {missing_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
