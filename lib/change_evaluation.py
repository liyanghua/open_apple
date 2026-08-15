"""Single deterministic entry point for operator change impact."""

from __future__ import annotations

from typing import Any

from lib.production_lock import compare_production_locks


_RANK = {"no_render": 0, "mux_only": 1, "full_render": 2}


def _props_impact(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    ignored = {"metadata", "notes", "created_at", "semantic_sha256", "artifact_sha256"}
    old_visual = {key: value for key, value in previous.items() if key not in ignored | {"audio"}}
    new_visual = {key: value for key, value in current.items() if key not in ignored | {"audio"}}
    visual = old_visual != new_visual
    audio = previous.get("audio", {}) != current.get("audio", {})
    route = "full_render" if visual else "mux_only" if audio else "no_render"
    scene_ids = []
    if visual:
        scene_ids = [
            str(item.get("id"))
            for item in current.get("scenes", [])
            if isinstance(item, dict) and item.get("id") is not None
        ]
    return {"route": route, "scene_ids": scene_ids, "sample": visual or audio}


def evaluate_change_impact(
    previous_lock: dict[str, Any],
    current_lock: dict[str, Any],
    previous_props: dict[str, Any],
    current_props: dict[str, Any],
    *,
    adapter_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine lock, final-props and adapter changes using the safest route."""
    lock = compare_production_locks(previous_lock, current_lock)
    props = _props_impact(previous_props, current_props)
    signals = adapter_signals or {}
    routes = [lock.render_route, props["route"], signals.get("render_route", "no_render")]
    route = max(routes, key=lambda item: _RANK.get(item, 2))
    return {
        "render_route": route,
        "reopen_creative": bool(
            lock.reopen_creative_lock or signals.get("reopen_creative", False)
        ),
        "reopen_sample": bool(
            lock.reopen_sample or props["sample"] or signals.get("reopen_sample", False)
        ),
        "affected_scene_ids": props["scene_ids"],
        "changed_lock_fields": list(lock.changed_paths),
    }

