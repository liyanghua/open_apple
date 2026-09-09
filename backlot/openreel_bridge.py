"""Strict adapter between OpenReel actions and canonical EditDelta inputs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from lib.cache_keys import canonical_digest


class BridgeError(ValueError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.details = details
        super().__init__(message)


def _indexes(snapshot: Mapping[str, Any]) -> tuple[dict[str, tuple[str, str]], dict[str, Mapping[str, Any]]]:
    timeline = snapshot.get("timeline") if isinstance(snapshot.get("timeline"), Mapping) else {}
    clips = {
        str(clip.get("id")): (str(track.get("id")), str(track.get("kind")))
        for track in (timeline.get("tracks") or []) if isinstance(track, Mapping)
        for clip in (track.get("clips") or []) if isinstance(clip, Mapping) and clip.get("id")
    }
    catalogue = snapshot.get("asset_catalogue") if isinstance(snapshot.get("asset_catalogue"), Mapping) else {}
    assets = {str(item.get("asset_id")): item for item in (catalogue.get("assets") or []) if isinstance(item, Mapping) and item.get("asset_id")}
    return clips, assets


def _number(params: Mapping[str, Any], key: str) -> Any:
    if key not in params:
        raise BridgeError("invalid_action", f"missing {key}")
    return params[key]


def actions_to_delta(snapshot: Mapping[str, Any], actions: list[Mapping[str, Any]], *, idempotency_key: str) -> dict[str, Any]:
    timeline = snapshot.get("timeline")
    if not isinstance(timeline, Mapping):
        raise BridgeError("invalid_snapshot", "canonical timeline is missing")
    clips, assets = _indexes(snapshot)
    operations = []
    for action in actions:
        action_type = str(action.get("type") or "")
        params = action.get("params") if isinstance(action.get("params"), Mapping) else {}
        clip_id = str(params.get("clipId") or "")
        if action_type == "color_grade/apply":
            raise BridgeError("unsupported_action", "color grade is not supported by EditorialTimeline V1")
        if action_type != "clip/add" and (not clip_id or clip_id not in clips):
            raise BridgeError("clip_not_found", "action references an unknown server clip ID", clip_id=clip_id)
        if action_type == "clip/add":
            track_id = str(params.get("trackId") or "")
            track_kind = next((track_kind for track, track_kind in clips.values() if track == track_id), None)
            if track_kind is None:
                raise BridgeError("track_not_found", "new clip must target a known server track", track_id=track_id)
            if track_kind != "video":
                raise BridgeError("operation_track_mismatch", "clip/add is supported only on video tracks", track_id=track_id)
            kind = track_kind
        else:
            track_id, kind = clips[clip_id]
        base = {"track_id": track_id, "clip_id": clip_id}
        if action_type == "clip/trim":
            operation = {**base, "op": "trim_clip", "source_in_seconds": _number(params, "inPoint"), "source_out_seconds": _number(params, "outPoint")}
        elif action_type == "clip/split":
            operation = {**base, "op": "split_clip", "at_seconds": _number(params, "time")}
        elif action_type == "clip/move":
            operation = {**base, "op": "move_clip", "start_seconds": _number(params, "start")}
        elif action_type == "clip/replace":
            asset_id = str(params.get("assetId") or "")
            if asset_id not in assets:
                raise BridgeError("asset_not_approved", "replacement asset is not in the server catalogue", asset_id=asset_id)
            approved = assets[asset_id]
            operation = {**base, "op": "replace_clip", "asset_id": asset_id,
                         "source_sha256": approved.get("source_sha256"),
                         "source_in_seconds": _number(params, "inPoint"),
                         "source_out_seconds": _number(params, "outPoint")}
        elif action_type == "clip/add":
            asset_id = str(params.get("assetId") or "")
            if asset_id not in assets:
                raise BridgeError("asset_not_approved", "added asset is not in the server catalogue", asset_id=asset_id)
            approved = assets[asset_id]
            operation = {"op": "add_clip", "track_id": track_id, "clip": {
                "id": str(params.get("clipId") or ""), "asset_id": asset_id,
                "source_sha256": approved.get("source_sha256"),
                "source_in_seconds": _number(params, "inPoint"),
                "source_out_seconds": _number(params, "outPoint"),
                "start_seconds": _number(params, "start"),
                "fact_scope": deepcopy(dict(approved.get("fact_scope") or {})),
            }}
        elif action_type == "audio/gain":
            operation = {**base, "op": "set_gain", "gain_db": _number(params, "gainDb")}
        elif action_type == "audio/fade":
            operation = {**base, "op": "set_fade", "fade_in_seconds": _number(params, "fadeIn"), "fade_out_seconds": _number(params, "fadeOut")}
        elif action_type == "audio/duck":
            operation = {**base, "op": "set_ducking", "enabled": params.get("enabled") is True, "reduction_db": _number(params, "reductionDb")}
        elif action_type == "caption/timing":
            operation = {**base, "op": "set_caption_timing", "start_seconds": _number(params, "start"), "end_seconds": _number(params, "end")}
        else:
            raise BridgeError("unsupported_action", f"unsupported OpenReel action: {action_type}", action_type=action_type)
        operations.append(operation)
    if not operations:
        raise BridgeError("invalid_action", "at least one action is required")
    session_id = str(snapshot.get("session_id") or "")
    return {
        "version": "1.0",
        "delta_id": f"delta-{canonical_digest({'session_id': session_id, 'idempotency_key': idempotency_key, 'operations': operations})[:24]}",
        "session_id": session_id,
        "base_generation_id": timeline.get("base_generation_id"),
        "base_timeline_hash": canonical_digest(timeline),
        "operation_sequence": int(snapshot.get("revision") or 0) + 1,
        "idempotency_key": idempotency_key,
        "operations": operations,
    }


def normalize_actions(actions: list[Mapping[str, Any]], mapping: Mapping[str, Any], *, current_cuts: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Compatibility helper for the OpenReel UI: normalize without persistence."""
    clips = {str(key): str(value) for key, value in (mapping.get("clips") or {}).items()}
    subtitles = {str(key): str(value) for key, value in (mapping.get("subtitles") or {}).items()}
    synthetic = {"timeline": {"base_generation_id": "generation-unknown", "tracks": []}, "asset_catalogue": {"assets": []}}
    for clip_id, shot_id in clips.items():
        synthetic["timeline"]["tracks"].append({"id": shot_id, "kind": "video", "clips": [{"id": clip_id, "asset_id": shot_id, "source_sha256": "0" * 64, "source_in_seconds": 0, "source_out_seconds": 1, "start_seconds": 0}]})
    output = []
    unsupported = []
    for action in actions:
        kind = str(action.get("type") or "")
        params = action.get("params") if isinstance(action.get("params"), Mapping) else {}
        if kind in {"clip/split", "clip/slide", "clip/slip", "clip/rippleDelete", "clip/roll", "audio/mix", "color_grade/apply"}:
            unsupported.append({"action_type": kind, "reason": "unsupported_operation"})
            continue
        if kind == "clip/trim":
            shot_id = clips.get(str(params.get("clipId")))
            if not shot_id:
                unsupported.append({"action_type": kind, "reason": "unmapped_clip"})
            elif "inPoint" not in params or "outPoint" not in params:
                unsupported.append({"action_type": kind, "reason": "incomplete_trim"})
            else:
                output.append({"op": "set_source_range", "shot_id": shot_id, "in_seconds": float(params["inPoint"]), "out_seconds": float(params["outPoint"])})
        elif kind == "clip/setSpeed":
            shot_id = clips.get(str(params.get("clipId")))
            if shot_id and isinstance(params.get("speed"), (int, float)):
                output.append({"op": "set_shot_speed", "shot_id": shot_id, "speed": float(params["speed"])})
            else:
                unsupported.append({"action_type": kind, "reason": "unmapped_clip"})
        elif kind == "subtitle/update":
            shot_id = subtitles.get(str(params.get("subtitleId")))
            text = str(params.get("text") or "").strip()
            if shot_id and text:
                output.append({"op": "set_caption", "shot_id": shot_id, "text": text})
            else:
                unsupported.append({"action_type": kind, "reason": "timing_only" if shot_id else "unmapped_subtitle"})
        else:
            unsupported.append({"action_type": kind, "reason": "unsupported_operation"})
    return {"operations": output, "unsupported": unsupported}


