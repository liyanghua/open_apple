"""模板批量生产控制面（template_batch）builder。

43 条模板 → 43 个独立 run（每条一个 project），锁定模板包/商品事实/共享研究/
provider/model/runtime/并发/预算/发布策略。与 candidate_batch 不同：不强制"只选 1-2 条"。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

def _batch_id() -> str:
    return f"template-batch-{uuid.uuid4().hex[:12]}"


def create_template_batch(
    template_pack: Mapping[str, Any],
    *,
    product_facts_ref: Mapping[str, Any],
    template_run_plan_refs: Mapping[str, Mapping[str, Any]] | None = None,
    shared_research_refs: list[Mapping[str, Any]] | None = None,
    max_parallel: int = 2,
    max_cost_usd: float = 200.0,
    max_retries_per_run: int = 1,
    publish_policy: str = "selective",
    render_runtime: str | None = None,
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
    return {
        "version": "1.0",
        "batch_id": _batch_id(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "template_pack_ref": {"artifact_sha256": pack_hash, "version": str(template_pack.get("version") or "1.0")},
        "product_facts_ref": dict(product_facts_ref),
        "shared_research_refs": list(shared_research_refs or []),
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


def mark_pilot(batch: Mapping[str, Any], template_ids: list[str]) -> dict[str, Any]:
    """标记 pilot run（覆盖不同 archetype/treatment），返回更新后的 batch。"""
    updated = dict(batch)
    updated["pilot_run_ids"] = list(template_ids)
    return updated


def refresh_template_batch_status(
    batch: dict[str, Any],
    *,
    pipeline_dir: Path,
    pipeline_type: str = "cinematic-fast",
) -> dict[str, Any]:
    """把每个 run 的 status 从其项目 checkpoint 推进点刷新（只读投影，不写 run 项目）。

    映射（设计文档 §4.3 八态）：research→proposal 未完成/未审 = planned；
    有 proposal 且 scene_plan 在 completed = in_progress（可进入 assets）；
    有 scene_plan + 后续 sample 完成 = sampled/...；failed 由 run 的 failure 状态带出。
    这里只做"最低可观察状态"推进，避免伪造尚未发生的阶段。
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
        if "scene_plan" in completed:
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
    return updated


def refresh_template_batch_status_for_pipeline(batch: dict[str, Any], *, pipeline_dir: Path) -> dict[str, Any]:
    """便捷入口：默认 cinematic-fast 刷新。"""
    return refresh_template_batch_status(batch, pipeline_dir=pipeline_dir, pipeline_type="cinematic-fast")
