"""Import the 43-sheet reference library into a template_pack artifact.

用法：python -m scripts.import_template_pack [--xlsx docs/insight_source/视频分镜拆解_2026-08-15.xlsx] [--project template-pack-library]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.template_import import build_template_pack
from schemas.artifacts import validate_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Import 43-sheet reference library -> template_pack")
    parser.add_argument("--xlsx", default="docs/insight_source/视频分镜拆解_2026-08-15.xlsx")
    parser.add_argument("--project", default="template-pack-library")
    parser.add_argument("--evidence-dir", default="projects/template-pack-library/evidence")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    xlsx_path = root / args.xlsx
    ev_dir = root / args.evidence_dir
    pack = build_template_pack(xlsx_path, project_id=args.project, evidence_dir=ev_dir)
    sealed = attach_hashes(dict(pack))
    validate_artifact("template_pack", sealed)

    project_dir = root / "projects" / args.project
    (project_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    write_artifact_atomic(
        "artifacts/template_pack.json", "template_pack", sealed, project_dir=project_dir
    )
    n_vis = sum(1 for t in sealed["templates"] for s in t.get("slots") or [] if s.get("visual_reference_ref"))
    n_imgs = sum(1 for p in ev_dir.rglob("*") if p.is_file())
    print(f"OK: {len(sealed['templates'])} templates -> {project_dir}/artifacts/template_pack.json")
    print(f"visual_reference slots={n_vis} evidence_images={n_imgs}")
    print(f"source_sha256={sealed['source_document']['sha256']} artifact_sha256={sealed['artifact_sha256']}")
    print(f"warnings={len(sealed['normalization_warnings'])}")


if __name__ == "__main__":
    main()
