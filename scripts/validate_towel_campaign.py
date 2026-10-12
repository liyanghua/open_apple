"""Run the cross-artifact campaign admission gate for a local project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.campaign_contracts import validate_campaign_bundle


def validate(project_dir: Path, *, paid: bool = False) -> dict:
    project_dir = Path(project_dir)
    artifacts = project_dir / "artifacts"
    plan = json.loads((artifacts / "campaign_plan.json").read_text(encoding="utf-8"))
    snapshots = {}
    for path in sorted(artifacts.glob("fact_snapshot_*.json")):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshots[str(snapshot["snapshot_id"])] = snapshot
    recipes = {}
    for path in sorted((artifacts / "recipes").glob("*.json")):
        recipe = json.loads(path.read_text(encoding="utf-8"))
        recipes[str(recipe["recipe_id"])] = recipe
    result = validate_campaign_bundle(plan, snapshots, recipes, paid=paid)
    result.update({
        "campaign_id": plan.get("campaign_id"),
        "paid_gate": paid,
        "snapshot_count": len(snapshots),
        "recipe_count": len(recipes),
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--paid", action="store_true", help="require approved fact snapshots")
    args = parser.parse_args()
    result = validate(args.project_dir, paid=args.paid)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
