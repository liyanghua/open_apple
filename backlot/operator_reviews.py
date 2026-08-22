"""Atomic creative-lock and sample review state machines."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator

from backlot.operator_errors import OperatorError
from backlot.operator_language import STAGE_LABELS
from backlot.project_commit import ProjectCommitStore
from lib.approval_groups import approve_bundle, reject_bundle


class _Replay(Exception):
    def __init__(self, review: dict[str, Any]) -> None:
        self.review = review


# Canonical quality issue tags (mirrors schemas/artifacts/decision_log.schema.json
# issue_tags enum). A rejection without at least one tag is rejected by the API —
# the tags are the cohort-level quality feedback data.
REVIEW_ISSUE_TAGS = frozenset({
    "unclear_promise", "unsupported_claim", "information_gap",
    "weak_hook", "slow_start", "cover_mismatch",
    "repetition", "density_spike", "dead_air", "weak_payoff",
    "identity_drift", "artifact", "hierarchy_failure", "generic_visual",
    "pronunciation", "timing", "music_masking", "loudness",
    "unsafe_text", "wrong_duration", "mobile_illegibility",
    "weak_offer", "late_cta", "ambiguous_cta", "brand_mismatch",
    "blank_frame", "crop_mismatch", "claim_rejected", "caption_overlap",
    "render_failure", "infra_sidequest",
})

EFFECT_CONFIRMATION_KEYS = (
    "creative_direction", "hook", "proof", "pacing", "readability",
)
EFFECT_CONFIRMATION_VALUES = frozenset({"pass", "adjust", "redirect"})


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

    def ensure_sample_review_for_checkpoint(self) -> dict[str, Any] | None:
        """Backfill the formal review for a legacy awaiting sample checkpoint.

        Older projects wrote the sample checkpoint and report before the
        operator review contract existed.  Keep the checkpoint authoritative,
        but create the missing review from its bound report so the UI can use
        the normal version/hash guarded approval transaction.
        """
        existing = self.pending()
        if existing is not None:
            return existing
        checkpoint_path = self.project_dir / "checkpoint_sample.json"
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(checkpoint, Mapping) or checkpoint.get("status") != "awaiting_human":
            return None

        record = (checkpoint.get("artifacts") or {}).get("sample_report")
        report: Mapping[str, Any] | None = None
        record_hash = record.get("semantic_sha256") if isinstance(record, Mapping) else None
        if isinstance(record, Mapping):
            data = record.get("data")
            report = data if isinstance(data, Mapping) else record
            report_path = record.get("path")
        elif isinstance(record, str):
            report_path = record
        else:
            report_path = None
        if report is None and isinstance(report_path, str):
            try:
                candidate = Path(report_path)
                if not candidate.is_absolute():
                    candidate = self.project_dir / candidate
                candidate.resolve().relative_to(self.project_dir.resolve())
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                loaded = None
            if isinstance(loaded, Mapping):
                report = loaded.get("data") if isinstance(loaded.get("data"), Mapping) else loaded
                record_hash = record_hash or loaded.get("semantic_sha256")
        if not isinstance(report, Mapping):
            return None
        subject_hash = record_hash or report.get("semantic_sha256")
        if not isinstance(subject_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", subject_hash):
            return None
        output_path = report.get("output_path")
        match = re.search(r"sample-v(\d+)", str(output_path or ""))
        version = int(match.group(1)) if match else 1
        subject_id = f"sample-v{version}"
        return self.create(
            kind="sample",
            subject_id=subject_id,
            subject_version=version,
            subject_hash=subject_hash,
            submitted_by="legacy-compat",
        )

    def decide(
        self,
        *,
        review_id: str,
        decision: str,
        actor_id: str,
        reason: str,
        expected_version: int,
        expected_hash: str,
        issue_tags: list[str] | None = None,
        effect_confirmations: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        initial = self._find(review_id)
        if decision not in {"approved", "rejected"}:
            raise OperatorError.validation_failed("确认结果无效")
        if decision == "rejected":
            tags = [t for t in (issue_tags or []) if isinstance(t, str)]
            if not tags or any(t not in REVIEW_ISSUE_TAGS for t in tags):
                raise OperatorError.validation_failed(
                    "拒绝必须至少选择一个结构化原因标签(issue_tags)"
                )
        if decision == "approved" and initial.get("kind") == "sample":
            confirmations = effect_confirmations if isinstance(effect_confirmations, dict) else {}
            if set(confirmations) != set(EFFECT_CONFIRMATION_KEYS) or any(
                confirmations.get(key) not in EFFECT_CONFIRMATION_VALUES
                for key in EFFECT_CONFIRMATION_KEYS
            ):
                raise OperatorError.validation_failed("请先完成创意方向、钩子、核心证明、节奏和画面可读性的效果确认")
            if any(confirmations[key] != "pass" for key in EFFECT_CONFIRMATION_KEYS):
                raise OperatorError.validation_failed("仍有需要调整或方向不对的项目，不能直接进入下一步")
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
                    # P0-3: approval atomically advances the pipeline — stage
                    # the next stage's in_progress checkpoint and the first
                    # queued orchestration run event in this same generation.
                    self._stage_next_transition(sink, review_id, stage)
                elif decision == "rejected" and checkpoint is not None:
                    sink.stage_json(
                        f"history/operator-{stage}-{review_id}.json",
                        checkpoint,
                        schema="checkpoint_history",
                    )
                    sink.stage_delete(
                        checkpoint_path.relative_to(self.project_dir).as_posix()
                    )
                    # P2-⑥ producer: a rejection is quality feedback, not a
                    # deletion. Append a tagged review_rejection decision to
                    # the canonical decision log in this same generation so
                    # cohort analytics see every rework cause.
                    self._stage_rejection_decision(
                        sink, review, stage, reason, issue_tags or []
                    )
                decided = dict(review)
                decided.update(
                    status=decision,
                    decided_by=actor_id,
                    reason=reason,
                    decided_at=self.clock().isoformat(),
                )
                if review["kind"] == "sample" and effect_confirmations:
                    decided["effect_confirmation"] = dict(effect_confirmations or {})
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

    def _pipeline_type(self) -> str | None:
        """Resolve the pipeline type from the project marker or any checkpoint."""
        marker = self.project_dir / "project.json"
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        pipeline_type = data.get("pipeline_type")
        if isinstance(pipeline_type, str) and pipeline_type and pipeline_type != "unknown":
            return pipeline_type
        for path in sorted(self.project_dir.glob("checkpoint_*.json")):
            try:
                checkpoint = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            pipeline_type = checkpoint.get("pipeline_type")
            if isinstance(pipeline_type, str) and pipeline_type and pipeline_type != "unknown":
                return pipeline_type
        return None

    def _next_stage_name(self, stage: str) -> str | None:
        """The stage immediately after ``stage`` in the pipeline's stage order."""
        stages: list[str] | None = None
        try:
            from lib.checkpoint import get_pipeline_stages

            stages = list(get_pipeline_stages(self._pipeline_type()))
        except Exception:
            stages = None
        if not stages:
            stages = [
                "research", "proposal", "idea", "script", "scene_plan",
                "assets", "edit", "compose", "publish",
            ]
        if stage not in stages:
            return None
        index = stages.index(stage)
        return stages[index + 1] if index + 1 < len(stages) else None

    def _stage_rejection_decision(
        self,
        sink: Any,
        review: dict[str, Any],
        stage: str,
        reason: str,
        issue_tags: list[str],
    ) -> None:
        """Append a tagged `review_rejection` decision to the canonical
        decision log inside the same commit generation as the rejection.

        The schema requires issue_tags (canonical enum) + rework_round for
        this category — the API already fail-closes when tags are absent, so
        this producer always writes a valid entry.
        """
        canonical = self.project_dir / "artifacts" / "decision_log.json"
        legacy = self.project_dir / "decision_log.json"
        source = canonical if canonical.exists() else (legacy if legacy.exists() else None)
        if source is not None:
            try:
                existing = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
        else:
            existing = {}
        if isinstance(existing, dict) and isinstance(existing.get("data"), dict):
            existing = existing["data"]
        if not isinstance(existing, dict):
            existing = {}
        decisions = list(existing.get("decisions") or [])
        rework_round = (
            1 + sum(
                1 for d in decisions
                if isinstance(d, dict) and d.get("category") == "review_rejection"
            )
        )
        entry = {
            "decision_id": f"reject-{review.get('review_id', '')}",
            "stage": stage,
            "category": "review_rejection",
            "subject": f"{stage} 阶段审核拒绝",
            "options_considered": [
                {
                    "option_id": "reject",
                    "label": "拒绝并要求返工",
                    "score": 0.0,
                    "reason": reason or "用户拒绝",
                }
            ],
            "selected": "reject",
            "reason": reason or "用户拒绝",
            "user_visible": True,
            "user_approved": True,
            "issue_tags": sorted(set(issue_tags)),
            "rework_round": rework_round,
        }
        merged = {
            key: value
            for key, value in existing.items()
            if key not in {"semantic_sha256", "artifact_sha256"}
        }
        merged.update(
            version=existing.get("version", "1.0"),
            project_id=existing.get("project_id", self.store.project_id),
            decisions=decisions + [entry],
        )
        from lib.artifact_io import write_artifact_atomic

        write_artifact_atomic(
            "artifacts/decision_log.json",
            "decision_log",
            merged,
            project_dir=self.project_dir,
            sink=sink,
        )

    def _stage_next_transition(
        self, sink: Any, review_id: str, stage: str
    ) -> None:
        """Stage the next stage's in_progress checkpoint + a queued run event.

        Both land in the SAME ProjectCommitStore generation as the review
        decision, so an approval atomically advances the pipeline instead of
        leaving "what happens next" to a later agent's guesswork.

        Monotonicity rule (review P1-④): the transition is staged ONLY when
        the next stage has no checkpoint yet. If one already exists — including
        a completed/awaiting_human/failed terminal checkpoint — it is left
        untouched. Approving an earlier stage must never regress a later stage
        that has already run.
        """
        next_stage = self._next_stage_name(stage)
        if not next_stage:
            return
        next_path = self.project_dir / f"checkpoint_{next_stage}.json"
        if next_path.exists():
            # Never overwrite an existing checkpoint: the pipeline is already
            # at or beyond that stage, and downgrading it (e.g. completed ->
            # in_progress) would regress state and re-run finished work.
            return
        next_checkpoint: dict[str, Any] = {
            "version": "1.0",
            "project_id": self.store.project_id,
            "pipeline_type": self._pipeline_type() or "unknown",
            "stage": next_stage,
            "artifacts": {},
        }
        label = STAGE_LABELS.get(next_stage, next_stage)
        next_checkpoint.update(
            status="in_progress",
            timestamp=self.clock().isoformat(),
            next_action={
                "verb": "run_stage",
                "summary": f"执行{label}阶段",
                "context_refs": [f"checkpoint_{stage}.json"],
                "set_at": self.clock().isoformat(),
            },
        )
        sink.stage_json(
            next_path.relative_to(self.project_dir).as_posix(),
            next_checkpoint,
            schema="checkpoint",
        )
        sink.append_event("events", {
            "schema_version": "1.0",
            "run_id": f"approval-{review_id}-{int(self.clock().timestamp())}",
            "ts": self.clock().isoformat(),
            "stage": next_stage,
            "operation": "run_stage",
            "status": "queued",
            "wait_reason": "orchestrating",
            "message": f"批准后进入{label}阶段",
        })
