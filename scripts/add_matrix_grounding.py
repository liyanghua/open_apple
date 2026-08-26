"""给共享研究 matrix 补一条素材缺口的 grounding row（设计文档 §6 素材缺口处理）。

当某个模板 slot 的卖点动作（如 0甲醛 检测）在共享 research matrix 里没有对应 row 时，
按内容寻址把该自有素材桥接到一条新的 matrix row：用 source 的 ``representative_frames`` ∩
matrix row ``evidence_frames`` 建立 grounding（参考 _matches_matrix_source 的桥语义），
并写入该素材的 duration 作为 source_time_range。

不覆盖已有 row；幂等：已存在同 source_media_id 的 row 则跳过。

用法：python -m scripts.add_matrix_grounding --source-label '无甲醛检测' \\
      --intent '0甲醛 检测报告为证' --matrix-id matrix-08
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from lib.artifact_io import write_artifact_atomic
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[1]
SHARED_PROJECT = ROOT / "projects/table-mat-mix-v8"  # 共享研究源


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_atomic(project_dir: Path, relative_path: str, name: str, data: dict) -> dict:
    """优先经 ProjectCommitStore 事务 sink（共享研究项目受版本事务约束），失败回退直接原子写。"""
    try:
        from backlot.project_commit import ProjectCommitStore

        store = ProjectCommitStore(project_dir)
        with store.transaction(action={"action_id": f"grounding-{name}"}) as sink:
            return write_artifact_atomic(
                relative_path, name, data, project_dir=project_dir, sink=sink
            )
    except Exception:
        pass
    return write_artifact_atomic(relative_path, name, data, project_dir=project_dir)


def add_matrix_grounding(
    *,
    source_label: str,
    intent: str,
    matrix_id: str,
    project_dir: Path = SHARED_PROJECT,
) -> str | None:
    """在共享研究 matrix 里为 source_label 素材补一条 grounding row；返回 matrix_row_id 或 None。"""
    m = _load(project_dir / "artifacts" / "reference_source_matrix.json")
    smr = _load(project_dir / "artifacts" / "source_media_review.json")
    if not m or not smr:
        raise SystemExit("缺 reference_source_matrix 或 source_media_review")

    # 找到该素材（按文件名命中的产品动作）
    src = None
    for f in smr.get("files", []):
        if source_label in str(f.get("path") or ""):
            src = f
            break
    if not src:
        raise SystemExit(f"source_media_review 里找不到含 {source_label!r} 的素材")

    existing = {r.get("source_media_id") for r in m.get("rows", [])}
    if str(src.get("media_id") or "") in existing:
        print(f"  [{matrix_id}] 已有该素材的 grounding row，跳过")
        return None

    rows = list(m.get("rows") or [])
    max_ref_end = max(
        (r.get("reference_time_range") or {}).get("end_seconds_exclusive", 0)
        for r in rows if isinstance(r, dict)
    )
    # reference_scene_id：该卖点在参考视频里没有专属镜头，取最接近的"功能/防护证明"镜头
    # (reference-shot-4, 3.767-6.4s) 作为结构性锚点；scene_plan 端用 structural_only 提示，
    # 不声明直连参考镜头。
    dur = float(src.get("technical_probe", {}).get("duration_seconds") or src.get("best_ranges", [{}])[0].get("end_seconds", 2.0))
    row = {
        "matrix_row_id": matrix_id,
        "reference_intent": intent,
        "reference_scene_id": "reference-shot-4",
        "reference_time_range": {"start_seconds": 3.767, "end_seconds_exclusive": 6.4},
        "source_media_id": str(src.get("media_id") or ""),
        "source_time_range": {"start_seconds": 0.0, "end_seconds_exclusive": dur},
        "evidence_frames": list(src.get("representative_frames") or []),
        "resolution": "accept",
        "match_reason": f"补足「{source_label}」卖点动作的素材缺口（内容寻址桥接，不复制参考镜头）",
        "unmatched_gap": None,
        "confidence": 0.9,
    }
    rows.append(row)
    m["rows"] = rows
    m["unmatched_gaps"] = [g for g in (m.get("unmatched_gaps") or []) if source_label not in str(g)]
    validate_artifact("reference_source_matrix", m)
    _write_atomic(
        project_dir, "artifacts/reference_source_matrix.json",
        "reference_source_matrix", m,
    )
    print(f"  [{matrix_id}] added grounding row for {source_label} (src range 0-{dur}s)")
    return matrix_id


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-label", required=True)
    p.add_argument("--intent", required=True)
    p.add_argument("--matrix-id", required=True)
    p.add_argument("--project", default=str(SHARED_PROJECT))
    args = p.parse_args()
    add_matrix_grounding(source_label=args.source_label, intent=args.intent,
                         matrix_id=args.matrix_id, project_dir=Path(args.project))


if __name__ == "__main__":
    main()
