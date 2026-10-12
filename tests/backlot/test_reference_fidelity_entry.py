from pathlib import Path

from backlot.skill_catalog import SkillCatalog


ROOT = Path(__file__).resolve().parents[2]


def test_versioned_strict_entry_accepts_analysis_only_reference():
    catalog = SkillCatalog(ROOT / "skills/catalog")
    resolved = catalog.resolve("ecommerce-viral-remix", "1.0.1")
    catalog.validate_intake(resolved, {
        "input_mode": "reference_fidelity",
        "external_reference": {
            "present": True,
            "paths": ["inputs/reference/demo.mp4"],
            "usage": "analysis_only",
        },
        "product_name": "透明桌垫",
        "category": "home-protection",
        "platforms": ["douyin"],
        "duration_seconds": 30,
        "reference_paths": ["inputs/reference/demo.mp4"],
        "source_paths": ["inputs/source/video/product/demo.mp4"],
        "copyright_confirmed": True,
        "brand_cta": "查看同款",
        "paid_generation_approved": False,
    })
