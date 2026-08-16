"""Deterministic read-only migration from legacy cinematic projects."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backlot.auth_store import AuthStore
from backlot.project_creation import ProjectCreationService
from lib.approval_groups import build_approval_bundle
from lib.artifact_hashing import semantic_sha256
from lib.artifact_io import write_artifact_atomic
from lib.production_lock import build_production_lock


def _load_artifact(source: Path, name: str) -> dict[str, Any] | None:
    path = source / "artifacts" / f"{name}.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(value, dict) and isinstance(value.get("data"), dict):
        value = value["data"]
    return value if isinstance(value, dict) else None


def _clean_for_project(value: dict[str, Any], project_id: str) -> dict[str, Any]:
    cleaned = dict(value)
    if "project_id" in cleaned:
        cleaned["project_id"] = project_id
    for field in ("semantic_sha256", "artifact_sha256"):
        cleaned.pop(field, None)
    return cleaned


class OperatorMigrationService:
    MIGRATION_VERSION = "operator-m2-v1"

    def __init__(self, projects_dir: Path, auth_store: AuthStore) -> None:
        self.projects_dir = Path(projects_dir).resolve()
        self.creation = ProjectCreationService(self.projects_dir, auth_store)

    def migrate(
        self,
        *,
        source_project_id: str,
        target_project_id: str,
        owner_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        source = self.projects_dir / source_project_id
        marker = json.loads((source / "project.json").read_text(encoding="utf-8"))
        if marker.get("pipeline_type") != "cinematic":
            raise ValueError("Only legacy cinematic projects can be migrated")

        def initialize(target: Path) -> None:
            now = datetime.now(timezone.utc).isoformat()
            project_marker = {
                "project_id": target_project_id,
                "title": str(marker.get("title") or target_project_id),
                "pipeline_type": "cinematic-fast",
                "parent_project_id": source_project_id,
                "parent_pipeline_type": "cinematic",
                "migration_version": self.MIGRATION_VERSION,
                "legacy_deliverable": {
                    "source_project_id": source_project_id,
                    "available": (source / "renders/final.mp4").exists(),
                },
            }
            (target / "project.json").parent.mkdir(parents=True, exist_ok=True)
            (target / "project.json").write_text(
                json.dumps(project_marker, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            envelopes: dict[str, dict[str, Any]] = {}
            copied: set[str] = set()
            stage_artifacts = {
                "research": ("research_brief", "video_analysis_brief", "source_media_review"),
                "proposal": ("proposal_packet",),
                "script": ("script",),
                "scene_plan": ("scene_plan",),
            }
            continuity = True
            for stage, names in stage_artifacts.items():
                stage_written = False
                if continuity:
                    for name in names:
                        value = _load_artifact(source, name)
                        if value is None:
                            continue
                        try:
                            envelope = write_artifact_atomic(
                                f"artifacts/{name}.json",
                                name,
                                _clean_for_project(value, target_project_id),
                                project_dir=target,
                            )
                        except Exception:
                            continue
                        envelopes[name] = envelope
                        copied.add(name)
                        stage_written = True
                required = names[0]
                continuity = continuity and required in copied
                if continuity and stage_written:
                    (target / f"checkpoint_{stage}.json").write_text(
                        json.dumps(
                            {
                                "version": "1.0", "project_id": target_project_id,
                                "pipeline_type": "cinematic-fast", "stage": stage,
                                "status": "completed", "timestamp": now,
                                "checkpoint_policy": "guided",
                                "human_approval_required": False, "human_approved": False,
                                "artifacts": {name: envelopes[name] for name in names if name in envelopes},
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )

            old_decisions = _load_artifact(source, "decision_log") or {
                "version": "1.0", "project_id": target_project_id, "decisions": []
            }
            decisions = list(old_decisions.get("decisions", []))
            decisions.append(
                {
                    "decision_id": f"migration-{uuid.uuid4().hex}",
                    "stage": "proposal", "category": "pipeline_selection",
                    "subject": "创建快线运营副本",
                    "options_considered": [
                        {"option_id": "fork", "label": "创建独立副本", "score": 1, "reason": "保留旧项目只读"}
                    ],
                    "selected": "fork", "reason": "运营编辑需要独立版本历史",
                    "user_visible": True, "user_approved": True,
                }
            )
            decision_envelope = write_artifact_atomic(
                "artifacts/decision_log.json", "decision_log",
                {"version": "1.0", "project_id": target_project_id, "decisions": decisions},
                project_dir=target,
            )
            envelopes["decision_log"] = decision_envelope

            source_manifest = _load_artifact(source, "asset_manifest") or {"assets": []}
            planned = []
            for index, asset in enumerate(source_manifest.get("assets", [])):
                if not isinstance(asset, dict):
                    continue
                planned.append(
                    {
                        "id": str(asset.get("id") or f"candidate-{index + 1}"),
                        "type": str(asset.get("type") or "media"),
                        "provider": "reuse_only", "model": "existing-source",
                        "cost_estimate_usd": 0, "paid": False,
                        "output_path": str(asset.get("path") or f"assets/candidate-{index + 1}"),
                        "source_stage": "migration", "exists": False,
                    }
                )
            asset_plan = {
                "version": "2.0", "project_id": target_project_id,
                "created_at": now, "producer": "operator_migration",
                "input_hashes": {"legacy_asset_manifest": semantic_sha256(source_manifest)},
                "planned_assets": planned, "paid_generation_approved": False,
            }
            envelopes["asset_plan"] = write_artifact_atomic(
                "artifacts/asset_plan.json", "asset_plan", asset_plan, project_dir=target
            )
            proposal = _load_artifact(target, "proposal_packet") or {}
            script = _load_artifact(target, "script") or {}
            scene_plan = _load_artifact(target, "scene_plan") or {}
            production_lock = build_production_lock(
                proposal=proposal, script=script, scene_plan=scene_plan,
                asset_plan=envelopes["asset_plan"], decisions=decision_envelope,
            )
            envelopes["production_lock"] = write_artifact_atomic(
                "artifacts/production_lock.json", "production_lock",
                {key: value for key, value in production_lock.items() if key not in {"semantic_sha256", "artifact_sha256"}},
                project_dir=target,
            )
            for stage in ("proposal", "script", "scene_plan"):
                checkpoint = target / f"checkpoint_{stage}.json"
                if not checkpoint.exists():
                    checkpoint.write_text(
                        json.dumps({"stage": stage, "status": "completed", "artifacts": {}}),
                        encoding="utf-8",
                    )
            (target / "checkpoint_assets.json").write_text(
                json.dumps(
                    {
                        "stage": "assets", "status": "awaiting_human",
                        "human_approved": False,
                        "artifacts": {
                            "asset_plan": envelopes["asset_plan"],
                            "production_lock": envelopes["production_lock"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            group_manifest = {
                "approval_groups": {
                    "creative_lock": {
                        "members": ["proposal", "script", "scene_plan", "assets"],
                        "terminal_stage": "assets", "required_artifacts": [],
                    }
                }
            }
            bundle = build_approval_bundle(target, group_manifest, "creative_lock")
            review = {
                "schema_version": "1.0",
                "review_id": f"{target_project_id}-creative_lock-v1",
                "project_id": target_project_id, "kind": "creative_lock",
                "subject_id": bundle["bundle_id"], "subject_version": 1,
                "subject_hash": bundle["semantic_sha256"], "status": "awaiting_human",
                "submitted_by": owner_id, "decided_by": None, "reason": None,
                "created_at": now, "decided_at": None,
            }
            review_path = target / "operator/reviews" / f"{review['review_id']}.json"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

        return self.creation._create(
            project_id=target_project_id,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            source_project_id=source_project_id,
            initializer=initialize,
        )
