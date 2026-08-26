"""人工门 + A/B 对比：记录一条（--record）+ 汇总（--summarize）。

用法：
  python -m scripts.human_ab_review --template old-label new-label      # 生成待填模板
  python -m scripts.human_ab_review --record <filled.json> --project <dir>
  python -m scripts.human_ab_review --summarize --project <dir>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.human_ab import build_human_ab_template, print_summary, record_human_ab, summarize_human_ab


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--template", nargs=2, metavar=("OLD", "NEW"))
    p.add_argument("--record", metavar="JSON")
    p.add_argument("--project", default="projects/human-ab")
    p.add_argument("--summarize", action="store_true")
    args = p.parse_args()

    if args.template:
        print(json.dumps(build_human_ab_template(args.template[0], args.template[1]), ensure_ascii=False, indent=2))
    elif args.record:
        review = json.loads(Path(args.record).read_text(encoding="utf-8"))
        sealed = record_human_ab(review, args.project)
        print(f"recorded -> {args.project}/artifacts/human_ab_review.json (artifact_sha256={sealed['artifact_sha256'][:16]})")
        print(print_summary([sealed]))
    elif args.summarize:
        root = Path(args.project)
        reviews = []
        for path in sorted((root / "artifacts").glob("human_ab_review*.json")):
            try:
                reviews.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        print(print_summary(reviews))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
