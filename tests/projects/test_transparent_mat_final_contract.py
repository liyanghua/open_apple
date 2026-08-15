from __future__ import annotations

import json
from pathlib import Path

from lib.final_props import validate_final_props


ROOT = Path(__file__).parents[2]
PROJECT = ROOT / "projects" / "transparent-table-mat-remix-01"


def test_transparent_mat_final_props_is_single_timeline_source() -> None:
    props = json.loads((PROJECT / "artifacts" / "final_props.json").read_text())
    validate_final_props(props, project_dir=PROJECT)
    assert props["durationInFrames"] == sum(scene["durationInFrames"] for scene in props["scenes"])
    assert len(props["scenes"]) == 16


def test_remotion_entry_does_not_register_a_second_production_timeline() -> None:
    root = (PROJECT / "Root.tsx").read_text()
    composition = (PROJECT / "Composition.tsx").read_text()
    assert "TransparentMatSample" not in root
    assert "finalCaptions" not in root
    assert "durationInFrames={900}" not in root
    assert "durationInFrames: 900" not in composition
    assert "durationInFrames: props.durationInFrames" in composition
    assert "scenes.map" in composition
    assert "footage[scene.footageKey]" in composition


def test_visual_scene_components_read_clip_timing_from_scene_props() -> None:
    composition = (PROJECT / "Composition.tsx").read_text()
    for scene_id in range(1, 17):
        start = composition.index(f"const Scene{scene_id:02d}")
        end = composition.find("const Scene", start + 1)
        section = composition[start:] if end == -1 else composition[start:end]
        assert "trimSeconds=" in section
        assert "scene.sourceInSeconds" in section or "segments[" in section
        assert "durationFrames={" not in section or "scene.durationInFrames" in section or "segments[" in section
