"""Materialize an executable, fact-bound EditorialTimeline from approved artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import math
from typing import Any

from lib.cache_keys import canonical_digest
from lib.artifact_hashing import semantic_sha256, verify_hashes
from lib.editorial_asset_catalogue import (
    EditorialMaterializationError,
    build_editorial_asset_catalogue,
)
from schemas.artifacts import validate_artifact


class EditorialDeltaError(ValueError):
    """A machine-readable rejection of an editorial timeline operation."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _reject(code: str, message: str, **details: Any) -> None:
    raise EditorialDeltaError(code, message, **details)


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        _reject("invalid_numeric", f"{field} must be a finite number", field=field, value=value)
    return float(value)


def _validate_operation_numbers(operation: Mapping[str, Any]) -> None:
    operation_name = operation.get("op")
    required: dict[str, tuple[str, ...]] = {
        "move_clip": ("start_seconds",),
        "split_clip": ("at_seconds",),
        "trim_clip": ("source_in_seconds", "source_out_seconds"),
        "set_speed": ("speed",),
        "move_audio": ("start_seconds",),
        "set_gain": ("gain_db",),
        "set_caption_timing": ("start_seconds", "end_seconds"),
        "set_text_timing": ("start_seconds", "end_seconds"),
    }
    for field in required.get(str(operation_name), ()):
        if field not in operation:
            _reject("invalid_numeric", f"{operation_name}.{field} is required", field=field)
        _finite_number(operation[field], field=f"{operation_name}.{field}")
    for field in ("fade_in_seconds", "fade_out_seconds", "reduction_db"):
        if field in operation:
            _finite_number(operation[field], field=f"{operation_name}.{field}")
    if operation_name == "replace_clip":
        for field in ("source_in_seconds", "source_out_seconds"):
            if field not in operation:
                _reject("invalid_numeric", f"replace_clip.{field} is required", field=field)
            _finite_number(operation[field], field=f"replace_clip.{field}")


def _timeline_track(timeline: Mapping[str, Any], track_id: str) -> dict[str, Any]:
    for track in timeline.get("tracks", []):
        if isinstance(track, dict) and track.get("id") == track_id:
            return track
    _reject("track_not_found", f"track {track_id} does not exist", track_id=track_id)


def _timeline_clip(track: Mapping[str, Any], clip_id: str) -> tuple[int, dict[str, Any]]:
    for index, clip in enumerate(track.get("clips", [])):
        if isinstance(clip, dict) and clip.get("id") == clip_id:
            return index, clip
    _reject(
        "clip_not_found",
        f"clip {clip_id} does not exist on track {track.get('id')}",
        track_id=track.get("id"),
        clip_id=clip_id,
    )


def _require_track_kind(track: Mapping[str, Any], allowed: set[str], *, operation: str) -> None:
    if track.get("kind") not in allowed:
        _reject(
            "operation_track_mismatch",
            f"{operation} is not supported on {track.get('kind')} tracks",
            operation=operation,
            track_id=track.get("id"),
        )


def _catalogue_asset(
    asset_catalogue: Mapping[str, Any] | None, asset_id: str
) -> Mapping[str, Any]:
    if not isinstance(asset_catalogue, Mapping):
        _reject(
            "asset_catalogue_required",
            f"an approved asset catalogue is required for {asset_id}",
            asset_id=asset_id,
        )
    assets = asset_catalogue.get("assets")
    if not isinstance(assets, list):
        _reject("invalid_asset_catalogue", "asset catalogue has no asset list")
    asset = next(
        (
            item for item in assets
            if isinstance(item, Mapping) and item.get("asset_id") == asset_id
        ),
        None,
    )
    if asset is None:
        _reject(
            "asset_not_approved",
            f"asset {asset_id} was not issued by the approved catalogue",
            asset_id=asset_id,
        )
    candidate_id = asset_catalogue.get("candidate_id")
    project_id = asset_catalogue.get("project_id")
    if (
        asset.get("candidate_id") != candidate_id
        or asset.get("project_id") != project_id
    ):
        _reject(
            "asset_scope_violation",
            f"asset {asset_id} belongs to another candidate or project",
            asset_id=asset_id,
            expected_candidate_id=candidate_id,
            expected_project_id=project_id,
        )
    return asset


def _require_hash(asset: Mapping[str, Any], source_sha256: Any, *, asset_id: str) -> None:
    if asset.get("source_sha256") != source_sha256:
        _reject(
            "asset_hash_mismatch",
            f"asset {asset_id} hash does not match its approved catalogue entry",
            asset_id=asset_id,
        )


def _require_source_range(
    asset: Mapping[str, Any], source_in: float, source_out: float, *, asset_id: str
) -> None:
    valid_range = asset.get("valid_range")
    if not isinstance(valid_range, Mapping):
        _reject(
            "source_range_unavailable",
            f"asset {asset_id} has no approved source range",
            asset_id=asset_id,
        )
    start = valid_range.get("start_seconds")
    end = valid_range.get("end_seconds")
    if (
        not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
        or not math.isfinite(float(start))
        or not math.isfinite(float(end))
        or source_in < start
        or source_out > end
        or source_out <= source_in
    ):
        _reject(
            "invalid_numeric" if not math.isfinite(float(start)) or not math.isfinite(float(end)) else "source_range_overflow",
            f"requested range for {asset_id} exceeds its approved source range",
            asset_id=asset_id,
            requested={"start_seconds": source_in, "end_seconds": source_out},
            approved=dict(valid_range),
        )


