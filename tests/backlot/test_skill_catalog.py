from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _intake() -> dict:
    return {
        "product_name": "透明桌垫",
        "category": "home-protection",
        "platforms": ["douyin", "wechat_channels", "xiaohongshu"],
        "duration_seconds": 30,
        "reference_paths": ["inputs/reference/demo.mp4"],
        "source_paths": ["inputs/source/video/product"],
        "copyright_confirmed": True,
        "brand_cta": "查看商品详情",
        "paid_generation_approved": False,
    }


def test_catalog_resolves_validated_immutable_skill(tmp_path) -> None:
    from backlot.skill_catalog import SkillCatalog

    catalog = SkillCatalog(REPO_ROOT / "skills/catalog")
    resolved = catalog.resolve("ecommerce-viral-remix")
    catalog.validate_intake(resolved, _intake())
    assert resolved["manifest"]["pipeline"] == "cinematic-fast"
    assert resolved["digest"] == "ed33f41c9d861d0ee962a19027cb3355cf5f3ac266e369621b4d30071f183c6e"

    catalog.write_snapshot(tmp_path, resolved, _intake())
    locked = json.loads((tmp_path / "operator/skill-snapshot/resolved.json").read_text())
    assert locked["version"] == "1.0.0"
    assert locked["digest"] == resolved["digest"]


def test_catalog_list_uses_business_language_without_unproven_sla() -> None:
    from backlot.skill_catalog import SkillCatalog

    item = SkillCatalog(REPO_ROOT / "skills/catalog").list()[0]
    assert item["name"] == "电商爆款复刻"
    assert item["status"] == "trial"
    assert item["performance_promise"] is None


def test_create_project_from_skill_locks_snapshot(backlot_client, projects_root) -> None:
    response = backlot_client.post(
        "/api/v2/projects",
        headers={"Origin": "http://testserver", "X-CSRF-Token": "test-csrf", "Idempotency-Key": "skill-create-1"},
        json={
            "project_id": "new-table-mat", "title": "透明桌垫复刻",
            "skill_id": "ecommerce-viral-remix", "skill_version": "1.0.0",
            "intake": _intake(),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["skill"] == {"id": "ecommerce-viral-remix", "version": "1.0.0"}
    assert (projects_root / "new-table-mat/operator/skill-snapshot/intake.json").is_file()
