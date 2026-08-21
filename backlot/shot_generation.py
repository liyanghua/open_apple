"""Persisted, operator-confirmed Seedance shot-generation tasks."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from backlot.operator_errors import OperatorError
from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes, semantic_sha256
from lib.config_model import BudgetMode
from schemas.artifacts import validate_artifact
from tools.cost_tracker import CostTracker


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".shot-generation-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class ShotGenerationService:
    """Runs only proposals embedded in a locked execution plan.

    The browser contributes IDs, desired quality and an already-displayed cost
    confirmation. Prompt text and all media paths are resolved server-side.
    """

    def __init__(self, project_dir: Path, *, selector: Any | None = None, run_async: bool = True) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.run_async = run_async
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shot-generation") if run_async else None
        if selector is None:
            from tools.tool_registry import registry
            registry.ensure_discovered()
            selector = registry.get("video_selector")
        self.selector = selector

    @property
    def task_dir(self) -> Path:
        return self.project_dir / "operator" / "shot-generation" / "tasks"

    @property
    def cost_log_path(self) -> Path:
        return self.project_dir / "cost_log.json"

    def _task_path(self, task_id: str) -> Path:
        return self.task_dir / f"{task_id}.json"

    def _load_plan(self) -> dict[str, Any]:
        path = self.project_dir / "artifacts" / "shot_execution_plan.json"
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OperatorError.validation_failed("还没有可用的镜头执行单") from exc
        if not isinstance(plan, dict) or plan.get("status") != "approved":
            raise OperatorError.validation_failed("请先锁定镜头执行单，再生成预览")
        return plan

    @staticmethod
    def _find(plan: dict[str, Any], shot_id: str, proposal_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        shot = next((item for item in plan.get("shots", []) if item.get("id") == shot_id), None)
        if not isinstance(shot, dict):
            raise OperatorError.validation_failed("找不到要生成的镜头")
        proposal = next((item for item in shot.get("generation_proposals", []) if item.get("id") == proposal_id), None)
        if not isinstance(proposal, dict):
            raise OperatorError.validation_failed("找不到这个镜头的生成方案")
        return shot, proposal

    def _load_task(self, task_id: str) -> dict[str, Any]:
        try:
            task = json.loads(self._task_path(task_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OperatorError.validation_failed("找不到生成任务") from exc
        if not isinstance(task, dict):
            raise OperatorError.validation_failed("生成任务内容不正确")
        return task

    def _write_task(self, task: dict[str, Any]) -> None:
        _atomic_write(self._task_path(str(task["task_id"])), task)

    def list(self) -> list[dict[str, Any]]:
        tasks = []
        for path in sorted(self.task_dir.glob("*.json")) if self.task_dir.exists() else []:
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(task, dict):
                tasks.append(task)
        return tasks

    def get(self, task_id: str) -> dict[str, Any]:
        return self._load_task(task_id)

    def _inputs(
        self,
        proposal: dict[str, Any],
        *,
        quality: str,
        seed: int | None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if quality not in {"fast", "standard"}:
            raise OperatorError.validation_failed("只支持预览或清晰版生成")
        duration = 5 if quality == "fast" else max(4, min(15, int(proposal["duration_seconds"])))
        inputs: dict[str, Any] = {
            "prompt": proposal["prompt"],
            "preferred_provider": "seedance",
            "allowed_providers": ["seedance"],
            "operation": proposal["operation"],
            "model_variant": quality,
            "duration": str(duration),
            "aspect_ratio": proposal["aspect_ratio"],
            "resolution": "480p" if quality == "fast" else "720p",
            "generate_audio": True,
        }
        if seed is not None:
            inputs["seed"] = seed
        references = proposal.get("reference_paths") or []
        resolved_paths = []
        for relative in references:
            if not isinstance(relative, str) or not relative.startswith("inputs/source/"):
                raise OperatorError.validation_failed("生成参考只能使用项目自有素材")
            candidate = (self.project_dir / relative).resolve()
            if self.project_dir not in candidate.parents or not candidate.exists():
                raise OperatorError.validation_failed("生成参考素材不存在或不属于当前项目")
            resolved_paths.append(str(candidate))
        if inputs["operation"] == "image_to_video":
            if not resolved_paths:
                raise OperatorError.validation_failed("图生视频需要一张已确认的自有参考图")
            inputs["reference_image_path"] = resolved_paths[0]
        if inputs["operation"] == "reference_to_video":
            if not resolved_paths:
                raise OperatorError.validation_failed("参考生成需要已确认的自有参考素材")
            inputs["reference_image_paths"] = resolved_paths
        if task_id:
            inputs["output_path"] = str(
                self.project_dir / "assets" / "video" / "generated" / proposal["id"].replace("proposal-", "shot-") / f"{task_id}.mp4"
            )
        return inputs

    def quote(
        self,
        *,
        shot_id: str,
        proposal_id: str,
        quality: str,
        parent_task_id: str | None = None,
    ) -> dict[str, Any]:
        plan = self._load_plan()
        _shot, proposal = self._find(plan, shot_id, proposal_id)
        seed = None
        if quality == "standard":
            if not parent_task_id:
                raise OperatorError.validation_failed("请先选择一个可用的预览，再生成清晰版")
            parent = self._load_task(parent_task_id)
            if parent.get("status") != "completed" or parent.get("quality") != "fast" or parent.get("proposal_id") != proposal_id:
                raise OperatorError.validation_failed("清晰版必须基于同一方案的已完成预览")
            seed = parent.get("seed")
            if not isinstance(seed, int):
                raise OperatorError.validation_failed("预览没有可复用的 seed，请重新生成预览")
        inputs = self._inputs(proposal, quality=quality, seed=seed)
        estimated = round(float(self.selector.estimate_cost(inputs)), 2)
        return {
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "plan_hash": plan.get("artifact_sha256") or semantic_sha256(plan),
            "shot_id": shot_id,
            "proposal_id": proposal_id,
            "quality": quality,
            "provider": "seedance",
            "model": f"Seedance 2.0 {'Fast' if quality == 'fast' else 'Standard'}",
            "variant": quality,
            "duration_seconds": int(inputs["duration"]),
            "resolution": inputs["resolution"],
            "estimated_cost_usd": estimated,
            "evidence_risk": proposal["evidence_risk"],
            "seed": seed,
            "remaining_budget_usd": self._tracker().cost_snapshot()["budget_remaining_usd"],
        }

    def _tracker(self) -> CostTracker:
        budget = 2.0
        try:
            marker = json.loads((self.project_dir / "project.json").read_text(encoding="utf-8"))
            budget = float(marker.get("budget_total_usd", budget))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        return CostTracker(
            budget_total_usd=budget,
            mode=BudgetMode.OBSERVE,
            cost_log_path=self.cost_log_path,
        )

    def enqueue(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        shot_id: str,
        proposal_id: str,
        plan_version: int,
        quality: str,
        confirmed_estimated_cost_usd: float,
        parent_task_id: str | None = None,
    ) -> dict[str, Any]:
        request = {
            "actor_id": actor_id, "shot_id": shot_id, "proposal_id": proposal_id,
            "plan_version": plan_version, "quality": quality,
            "confirmed_estimated_cost_usd": confirmed_estimated_cost_usd,
            "parent_task_id": parent_task_id,
        }
        digest = semantic_sha256(request)
        with self._lock:
            for existing in self.list():
                if existing.get("idempotency_key") != idempotency_key:
                    continue
                if existing.get("request_digest") != digest:
                    raise OperatorError("idempotency_conflict", "这个重复提交标识已用于其他生成请求", 409)
                return existing
            quote = self.quote(
                shot_id=shot_id,
                proposal_id=proposal_id,
                quality=quality,
                parent_task_id=parent_task_id,
            )
            if quote["plan_version"] != plan_version:
                raise OperatorError.validation_failed("镜头执行单已更新，请重新查看费用")
            if abs(float(confirmed_estimated_cost_usd) - quote["estimated_cost_usd"]) > 1e-9:
                raise OperatorError.validation_failed("费用已变化，请重新确认")
            tracker = self._tracker()
            reservation_id = tracker.estimate("video_selector", "generate", quote["estimated_cost_usd"])
            tracker.approve_tool("video_selector")
            tracker.reserve(reservation_id)
            task_id = f"shotgen-{uuid.uuid4().hex}"
            task = {
                "task_id": task_id,
                "status": "queued",
                "actor_id": actor_id,
                "idempotency_key": idempotency_key,
                "request_digest": digest,
                "shot_id": shot_id,
                "proposal_id": proposal_id,
                "plan_id": quote["plan_id"],
                "plan_version": quote["plan_version"],
                "plan_hash": quote["plan_hash"],
                "quality": quality,
                "parent_task_id": parent_task_id,
                "reservation_id": reservation_id,
                "estimated_cost_usd": quote["estimated_cost_usd"],
                "actual_cost_usd": None,
                "remote_task_id": None,
                "remote_state": None,
                "seed": quote["seed"],
                "output_path": None,
                "error": None,
            }
            self._write_task(task)
            if self._executor:
                self._executor.submit(self._run, task_id)
            else:
                self._run(task_id)
            return self.get(task_id)

    def _run(self, task_id: str) -> None:
        with self._lock:
            task = self._load_task(task_id)
            if task.get("status") != "queued":
                return
            task["status"] = "generating"
            self._write_task(task)
        try:
            plan = self._load_plan()
            if plan.get("artifact_sha256") != task["plan_hash"]:
                raise ValueError("镜头执行单已变更，已取消这次生成")
            _shot, proposal = self._find(plan, task["shot_id"], task["proposal_id"])
            inputs = self._inputs(proposal, quality=task["quality"], seed=task.get("seed"), task_id=task_id)

            def record_remote(remote: dict[str, Any]) -> None:
                with self._lock:
                    current = self._load_task(task_id)
                    current["remote_task_id"] = remote.get("remote_task_id") or remote.get("request_id")
                    current["remote_state"] = {
                        key: remote[key] for key in ("status_url", "response_url") if remote.get(key)
                    }
                    self._write_task(current)

            inputs["_status_callback"] = record_remote
            result = self.selector.execute(inputs)
            with self._lock:
                current = self._load_task(task_id)
                if not result.success:
                    current.update(status="failed", error=str(result.error or "视频生成失败"), actual_cost_usd=0.0)
                    self._tracker().reconcile(current["reservation_id"], 0.0, success=False)
                else:
                    data = result.data or {}
                    current.update(
                        status="completed",
                        actual_cost_usd=float(result.cost_usd or current["estimated_cost_usd"]),
                        seed=data.get("seed") if isinstance(data.get("seed"), int) else current.get("seed"),
                        output_path=str(Path(data.get("output_path") or data.get("output")).resolve().relative_to(self.project_dir)),
                        provider=data.get("selected_provider", "seedance"),
                        model=data.get("model"),
                    )
                    self._tracker().reconcile(current["reservation_id"], current["actual_cost_usd"], success=True)
                self._write_task(current)
        except Exception as exc:
            with self._lock:
                current = self._load_task(task_id)
                current.update(status="failed", error=str(exc), actual_cost_usd=0.0)
                self._tracker().reconcile(current["reservation_id"], 0.0, success=False)
                self._write_task(current)

    def recover(self) -> None:
        for task in self.list():
            if task.get("status") == "queued":
                if self._executor:
                    self._executor.submit(self._run, task["task_id"])
                else:
                    self._run(task["task_id"])
            elif task.get("status") == "generating":
                task["status"] = "needs_confirmation"
                task["error"] = "服务重启时远端状态无法安全确认，未自动再次扣费"
                self._write_task(task)

    def adopt(self, *, actor_id: str, task_id: str) -> dict[str, Any]:
        task = self._load_task(task_id)
        if task.get("status") != "completed" or task.get("quality") != "standard":
            raise OperatorError.validation_failed("只有已完成的清晰版可以用于这个镜头")
        output_path = task.get("output_path")
        if not isinstance(output_path, str) or not output_path:
            raise OperatorError.validation_failed("生成片段没有可用文件")
        store = ProjectCommitStore(self.project_dir)
        with store.transaction(
            action={"action_id": f"adopt-{task_id}", "type": "adopt_shot_generation", "actor_id": actor_id},
            result={"status": "adopted", "task_id": task_id},
            audit={"event_type": "shot_generation_adopted", "actor_id": actor_id},
            business_diff=["已选择生成片段作为本镜头素材"],
        ) as sink:
            plan = sink.read_json("artifacts/shot_execution_plan.json")
            if not isinstance(plan, dict) or plan.get("status") != "approved":
                raise OperatorError.validation_failed("镜头执行单已变化，请重新确认后再采用")
            if plan.get("artifact_sha256") != task.get("plan_hash"):
                raise OperatorError.validation_failed("镜头执行单已变化，请重新确认后再采用")
            shot, _proposal = self._find(plan, str(task["shot_id"]), str(task["proposal_id"]))
            shot["selected_generation_task_id"] = task_id
            plan.pop("semantic_sha256", None)
            plan.pop("artifact_sha256", None)
            locked_plan = attach_hashes(plan)
            validate_artifact("shot_execution_plan", locked_plan)
            sink.stage_json("artifacts/shot_execution_plan.json", locked_plan, schema="shot_execution_plan")

            manifest = sink.read_json("artifacts/asset_manifest.json")
            if not isinstance(manifest, dict):
                manifest = {"version": "1.0", "assets": [], "total_cost_usd": 0.0}
            assets = [item for item in manifest.get("assets", []) if isinstance(item, dict)]
            assets = [item for item in assets if item.get("id") != f"generated-{task_id}"]
            assets.append({
                "id": f"generated-{task_id}",
                "type": "video",
                "path": output_path,
                "source_tool": "video_selector",
                "scene_id": str(task["shot_id"]),
                "prompt": _proposal["prompt"],
                "seed": task.get("seed"),
                "model": task.get("model") or "Seedance 2.0",
                "provider": task.get("provider") or "seedance",
                "cost_usd": float(task.get("actual_cost_usd") or 0),
                "duration_seconds": float(_proposal["duration_seconds"]),
                "resolution": "720p",
                "format": "mp4",
                "subtype": "generated_demo",
                "generation_summary": "审核台确认采用的生成演示片段",
            })
            manifest["assets"] = assets
            manifest["total_cost_usd"] = round(sum(float(item.get("cost_usd") or 0) for item in assets), 4)
            manifest.pop("semantic_sha256", None)
            manifest.pop("artifact_sha256", None)
            selected_manifest = attach_hashes(manifest)
            validate_artifact("asset_manifest", selected_manifest)
            sink.stage_json("artifacts/asset_manifest.json", selected_manifest, schema="asset_manifest")
            sink.append_event("events", {
                "event_type": "shot_generation_adopted", "task_id": task_id,
                "shot_id": task["shot_id"], "actor_id": actor_id,
            })
        return {"status": "adopted", "task_id": task_id}
