"""构建单条审批工作台的手动验收 fixture（一次性、可丢弃）。

以真实完成的候选项目 projects/table-mat-batch-002-c1 为只读模板，复制出
.backlot/review-stage/ 下的临时副本，仅改写 checkpoints 状态与 project 标识，
得到六种候选状态：
  - review-script-gate   等待确认脚本（script 门 + 待审 review）
  - review-assets-gate   等待制作准备（assets 门 + 待审 review）
  - review-sample-gate   等待样片（sample 门 + 待审 review + 样片媒体）
  - review-missing       样片门但媒体缺失（样片未生成）
  - review-failed        样片阶段失败（处理失败 + 无媒体）
  - review-completed     已完成候选（只读成片检查）

不改动 projects/ 下的真实项目与真实审批事实；fixture 目录可整体删除。

用法：
    PYTHONPATH=. .venv/bin/python scripts/backlot_review_stage.py
    OPENMONTAGE_PROJECTS_DIR=.backlot/review-stage .venv/bin/python -m backlot serve --port 4790
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.checkpoint import write_checkpoint  # noqa: E402

STAGE_DIR = ROOT / ".backlot" / "review-stage"
TEMPLATE = ROOT / "projects" / "table-mat-batch-002-c1"

GATES = {
    "review-script-gate": ("script", "等待确认脚本"),
    "review-assets-gate": ("assets", "等待制作准备"),
    "review-sample-gate": ("sample", "等待样片"),
    "review-missing": ("sample", "样片缺失"),
    "review-failed": ("sample", "样片失败"),
    "review-completed": (None, "已完成"),
}


def _copy_template(pid: str, title: str) -> Path:
    target = STAGE_DIR / pid
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(TEMPLATE, target, ignore=shutil.ignore_patterns("history"))
    operator_dir = target / "operator"
    if operator_dir.exists():
        # 构建期去掉 operator 状态（写 checkpoint 会被只读 sink 拦截）；
        # 构建完成后按官方 ReviewService 事务路径补建 review。
        shutil.rmtree(operator_dir)
    marker = json.loads((target / "project.json").read_text(encoding="utf-8"))
    marker["project_id"] = pid
    marker["title"] = title
    (target / "project.json").write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
    return target


def _stage_artifacts(target: Path, stage: str) -> dict:
    """从模板 checkpoint 取 artifact 记录，并按磁盘制品重建信封数据。

    模板项目的磁盘 artifacts/*.json 比 checkpoint 内嵌数据更新（审批写入
    了 status/title 等字段），必须用磁盘数据重建信封，否则校验失败：
    "Artifact disk data does not match embedded checkpoint data"。
    """
    cp = json.loads((target / f"checkpoint_{stage}.json").read_text(encoding="utf-8"))
    rebuilt: dict = {}
    for name, record in (cp.get("artifacts") or {}).items():
        disk_file = target / "artifacts" / f"{name}.json"
        if disk_file.exists() and isinstance(record, dict) and isinstance(record.get("data"), dict):
            try:
                data = json.loads(disk_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = None
            if isinstance(data, dict):
                rebuilt[name] = {
                    **record,
                    "data": data,
                    "semantic_sha256": data.get("semantic_sha256") or record.get("semantic_sha256"),
                    "artifact_sha256": data.get("artifact_sha256") or record.get("artifact_sha256"),
                }
                continue
        rebuilt[name] = record
    return rebuilt


def _rewrite_checkpoint(target: Path, pid: str, stage: str, status: str, artifacts: dict,
                        *, human_approved: bool = False, error: str | None = None) -> None:
    kw: dict = {"pipeline_type": "cinematic-fast", "style_playbook": "clean-professional"}
    if status in {"completed", "awaiting_human"}:
        kw["next_action"] = {
            "summary": f"等待确认 {stage} 阶段" if status == "awaiting_human" else f"{stage} 阶段已完成",
            "verb": "await_user" if status == "awaiting_human" else "run_stage",
            "context_refs": ["project.json"],
        }
    if human_approved:
        kw["human_approved"] = True
    if error:
        kw["error"] = error
    write_checkpoint(STAGE_DIR, pid, stage, status, artifacts, **kw)


def _cleanup_after(target: Path, keep_stage: str | None) -> None:
    """删除目标门之后的 checkpoint，避免后续阶段残留。"""
    order = ["research", "proposal", "script", "scene_plan", "assets", "sample",
             "edit", "compose", "publish"]
    if keep_stage is None:
        return
    idx = order.index(keep_stage)
    for stage in order[idx + 1:]:
        cp = target / f"checkpoint_{stage}.json"
        if cp.exists():
            cp.unlink()


def _strip_reviews(target: Path) -> None:
    reviews_dir = target / "operator" / "reviews"
    if reviews_dir.exists():
        for review in reviews_dir.glob("*.json"):
            review.unlink()


def build_stage() -> None:
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)
    STAGE_DIR.mkdir(parents=True)

    for pid, (gate, title) in GATES.items():
        target = _copy_template(pid, title)
        if gate is None:
            continue  # completed：保留模板原封不动的剩余 checkpoint 与 review
        _strip_reviews(target)
        for stage in ("research", "proposal", "script"):
            artifacts = _stage_artifacts(target, stage)
            _rewrite_checkpoint(target, pid, stage, "completed", artifacts, human_approved=True)
        if gate in {"assets", "sample"}:
            scene_plan = _stage_artifacts(target, "scene_plan")
            _rewrite_checkpoint(target, pid, "scene_plan", "completed", scene_plan, human_approved=True)
        if gate == "sample":
            assets = _stage_artifacts(target, "assets")
            _rewrite_checkpoint(target, pid, "assets", "completed", assets, human_approved=True)
            _rewrite_checkpoint(target, pid, "sample", "awaiting_human",
                                _stage_artifacts(target, "sample"))
            if pid == "review-missing":
                for media in (target / "renders").glob("*sample*"):
                    media.unlink()
            if pid == "review-failed":
                sample_artifacts = _stage_artifacts(target, "sample")
                (target / "checkpoint_sample.json").unlink()
                _rewrite_checkpoint(target, pid, "sample", "failed", sample_artifacts,
                                    error="样片生成超时：视频服务未在 900 秒内返回")
        elif gate == "assets":
            scene_plan = _stage_artifacts(target, "scene_plan")
            _rewrite_checkpoint(target, pid, "scene_plan", "completed", scene_plan, human_approved=True)
            _rewrite_checkpoint(target, pid, "assets", "awaiting_human",
                                _stage_artifacts(target, "assets"))
        elif gate == "script":
            _rewrite_checkpoint(target, pid, "script", "awaiting_human",
                                _stage_artifacts(target, "script"))
        _cleanup_after(target, "sample" if gate == "sample" else gate)

    # 构建完成后补 operator 标记，再走官方 review 事务补建 pending review。
    for pid in GATES:
        operator_dir = STAGE_DIR / pid / "operator"
        operator_dir.mkdir(exist_ok=True)
        (operator_dir / "operator-managed").touch()
        (operator_dir / "reviews").mkdir(exist_ok=True)


def ensure_reviews() -> None:
    from backlot.operator_reviews import ReviewService

    for pid, gate in (("review-script-gate", "script"), ("review-assets-gate", "assets"),
                      ("review-sample-gate", "sample"), ("review-missing", "sample")):
        svc = ReviewService(STAGE_DIR / pid)
        fn = {"script": svc.ensure_script_review_for_checkpoint,
              "assets": svc.ensure_assets_review_for_checkpoint,
              "sample": svc.ensure_sample_review_for_checkpoint}[gate]
        created = fn()
        print(f"  [{pid}] {gate}: {'review created' if created else 'no review'}")


if __name__ == "__main__":
    if not TEMPLATE.exists():
        print(f"模板项目不存在：{TEMPLATE}")
        raise SystemExit(1)
    build_stage()
    ensure_reviews()
    print(f"fixtures ready in {STAGE_DIR}")
