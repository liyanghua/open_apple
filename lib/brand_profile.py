"""Merge reusable brand defaults without bypassing approved production locks."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lib.production_lock import append_decision_revision
from schemas.artifacts import validate_artifact


_MISSING = object()

_LOCK_PATHS = {
    "voice.provider": "tts.provider",
    "voice.resource": "tts.resource",
    "voice.voice": "tts.voice",
    "voice.rate": "tts.rate",
    "bgm.family": "bgm.family",
    "font.family": "font.family",
    "font.fallbacks": "font.fallbacks",
    "caption_profile.safe_zone_profile": "captions.safe_zone_profile",
    "caption_profile.font_min": "captions.font_min",
    "caption_profile.font_max": "captions.font_max",
    "caption_profile.max_width": "captions.max_width",
    "caption_profile.strip_trailing_punctuation": "captions.strip_trailing_punctuation",
    "emphasis_rules": "captions.emphasis_rules",
    "cta_pattern": "cta.pattern",
    "platform_defaults": "platform.defaults",
}


def _flatten(value: Mapping[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    flattened: list[tuple[str, Any]] = []
    for key, item in value.items():
        if key in {"version", "profile_id"} and not prefix:
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, Mapping) and path not in {"platform_defaults"}:
            flattened.extend(_flatten(item, path))
        else:
            flattened.append((path, copy.deepcopy(item)))
    return flattened


def _get(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set(value: dict[str, Any], path: str, item: Any) -> None:
    parts = path.split(".")
    current = value
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = copy.deepcopy(item)


def _decision_category(path: str) -> str:
    if path.startswith("voice."):
        return "voice_selection"
    if path.startswith("bgm."):
        return "music_source"
    if path.startswith(("font.", "caption_profile.", "emphasis_rules")):
        return "visual_accuracy_check"
    if path == "cta_pattern":
        return "concept_selection"
    return "pipeline_selection"


def merge_brand_defaults(
    profile: dict[str, Any],
    selected: dict[str, Any],
    *,
    production_lock: dict[str, Any] | None = None,
    project_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Fill missing selections and report lock conflicts for reapproval."""
    validate_artifact("brand_profile", profile)
    merged = copy.deepcopy(selected)
    locked_values = (production_lock or {}).get("locked_values") or {}
    applied: list[str] = []
    conflicts: list[dict[str, Any]] = []

    for profile_path, profile_value in _flatten(profile):
        selected_value = _get(merged, profile_path)
        if selected_value is not _MISSING and selected_value is not None:
            continue
        lock_path = _LOCK_PATHS.get(profile_path, profile_path)
        locked_value = _get(locked_values, lock_path)
        if locked_value is not _MISSING:
            _set(merged, profile_path, locked_value)
            if locked_value != profile_value:
                revision_id = None
                if project_dir is not None:
                    revision_id = append_decision_revision(
                        Path(project_dir),
                        category=_decision_category(profile_path),
                        subject=f"Brand profile {profile_path}",
                        selected=profile_value,
                        superseded=locked_value,
                        reason=f"brand profile {profile.get('profile_id')} requests a locked-value change",
                    )
                conflicts.append({
                    "path": profile_path,
                    "locked_value": copy.deepcopy(locked_value),
                    "profile_value": copy.deepcopy(profile_value),
                    "requires_reapproval": True,
                    "decision_revision_id": revision_id,
                })
            continue
        _set(merged, profile_path, profile_value)
        applied.append(profile_path)

    return {
        "merged": merged,
        "applied_defaults": applied,
        "conflicts": conflicts,
        "requires_reapproval": bool(conflicts),
    }