def _require_fact_scope(
    expected: Mapping[str, Any], asset: Mapping[str, Any], *, asset_id: str
) -> None:
    actual = asset.get("fact_scope")
    if (
        not isinstance(actual, Mapping)
        or dict(actual) != dict(expected)
        or list(asset.get("claim_ids") or []) != list(expected.get("claim_ids") or [])
        or asset.get("visual_requirement_id") != expected.get("visual_requirement_id")
    ):
        _reject(
            "fact_scope_violation",
            f"asset {asset_id} does not preserve the clip product-fact scope",
            asset_id=asset_id,
            expected_fact_scope=dict(expected),
            actual_fact_scope=dict(actual) if isinstance(actual, Mapping) else None,
        )
    if asset.get("source_class") not in expected.get("allowed_source_classes", []):
        _reject(
            "fact_scope_violation",
            f"asset {asset_id} has a source class forbidden by the clip fact scope",
            asset_id=asset_id,
        )


def _validate_catalogue_binding(
    timeline: Mapping[str, Any], asset_catalogue: Mapping[str, Any] | None
) -> None:
    if asset_catalogue is None:
        return
    supplied_hash = asset_catalogue.get("catalogue_hash")
    unsigned = dict(asset_catalogue)
    unsigned.pop("catalogue_hash", None)
    if not isinstance(supplied_hash, str) or supplied_hash != canonical_digest(unsigned):
        _reject("catalogue_hash_mismatch", "approved asset catalogue hash is invalid")
    expected_timeline_hash = canonical_digest(timeline)
    if asset_catalogue.get("timeline_hash") != expected_timeline_hash:
        _reject(
            "catalogue_binding_mismatch",
            "approved asset catalogue is bound to another timeline snapshot",
            expected_timeline_hash=expected_timeline_hash,
        )
    for field in ("base_generation_id", "base_edit_revision", "timeline_id"):
        if asset_catalogue.get(field) != timeline.get(field):
            _reject(
                "catalogue_binding_mismatch",
                f"approved asset catalogue {field} does not match timeline",
                field=field,
            )
    source_hashes = asset_catalogue.get("source_artifact_hashes")
    if source_hashes != timeline.get("source_artifact_hashes"):
        _reject(
            "catalogue_binding_mismatch",
            "approved asset catalogue source snapshot does not match timeline",
        )
    if not isinstance(asset_catalogue.get("candidate_id"), str) or not isinstance(asset_catalogue.get("project_id"), str):
        _reject("catalogue_binding_mismatch", "approved asset catalogue ownership is required")


def _all_clip_ids(timeline: Mapping[str, Any]) -> set[str]:
    return {
        str(clip.get("id"))
        for track in timeline.get("tracks", [])
        if isinstance(track, Mapping)
        for clip in track.get("clips", [])
        if isinstance(clip, Mapping) and isinstance(clip.get("id"), str)
    }


def _validate_fact_bound_timing(
    timeline: Mapping[str, Any], clip: Mapping[str, Any], *, start: float, end: float
) -> None:
    if end <= start:
        _reject("invalid_numeric", "timing end must be greater than start")
    claims = set(clip.get("claim_ids") or [])
    if not claims:
        return
    if _fact_bound_interval_covers(timeline, claims=claims, start=start, end=end):
        return
    _reject(
        "fact_bound_timing_violation",
        "text timing must remain within contiguous fact-bound video coverage",
        clip_id=clip.get("id"),
    )


def _fact_bound_interval_covers(
    timeline: Mapping[str, Any], *, claims: set[str], start: float, end: float
) -> bool:
    intervals_by_scope: dict[str, list[tuple[float, float]]] = {}
    for track in timeline.get("tracks", []):
        if not isinstance(track, Mapping) or track.get("kind") != "video":
            continue
        for video in track.get("clips", []):
            if not isinstance(video, Mapping):
                continue
            scope = video.get("fact_scope")
            if not isinstance(scope, Mapping) or not claims.issubset(set(scope.get("claim_ids") or [])):
                continue
            speed = _finite_number(video.get("speed", 1.0), field="video.speed")
            video_start = _finite_number(video.get("start_seconds"), field="video.start_seconds")
            video_end = video_start + (
                _finite_number(video.get("source_out_seconds"), field="video.source_out_seconds")
                - _finite_number(video.get("source_in_seconds"), field="video.source_in_seconds")
            ) / speed
            intervals_by_scope.setdefault(canonical_digest(dict(scope)), []).append(
                (video_start, video_end)
            )
    for intervals in intervals_by_scope.values():
        merged_start: float | None = None
        merged_end: float | None = None
        for interval_start, interval_end in sorted(intervals):
            if merged_start is None or interval_start > merged_end + 1e-9:
                if merged_start is not None and merged_start <= start and end <= merged_end:
                    return True
                merged_start, merged_end = interval_start, interval_end
            else:
                merged_end = max(merged_end, interval_end)
        if merged_start is not None and merged_start <= start and end <= merged_end:
            return True
    return False


def _validate_all_fact_bound_timing(timeline: Mapping[str, Any]) -> None:
    for track in timeline.get("tracks", []):
        if not isinstance(track, Mapping) or track.get("kind") not in {"text", "subtitle"}:
            continue
        for clip in track.get("clips", []):
            if not isinstance(clip, Mapping) or not clip.get("claim_ids"):
                continue
            start = _finite_number(clip.get("start_seconds"), field=f"{track.get('kind')}.start_seconds")
            end = _finite_number(clip.get("end_seconds"), field=f"{track.get('kind')}.end_seconds")
            claims = set(clip.get("claim_ids") or [])
            if not _fact_bound_interval_covers(
                timeline, claims=claims, start=start, end=end
            ):
                _reject(
                    "fact_bound_timing_violation",
                    "claim-bearing text is not covered by contiguous compatible video clips",
                    clip_id=clip.get("id"),
                )


