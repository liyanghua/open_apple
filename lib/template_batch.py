"""模板批量生产控制面（template_batch）builder。

43 条模板 → 43 个独立 run（每条一个 project），锁定模板包/商品事实/共享研究/
provider/model/runtime/并发/预算/发布策略。与 candidate_batch 不同：不强制"只选 1-2 条"。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib.artifact_hashing import attach_hashes, verify_hashes
from lib.artifact_io import write_artifact_atomic
from schemas.artifacts import validate_artifact

def _batch_id() -> str:
    return f"template-batch-{uuid.uuid4().hex[:12]}"


def create_template_batch(
    template_pack: Mapping[str, Any],
    *,
    product_facts_ref: Mapping[str, Any],
    batch_id: str | None = None,
    template_run_plan_refs: Mapping[str, Mapping[str, Any]] | None = None,
    shared_research_refs: list[Mapping[str, Any]] | None = None,
    max_parallel: int = 2,
    max_cost_usd: float = 200.0,
    max_retries_per_run: int = 1,
    publish_policy: str = "selective",
    render_runtime: str | None = None,
    differentiation_plan_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """由 template_pack 创建 template_batch：每条模板一个 run。

    P0：不在此创建/捏造 run plan 引用。调用方必须先为每个项目原子落盘真实的
    ``template_run_plan``，再把其 ``artifact_sha256`` 通过 ``template_run_plan_refs``
    传入；未传入的 run 其 ``template_run_plan_ref`` 为 null（plan 尚未落盘）。
    """
    if publish_policy not in {"all_qa_passed", "selective"}:
        raise ValueError(f"invalid publish_policy {publish_policy!r}")
    pack_hash = str((template_pack.get("artifact_sha256") or template_pack.get("semantic_sha256") or ""))
    runs: list[dict[str, Any]] = []
    template_run_plan_refs = template_run_plan_refs or {}
    for template in (template_pack.get("templates") or []):
        if not isinstance(template, Mapping):
            continue
        template_id = str(template.get("template_id") or "")
        if not template_id:
            continue
        run_plan_ref = template_run_plan_refs.get(template_id)
        runs.append({
            "template_id": template_id,
            "project_id": f"template-run-{template_id}",
            "template_run_plan_ref": dict(run_plan_ref) if run_plan_ref else None,
            "status": "planned",
            "cost_usd": 0.0,
            "attempts": 0,
            "failure_reason": None,
        })
    batch = {
        "version": "1.0",
        "batch_id": str(batch_id or _batch_id()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "template_pack_ref": {"artifact_sha256": pack_hash, "version": str(template_pack.get("version") or "1.0")},
        "product_facts_ref": dict(product_facts_ref),
        "shared_research_refs": list(shared_research_refs or []),
        "differentiation_plan_ref": dict(differentiation_plan_ref) if differentiation_plan_ref else None,
        "runs": runs,
        "concurrency": {"max_parallel": max(1, int(max_parallel))},
        "budget": {"max_cost_usd": max_cost_usd, "max_retries_per_run": max(0, int(max_retries_per_run))},
        "publish_policy": publish_policy,
        "pilot_run_ids": [],
        "provider": None,
        "render_runtime": render_runtime,
        "model": None,
        "decision_ref": None,
        "status": "planned",  # 未决；需人工审批后才可调度付费
        "progress": None,
        "report_ref": None,
    }
    validate_template_batch_owner(batch)
    return batch


def mark_pilot(batch: Mapping[str, Any], template_ids: list[str]) -> dict[str, Any]:
    """标记 pilot run（覆盖不同 archetype/treatment），返回更新后的 batch。"""
    updated = dict(batch)
    updated["pilot_run_ids"] = list(template_ids)
    return updated


def validate_template_batch_owner(batch: Mapping[str, Any]) -> None:
    """Ensure the batch root is the only owner of its differentiation ref."""
    ref = batch.get("differentiation_plan_ref")
    if ref is not None and not (
        isinstance(ref, Mapping) and ref.get("name") == "differentiation_plan"
        and str(ref.get("path") or "").startswith("artifacts/")
        and len(str(ref.get("artifact_sha256") or "")) == 64
    ):
        raise ValueError("template_batch has invalid differentiation_plan_ref")
    if any("differentiation_plan_ref" in run for run in batch.get("runs", []) if isinstance(run, Mapping)):
        raise ValueError("template_batch runs must consume the root ref through template_run_plan")


def persist_template_batch(project_dir: Path, batch: Mapping[str, Any], *, sink=None) -> dict[str, Any]:
    from lib.differentiation import validate_batch_plan_owner
    validate_template_batch_owner(batch)
    validate_batch_plan_owner(project_dir, batch)
    sealed = attach_hashes(dict(batch))
    validate_artifact("template_batch", sealed)
    return write_artifact_atomic("artifacts/template_batch.json", "template_batch", sealed, project_dir=project_dir, sink=sink)


def resolve_run_batch_differentiation_ref(project: Path, pipeline_dir: Path) -> tuple[str | None, Mapping[str, Any] | None]:
    """Resolve the authoritative batch-root ref declared by a canonical run marker."""
    marker_path = project / "project.json"
    try:
        import json
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    input_mode = marker.get("input_mode")
    if input_mode != "source_led_template":
        return input_mode, None
    template_run = marker.get("template_run") if isinstance(marker.get("template_run"), Mapping) else {}
    batch_project_id = str(template_run.get("batch_project_id") or "")
    if not batch_project_id:
        raise ValueError("source_led_template run missing batch_project_id for differentiation owner")
    root = pipeline_dir.resolve()
    batch_dir = (root / batch_project_id).resolve()
    try:
        batch_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("batch_project_id escapes pipeline root") from exc
    for artifact_name in ("template_batch", "candidate_batch"):
        path = batch_dir / "artifacts" / f"{artifact_name}.json"
        try:
            batch = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        validate_artifact(artifact_name, batch)
        if not verify_hashes(batch).valid:
            raise ValueError(f"{artifact_name} owner hash invalid")
        members = batch.get("runs") if artifact_name == "template_batch" else batch.get("candidates")
        if not any(
            isinstance(item, Mapping) and str(item.get("project_id") or "") == project.name
            for item in (members or [])
        ):
            raise ValueError(f"run {project.name!r} is not a member of authoritative {artifact_name}")
        ref = batch.get("differentiation_plan_ref")
        if not isinstance(ref, Mapping):
            raise ValueError(f"{artifact_name} missing differentiation_plan_ref")
        return input_mode, ref
    raise ValueError("source_led_template run cannot locate authoritative batch artifact")


def refresh_template_batch_status(
    batch: dict[str, Any],
    *,
    pipeline_dir: Path,
    pipeline_type: str = "cinematic-fast",
) -> dict[str, Any]:
    """把每个 run 的 status 从其项目 checkpoint 推进点刷新（只读投影，不写 run 项目）。

    映射（设计文档 §4.3 八态）按最新完成阶段投影。终态必须优先：
    publish → published，compose → evaluated，sample → sampled；否则才回落到
    进行中或等待审批。这样 Overview 不会把已交付的成片误显示为进行中。
    """
    from lib.checkpoint import get_completed_stages, read_checkpoint
    from pathlib import Path

    runs = list(batch.get("runs") or [])
    for r in runs:
        project_id = str(r.get("project_id") or "")
        proj = pipeline_dir / project_id
        if not (proj / "project.json").is_file():
            continue
        try:
            completed = set(get_completed_stages(pipeline_dir, project_id, pipeline_type))
        except Exception:
            completed = set()
        if "publish" in completed:
            r["status"] = "published"
        elif "compose" in completed:
            r["status"] = "evaluated"
        elif "sample" in completed:
            r["status"] = "sampled"
        elif "scene_plan" in completed:
            r["status"] = "in_progress"  # 已产出 scene_plan，可进 assets
        elif "script" in completed or "proposal" in completed:
            cp = read_checkpoint(pipeline_dir, project_id, "script")
            r["status"] = "awaiting_human" if (cp and cp.get("status") == "awaiting_human") else "in_progress"
        elif "proposal" in completed:
            r["status"] = "awaiting_human"
        else:
            r["status"] = "planned"
    updated = dict(batch)
    updated["runs"] = runs
    statuses = [str(item.get("status") or "planned") for item in runs]
    published = sum(status == "published" for status in statuses)
    failed = sum(status == "failed" for status in statuses)
    terminal = {"published", "skipped"}
    updated["progress"] = {
        "total": len(runs),
        "published": published,
        "completed": sum(status in terminal for status in statuses),
        "failed": failed,
        "in_progress": sum(status not in terminal | {"failed"} for status in statuses),
    }
    if runs and all(status in terminal for status in statuses):
        updated["status"] = "completed"
    elif failed and failed == len(runs):
        updated["status"] = "failed"
    elif any(status == "awaiting_human" for status in statuses):
        updated["status"] = "awaiting_human"
    else:
        updated["status"] = "in_progress"
    return updated


def refresh_template_batch_status_for_pipeline(batch: dict[str, Any], *, pipeline_dir: Path) -> dict[str, Any]:
    """便捷入口：默认 cinematic-fast 刷新。"""
    return refresh_template_batch_status(batch, pipeline_dir=pipeline_dir, pipeline_type="cinematic-fast")
