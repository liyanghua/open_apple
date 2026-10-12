"""Refresh visual selling-point captions without regenerating approved media."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lib.template_render import build_final_props


def build_refreshed_final_props(
    project: Path,
    *,
    existing_final_props: Mapping[str, Any],
    script: Mapping[str, Any],
    shot_plan: Mapping[str, Any],
    profile: str,
) -> dict[str, Any]:
    """Rebuild only the timeline props, retaining the approved realized mix."""
    mix = existing_final_props.get("audio", {}).get("mix", {})
    narration = str(mix.get("narration", {}).get("path") or "assets/audio/sample-mix.mp3")
    music = str(mix.get("music", {}).get("path") or "assets/music/bgm.mp3")
    shots = shot_plan.get("shots") or []
    if not isinstance(shots, list) or not shots:
        raise ValueError("shot_execution_plan.shots is required for caption refresh")
    return build_final_props(
        project,
        dict(script),
        shots,
        narration_mix=narration,
        bgm_path=music,
        profile=profile,
        input_hashes={
            "script": str(script.get("semantic_sha256") or ""),
            "shot_execution_plan": str(shot_plan.get("semantic_sha256") or ""),
        },
    )
