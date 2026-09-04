"""阶段 4 兼容入口：通过 cinematic-fast 主干构建 scene/assets 制品。

保留历史 CLI 与输出路径；本文件只解析毛巾批次 run，实际 scene plan、shot plan、
asset plan、production lock 和 approval bundle 全部委托 canonical builders。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from towel_creative import PRODUCTS  # noqa: E402

from lib.checkpoint import write_checkpoint  # noqa: E402
from lib.template_assets import build_assets  # noqa: E402
from lib.template_mainline import build_scene_plan as build_canonical_scene_plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
PRODUCT_KEYS = ("yinlizi", "tiansi", "chenxu", "yujin")


def build_canonical_scene_plan_for_run(project_dir: Path, template: dict, run_plan: dict,
                                       ccp: dict, facts: dict) -> dict:
    """Compatibility seam returning the canonical scene-plan envelope."""
    return build_canonical_scene_plan(project_dir, template, run_plan, ccp, facts)


def build_canonical_assets_for_run(project_dir: Path, template: dict) -> dict[str, dict]:
    """Use public mainline builders; do not reproduce artifact construction here."""
    run_plan = json.loads((project_dir / "artifacts/template_run_plan.json").read_text(encoding="utf-8"))
    ccp = json.loads((project_dir / "artifacts/creative_control_plan.json").read_text(encoding="utf-8"))
    facts = json.loads((project_dir / "artifacts/product_facts.json").read_text(encoding="utf-8"))
    scene_env = build_canonical_scene_plan_for_run(project_dir, template, run_plan, ccp, facts)
    asset_envs = build_assets(
        project_dir, template, pipeline_dir=PROJECTS,
        output_profile="social_vertical_3_4_2160p30",
    )
    return {"scene_plan": scene_env, **asset_envs}


def assets_checkpoint_state(*, previous: dict | None = None) -> dict[str, object]:
    """A rebuilt creative-lock bundle always requires a fresh human approval."""
    return {"status": "awaiting_human", "human_approved": False}


def main() -> int:
    for product_key in PRODUCT_KEYS:
        slug = PRODUCTS[product_key]["slug"]
        pack_path = PROJECTS / f"{slug}-batch" / "artifacts/template_pack.json"
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        templates = {str(item["template_id"]): item for item in pack.get("templates", [])}
        for arch in "ABCD":
            template_id = f"{product_key}-{arch}"
            run_dir = PROJECTS / f"template-run-{template_id}"
            canonical = build_canonical_assets_for_run(run_dir, templates[template_id])
            write_checkpoint(
                PROJECTS, run_dir.name, "scene_plan", "completed",
                {"scene_plan": canonical["scene_plan"]},
                pipeline_type="cinematic-fast", next_action=None,
            )
            bundle = canonical["approval_bundle"]["data"]
            checkpoint_state = assets_checkpoint_state()
            write_checkpoint(
                PROJECTS, run_dir.name, "assets",
                str(checkpoint_state["status"]),
                {name: canonical[name] for name in (
                    "shot_execution_plan", "asset_plan", "production_lock", "approval_bundle"
                )},
                pipeline_type="cinematic-fast", human_approval_required=True,
                human_approved=bool(checkpoint_state["human_approved"]), approval_group="creative_lock",
                approval_bundle_id=bundle["bundle_id"],
                approval_bundle_version=bundle["bundle_version"],
                next_action={
                    "verb": "await_user",
                    "summary": "creative lock 门：确认 canonical 素材映射、TTS/BGM 与 3:4 输出规格",
                    "context_refs": [f"projects/{run_dir.name}/artifacts/approval_bundle.json"],
                },
            )
            print(f"[{template_id}] canonical scene/assets ✓")
    print("[done] stage 4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
