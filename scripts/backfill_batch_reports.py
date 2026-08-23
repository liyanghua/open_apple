"""Backfill `batch_run_report` / `batch_quality_report` for a batch project.

Read-only: only reads candidate index, events, cost logs, checkpoints, and
scoped evaluation reports — never calls TTS/music/VLM/render tools. Writes via
the canonical artifact path with a ProjectCommitStore transaction (falling back
to a direct atomic write). Idempotent: existing reports are preserved unless
--overwrite is passed; a rebuild of identical inputs yields the same semantic
hashes.

    python scripts/backfill_batch_reports.py projects/table-mat-batch-001
    python scripts/backfill_batch_reports.py projects/table-mat-batch-001 --dry-run
    python scripts/backfill_batch_reports.py projects/table-mat-batch-001 --overwrite
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.artifact_io import write_artifact_atomic
from lib.batch_reporting import build_batch_run_report, build_batch_quality_report


def _write(batch_dir: Path, name: str, data: dict[str, Any]) -> None:
    """Write via ProjectCommitStore transaction, falling back to a direct write."""
    from lib.artifact_hashing import attach_hashes

    relative = f"artifacts/{name}.json"
    sealed = attach_hashes(data)
    try:
        from backlot.project_commit import ProjectCommitStore

        store = ProjectCommitStore(batch_dir)
        with store.transaction(action={"action_id": f"backfill-{name}", "type": "backfill"}) as sink:
            write_artifact_atomic(relative, name, sealed, project_dir=batch_dir, sink=sink)
    except Exception:
        write_artifact_atomic(relative, name, sealed, project_dir=batch_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_dir", help="批项目目录，如 projects/table-mat-batch-001")
    parser.add_argument("--dry-run", action="store_true", help="只构建并打印，不写盘")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的报告（默认保留）")
    args = parser.parse_args()

    batch_dir = Path(args.batch_dir)
    if not (batch_dir / "artifacts" / "candidate_batch.json").is_file():
        print(f"不是批项目（缺 candidate_batch）：{batch_dir}", file=sys.stderr)
        return 2

    run_report = build_batch_run_report(batch_dir)
    quality_report = build_batch_quality_report(batch_dir)

    outputs = {
        "batch_run_report.json": run_report,
        "batch_quality_report.json": quality_report,
    }

    if args.dry_run:
        for filename, report in outputs.items():
            cycle_len = len(report.get("candidate_cycles", []))
            cand_len = len(report.get("candidates", []))
            print(f"[dry-run] {filename} -> data_quality={report['data_quality']['status']} "
                  f"cycles={cycle_len} quality_candidates={cand_len}")
        print("dry-run 未写盘")
        return 0

    for filename, report in outputs.items():
        target = batch_dir / "artifacts" / filename
        if target.exists() and not args.overwrite:
            print(f"skip {filename}（已存在，用 --overwrite 覆盖）")
            continue
        _write(batch_dir, filename.removesuffix(".json"), report)
        print(f"written {filename}")

    # 幂等校验：再构建一次比对语义哈希
    import hashlib
    from lib.artifact_hashing import semantic_sha256

    rr2 = build_batch_run_report(batch_dir)
    qr2 = build_batch_quality_report(batch_dir)
    ok = (semantic_sha256(run_report) == semantic_sha256(rr2)
          and semantic_sha256(quality_report) == semantic_sha256(qr2))
    print(f"idempotency check: {'ok' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
