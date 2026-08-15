"""Deterministic change classification for the fastline render router."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from lib.cache_keys import canonical_digest


def _hash(value: Any) -> str:
    return canonical_digest(value)


def _semantic(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if k not in {"metadata", "notes", "created_at"}}


def classify_change(
    previous_lock: dict[str, Any], current_lock: dict[str, Any],
    previous_props: dict[str, Any], current_props: dict[str, Any],
) -> dict[str, Any]:
    """Return a schema-shaped impact artifact with the smallest safe route."""
    previous_timeline = _hash(_semantic(previous_props))
    current_timeline = _hash(_semantic(current_props))
    previous_audio = previous_props.get("audio", {})
    current_audio = current_props.get("audio", {})
    audio_changed = previous_audio != current_audio
    visual_changed = _semantic({k: v for k, v in previous_props.items() if k != "audio"}) != _semantic({k: v for k, v in current_props.items() if k != "audio"})
    metadata_changed = previous_props.get("metadata") != current_props.get("metadata") or previous_props.get("notes") != current_props.get("notes")
    if audio_changed and not visual_changed:
        route, reason = "mux_only", "audio changed while visual timeline is unchanged"
    elif visual_changed:
        route, reason = "full_render", "visual timeline, scenes, or captions changed"
    elif metadata_changed:
        route, reason = "no_render", "metadata-only change"
    else:
        route, reason = "no_render", "no render-affecting change"
    previous_hash = _hash(previous_lock)
    current_hash = _hash(current_lock)
    return {
        "version": "1.0", "project_id": current_lock.get("project_id", "unknown"),
        "created_at": datetime.now(timezone.utc).isoformat(), "producer": "change_impact",
        "input_hashes": {"previous_props": previous_timeline, "current_props": current_timeline},
        "semantic_sha256": _hash({"route": route, "previous": previous_timeline, "current": current_timeline}),
        "artifact_sha256": _hash({"previous_lock": previous_hash, "current_lock": current_hash, "route": route}),
        "previous_lock_hash": previous_hash, "current_lock_hash": current_hash,
        "route": route, "reasons": [reason],
        "dirty_scene_ids": [] if not visual_changed else [str(s.get("id")) for s in current_props.get("scenes", []) if isinstance(s, dict)],
        "reopen_creative_lock": route == "full_render", "reopen_sample": route in {"full_render", "mux_only"},
    }