def _validate_primary_video_overlaps(timeline: Mapping[str, Any]) -> None:
    for track in timeline.get("tracks", []):
        if not isinstance(track, Mapping) or track.get("kind") != "video":
            continue
        intervals: list[tuple[float, float, str]] = []
        for clip in track.get("clips", []):
            speed = _finite_number(clip.get("speed", 1.0), field="video.speed")
            if speed <= 0:
                _reject(
                    "invalid_speed", "video speed must be positive", clip_id=clip.get("id")
                )
            start = _finite_number(clip.get("start_seconds"), field="video.start_seconds")
            end = start + (
                _finite_number(clip.get("source_out_seconds"), field="video.source_out_seconds")
                - _finite_number(clip.get("source_in_seconds"), field="video.source_in_seconds")
            ) / speed
            intervals.append((start, end, str(clip.get("id"))))
        intervals.sort()
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                _reject(
                    "overlapping_primary_clips",
                    f"video clips {previous[2]} and {current[2]} overlap",
                    track_id=track.get("id"),
                    clip_ids=[previous[2], current[2]],
                )


def _validate_changed_video_binding(
    clip: Mapping[str, Any], asset_catalogue: Mapping[str, Any] | None
) -> None:
    asset_id = str(clip["asset_id"])
    asset = _catalogue_asset(asset_catalogue, asset_id)
    _require_hash(asset, clip.get("source_sha256"), asset_id=asset_id)
    _require_source_range(
        asset,
        float(clip["source_in_seconds"]),
        float(clip["source_out_seconds"]),
        asset_id=asset_id,
    )
    fact_scope = clip.get("fact_scope")
    if not isinstance(fact_scope, Mapping):
        _reject("fact_scope_violation", f"clip {clip.get('id')} has no fact scope")
    _require_fact_scope(fact_scope, asset, asset_id=asset_id)


def _set_fields(clip: dict[str, Any], operation: Mapping[str, Any], *fields: str) -> None:
    for field in fields:
        if field in operation:
            clip[field] = operation[field]


