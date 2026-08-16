"""Atomic creative-lock and sample review state machines."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from backlot.operator_errors import OperatorError
from backlot.project_commit import ProjectCommitStore
from lib.approval_groups import approve_bundle, reject_bundle


class _Replay(Exception):
    def __init__(self, review: dict[str, Any]) -> None:
        self.review = review


class ReviewService:
    def __init__(
        self,
        project_dir: Path,
        *,
        store: ProjectCommitStore | None = None,
        reviewer_required: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.store = store or ProjectCommitStore(self.project_dir)
        self.reviewer_required = reviewer_required
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        schema_path = Path(__file__).parents[1] / "schemas/backlot/operator_review.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

    @property
    def review_dir(self) -> Path:
        return self.project_dir / "operator" / "reviews"

    def list(self) -> list[dict[str, Any]]:
        result = []
        for path in sorted(self.review_dir.glob("*.json")) if self.review_dir.exists() else []:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    def _find(self, review_id: str) -> dict[str, Any]:
        path = self.review_dir / f"{review_id}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OperatorError.validation_failed("找不到待确认内容") from exc
        if not isinstance(value, dict):
            raise OperatorError.validation_failed("待确认内容无效")
        return value

    def _validate(self, review: dict[str, Any]) -> None:
        if list(self.validator.iter_errors(review)):
            raise OperatorError.validation_failed("待确认内容不符合要求")

    def create(
        self,
        *,
        kind: str,
        subject_id: str,
        subject_version: int,
        subject_hash: str,
        submitted_by: str,
    ) -> dict[str, Any]:
        review_id = (
            f"{self.store.project_id}-{kind}-v{subject_version}-{uuid.uuid4().hex[:10]}"
        )
        review = {
            "schema_version": "1.0",
            "review_id": review_id,
            "project_id": self.store.project_id,
            "kind": kind,
            "subject_id": subject_id,
            "subject_version": subject_version,
            "subject_hash": subject_hash,
            "status": "awaiting_human",
            "submitted_by": submitted_by,
            "decided_by": None,
            "reason": None,
            "created_at": self.clock().isoformat(),
            "decided_at": None,
        }
        self._validate(review)
        with self.store.transaction(
            action={"action_id": f"create-{review_id}", "type": "create_review"},
            result={"status": "awaiting_human", "review_id": review_id},
            audit={"event_type": "review_created", "actor_id": submitted_by},
        ) as sink:
            for current in self.list():
                if current.get("kind") == kind and current.get("status") == "awaiting_human":
                    superseded = dict(current)
                    superseded.update(
                        status="superseded",
                        decided_by=submitted_by,
                        reason="已有更新版本等待确认",
                        decided_at=self.clock().isoformat(),
                    )
                    self._validate(superseded)
                    sink.stage_json(
                        f"operator/reviews/{current['review_id']}.json",
                        superseded,
                        schema="operator_review",
                    )
            sink.stage_json(
                f"operator/reviews/{review_id}.json", review, schema="operator_review"
            )
        return review

    def decide(
        self,
        *,
        review_id: str,
        decision: str,
        actor_id: str,
        reason: str,
        expected_version: int,
        expected_hash: str,
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise OperatorError.validation_failed("确认结果无效")
        initial = self._find(review_id)
        if initial.get("status") == decision:
            return initial
        if initial.get("status") != "awaiting_human":
            raise OperatorError("review_already_decided", "该内容已经完成确认", 409)
        try:
            with self.store.transaction(
                action={"action_id": f"decide-{review_id}-{decision}", "type": decision},
                result={"status": decision, "review_id": review_id},
                audit={"event_type": f"review_{decision}", "actor_id": actor_id},
            ) as sink:
                review = self._find(review_id)
                if review.get("status") == decision:
                    raise _Replay(review)
                if review.get("status") != "awaiting_human":
                    raise OperatorError("review_already_decided", "该内容已经完成确认", 409)
                if (
                    review.get("subject_version") != expected_version
                    or review.get("subject_hash") != expected_hash
                ):
                    raise OperatorError("review_stale", "待确认内容已更新，请刷新后重试", 409)
                if self.reviewer_required and review.get("submitted_by") == actor_id:
                    raise OperatorError("forbidden", "该项目要求由其他人员完成确认", 403)

                if review["kind"] == "creative_lock":
                    if decision == "approved":
                        approve_bundle(
                            self.project_dir,
                            review["subject_id"],
                            approved_by=actor_id,
                            expected_version=expected_version,
                            expected_hash=expected_hash,
                            sink=sink,
                        )
                    else:
                        reject_bundle(
                            self.project_dir,
                            review["subject_id"],
                            reason=reason,
                            expected_version=expected_version,
                            expected_hash=expected_hash,
                            sink=sink,
                        )
                stage = "assets" if review["kind"] == "creative_lock" else "sample"
                checkpoint_path = self.project_dir / f"checkpoint_{stage}.json"
                checkpoint = None
                if checkpoint_path.exists():
                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if decision == "approved" and checkpoint is not None:
                    checkpoint.update(
                        status="completed",
                        human_approval_required=True,
                        human_approved=True,
                    )
                    sink.stage_json(
                        checkpoint_path.relative_to(self.project_dir).as_posix(),
                        checkpoint,
                        schema="checkpoint",
                    )
                elif decision == "rejected" and checkpoint is not None:
                    sink.stage_json(
                        f"history/operator-{stage}-{review_id}.json",
                        checkpoint,
                        schema="checkpoint_history",
                    )
                    sink.stage_delete(
                        checkpoint_path.relative_to(self.project_dir).as_posix()
                    )
                decided = dict(review)
                decided.update(
                    status=decision,
                    decided_by=actor_id,
                    reason=reason,
                    decided_at=self.clock().isoformat(),
                )
                self._validate(decided)
                sink.stage_json(
                    f"operator/reviews/{review_id}.json",
                    decided,
                    schema="operator_review",
                )
        except _Replay as replay:
            return replay.review
        return decided

    def pending(self) -> dict[str, Any] | None:
        active = [item for item in self.list() if item.get("status") == "awaiting_human"]
        return active[-1] if active else None