def build_delta(*, session: Mapping[str, Any], actions: list[Mapping[str, Any]], mapping: Mapping[str, Any], current_cuts: Mapping[str, Any] | None = None, actor_id: str = "", idempotency_key: str) -> dict[str, Any]:
    if not idempotency_key:
        raise BridgeError("invalid_action", "missing idempotency key")
    normalized = normalize_actions(actions, mapping, current_cuts=current_cuts)
    if not normalized["operations"]:
        raise BridgeError("invalid_action", "没有可提交的编辑操作")
    digest = canonical_digest({"session": dict(session), "operations": normalized["operations"], "actions": list(actions)})
    return {"version": "1.0", "delta_id": f"delta-{digest[:24]}", **dict(session), "operations": normalized["operations"], "created_by": actor_id, "idempotency_key": idempotency_key, "canonical_hash": digest, "unsupported_actions": normalized["unsupported"]}


def materialize_snapshot(child_dir: Any, decisions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Expose a safe OpenReel snapshot from canonical timeline artifacts."""
    import json
    root = __import__("pathlib").Path(child_dir)
    if decisions is None:
        try:
            decisions = json.loads((root / "artifacts" / "editorial_timeline.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            decisions = {}
    if "timeline" in decisions:
        return snapshot_to_openreel({"timeline": decisions["timeline"], "session_id": decisions.get("session_id")})
    return {"schema_version": "1.0", "project_id": root.name, "tracks": [], "clips": [], "assets": [], "mapping": {"clips": {}, "subtitles": {}}}


def snapshot_to_openreel(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    timeline = snapshot.get("timeline") if isinstance(snapshot.get("timeline"), Mapping) else {}
    clips = []
    tracks = []
    for track in timeline.get("tracks") or []:
        if not isinstance(track, Mapping):
            continue
        track_view = {"id": track.get("id"), "kind": track.get("kind"), "clip_ids": []}
        for clip in track.get("clips") or []:
            if not isinstance(clip, Mapping):
                continue
            clip_view = {key: deepcopy(clip.get(key)) for key in (
                "id", "asset_id", "source_in_seconds", "source_out_seconds",
                "start_seconds", "end_seconds", "text", "fact_scope", "claim_ids",
            ) if key in clip}
            clips.append(clip_view)
            track_view["clip_ids"].append(clip.get("id"))
        tracks.append(track_view)
    catalogue = snapshot.get("asset_catalogue") if isinstance(snapshot.get("asset_catalogue"), Mapping) else {}
    assets = [{key: deepcopy(item.get(key)) for key in ("asset_id", "media_kind", "role", "valid_range", "fact_scope", "claim_ids") if key in item}
              for item in (catalogue.get("assets") or []) if isinstance(item, Mapping)]
    return {"session_id": snapshot.get("session_id"), "revision": snapshot.get("revision"),
            "timeline_hash": snapshot.get("timeline_hash"), "tracks": tracks,
            "clips": clips, "assets": assets}