def apply_delta(
    timeline: Mapping[str, Any],
    delta: Mapping[str, Any],
    *,
    asset_catalogue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a typed edit without mutating the source timeline.

    Asset-changing operations are authorized exclusively by the server-issued
    catalogue. Moves are deliberately non-ripple and affect only their track.
    """
    source = deepcopy(dict(timeline))
    request = deepcopy(dict(delta))
    _validate_catalogue_binding(source, asset_catalogue)
    if request.get("base_generation_id") != source.get("base_generation_id"):
        _reject("stale_generation", "delta targets another generation")
    expected_hash = canonical_digest(source)
    if request.get("base_timeline_hash") != expected_hash:
        _reject(
            "stale_timeline",
            "delta base timeline hash is stale",
            expected_timeline_hash=expected_hash,
        )
    operations = request.get("operations")
    if not isinstance(operations, list) or not operations:
        _reject("invalid_delta", "delta must contain at least one operation")

    for operation_index, operation in enumerate(operations, start=1):
        if not isinstance(operation, Mapping):
            _reject("invalid_delta", "each operation must be an object")
        operation_name = operation.get("op")
        track_id = operation.get("track_id")
        clip_id = operation.get("clip_id")
        if not isinstance(operation_name, str) or not isinstance(track_id, str):
            _reject("invalid_delta", "operation and track IDs are required")
        _validate_operation_numbers(operation)
        track = _timeline_track(source, track_id)

        if operation_name == "add_clip":
            _require_track_kind(track, {"video"}, operation=operation_name)
            clip = deepcopy(operation.get("clip"))
            if not isinstance(clip, dict):
                _reject("invalid_delta", "add_clip requires a video clip")
            if any(existing.get("id") == clip.get("id") for existing in track["clips"]):
                _reject("duplicate_clip_id", f"clip {clip.get('id')} already exists")
            if clip.get("id") in _all_clip_ids(source):
                _reject("duplicate_clip_id", f"clip {clip.get('id')} already exists")
            track["clips"].append(clip)
            _validate_changed_video_binding(clip, asset_catalogue)
        else:
            if not isinstance(clip_id, str):
                _reject("invalid_delta", f"{operation_name} requires clip_id")
            clip_index, clip = _timeline_clip(track, clip_id)

            if operation_name == "remove_clip":
                track["clips"].pop(clip_index)
            elif operation_name == "move_clip":
                _require_track_kind(track, {"video"}, operation=operation_name)
                clip["start_seconds"] = operation.get("start_seconds")
            elif operation_name == "split_clip":
                _require_track_kind(track, {"video"}, operation=operation_name)
                at = operation.get("at_seconds")
                speed = _finite_number(clip.get("speed", 1.0), field="video.speed")
                timeline_start = _finite_number(clip.get("start_seconds"), field="video.start_seconds")
                timeline_end = timeline_start + (
                    _finite_number(clip.get("source_out_seconds"), field="video.source_out_seconds")
                    - _finite_number(clip.get("source_in_seconds"), field="video.source_in_seconds")
                ) / speed
                if not isinstance(at, (int, float)) or not timeline_start < at < timeline_end:
                    _reject(
                        "invalid_split_point",
                        "split point must be inside the clip timeline range",
                        clip_id=clip_id,
                    )
                source_at = float(clip["source_in_seconds"]) + (float(at) - timeline_start) * speed
                left = deepcopy(clip)
                right = deepcopy(clip)
                left["source_out_seconds"] = source_at
                child_id = f"{clip_id}-split-{operation_index}"
                if child_id in _all_clip_ids(source):
                    _reject("duplicate_clip_id", f"split child ID {child_id} already exists")
                right.update({
                    "id": child_id,
                    "source_in_seconds": source_at,
                    "start_seconds": float(at),
                })
                track["clips"][clip_index:clip_index + 1] = [left, right]
                _validate_changed_video_binding(left, asset_catalogue)
                _validate_changed_video_binding(right, asset_catalogue)
            elif operation_name == "trim_clip":
                _require_track_kind(track, {"video"}, operation=operation_name)
                _set_fields(clip, operation, "source_in_seconds", "source_out_seconds")
                _validate_changed_video_binding(clip, asset_catalogue)
            elif operation_name == "replace_clip":
                _require_track_kind(track, {"video"}, operation=operation_name)
                replacement = _catalogue_asset(asset_catalogue, str(operation.get("asset_id")))
                _require_hash(
                    replacement,
                    operation.get("source_sha256"),
                    asset_id=str(operation.get("asset_id")),
                )
                fact_scope = clip.get("fact_scope")
                if not isinstance(fact_scope, Mapping):
                    _reject("fact_scope_violation", f"clip {clip_id} has no fact scope")
                _require_fact_scope(
                    fact_scope, replacement, asset_id=str(operation.get("asset_id"))
                )
                _set_fields(
                    clip,
                    operation,
                    "asset_id", "source_sha256", "source_in_seconds", "source_out_seconds",
                )
                _validate_changed_video_binding(clip, asset_catalogue)
            elif operation_name == "set_speed":
                _require_track_kind(track, {"video"}, operation=operation_name)
                speed = operation.get("speed")
                if not isinstance(speed, (int, float)) or isinstance(speed, bool) or speed <= 0:
                    _reject("invalid_speed", "video speed must be positive", clip_id=clip_id)
                clip["speed"] = float(speed)
            elif operation_name == "set_transition":
                _require_track_kind(track, {"video"}, operation=operation_name)
                clip["transition"] = operation.get("transition")
            elif operation_name == "move_audio":
                _require_track_kind(track, {"narration", "music"}, operation=operation_name)
                duration = _finite_number(clip.get("end_seconds"), field="audio.end_seconds") - _finite_number(clip.get("start_seconds"), field="audio.start_seconds")
                clip["start_seconds"] = operation.get("start_seconds")
                clip["end_seconds"] = _finite_number(operation.get("start_seconds"), field="move_audio.start_seconds") + duration
            elif operation_name == "set_gain":
                _require_track_kind(track, {"narration", "music"}, operation=operation_name)
                clip["gain_db"] = operation.get("gain_db")
            elif operation_name == "set_fade":
                _require_track_kind(track, {"narration", "music"}, operation=operation_name)
                _set_fields(clip, operation, "fade_in_seconds", "fade_out_seconds")
            elif operation_name == "set_ducking":
                _require_track_kind(track, {"music"}, operation=operation_name)
                clip["ducking"] = {
                    "enabled": operation.get("enabled"),
                    "reduction_db": operation.get("reduction_db"),
                }
            elif operation_name in {"replace_narration", "replace_music"}:
                expected_kind = "narration" if operation_name == "replace_narration" else "music"
                _require_track_kind(track, {expected_kind}, operation=operation_name)
                replacement = _catalogue_asset(asset_catalogue, str(operation.get("asset_id")))
                _require_hash(
                    replacement,
                    operation.get("source_sha256"),
                    asset_id=str(operation.get("asset_id")),
                )
                if replacement.get("media_kind") != "audio":
                    _reject(
                        "asset_media_kind_violation",
                        f"asset {operation.get('asset_id')} is not approved audio",
                    )
                if replacement.get("role") != expected_kind:
                    _reject(
                        "asset_role_violation",
                        f"asset {operation.get('asset_id')} is not approved for {expected_kind}",
                    )
                _set_fields(clip, operation, "asset_id", "source_sha256")
            elif operation_name == "set_caption_text":
                _require_track_kind(track, {"subtitle"}, operation=operation_name)
                clip["text"] = operation.get("text")
            elif operation_name == "set_caption_timing":
                _require_track_kind(track, {"subtitle"}, operation=operation_name)
                _set_fields(clip, operation, "start_seconds", "end_seconds")
                _validate_fact_bound_timing(
                    source,
                    clip,
                    start=_finite_number(clip.get("start_seconds"), field="caption.start_seconds"),
                    end=_finite_number(clip.get("end_seconds"), field="caption.end_seconds"),
                )
            elif operation_name == "set_text_style":
                _require_track_kind(track, {"text"}, operation=operation_name)
                _set_fields(clip, operation, "style_token", "position")
            elif operation_name == "set_text_timing":
                _require_track_kind(track, {"text"}, operation=operation_name)
                _set_fields(clip, operation, "start_seconds", "end_seconds")
                _validate_fact_bound_timing(
                    source,
                    clip,
                    start=_finite_number(clip.get("start_seconds"), field="text.start_seconds"),
                    end=_finite_number(clip.get("end_seconds"), field="text.end_seconds"),
                )
            elif operation_name == "set_enabled":
                _require_track_kind(track, {"text", "subtitle"}, operation=operation_name)
                clip["enabled"] = operation.get("enabled")
            else:
                _reject(
                    "unsupported_operation",
                    f"operation {operation_name} is not supported",
                    operation=operation_name,
                )

    _validate_primary_video_overlaps(source)
    _validate_all_fact_bound_timing(source)
    try:
        validate_artifact("editorial_timeline", source)
        validate_artifact("editorial_edit_delta", request)
    except Exception as exc:
        _reject("invalid_delta_result", "delta produced an invalid timeline", reason=str(exc))
    return {"timeline": source, "timeline_hash": canonical_digest(source)}


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EditorialMaterializationError(f"{field} must be an object")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise EditorialMaterializationError(f"{field} must be a sha256")
    return value


def _number(value: Any, *, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise EditorialMaterializationError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise EditorialMaterializationError(f"{field} must be finite")
    return result


def _artifact_hash(artifact: Mapping[str, Any], *, field: str) -> str:
    value = dict(artifact)
    if "artifact_sha256" in value:
        if not verify_hashes(value).valid:
            raise EditorialMaterializationError(f"{field} artifact hash verification failed")
    return semantic_sha256(value)


def _asset_index(asset_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    assets = asset_manifest.get("assets")
    if not isinstance(assets, list):
        raise EditorialMaterializationError("asset_manifest.assets must be a list")
    return {
        str(asset["id"]): asset for asset in assets
        if isinstance(asset, Mapping) and isinstance(asset.get("id"), str)
    }


def _approved_audio(
    assets: Mapping[str, Mapping[str, Any]], supplied: Mapping[str, Any], *, role: str
) -> tuple[str, str]:
    asset_id = supplied.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id:
        raise EditorialMaterializationError(f"{role}.asset_id is required")
    asset = assets.get(asset_id)
    if asset is None or asset.get("approved") is not True or asset.get("type") != "audio":
        raise EditorialMaterializationError(f"{role}.asset_id must be an approved audio asset")
    if asset.get("role") != role:
        raise EditorialMaterializationError(f"{role}.asset_id has the wrong audio role")
    return asset_id, _sha256(asset.get("sha256"), field=f"{role} asset sha256")


def _scene_time(scene: Mapping[str, Any], *, fps: float, field: str) -> tuple[float, float]:
    start = _number(scene.get("fromFrame"), field=f"{field}.fromFrame") / fps
    end = _number(scene.get("toFrameExclusive"), field=f"{field}.toFrameExclusive") / fps
    if start < 0 or end <= start:
        raise EditorialMaterializationError(f"{field} has an invalid timeline range")
    return start, end


def materialize_editorial_timeline(
    *,
    candidate_id: str,
    project_id: str,
    base_generation_id: str,
    base_edit_revision: str,
    edit_decisions: Mapping[str, Any],
    final_props: Mapping[str, Any],
    asset_manifest: Mapping[str, Any],
    coverage_matrix: Mapping[str, Any],
    product_facts: Mapping[str, Any],
    source_media_evidence: Mapping[str, Any],
    source_videos: Mapping[str, Any] | list[Mapping[str, Any]],
    shot_execution_plan: Mapping[str, Any] | None = None,
    generation_tasks: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
    narration: Mapping[str, Any],
    bgm: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a five-track snapshot, rejecting unproven material before rendering."""
    identifiers = (
        ("candidate_id", candidate_id),
        ("project_id", project_id),
        ("base_generation_id", base_generation_id),
        ("base_edit_revision", base_edit_revision),
    )
    for field, value in identifiers:
        if not isinstance(value, str) or not value:
            raise EditorialMaterializationError(f"{field} must be a non-empty string")
    edit_decisions = _mapping(edit_decisions, field="edit_decisions")
    final_props = _mapping(final_props, field="final_props")
    asset_manifest = _mapping(asset_manifest, field="asset_manifest")
    product_facts = _mapping(product_facts, field="product_facts")
    narration = _mapping(narration, field="narration")
    bgm = _mapping(bgm, field="bgm")
    if edit_decisions.get("render_runtime") != "remotion":
        raise EditorialMaterializationError("editorial timelines require the remotion runtime")

    catalogue = build_editorial_asset_catalogue(
        candidate_id=candidate_id,
        project_id=project_id,
        asset_manifest=asset_manifest,
        coverage_matrix=coverage_matrix,
        product_facts=product_facts,
        source_media_evidence=source_media_evidence,
        source_videos=source_videos,
        shot_execution_plan=shot_execution_plan,
        generation_tasks=generation_tasks,
    )
    fps = _number(final_props.get("fps"), field="final_props.fps")
    if fps <= 0:
        raise EditorialMaterializationError("final_props.fps must be positive")
    scenes = final_props.get("scenes")
    cuts = edit_decisions.get("cuts")
    if not isinstance(scenes, list) or not isinstance(cuts, list) or not cuts:
        raise EditorialMaterializationError(
            "approved final_props scenes and edit_decisions cuts are required"
        )
    scene_by_id = {
        str(scene["id"]): scene for scene in scenes
        if isinstance(scene, Mapping) and isinstance(scene.get("id"), str)
    }
    catalogue_by_row = {asset["matrix_row_id"]: asset for asset in catalogue["assets"]}
    video_clips: list[dict[str, Any]] = []
    text_clips: list[dict[str, Any]] = []
    for cut in cuts:
        if not isinstance(cut, Mapping) or not isinstance(cut.get("id"), str):
            raise EditorialMaterializationError("edit_decisions cut id is required")
        shot_id = cut["id"]
        scene = scene_by_id.get(shot_id)
        if scene is None:
            raise EditorialMaterializationError(f"cut {shot_id} has no approved final_props scene")
        row_ids = scene.get("evidence_row_ids")
        if not isinstance(row_ids, list) or len(row_ids) != 1 or not isinstance(row_ids[0], str):
            raise EditorialMaterializationError(f"scene {shot_id} requires exactly one accepted coverage row")
        approved = catalogue_by_row.get(row_ids[0])
        if approved is None:
            raise EditorialMaterializationError(f"scene {shot_id} has no accepted coverage")
        if approved.get("shot_id") != shot_id:
            raise EditorialMaterializationError(
                f"scene {shot_id} does not match shot execution plan"
            )
        scene_claims = scene.get("claim_ids")
        if not isinstance(scene_claims, list) or scene_claims != approved["claim_ids"]:
            raise EditorialMaterializationError(f"scene {shot_id} claim ids do not match accepted coverage")
        start, end = _scene_time(scene, fps=fps, field=f"scene {shot_id}")
        source_in = _number(
            scene.get("sourceInSeconds"),
            field=f"scene {shot_id}.sourceInSeconds",
        )
        source_out = _number(
            scene.get("sourceOutSeconds"),
            field=f"scene {shot_id}.sourceOutSeconds",
        )
        valid_range = approved["valid_range"]
        if (
            source_in < valid_range["start_seconds"]
            or source_out > valid_range["end_seconds"]
            or source_out <= source_in
        ):
            raise EditorialMaterializationError(f"scene {shot_id} exceeds approved source range")
        fact_scope = dict(approved["fact_scope"])
        video_clips.append({
            "id": f"video-{shot_id}", "asset_id": approved["asset_id"],
            "source_sha256": approved["source_sha256"], "source_in_seconds": source_in,
            "source_out_seconds": source_out, "start_seconds": start,
            "fact_scope": fact_scope,
        })
        screen_copy = scene.get("screen_copy")
        if not isinstance(screen_copy, str) or not screen_copy.strip():
            raise EditorialMaterializationError(f"scene {shot_id} lacks approved selling-point text")
        text_clips.append({
            "id": f"text-{shot_id}", "text": screen_copy.strip(), "start_seconds": start,
            "end_seconds": end, "style_token": "taobao_selling_point_v1",
            "position": "top_center", "claim_ids": list(scene_claims),
        })

    assets = _asset_index(asset_manifest)
    narration_source_id, narration_hash = _approved_audio(
        assets, narration, role="narration"
    )
    narration_start = _number(
        narration.get("start_seconds"), field="narration.start_seconds"
    )
    narration_end = _number(
        narration.get("end_seconds"), field="narration.end_seconds"
    )
    narration_text = narration.get("text")
    narration_claims = narration.get("claim_ids")
    if (
        narration_end <= narration_start
        or not isinstance(narration_text, str)
        or not narration_text.strip()
        or not isinstance(narration_claims, list)
        or not narration_claims
    ):
        raise EditorialMaterializationError("narration must have text, claims, and a positive range")
    fact_ids = {
        str(claim.get("id", claim.get("claim_id")))
        for claim in (product_facts.get("claims") or [])
        if isinstance(claim, Mapping) and claim.get("id", claim.get("claim_id"))
    }
    if any(claim not in fact_ids for claim in narration_claims):
        raise EditorialMaterializationError("narration claim is outside product facts")
    music_source_id, music_hash = _approved_audio(assets, bgm, role="music")
    music_start = _number(bgm.get("start_seconds"), field="bgm.start_seconds")
    music_end = _number(bgm.get("end_seconds"), field="bgm.end_seconds")
    if music_end <= music_start:
        raise EditorialMaterializationError("bgm must have a positive range")

    # Audio assets participate in the same server-issued catalogue as visual
    # assets so replacement operations cannot inject arbitrary files.
    catalogue_assets = list(catalogue.get("assets") or [])
    audio_ids: dict[str, str] = {}
    for source_asset_id, audio_asset in assets.items():
        if (
            audio_asset.get("approved") is not True
            or audio_asset.get("type") != "audio"
            or audio_asset.get("role") not in {"narration", "music"}
        ):
            continue
        source_hash = _sha256(
            audio_asset.get("sha256"),
            field=f"asset_manifest {source_asset_id}.sha256",
        )
        issued_id = "editorial-audio-" + canonical_digest({
            "candidate_id": candidate_id,
            "project_id": project_id,
            "source_asset_id": source_asset_id,
            "source_sha256": source_hash,
            "role": audio_asset.get("role"),
        })[:24]
        audio_ids[source_asset_id] = issued_id
        catalogue_assets.append({
            "asset_id": issued_id,
            "candidate_id": candidate_id,
            "project_id": project_id,
            "source_asset_id": source_asset_id,
            "source_sha256": source_hash,
            "media_kind": "audio",
            "role": audio_asset.get("role"),
            "provenance": {"source": "asset_manifest", "asset_id": source_asset_id},
        })
    narration_id = audio_ids.get(narration_source_id, narration_source_id)
    music_id = audio_ids.get(music_source_id, music_source_id)
    catalogue = {**catalogue, "assets": catalogue_assets}

    subtitle_clips: list[dict[str, Any]] = []
    captions = final_props.get("captions")
    if not isinstance(captions, list) or not captions:
        raise EditorialMaterializationError("final_props captions are required")
    for index, caption in enumerate(captions, start=1):
        if (
            not isinstance(caption, Mapping)
            or not isinstance(caption.get("text"), str)
            or not caption["text"].strip()
        ):
            raise EditorialMaterializationError("final_props caption text is required")
        start = _number(caption.get("startMs"), field="caption.startMs") / 1000
        end = _number(caption.get("endMs"), field="caption.endMs") / 1000
        matching_video = next(
            (
                clip for clip in video_clips
                if clip["start_seconds"] <= start
                and end <= (
                    clip["start_seconds"]
                    + clip["source_out_seconds"]
                    - clip["source_in_seconds"]
                )
            ),
            None,
        )
        if end <= start or matching_video is None:
            raise EditorialMaterializationError(
                "caption must stay within one fact-bound video clip"
            )
        claims = matching_video["fact_scope"]["claim_ids"]
        subtitle_clips.append({
            "id": f"subtitle-{index}", "text": caption["text"].strip(), "start_seconds": start,
            "end_seconds": end, "style_token": "taobao_subtitle_v1", "position": "bottom_center",
            "claim_ids": claims, "original_text_sha256": canonical_digest({"text": caption["text"].strip()}),
        })

    timeline = {
        "version": "1.0",
        "timeline_id": "editorial-" + canonical_digest({
            "candidate_id": candidate_id,
            "project_id": project_id,
            "revision": base_edit_revision,
        })[:24],
        "profile": {
            "profile_id": "taobao-detail-3-4", "aspect_ratio": "3:4",
            "width": int(_number(final_props.get("width"), field="final_props.width")),
            "height": int(_number(final_props.get("height"), field="final_props.height")),
            "fps": int(fps), "render_runtime": "remotion", "safe_zone": "taobao_detail_3_4",
        },
        "base_generation_id": base_generation_id,
        "base_edit_revision": base_edit_revision,
        "source_artifact_hashes": {
            "edit_decisions": _artifact_hash(edit_decisions, field="edit_decisions"),
            "final_props": _artifact_hash(final_props, field="final_props"),
            "asset_manifest": _artifact_hash(asset_manifest, field="asset_manifest"),
            "coverage_matrix": _artifact_hash(
                _mapping(coverage_matrix, field="coverage_matrix"),
                field="coverage_matrix",
            ),
            "product_facts": _artifact_hash(product_facts, field="product_facts"),
        },
        "tracks": [
            {"id": "video-main", "kind": "video", "clips": video_clips},
            {"id": "narration-main", "kind": "narration", "clips": [{
                "id": "narration-main-001", "asset_id": narration_id, "source_sha256": narration_hash,
                "start_seconds": narration_start, "end_seconds": narration_end,
                "claim_ids": list(narration_claims),
                "original_text_sha256": canonical_digest({"text": narration_text.strip()}),
            }]},
            {"id": "music-main", "kind": "music", "clips": [{
                "id": "music-main-001", "asset_id": music_id, "source_sha256": music_hash,
                "start_seconds": music_start, "end_seconds": music_end,
            }]},
            {"id": "text-main", "kind": "text", "clips": text_clips},
            {"id": "subtitle-main", "kind": "subtitle", "clips": subtitle_clips},
        ],
    }
    # Bind the read-only catalogue to this exact timeline snapshot and source
    # artifact set. The hash excludes its own field to remain recomputable.
    catalogue = {
        **catalogue,
        "timeline_id": timeline["timeline_id"],
        "base_generation_id": base_generation_id,
        "base_edit_revision": base_edit_revision,
        "timeline_hash": canonical_digest(timeline),
        "source_artifact_hashes": dict(timeline["source_artifact_hashes"]),
    }
    catalogue.pop("catalogue_hash", None)
    catalogue["catalogue_hash"] = canonical_digest(catalogue)
    validate_artifact("editorial_timeline", timeline)
    return {"timeline": timeline, "asset_catalogue": catalogue}


def project_timeline_for_compose(
    timeline: Mapping[str, Any],
    *,
    asset_catalogue: Mapping[str, Any],
    asset_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Adapt the canonical timeline into explicit Remotion composition props.

    The adapter is intentionally strict: only the locked Remotion contract is
    projected and every media reference is resolved through the server-owned
    catalogue/manifest pair.  Unsupported runtime features fail before a
    renderer is invoked instead of being silently dropped.
    """
    source = deepcopy(dict(timeline))
    profile = source.get("profile")
    if not isinstance(profile, Mapping) or profile.get("render_runtime") != "remotion":
        _reject(
            "unsupported_delivery_operation",
            "editorial composition is locked to the remotion runtime",
            render_runtime=profile.get("render_runtime") if isinstance(profile, Mapping) else None,
        )
    # The catalogue is bound to the base snapshot.  A validated EditDelta
    # legitimately changes the current timeline hash, so only immutable
    # generation/revision/source ownership is checked here.
    if asset_catalogue.get("base_generation_id") != source.get("base_generation_id") or asset_catalogue.get("base_edit_revision") != source.get("base_edit_revision"):
        _reject("catalogue_binding_mismatch", "approved asset catalogue belongs to another revision")
    manifest_assets = asset_manifest.get("assets") if isinstance(asset_manifest, Mapping) else None
    if not isinstance(manifest_assets, list):
        _reject("unsupported_delivery_operation", "asset manifest is required for composition")
    manifest_by_id = {
        item.get("id"): item for item in manifest_assets
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    catalogue_by_id = {
        item.get("asset_id"): item for item in (asset_catalogue.get("assets") or [])
        if isinstance(item, Mapping) and isinstance(item.get("asset_id"), str)
    }
    fps = int(profile.get("fps") or 30)
    if fps <= 0:
        _reject("unsupported_delivery_operation", "timeline fps must be positive")

    def media_source(clip: Mapping[str, Any], *, audio: bool = False) -> str:
        asset_id = clip.get("asset_id")
        catalogue_asset = catalogue_by_id.get(asset_id)
        if catalogue_asset is None:
            _reject("unsupported_delivery_operation", f"asset {asset_id} is not in the approved catalogue", asset_id=asset_id)
        manifest_id = catalogue_asset.get("source_asset_id")
        item = manifest_by_id.get(manifest_id)
        if item is None or not isinstance(item.get("path"), str) or not item.get("path"):
            _reject("unsupported_delivery_operation", f"asset {asset_id} has no renderable path", asset_id=asset_id)
        if audio and item.get("type") != "audio":
            _reject("unsupported_delivery_operation", f"asset {asset_id} is not audio", asset_id=asset_id)
        if not audio and item.get("type") != "video":
            _reject("unsupported_delivery_operation", f"asset {asset_id} is not video", asset_id=asset_id)
        return str(item["path"])

    order = {"video": 0, "narration": 1, "music": 2, "text": 3, "subtitle": 4}
    projected_tracks: list[dict[str, Any]] = []
    max_end = 0.0
    for track in sorted(
        (item for item in source.get("tracks", []) if isinstance(item, Mapping)),
        key=lambda item: (order.get(str(item.get("kind")), 99), str(item.get("id", ""))),
    ):
        kind = str(track.get("kind"))
        if kind not in order:
            _reject("unsupported_delivery_operation", f"track kind {kind} is not supported")
        clips: list[dict[str, Any]] = []
        for clip in sorted(
            (item for item in track.get("clips", []) if isinstance(item, Mapping)),
            key=lambda item: (float(item.get("start_seconds", 0)), str(item.get("id", ""))),
        ):
            start = _finite_number(clip.get("start_seconds"), field=f"{kind}.start_seconds")
            end = _finite_number(clip.get("end_seconds"), field=f"{kind}.end_seconds") if kind in {"narration", "music", "text", "subtitle"} else None
            speed = _finite_number(clip.get("speed", 1.0), field="video.speed") if kind == "video" else 1.0
            if speed <= 0:
                _reject("unsupported_delivery_operation", "video speed must be positive", clip_id=clip.get("id"))
            if kind == "video":
                _validate_changed_video_binding(clip, asset_catalogue)
                source_in = _finite_number(clip.get("source_in_seconds"), field="video.source_in_seconds")
                source_out = _finite_number(clip.get("source_out_seconds"), field="video.source_out_seconds")
                duration = (source_out - source_in) / speed
                if duration <= 0:
                    _reject("unsupported_delivery_operation", "video source range must be positive", clip_id=clip.get("id"))
                end = start + duration
            assert end is not None
            if end <= start:
                _reject("unsupported_delivery_operation", "clip range must be positive", clip_id=clip.get("id"))
            max_end = max(max_end, end)
            item: dict[str, Any] = {
                "id": str(clip.get("id")),
                "startFrame": round(start * fps),
                "durationInFrames": max(1, round((end - start) * fps)),
            }
            if kind == "video":
                transition = clip.get("transition", "cut")
                if transition not in {"cut", "fade", "crossfade"}:
                    _reject("unsupported_delivery_operation", f"transition {transition} is not supported", clip_id=clip.get("id"))
                item.update({
                    "source": media_source(clip),
                    "sourceInSeconds": source_in,
                    "sourceOutSeconds": source_out,
                    "playbackRate": speed,
                    "zIndex": int(clip.get("z_index", 0)),
                    "transition": transition,
                    "fadeInSeconds": float(clip.get("fade_in_seconds", 0) or 0),
                    "fadeOutSeconds": float(clip.get("fade_out_seconds", 0) or 0),
                    "transform": {
                        "scale": (clip.get("transform") or {}).get("scale", 1),
                        "x": (clip.get("transform") or {}).get("x", 0),
                        "y": (clip.get("transform") or {}).get("y", 0),
                        "rotationDegrees": (clip.get("transform") or {}).get("rotation_degrees", 0),
                    },
                })
            elif kind in {"narration", "music"}:
                approved_audio = catalogue_by_id.get(clip.get("asset_id"))
                if (
                    approved_audio is None
                    or approved_audio.get("media_kind") != "audio"
                    or approved_audio.get("role") != kind
                    or approved_audio.get("source_sha256") != clip.get("source_sha256")
                ):
                    _reject(
                        "unsupported_delivery_operation",
                        f"audio asset {clip.get('asset_id')} is not approved for {kind}",
                        asset_id=clip.get("asset_id"),
                    )
                item.update({
                    "source": media_source(clip, audio=True),
                    "gainDb": float(clip.get("gain_db", 0) or 0),
                    "fadeInSeconds": float(clip.get("fade_in_seconds", 0) or 0),
                    "fadeOutSeconds": float(clip.get("fade_out_seconds", 0) or 0),
                })
                if kind == "music":
                    ducking = clip.get("ducking") or {}
                    item["ducking"] = {
                        "enabled": bool(ducking.get("enabled", False)),
                        "reductionDb": float(ducking.get("reduction_db", 0) or 0),
                    }
            else:
                item.update({
                    "text": str(clip.get("text", "")),
                    "position": str(clip.get("position")),
                    "styleToken": str(clip.get("style_token")),
                    "claimIds": list(clip.get("claim_ids") or []),
                    "enabled": clip.get("enabled", True),
                })
            clips.append(item)
        projected_tracks.append({"id": str(track.get("id")), "kind": kind, "clips": clips})

    return {
        "renderer_family": "editorial-timeline",
        "composition_id": "EditorialTimeline",
        "durationInFrames": max(1, round(max_end * fps)),
        "editorialTimeline": {
            "fps": fps,
            "width": int(profile.get("width")),
            "height": int(profile.get("height")),
            "safeZone": profile.get("safe_zone"),
            "tracks": projected_tracks,
        },
    }
