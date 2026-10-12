"""Small, complete table-mat Research source for clean-checkout tests."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path, PurePosixPath

from PIL import Image

from lib.research_validation import _iter_evidence_paths


ROOT = Path(__file__).resolve().parents[2]
REAL_SOURCE = ROOT / "tests/fixtures/tablemat_research/artifacts"
RESEARCH_ARTIFACTS = (
    "research_brief", "video_analysis_brief", "source_media_review", "media_index",
    "reference_fingerprint", "research_breakdown", "reference_source_matrix",
    "research_synthesis", "research_scorecard", "caption_style_fingerprint",
)


def install_tablemat_research(tmp_path: Path) -> Path:
    """Copy checked-in Research JSON and synthesize its referenced JPEG frames."""
    source = tmp_path / "tablemat-research-source"
    artifacts = source / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    evidence_paths: set[str] = set()
    for name in RESEARCH_ARTIFACTS:
        original = REAL_SOURCE / f"{name}.json"
        if not original.is_file():
            raise FileNotFoundError(f"Table-mat Research fixture is missing {original}")
        data = json.loads(original.read_text(encoding="utf-8"))
        evidence_paths.update(
            path for path in _iter_evidence_paths(data) if path.startswith("analysis/")
        )
        shutil.copyfile(original, artifacts / original.name)

    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (150, 160, 170)).save(buffer, format="JPEG")
    jpeg = buffer.getvalue()
    for raw in sorted(evidence_paths):
        relative = PurePosixPath(raw)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".jpg":
            raise ValueError(f"Unsafe or unsupported Research evidence path: {raw}")
        target = source.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(jpeg)
    return source
