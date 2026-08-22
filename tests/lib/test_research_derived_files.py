"""Research derived-file integrity gate (评审 P2 B3) tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.research_validation import validate_research_derived_files


def _artifacts() -> dict:
    return {
        "research_breakdown": {
            "reference_shots": [
                {"values": {"evidence_frames": ["analysis/reference/keyframes/frame_0000.jpg"]}},
            ],
        },
        "reference_source_matrix": {
            "rows": [{"evidence_frames": ["analysis/source/abc/frame_0001.jpg"]}],
        },
        "caption_style_fingerprint": {
            "source": {"evidence_frames": ["analysis/reference/keyframes/frame_0000.jpg"]},
        },
    }


def test_passes_when_all_derived_files_exist(tmp_path: Path):
    for rel in (
        "analysis/reference/keyframes/frame_0000.jpg",
        "analysis/source/abc/frame_0001.jpg",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"frame")
    validate_research_derived_files(tmp_path, _artifacts())  # 不抛


def test_fails_when_analysis_files_missing(tmp_path: Path):
    with pytest.raises(ValueError, match="派生证据文件缺失"):
        validate_research_derived_files(tmp_path, _artifacts())


def test_ignores_external_and_non_derived_refs(tmp_path: Path):
    artifacts = {
        "research_breakdown": {
            "reference_shots": [
                {"values": {"evidence_frames": [
                    "https://example.com/f.jpg",
                    "inputs/source/owned.mp4",
                    "artifacts/reference-frames/frame-001.jpg",
                ]}},
            ],
        },
    }
    validate_research_derived_files(tmp_path, artifacts)  # 不抛
