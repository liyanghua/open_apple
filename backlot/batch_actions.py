"""跨项目审批一致性契约（Batch_Workbench_Cross_Project_Approval_Consistency_Contract v1.0）。

协调记录：批根 `operator/batch-actions/<batch_action_id>.json`，状态机
preparing → prepared → committing → committed | rejected | needs_recovery |
replayed；参与者状态 pending → prepared → committing → committed | failed。

提交协议：逐候选原子提交（每候选一次 ProjectCommitStore 事务），提交成功即
写 commit marker；进程崩溃后 `recover_batch_action` 续跑。已提交事实不回滚
删除——无法继续时协调记录保持 needs_recovery（API 503），绝不静默覆盖。
每个候选仍保留自己的 review 与 decision_log；批级协调记录只建立关联，不合并
审计。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from backlot.operator_errors import OperatorError
from backlot.operator_reviews import EFFECT_CONFIRMATION_KEYS, ReviewService
from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import semantic_sha256
from lib.artifact_io import write_artifact_atomic
from lib.candidate_batch import select_for_edit as candidate_select

_GATE_KIND = {"script": "script_lock", "assets": "creative_lock", "sample": "sample"}
_GATE_LABELS = {"script": "剧本", "assets": "素材创意", "sample": "样片效果"}
_ACTIONS_DIR = "operator/batch-actions"

COORDINATOR_STATUSES = (
    "preparing", "prepared", "committing", "committed", "rejected",
    "rolled_back", "needs_recovery", "replayed",
)
PARTICIPANT_STATES = ("pending", "prepared", "committing", "committed", "rolled_back", "failed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _actions_dir(batch_dir: Path) -> Path:
    path = batch_dir / _ACTIONS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_record(batch_dir: Path, batch_action_id: str) -> dict[str, Any] | None:
    path = _actions_dir(batch_dir) / f"{batch_action_id}.json"
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def _save_record(batch_dir: Path, record: dict[str, Any]) -> None:
    path = _actions_dir(batch_dir) / f"{record['batch_action_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    handle, temp_path = tempfile.mkstemp(prefix=".coordinator-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(record, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def _batch_json(batch_dir: Path) -> dict[str, Any]:
    path = batch_dir / "artifacts" / "candidate_batch.json"
    if not path.is_file():
        raise OperatorError.validation_failed("该项目不是批量项目（缺少 candidate_batch）")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise OperatorError.validation_failed("candidate_batch 内容不合法")
    return data


def selection_quality_failures(
    batch: Mapping[str, Any],
    candidate: Mapping[str, Any],
    child_dir: Path,
) -> list[str]:
    """P1 质量门：候选可被选入终稿编辑室前的硬门槛。

    检查评估报告非 fatal、样本五项效果确认全 pass、字幕完整、开场对齐、候选差异度；
    返回失败列表（空表示可选）。只读候选自身制品，不脆断真实候选。
    """
    failures: list[str] = []
    child_dir = Path(child_dir)

    def _read(name: str) -> Any:
        stem = name if name.endswith(".json") else f"{name}.json"
        for path in (child_dir / "artifacts" / stem,
                     child_dir / "artifacts" / f"{name}.final.json",
                     child_dir / "artifacts" / f"{name}.sample.json"):
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return None
        return None

    # 1) 评估报告不得为 fatal fail（SKU/价格/参数/敏感词致命项）。
    er = _read("evaluation_report")
    if not isinstance(er, dict):
        failures.append("缺少评价报告，不可选入终稿")
    elif er.get("status") == "fail":
        failures.append("评估报告为 fail（fatal L1a），不可选入终稿")
    # 2) 样本五项效果确认须全部 pass（若已批准则取 review 上的确认项）。
    reviews_dir = child_dir / "operator" / "reviews"
    sample_reviews: list[dict[str, Any]] = []
    if reviews_dir.is_dir():
        for rp in sorted(reviews_dir.glob("*.json")):
            try:
                review = json.loads(rp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(review, dict) and review.get("kind") == "sample":
                sample_reviews.append(review)
    latest_sample = max(
        sample_reviews,
        key=lambda item: (str(item.get("created_at") or ""), str(item.get("review_id") or "")),
        default=None,
    )
    if latest_sample is not None:
        confirmations = latest_sample.get("effect_confirmation")
        if latest_sample.get("status") != "approved" or not isinstance(confirmations, dict) or set(confirmations) != {
            "creative_direction", "hook", "proof", "pacing", "readability"
        } or any(v != "pass" for v in confirmations.values()):
            failures.append("样本五项效果确认未全部 pass")
    else:
        failures.append("缺少样片审批记录，不可进入终稿")
    # 3) 字幕完整性：final_props.captions 非空且无空文案。
    fp = _read("final_props")
    captions = (fp.get("captions") if isinstance(fp, dict) else None) or []
    if not captions or any(not str(c.get("text") or c.get("word") or "").strip() for c in captions):
        failures.append("字幕缺失或存在空字幕项")
    # 4) 开场对齐：首镜头须有屏显文案（首镜承担钩子）。
    sep = _read("shot_execution_plan")
    shots = (sep.get("shots") if isinstance(sep, dict) else None) or []
    opening = next((s for s in shots if str(s.get("id") or "").endswith("01")), shots[0] if shots else None)
    opening_copy = ((opening or {}).get("screen_copy") or "").strip() if opening else ""
    if not opening_copy:
        failures.append("开场镜头无屏显文案（开场对齐缺失，钩子不可读）")
    # 5) 候选差异度：钩子/方向须与其它候选不同（禁止同质化候选打头）。
    hook = str((candidate.get("direction") or {}).get("hook") or "").strip()
    other_hooks = {
        str((o.get("direction") or {}).get("hook") or "").strip()
        for o in (batch.get("candidates") or [])
        if o.get("candidate_id") != candidate.get("candidate_id")
    }
    if hook and other_hooks and len({hook, *other_hooks}) == 1:
        failures.append("候选与其它候选同质化（钩子完全一致，无差异度）")
    # 6) 候选差异度：历史批次保持只读；新批次按 mode 执行硬门。
    diversity_mode = str(batch.get("diversity_mode") or "legacy_read_only")
    if diversity_mode == "legacy_read_only":
        return failures
    variant_plan = _read("candidate_variant_plan")
    if isinstance(variant_plan, dict):
        from lib.candidate_diversity import compare_candidate_pair, selection_diversity_failures
        siblings = []
        for other in (batch.get("candidates") or []):
            if not isinstance(other, Mapping) or other.get("candidate_id") == candidate.get("candidate_id"):
                continue
            other_id = str(other.get("project_id") or other.get("candidate_id") or "")
            other_plan = None
            try:
                other_dir = (child_dir.parent / other_id).resolve()
                other_dir.relative_to(child_dir.parent.resolve())
                other_path = other_dir / "artifacts" / "candidate_variant_plan.json"
            except (ValueError, OSError):
                other_path = child_dir.parent / "__invalid_candidate__" / "artifacts" / "candidate_variant_plan.json"
            try:
                other_plan = json.loads(other_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            if isinstance(other_plan, dict):
                siblings.append(other_plan)
        diversity = selection_diversity_failures(variant_plan, siblings)
        if diversity_mode == "hard_gate":
            for item in diversity["structural_failures"]:
                failures.append(f"差异度不足：{item}")
            for sibling in siblings:
                pair = compare_candidate_pair(variant_plan, sibling)
                if not pair["passes"]:
                    failures.append(f"与候选 {sibling.get('candidate_id')} 的批级差异不足")
    else:
        if diversity_mode == "hard_gate":
            failures.append("缺少候选差异计划（candidate_variant_plan），不可选入终稿")
    return failures


def _decision_log(batch_dir: Path) -> dict[str, Any]:
    path = batch_dir / "artifacts" / "decision_log.json"
    if not path.is_file():
        return {"version": "1.0", "project_id": batch_dir.name, "decisions": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"version": "1.0", "project_id": batch_dir.name, "decisions": []}


def _build_batch_approval_decision(
    child_dir: Path,
    *,
    actor_id: str,
    batch_action_id: str,
    gate: str,
    review_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """候选 decision_log 追加 batch_approval 条目（契约 §6：可互相追溯）。

    仅构建并返回 entry；实际落盘由 ``ReviewService.decide(batch_decision=...)``
    在**同一个候选生成事务**内 staged（P0-2 原子性），避免「review 已提交、
    decision_log 未提交」的半提交。
    """
    return {
        "decision_id": f"{batch_action_id}-{child_dir.name}",
        "stage": "sample" if gate == "sample" else "script" if gate == "script" else "assets",
        "category": "batch_approval",
        "subject": f"批级一键通过（{_GATE_LABELS.get(gate, gate)}）",
        "options_considered": [
            {
                "option_id": "approve",
                "label": "批级批准",
                "score": 1.0,
                "reason": "批级驾驶舱一键通过",
            }
        ],
        "selected": "approve",
        "reason": f"batch_action_id={batch_action_id}",
        "user_visible": True,
        "user_approved": True,
        "batch_action_id": batch_action_id,
        "review_snapshot": dict(review_snapshot),
    }


def _ensure_batch_approval_decision(
    child_dir: Path, entry: Mapping[str, Any], *, actor_id: str
) -> None:
    """Idempotently ensure a batch-approval decision is present in the log.

    Used only during recovery of a half-commit (review already approved but its
    decision-log audit may be missing). Appending here is a recovery-time
    compensation write; the normal path stages it atomically via
    ``ReviewService.decide(batch_decision=...)``.
    """
    from lib.artifact_hashing import attach_hashes
    from lib.artifact_io import write_artifact_atomic

    log = _decision_log(child_dir)
    log.pop("semantic_sha256", None)
    log.pop("artifact_sha256", None)
    decisions = list(log.get("decisions") or [])
    decision_id = str(entry.get("decision_id") or "")
    if any(d.get("decision_id") == decision_id for d in decisions):
        return
    decisions.append(dict(entry))
    log["decisions"] = decisions
    store = ProjectCommitStore(child_dir)
    with store.transaction(
        action={"action_id": f"batch-decision-{decision_id}", "type": "batch_approval"},
        result={"status": "committed"},
        audit={"event_type": "batch_approval_decision", "actor_id": actor_id},
    ) as sink:
        write_artifact_atomic(
            "artifacts/decision_log.json", "decision_log", attach_hashes(log),
            project_dir=child_dir, sink=sink,
        )


class BatchActionService:
    """批级跨项目动作协调器。

    `authorizer(project_id, actor_id) -> bool`：由路由注入的真实权限检查；
    缺省放行（测试用）。批根 review 权限由路由层已校验。
    """

    def __init__(
        self,
        batch_dir: Path,
        *,
        authorizer: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.batch_dir = Path(batch_dir).resolve()
        self.authorizer = authorizer or (lambda project_id, actor_id: True)
        self.store = ProjectCommitStore(self.batch_dir)

    # ------------------------------------------------------------- aggregate
    def _current_revision(self) -> tuple[str, dict[str, Any]]:
        from backlot.batch_state import build_batch_review_data

        board = {
            "_project_dir": self.batch_dir,
            "project_id": self.store.project_id,
            "title": self.store.project_id,
            "artifacts": {"candidate_batch": _batch_json(self.batch_dir)},
        }
        data = build_batch_review_data(board, board["artifacts"]["candidate_batch"])
        current = {
            view["candidate_id"]: view["child_revision"] for view in data["candidates"]
        }
        return data["aggregate_revision"], current

    def _assert_aggregate_revision(self, aggregate_revision: str) -> dict[str, Any]:
        current, revisions = self._current_revision()
        if current != str(aggregate_revision or ""):
            raise OperatorError(
                "stale",
                "批聚合状态已更新，请刷新后重试",
                409,
                details={
                    "current_revisions": revisions,
                    "current_aggregate_revision": current,
                    "retryable": True,
                },
            )
        return revisions

    # -------------------------------------------------------------- idempotency
    def _find_replay(self, key: str, digest: str) -> dict[str, Any] | None:
        """扫描协调记录：同 key+digest → 回放；同 key 异 digest → 409。"""
        for path in sorted(_actions_dir(self.batch_dir).glob("*.json")):
            record = _load_record(self.batch_dir, path.stem)
            if record is None or record.get("idempotency_key") != key:
                continue
            if record.get("request_digest") != digest:
                raise OperatorError(
                    "idempotency_conflict", "该请求标识已用于其他内容", 409,
                    details={"batch_action_id": record["batch_action_id"], "retryable": False},
                )
            result = record.get("result") or {}
            payload = dict(result)
            payload.pop("status", None)  # 重放状态必须为 replayed
            return {
                "status": "replayed",
                "batch_action_id": record["batch_action_id"],
                **payload,
            }
        return None

    # --------------------------------------------------------------- select
    def select_for_edit(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        aggregate_revision: str,
        candidate_ids: list[str],
        reason: str,
    ) -> dict[str, Any]:
        if not candidate_ids or len(candidate_ids) > 2:
            raise OperatorError.validation_failed("请选择 1-2 个候选进入精剪")
        digest_pre = semantic_sha256({
            "action_type": "batch_select_for_edit",
            "aggregate_revision": aggregate_revision,
            "candidate_ids": sorted(candidate_ids),
            "reason": reason,
            "actor_id": actor_id,
        })
        replay_pre = self._find_replay(idempotency_key, digest_pre)
        if replay_pre is not None:
            return replay_pre
        self._assert_aggregate_revision(aggregate_revision)
        batch = _batch_json(self.batch_dir)
        by_id = {str(item["candidate_id"]): item for item in batch.get("candidates", [])}
        for candidate_id in candidate_ids:
            item = by_id.get(str(candidate_id))
            if item is None or item.get("status") != "evaluated" or not item.get("evaluation_report_ref"):
                raise OperatorError.validation_failed(
                    f"候选 {candidate_id} 当前不可选（必须 evaluated 且带评价引用）"
                )
            child_dir = self.batch_dir.parent / str(item.get("project_id") or candidate_id)
            q_failures = selection_quality_failures(batch, item, child_dir)
            if q_failures:
                raise OperatorError.validation_failed(
                    f"候选 {candidate_id} 未通过质量门：" + "；".join(q_failures)
                )

        batch_action_id = f"batch-action-{uuid.uuid4().hex}"
        digest = semantic_sha256({
            "action_type": "batch_select_for_edit",
            "aggregate_revision": aggregate_revision,
            "candidate_ids": sorted(candidate_ids),
            "reason": reason,
            "actor_id": actor_id,
        })
        record = {
            "schema_version": "1.0",
            "batch_action_id": batch_action_id,
            "idempotency_key": idempotency_key,
            "request_digest": digest,
            "action_type": "batch_select_for_edit",
            "status": "preparing",
            "actor_id": actor_id,
            "aggregate_revision": aggregate_revision,
            "participants": [],
            "created_at": _now(),
            "updated_at": _now(),
            "recovery": {"required": False, "last_error": None},
        }
        # 单提交（批根）：无 child commit，prepare 即 commit。
        updated_batch = candidate_select(batch, list(candidate_ids), reason=reason)
        with self.store.transaction(
            action={"action_id": batch_action_id, "type": "batch_select_for_edit", "actor_id": actor_id,
                    "idempotency_key": idempotency_key, "request_digest": digest},
            result={"status": "committed", "batch_action_id": batch_action_id},
            audit={"event_type": "batch_select_for_edit", "actor_id": actor_id},
        ) as sink:
            write_artifact_atomic(
                "artifacts/candidate_batch.json", "candidate_batch", updated_batch,
                project_dir=self.batch_dir, sink=sink,
            )
            log = _decision_log(self.batch_dir)
            log.pop("semantic_sha256", None)
            log.pop("artifact_sha256", None)
            entry = {
                "decision_id": f"batch-select-{batch_action_id}",
                "stage": "sample",
                "category": "concept_selection",
                "subject": "批量候选进入精剪",
                "options_considered": [
                    {"option_id": str(candidate_id), "label": str(candidate_id), "score": 1.0, "reason": "用户选择"}
                    for candidate_id in candidate_ids
                ],
                "selected": ",".join(candidate_ids),
                "reason": reason or "用户在驾驶舱选择进入精剪",
                "user_visible": True,
                "user_approved": True,
            }
            log["decisions"] = list(log.get("decisions") or []) + [entry]
            write_artifact_atomic(
                "artifacts/decision_log.json", "decision_log", log,
                project_dir=self.batch_dir, sink=sink,
            )
        record["status"] = "committed"
        record["updated_at"] = _now()
        result_payload = {
            "status": "committed",
            "batch_action_id": batch_action_id,
            "result_revision": updated_batch["semantic_sha256"],
            "selected_candidate_ids": list(candidate_ids),
        }
        record["result"] = result_payload
        _save_record(self.batch_dir, record)
        try:
            from backlot.batch_events import append_event
            append_event(
                self.batch_dir, type="selection_changed",
                aggregate_revision=updated_batch["semantic_sha256"],
                phase="selection",
                payload={"selected_candidate_ids": list(candidate_ids)},
            )
        except Exception:
            pass
        return result_payload

    # ----------------------------------------------------------- approve gate
    def approve_gate(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        aggregate_revision: str,
        gate: str,
        reason: str,
        participants: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if gate not in _GATE_KIND and gate != "script":
            raise OperatorError.validation_failed("未知的批级门")
        if not participants:
            raise OperatorError.validation_failed("缺少待确认的候选")
        batch_action_id = f"batch-action-{uuid.uuid4().hex}"
        normalized = sorted(
            (dict(item) for item in participants),
            key=lambda item: str(item.get("project_id") or item.get("candidate_id")),
        )
        digest = semantic_sha256({
            "action_type": "batch_approve_gate",
            "gate": gate,
            "aggregate_revision": aggregate_revision,
            "participants": normalized,
            "reason": reason,
            "actor_id": actor_id,
        })
        replay = self._find_replay(idempotency_key, digest)
        if replay is not None:
            return replay
        self._assert_aggregate_revision(aggregate_revision)
        batch = _batch_json(self.batch_dir)
        known = {str(item["candidate_id"]) for item in batch.get("candidates", [])}
        record = {
            "schema_version": "1.0",
            "batch_action_id": batch_action_id,
            "idempotency_key": idempotency_key,
            "request_digest": digest,
            "action_type": "batch_approve_gate",
            "gate": gate,
            "reason": reason,
            "status": "preparing",
            "actor_id": actor_id,
            "aggregate_revision": aggregate_revision,
            "participants": [
                {
                    "candidate_id": str(item.get("candidate_id") or ""),
                    "project_id": str(item.get("project_id") or item.get("candidate_id") or ""),
                    "review_id": str(item.get("review_id") or ""),
                    "subject_version": int(item.get("subject_version") or 0),
                    "subject_hash": str(item.get("subject_hash") or ""),
                    "effect_confirmations": dict(item.get("effect_confirmations") or {}),
                    "state": "pending",
                    "old_generation": None,
                    "prepared_generation": None,
                    "commit_marker": None,
                    "error": None,
                }
                for item in normalized
            ],
            "created_at": _now(),
            "updated_at": _now(),
            "recovery": {"required": False, "last_error": None},
        }
        _save_record(self.batch_dir, record)

        # ---- prepare：权限 / 归属 / 快照重读校验，无用户可见事实提交 ----
        for participant in record["participants"]:
            candidate_id = participant["candidate_id"]
            project_id = participant["project_id"]
            if candidate_id not in known:
                self._reject(batch_action_id, record, f"候选 {candidate_id} 不属于该批", "validation_failed", 422)
            if not self.authorizer(project_id, actor_id):
                self._reject(batch_action_id, record, f"候选 {candidate_id} 缺少审批权限", "forbidden", 403)
            child_dir = self.batch_dir.parent / project_id
            if (child_dir / "..").resolve() != self.batch_dir.parent.resolve() or not child_dir.is_dir():
                self._reject(batch_action_id, record, f"候选项目路径不合法：{project_id}", "validation_failed", 422)
            service = ReviewService(child_dir)
            pending = service.pending()
            if pending is None and gate == "script":
                # 检查点式 script 门：确保 formal script_lock review 存在
                pending = service.ensure_script_review_for_checkpoint()
            if pending is None and gate == "assets":
                # 检查点式 assets 门：确保 formal creative_lock review 存在
                pending = service.ensure_assets_review_for_checkpoint()
            if pending is None:
                self._reject(
                    batch_action_id, record, f"候选 {candidate_id} 没有待确认内容",
                    "stale", 409,
                    current={candidate_id: None},
                )
            if pending.get("kind") != _GATE_KIND.get(gate):
                self._reject(
                    batch_action_id, record, f"候选 {candidate_id} 的待确认内容不匹配 {gate} 门",
                    "stale", 409,
                    current={candidate_id: pending.get("kind")},
                )
            # script/assets 门：客户端可传空快照（review 由检查点服务端派生）——以服务端为准回填
            if gate in {"script", "assets"} and not participant["review_id"]:
                participant["review_id"] = str(pending["review_id"])
                participant["subject_version"] = int(pending["subject_version"])
                participant["subject_hash"] = str(pending["subject_hash"])
            # 服务端重读校验，不信任请求快照
            if (
                pending.get("review_id") != participant["review_id"]
                or int(pending.get("subject_version") or 0) != participant["subject_version"]
                or str(pending.get("subject_hash") or "") != participant["subject_hash"]
            ):
                self._reject(
                    batch_action_id, record, f"候选 {candidate_id} 的审批快照已过期",
                    "stale", 409,
                    current={
                        candidate_id: {
                            "review_id": pending.get("review_id"),
                            "subject_version": pending.get("subject_version"),
                            "subject_hash": pending.get("subject_hash"),
                        }
                    },
                )
            if gate == "sample":
                confirmations = participant["effect_confirmations"]
                if (
                    set(confirmations) != set(EFFECT_CONFIRMATION_KEYS)
                    or any(confirmations.get(key) != "pass" for key in EFFECT_CONFIRMATION_KEYS)
                ):
                    self._reject(
                        batch_action_id, record, f"候选 {candidate_id} 样片五项确认必须全部 pass",
                        "validation_failed", 422,
                    )
            if gate in {"assets", "sample"}:
                # 差异度硬门：候选须有有效的 candidate_variant_plan。hard_gate 拒，warning/legacy 继续。
                diversity_mode = str(batch.get("diversity_mode") or "legacy_read_only")
                variant_plan_path = child_dir / "artifacts" / "candidate_variant_plan.json"
                variant_plan = None
                if variant_plan_path.exists():
                    try:
                        variant_plan = json.loads(variant_plan_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        variant_plan = None
                from lib.candidate_diversity import assert_candidate_variant_ready
                div_failures = assert_candidate_variant_ready(variant_plan)
                if div_failures and diversity_mode == "hard_gate":
                    self._reject(
                        batch_action_id, record,
                        f"候选 {candidate_id} 差异度硬门未通过：" + "；".join(div_failures),
                        "validation_failed", 422,
                    )
            participant["state"] = "prepared"
        record["status"] = "prepared"
        record["updated_at"] = _now()
        _save_record(self.batch_dir, record)

        # ---- commit：逐候选原子提交 + marker；失败 → needs_recovery ----
        record["status"] = "committing"
        record["updated_at"] = _now()
        _save_record(self.batch_dir, record)
        try:
            self._commit_all(batch_action_id, gate, reason, actor_id)
        except OperatorError:
            raise
        except Exception as exc:  # noqa: BLE001 — 故障注入与崩溃恢复路径
            current = _load_record(self.batch_dir, batch_action_id) or record
            current["status"] = "needs_recovery"
            current["recovery"] = {"required": True, "last_error": str(exc)}
            current["updated_at"] = _now()
            _save_record(self.batch_dir, current)
            raise OperatorError(
                "needs_recovery", "该批动作提交中断，需要恢复", 503,
                details={"batch_action_id": batch_action_id, "retryable": True},
            ) from exc

        final = _load_record(self.batch_dir, batch_action_id) or record
        committed = [p for p in final["participants"] if p["state"] == "committed"]
        final_aggregate, current_revisions = self._current_revision()
        result_payload = {
            "status": "committed",
            "batch_action_id": batch_action_id,
            "aggregate_revision": final_aggregate,
            "participants": [
                {
                    "candidate_id": p["candidate_id"],
                    "review_id": p["review_id"],
                    "status": "committed",
                    "result_revision": current_revisions.get(p["candidate_id"]),
                }
                for p in committed
            ],
        }
        final["result"] = result_payload
        _save_record(self.batch_dir, final)
        try:
            from backlot.batch_events import append_event
            append_event(
                self.batch_dir, type="gate_changed", aggregate_revision=final_aggregate,
                phase=gate, payload={"gate": gate, "candidates": [p["candidate_id"] for p in committed]},
            )
        except Exception:
            pass
        return result_payload

    def _reject(
        self,
        batch_action_id: str,
        record: dict[str, Any],
        message: str,
        code: str,
        status_code: int,
        *,
        current: dict[str, Any] | None = None,
    ) -> None:
        record["status"] = "rejected"
        record["recovery"] = {"required": False, "last_error": message}
        record["updated_at"] = _now()
        _save_record(self.batch_dir, record)
        raise OperatorError(
            code, message, status_code,
            details={
                "batch_action_id": batch_action_id,
                "participant_errors": [{"candidate_id": "prepare", "error": message}],
                "current_revisions": current,
                "retryable": code in {"stale", "validation_failed", "forbidden"},
            },
        )

    def _commit_all(self, batch_action_id: str, gate: str, reason: str, actor_id: str) -> None:
        record = _load_record(self.batch_dir, batch_action_id)
        if record is None:
            raise OperatorError("needs_recovery", "协调记录缺失", 503,
                                details={"batch_action_id": batch_action_id, "retryable": False})
        for participant in record["participants"]:
            if participant["state"] == "committed":
                continue
            candidate_id = participant["candidate_id"]
            child_dir = self.batch_dir.parent / participant["project_id"]
            service = ReviewService(child_dir)
            pending = service.pending()
            batch_decision = _build_batch_approval_decision(
                child_dir,
                actor_id=actor_id,
                batch_action_id=batch_action_id,
                gate=gate,
                review_snapshot={
                    "review_id": participant["review_id"],
                    "kind": _GATE_KIND.get(gate),
                    "subject_version": participant["subject_version"],
                    "subject_hash": participant["subject_hash"],
                },
            )
            if pending is not None and pending.get("review_id") != participant["review_id"]:
                raise OperatorError(
                    "stale", f"候选 {candidate_id} 的审批内容已变化，禁止静默覆盖", 409,
                    details={
                        "batch_action_id": batch_action_id,
                        "participant_errors": [{"candidate_id": candidate_id, "error": "review changed"}],
                        "retryable": False,
                    },
                )
            if pending is None:
                # 恢复/半提交：review 已不在 pending。区分「已 approved（幂等继续）」
                # 与「内容真的变化（stale）」，避免把已提交的候选误判为 stale。
                review = service.review_state(participant["review_id"])
                if review is None or review.get("status") != "approved":
                    raise OperatorError(
                        "stale", f"候选 {candidate_id} 的审批内容已变化，禁止静默覆盖", 409,
                        details={
                            "batch_action_id": batch_action_id,
                            "participant_errors": [{"candidate_id": candidate_id, "error": "review changed"}],
                            "retryable": False,
                        },
                    )
                # 幂等继续：补齐可能缺失的 auditor 决策（恢复期审计补偿）。
                _ensure_batch_approval_decision(child_dir, batch_decision, actor_id=actor_id)
                participant["state"] = "committed"
                participant["commit_marker"] = _now()
                record["updated_at"] = _now()
                _save_record(self.batch_dir, record)
                continue
            participant["state"] = "committing"
            record["updated_at"] = _now()
            _save_record(self.batch_dir, record)
            confirmations = None
            if gate == "sample":
                confirmations = {key: "pass" for key in EFFECT_CONFIRMATION_KEYS}
            service.decide(
                review_id=participant["review_id"],
                decision="approved",
                actor_id=actor_id,
                reason=reason or f"批级一键通过（{_GATE_LABELS.get(gate, gate)}）",
                expected_version=int(participant["subject_version"]),
                expected_hash=str(participant["subject_hash"]),
                effect_confirmations=confirmations,
                batch_decision=batch_decision,
            )
            participant["state"] = "committed"
            participant["commit_marker"] = _now()
            record["updated_at"] = _now()
            _save_record(self.batch_dir, record)
        record["status"] = "committed"
        record["updated_at"] = _now()
        _save_record(self.batch_dir, record)


def recover_batch_action(batch_dir: Path, batch_action_id: str) -> dict[str, Any]:
    """崩溃恢复：续跑未完成的提交（契约 §4.3）。

    已提交参与者不重复提交；外部修改（review 变化）→ needs_recovery，绝不
    静默覆盖。全部 marker 齐全则补写 committed。
    """
    record = _load_record(Path(batch_dir), batch_action_id)
    if record is None:
        raise OperatorError("validation_failed", "协调记录不存在", 422,
                            details={"batch_action_id": batch_action_id, "retryable": False})
    if record.get("status") == "committed":
        return {"status": "committed", "batch_action_id": batch_action_id}
    if record.get("status") not in {"prepared", "committing", "needs_recovery"}:
        raise OperatorError("validation_failed", "该记录不在可恢复状态", 422,
                            details={"batch_action_id": batch_action_id, "retryable": False})
    service = BatchActionService(Path(batch_dir))
    try:
        service._commit_all(
            batch_action_id,
            gate=str(record.get("gate") or "sample"),
            reason=record.get("reason") or "恢复续跑",
            actor_id=str(record.get("actor_id") or "recovery"),
        )
    except Exception as exc:  # noqa: BLE001
        current = _load_record(Path(batch_dir), batch_action_id) or record
        current["status"] = "needs_recovery"
        current["recovery"] = {"required": True, "last_error": str(exc)}
        current["updated_at"] = _now()
        _save_record(Path(batch_dir), current)
        raise OperatorError(
            "needs_recovery", "恢复未能完成，需人工介入", 503,
            details={"batch_action_id": batch_action_id, "retryable": True},
        ) from exc
    try:
        from backlot.batch_events import append_event
        append_event(
            Path(batch_dir), type="action_recovered", aggregate_revision=record.get("aggregate_revision") or "0" * 64,
            payload={"batch_action_id": batch_action_id},
        )
    except Exception:
        pass
    current = _load_record(Path(batch_dir), batch_action_id) or record
    try:
        aggregate, revisions = service._current_revision()
    except Exception:
        aggregate, revisions = str(current.get("aggregate_revision") or ""), {}
    committed = [p for p in current.get("participants", []) if p.get("state") == "committed"]
    result = {
        "status": "committed",
        "batch_action_id": batch_action_id,
        "aggregate_revision": aggregate,
        "participants": [
            {
                "candidate_id": p.get("candidate_id"),
                "review_id": p.get("review_id"),
                "status": "committed",
                "result_revision": revisions.get(p.get("candidate_id")),
            }
            for p in committed
        ],
    }
    current["result"] = result
    _save_record(Path(batch_dir), current)
    return result
