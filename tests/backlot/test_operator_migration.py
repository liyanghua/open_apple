from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_legacy_migration_is_read_only_and_creates_fresh_fastline_gates(tmp_path) -> None:
    from backlot.auth_store import AuthStore
    from backlot.operator_migration import OperatorMigrationService
    from tests.contracts.test_phase0_contracts import sample_artifact

    projects = tmp_path / "projects"; source = projects / "legacy"; (source / "artifacts").mkdir(parents=True)
    (source / "project.json").write_text(json.dumps({"project_id": "legacy", "title": "旧项目", "pipeline_type": "cinematic"}))
    for name in ("research_brief", "proposal_packet", "script", "scene_plan", "asset_manifest"):
        (source / "artifacts" / f"{name}.json").write_text(json.dumps(sample_artifact(name)))
    (source / "checkpoint_sample.json").write_text('{"status":"completed"}')
    (source / "artifacts/approvals").mkdir()
    (source / "artifacts/approvals/old-v1-approved.json").write_text('{"status":"approved"}')
    before = _tree_digest(source)
    auth = AuthStore(tmp_path / "backlot.db"); auth.initialize()
    owner = auth.create_user("owner", "a sufficiently long password", "operator")
    service = OperatorMigrationService(projects, auth)
    result = service.migrate(
        source_project_id="legacy", target_project_id="legacy-fast",
        owner_id=owner.user_id, idempotency_key="migration-1", request_digest="e" * 64,
    )
    replay = service.migrate(
        source_project_id="legacy", target_project_id="legacy-fast",
        owner_id=owner.user_id, idempotency_key="migration-1", request_digest="e" * 64,
    )
    assert result == replay
    assert _tree_digest(source) == before

    target = projects / "legacy-fast"
    marker = json.loads((target / "project.json").read_text())
    assert marker["pipeline_type"] == "cinematic-fast"
    assert marker["parent_project_id"] == "legacy"
    assert not (target / "checkpoint_sample.json").exists()
    assert not (target / "artifacts/approvals/old-v1-approved.json").exists()
    asset_plan = json.loads((target / "artifacts/asset_plan.json").read_text())
    assert asset_plan["paid_generation_approved"] is False
    assert all(item["provider"] == "reuse_only" and item["paid"] is False for item in asset_plan["planned_assets"])
    fresh = list((target / "artifacts/approvals").glob("*-awaiting_human.json"))
    assert len(fresh) == 1
    reviews = [json.loads(path.read_text()) for path in (target / "operator/reviews").glob("*.json")]
    assert len(reviews) == 1 and reviews[0]["status"] == "awaiting_human"

