"""Production-lock construction and append-only decision revisions.

The production lock is the small, reviewable contract for the choices that
must not drift between sample and final render.  Comparisons intentionally use
field paths rather than natural-language reasons so the render/approval route
is deterministic.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib.artifact_hashing import attach_hashes, semantic_sha256
from schemas.artifacts import validate_artifact


@dataclass(frozen=True)
class LockDiff:
    """The safe execution and approval route for a lock change."""

    changed_paths: tuple[str, ...]
    reopen_creative_lock: bool
    reopen_sample: bool
    render_route: str


_MISSING = object()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None:
            return value
    return default


def _unwrap(value: Any) -> Any:
    """Accept both a raw artifact and a v2 checkpoint envelope."""
    if isinstance(value, Mapping) and isinstance(value.get("data"), Mapping):
        return value["data"]
    return value


def _plan_value(proposal: Mapping[str, Any], *keys: str) -> Any:
    plan = _mapping(proposal.get("production_plan"))
    for key in keys:
        if key in proposal:
            return proposal[key]
        if key in plan:
            return plan[key]
    return None


def _decision_values(decisions: Any) -> dict[str, Any]:
    """Index the latest decision selection by category and subject."""
    raw = _unwrap(decisions)
    entries = raw.get("decisions", []) if isinstance(raw, Mapping) else raw
    result: dict[str, Any] = {}
    if not isinstance(entries, list):
        return result
    for decision in entries:
        if not isinstance(decision, Mapping):
            continue
        key = f"{decision.get('category', '')}:{decision.get('subject', '')}"
        if key != ":":
            result[key] = decision.get("selected")
    return result


def _decision_pick(index: Mapping[str, Any], *needles: str) -> Any:
    for key, selected in index.items():
        lowered = key.lower()
        if any(needle in lowered for needle in needles):
            return selected
    return None


def _extract_locked_values(
    *, proposal: Any, script: Any, scene_plan: Any, asset_plan: Any, decisions: Any
) -> dict[str, Any]:
    proposal_map = _mapping(_unwrap(proposal))
    script_map = _mapping(_unwrap(script))
    scene_map = _mapping(_unwrap(scene_plan))
    asset_map = _mapping(_unwrap(asset_plan))
    decision_index = _decision_values(decisions)

    narration = _first(
        script_map.get("narration"),
        script_map.get("voiceover"),
        script_map.get("text"),
        script if isinstance(script, str) else None,
        _decision_pick(decision_index, "narration", "voiceover"),
        default="",
    )
    tts = _first(
        asset_map.get("tts"),
        asset_map.get("voice"),
        _plan_value(proposal_map, "tts", "voice"),
        _decision_pick(decision_index, "tts", "voice", "provider"),
        default={},
    )
    bgm = _first(
        asset_map.get("bgm"),
        asset_map.get("music"),
        _plan_value(proposal_map, "bgm", "music"),
        _decision_pick(decision_index, "bgm", "music"),
        default={},
    )
    mix = _first(
        asset_map.get("mix"),
        _plan_value(proposal_map, "mix", "audio_mix", "mix_profile"),
        _decision_pick(decision_index, "mix", "lufs", "gain"),
        default={},
    )
    captions = _first(
        scene_map.get("captions"),
        scene_map.get("caption_profile"),
        _plan_value(proposal_map, "captions", "caption_profile"),
        scene_map if scene_map else None,
        default={},
    )
    output = _first(
        _plan_value(proposal_map, "output", "delivery", "format"),
        default={},
    )
    if not isinstance(output, Mapping):
        output = {"value": output}
    else:
        output = dict(output)
    # Proposals often keep delivery fields flat.  Normalize them into the
    # locked output object so resolution/fps/duration cannot be omitted merely
    # because an authoring tool used a different nesting convention.
    plan = _mapping(proposal_map.get("production_plan"))
    for output_key, aliases in {
        "resolution": ("resolution", "dimensions"),
        "fps": ("fps", "frame_rate"),
        "duration": ("duration", "duration_seconds", "durationInFrames"),
    }.items():
        if output_key in output:
            continue
        for alias in aliases:
            value = proposal_map.get(alias, plan.get(alias))
            if value is not None:
                output[output_key] = value
                break

    return {
        "script": _first(script_map.get("text"), script, default=""),
        "narration": narration,
        "tts": tts,
        "bgm": bgm,
        "mix": mix,
        "font": _first(
            scene_map.get("font"),
            scene_map.get("font_family"),
            _plan_value(proposal_map, "font", "font_family"),
            default="",
        ),
        "captions": captions,
        "cta": _first(
            _plan_value(proposal_map, "cta", "call_to_action"),
            _decision_pick(decision_index, "cta"),
            default="",
        ),
        "platform": _first(
            _plan_value(proposal_map, "platform", "target_platform"),
            default="",
        ),
        "output": dict(output),
        "render_runtime": _first(
            _plan_value(proposal_map, "render_runtime", "runtime"),
            _decision_pick(decision_index, "runtime", "renderer"),
            default="remotion",
        ),
        "composition_mode": _first(
            _plan_value(proposal_map, "composition_mode", "authoring_mode"),
            _decision_pick(decision_index, "composition_mode"),
            default="templated",
        ),
    }


def build_production_lock(
    *, proposal: Any, script: Any, scene_plan: Any, asset_plan: Any, decisions: Any
) -> dict[str, Any]:
    """Build and validate a new production lock from stage artifacts."""
    sources = {
        "proposal": _unwrap(proposal),
        "script": _unwrap(script),
        "scene_plan": _unwrap(scene_plan),
        "asset_plan": _unwrap(asset_plan),
        "decisions": _unwrap(decisions),
    }
    values = _extract_locked_values(**sources)
    decision_data = _unwrap(decisions)
    decision_entries = (
        decision_data.get("decisions", [])
        if isinstance(decision_data, Mapping)
        else []
    )
    decision_ids = [
        str(item["decision_id"])
        for item in decision_entries
        if isinstance(item, Mapping) and item.get("decision_id")
    ]
    body = {
        "version": "1.0",
        "project_id": str(
            _first(
                _mapping(_unwrap(proposal)).get("project_id"),
                _mapping(_unwrap(script)).get("project_id"),
                "unknown",
            )
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "production_lock",
        "input_hashes": {
            name: semantic_sha256(value) for name, value in sources.items()
        },
        "lock_version": 1,
        "locked_values": values,
        "decision_revision_ids": list(dict.fromkeys(decision_ids)),
    }
    lock = attach_hashes(body)
    validate_artifact("production_lock", lock)
    return lock


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, Mapping):
        flattened: dict[str, Any] = {}
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten(value[key], path))
        return flattened
    if isinstance(value, list):
        flattened = {}
        for index, item in enumerate(value):
            flattened.update(_flatten(item, f"{prefix}.{index}" if prefix else str(index)))
        return flattened
    return {prefix: value}


def compare_production_locks(previous: dict[str, Any], current: dict[str, Any]) -> LockDiff:
    """Compare locked values and select the smallest safe render route."""
    previous_values = _mapping(previous.get("locked_values"))
    current_values = _mapping(current.get("locked_values"))
    old = _flatten(previous_values)
    new = _flatten(current_values)
    changed = tuple(sorted(path for path in set(old) | set(new) if old.get(path, _MISSING) != new.get(path, _MISSING)))
    if not changed:
        return LockDiff((), False, False, "no_render")

    lowered = {path.lower() for path in changed}
    metadata_only = all(
        any(token in path.split(".") for token in ("metadata", "note", "notes"))
        for path in lowered
    )
    if metadata_only:
        return LockDiff(changed, False, False, "no_render")

    gain_only = all(
        path in {"mix.gain", "mix.lufs", "mix.target_lufs", "mix.loudness", "audio.gain", "audio.lufs"}
        for path in lowered
    )
    if gain_only:
        return LockDiff(changed, False, False, "mux_only")

    creative_tokens = (
        "script", "narration", "tts", "provider", "model", "resource", "voice",
        "rate", "bgm", "font", "cta", "platform", "output", "render_runtime",
        "composition_mode",
    )
    sample_tokens = (
        "caption", "scene", "timing", "transition", "crop", "speed", "playback",
    )
    creative = any(any(token in path for token in creative_tokens) for path in lowered)
    sample = any(any(token in path for token in sample_tokens) for path in lowered)
    if creative:
        return LockDiff(changed, True, True, "full_render")
    if sample:
        return LockDiff(changed, False, True, "full_render")
    return LockDiff(changed, True, True, "full_render")


def _revision_option(value: Any, *, option_id: str, score: float, reason: str, rejected: str | None = None) -> dict[str, Any]:
    if isinstance(value, Mapping):
        option = dict(value)
        option.setdefault("option_id", option_id)
        option.setdefault("label", str(option.get("value", value)))
        option.setdefault("score", score)
        option.setdefault("reason", reason)
    else:
        option = {"option_id": option_id, "label": str(value), "score": score, "reason": reason}
    if rejected:
        option["rejected_because"] = rejected
    return option


def _read_decision_log(project_dir: Path) -> dict[str, Any]:
    canonical = project_dir / "artifacts" / "decision_log.json"
    legacy = project_dir / "decision_log.json"
    path = canonical if canonical.exists() else legacy
    if not path.exists():
        return {"version": "1.0", "project_id": project_dir.name, "decisions": []}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("decision log must be a JSON object")
    return loaded


def append_decision_revision(
    project_dir: Path,
    *,
    category: str,
    subject: str,
    selected: object,
    superseded: object,
    reason: str,
    sink=None,
) -> str:
    """Append a revised decision without mutating any historical entry."""
    from lib.artifact_io import write_artifact_atomic

    project_dir = Path(project_dir)
    log = _read_decision_log(project_dir)
    decisions = list(log.get("decisions", []))
    existing_ids = {str(item.get("decision_id")) for item in decisions if isinstance(item, Mapping)}
    decision_id = f"decision-rev-{uuid.uuid4().hex}"
    while decision_id in existing_ids:
        decision_id = f"decision-rev-{uuid.uuid4().hex}"
    superseded_option_id = (
        str(superseded.get("option_id"))
        if isinstance(superseded, Mapping) and superseded.get("option_id")
        else str(superseded) if isinstance(superseded, str) and superseded else "superseded"
    )
    selected_option_id = (
        str(selected.get("option_id"))
        if isinstance(selected, Mapping) and selected.get("option_id")
        else str(selected) if isinstance(selected, str) and selected else "selected"
    )
    if selected_option_id == superseded_option_id:
        selected_option_id = f"{selected_option_id}-revision"
    superseded_option = _revision_option(
        superseded,
        option_id=superseded_option_id,
        score=0.0,
        reason="previous selection",
        rejected=f"changed/superseded: {reason}",
    )
    selected_option = _revision_option(selected, option_id=selected_option_id, score=1.0, reason=reason)
    revision = {
        "decision_id": decision_id,
        "stage": "revision",
        "category": category,
        "subject": subject,
        "options_considered": [
            superseded_option,
            selected_option,
        ],
        "selected": selected_option["option_id"],
        "reason": reason,
        "user_visible": True,
        "user_approved": False,
    }
    log = {
        "version": "1.0",
        "project_id": str(log.get("project_id") or project_dir.name),
        "decisions": decisions + [revision],
    }
    write_artifact_atomic(
        "artifacts/decision_log.json",
        "decision_log",
        log,
        project_dir=project_dir,
        sink=sink,
    )
    return decision_id
