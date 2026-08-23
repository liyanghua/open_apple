"""Batch cockpit actions（Batch_Workbench_Interaction_Design §4.2）。

- `batch_select_for_edit`：人工选择 1–2 个候选进入精剪（候选索引 + 审计）。
- `batch_approve_gate`：批级一键通过（script/assets/sample 三个门）——
  逐候选复用 ReviewService.decide，每条批准仍落在候选自己的 review/
  decision_log（审计不合并）；幂等键与批项目事务由 ActionService 保证。

实现说明：候选各自有独立 ProjectCommitStore，跨项目无法做到单一事务整体
回滚；批动作自身幂等（同 idempotency_key 回放），逐候选原子，失败按候选
明细报告。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backlot.operator_actions import ActionService
from backlot.operator_errors import OperatorError
from backlot.operator_reviews import EFFECT_CONFIRMATION_KEYS, ReviewService
from backlot.project_commit import ProjectCommitStore
from lib.artifact_io import write_artifact_atomic
from lib.candidate_batch import select_for_edit as candidate_select

# script 门走检查点直批（ReviewService 只有 creative_lock/sample 两种 review），
# assets/sample 门复用 ReviewService.decide。
_GATE_KIND = {"assets": "creative_lock", "sample": "sample"}
_GATE_LABELS = {"script": "剧本", "assets": "素材创意", "sample": "样片效果"}


class BatchActionService:
    def __init__(self, batch_dir: Path) -> None:
        self.batch_dir = Path(batch_dir).resolve()
        self.store = ProjectCommitStore(self.batch_dir)
        self.actions = ActionService(self.batch_dir, store=self.store)

    def _read_batch(self) -> dict[str, Any]:
        path = self.batch_dir / "artifacts" / "candidate_batch.json"
        if not path.is_file():
            raise OperatorError.validation_failed("该项目不是批量项目（缺少 candidate_batch）")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise OperatorError.validation_failed("candidate_batch 内容不合法")
        return data

    def _read_decision_log(self) -> dict[str, Any]:
        path = self.batch_dir / "artifacts" / "decision_log.json"
        if not path.is_file():
            return {
                "version": "1.0",
                "project_id": self.store.project_id,
                "decisions": [],
            }
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"version": "1.0", "project_id": self.store.project_id, "decisions": []}

    # ------------------------------------------------------------------ select
    def select_for_edit(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        candidate_ids: list[str],
        reason: str,
    ) -> dict[str, Any]:
        if not candidate_ids or len(candidate_ids) > 2:
            raise OperatorError.validation_failed("请选择 1-2 个候选进入精剪")
        return self.actions.execute(
            action_type="batch_select_for_edit",
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_body={"candidate_ids": list(candidate_ids), "reason": reason},
            mutate=lambda sink: self._mutate_select(sink, candidate_ids, reason),
        )

    def _mutate_select(
        self, sink: Any, candidate_ids: list[str], reason: str
    ) -> dict[str, Any]:
        batch = self._read_batch()
        updated = candidate_select(batch, list(candidate_ids), reason=reason)
        write_artifact_atomic(
            "artifacts/candidate_batch.json",
            "candidate_batch",
            updated,
            project_dir=self.batch_dir,
            sink=sink,
        )
        log = self._read_decision_log()
        log.pop("semantic_sha256", None)
        log.pop("artifact_sha256", None)
        entry = {
            "decision_id": f"batch-select-{'-'.join(candidate_ids)}",
            "stage": "sample",
            "category": "concept_selection",
            "subject": "批量候选进入精剪",
            "options_considered": [
                {
                    "option_id": str(candidate_id),
                    "label": str(candidate_id),
                    "score": 1.0,
                    "reason": "用户选择",
                }
                for candidate_id in candidate_ids
            ],
            "selected": ",".join(candidate_ids),
            "reason": reason or "用户在驾驶舱选择进入精剪",
            "user_visible": True,
            "user_approved": True,
        }
        log["decisions"] = list(log.get("decisions") or []) + [entry]
        write_artifact_atomic(
            "artifacts/decision_log.json",
            "decision_log",
            log,
            project_dir=self.batch_dir,
            sink=sink,
        )
        return {
            "status": "committed",
            "result_revision": updated["semantic_sha256"],
            "summary": f"已选择 {len(candidate_ids)} 个候选进入精剪",
        }

    # ------------------------------------------------------------- approve-gate
    def approve_gate(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        gate: str,
        candidate_ids: list[str],
        reason: str,
    ) -> dict[str, Any]:
        if gate not in {"script", "assets", "sample"}:
            raise OperatorError.validation_failed("未知的批级门")
        return self.actions.execute(
            action_type="batch_approve_gate",
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_body={"gate": gate, "candidate_ids": list(candidate_ids), "reason": reason},
            mutate=lambda sink: self._mutate_approve(sink, gate, candidate_ids, reason, actor_id),
        )

    def _mutate_approve(
        self, sink: Any, gate: str, candidate_ids: list[str], reason: str, actor_id: str
    ) -> dict[str, Any]:
        approved: list[str] = []
        skipped: list[str] = []
        failed: list[dict[str, str]] = []
        for candidate_id in candidate_ids:
            child_dir = self.batch_dir.parent / candidate_id
            try:
                if gate == "script":
                    self._approve_script_checkpoint(child_dir, actor_id, reason)
                else:
                    self._decide_child_review(child_dir, gate, actor_id, reason)
                approved.append(candidate_id)
            except OperatorError as exc:
                if exc.code in {"review_already_decided"}:
                    skipped.append(candidate_id)
                else:
                    failed.append({"candidate_id": candidate_id, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001 — 逐候选降级
                failed.append({"candidate_id": candidate_id, "error": str(exc)})
        if failed and not approved:
            details = "; ".join(
                f"{item['candidate_id']}: {item['error']}" for item in failed[:3]
            )
            raise OperatorError.validation_failed(f"批级门审批全部失败：{details}")
        return {
            "status": "committed",
            "summary": (
                f"批级{_GATE_LABELS[gate]}审批：通过 {len(approved)}、"
                f"跳过 {len(skipped)}、失败 {len(failed)}"
            ),
        }

    @staticmethod
    def _approve_script_checkpoint(
        child_dir: Path, actor_id: str, reason: str
    ) -> None:
        """script 门：把候选的 awaiting_human script 检查点直批为 completed。"""
        import uuid as _uuid
        from datetime import datetime as _dt

        path = child_dir / "checkpoint_script.json"
        if not path.is_file():
            raise OperatorError("review_already_decided", "该候选没有待确认的剧本检查点", 409)
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        if checkpoint.get("status") != "awaiting_human":
            raise OperatorError("review_already_decided", "该内容已经完成确认", 409)
        store = ProjectCommitStore(child_dir)
        with store.transaction(
            action={
                "action_id": f"batch-script-approve-{_uuid.uuid4().hex}",
                "type": "approve_script",
                "actor_id": actor_id,
            },
            result={"status": "committed"},
            audit={"event_type": "script_approved", "actor_id": actor_id},
        ) as sink:
            updated = dict(checkpoint)
            updated.update(
                status="completed",
                human_approval_required=True,
                human_approved=True,
                timestamp=_dt.now().astimezone().isoformat(),
                next_action={
                    "verb": "run_stage",
                    "summary": "剧本已批准（批级一键通过），执行分镜阶段",
                    "context_refs": ["checkpoint_script.json"],
                    "set_at": _dt.now().astimezone().isoformat(),
                },
            )
            sink.stage_json("checkpoint_script.json", updated, schema="checkpoint")
            sink.append_event(
                "events",
                {
                    "schema_version": "1.0",
                    "run_id": f"batch-script-approve-{actor_id}",
                    "ts": updated["timestamp"],
                    "stage": "scene_plan",
                    "operation": "run_stage",
                    "status": "queued",
                    "wait_reason": "orchestrating",
                    "message": f"批级批准剧本后进入分镜阶段（{reason or '批级一键通过'}）",
                },
            )

    @staticmethod
    def _decide_child_review(
        child_dir: Path, gate: str, actor_id: str, reason: str
    ) -> None:
        kind = _GATE_KIND[gate]
        service = ReviewService(child_dir)
        pending = service.pending()
        if pending is None:
            raise OperatorError("review_already_decided", "该候选没有待确认内容", 409)
        if pending.get("kind") != kind:
            raise OperatorError("review_already_decided", "该候选的待确认内容不匹配此门", 409)
        confirmations = None
        if gate == "sample":
            confirmations = {key: "pass" for key in EFFECT_CONFIRMATION_KEYS}
        service.decide(
            review_id=str(pending["review_id"]),
            decision="approved",
            actor_id=actor_id,
            reason=reason or f"批级一键通过（{_GATE_LABELS[gate]}）",
            expected_version=int(pending.get("subject_version") or 0),
            expected_hash=str(pending.get("subject_hash") or ""),
            effect_confirmations=confirmations,
        )
