"""Validation for the single production timeline consumed by Remotion."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


class FinalPropsError(ValueError):
    """Raised when final render properties cannot describe a contiguous edit."""


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FinalPropsError(f"{field} must be numeric")
    return float(value)


def _validate_source_window(
    scene: Mapping[str, Any],
    fps: int,
    *,
    probe_map: Mapping[str, float] | None,
    prefix: str,
) -> None:
    mode = scene.get("playbackMode", "normal")
    if mode not in {"normal", "loop", "hold"}:
        raise FinalPropsError(f"{prefix} has unknown playbackMode")
    if mode == "hold":
        return
    for field in ("sourceInSeconds", "sourceOutSeconds"):
        if field not in scene:
            raise FinalPropsError(f"{prefix} missing {field}")
    source_in = _number(scene["sourceInSeconds"], f"{prefix}.sourceInSeconds")
    source_out = _number(scene["sourceOutSeconds"], f"{prefix}.sourceOutSeconds")
    rate = _number(scene.get("playbackRate", 1.0), f"{prefix}.playbackRate")
    if source_in < 0 or source_out <= source_in or rate <= 0:
        raise FinalPropsError(f"{prefix} has invalid source window or playbackRate")
    footage_key = scene.get("footageKey")
    if probe_map and footage_key in probe_map and source_out > float(probe_map[footage_key]) + 1e-6:
        raise FinalPropsError(f"{prefix}.sourceOutSeconds exceeds source duration")
    duration = int(scene["durationInFrames"])
    if mode == "normal":
        expected = round((source_out - source_in) * fps / rate)
        if abs(duration - expected) > 1:
            raise FinalPropsError(f"{prefix} source duration and playback speed disagree")


def _validate_range(scene: Mapping[str, Any], expected_from: int, prefix: str) -> int:
    try:
        start = int(scene["fromFrame"])
        end = int(scene["toFrameExclusive"])
        duration = int(scene["durationInFrames"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FinalPropsError(f"{prefix} has incomplete frame range") from exc
    if start < 0 or duration <= 0 or end <= start or end - start != duration:
        raise FinalPropsError(f"{prefix} duration does not match half-open range")
    if start != expected_from:
        raise FinalPropsError(f"timeline gap or overlap before {prefix}")
    return end


def validate_final_props(
    props: dict[str, Any],
    *,
    project_dir: Path | None = None,
    probe_map: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Validate timeline math, media references, and timed overlays.

    ``probe_map`` is injectable so tests and callers with cached ffprobe data do
    not need to invoke FFmpeg.  Paths are checked only when ``project_dir`` is
    supplied; this keeps the validator useful for schema fixtures.
    """
    if not isinstance(props, dict):
        raise FinalPropsError("final props must be an object")
    try:
        fps = int(props["fps"])
        width = int(props["width"])
        height = int(props["height"])
        total = int(props["durationInFrames"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FinalPropsError("fps, width, height, and durationInFrames are required") from exc
    if fps <= 0 or width <= 0 or height <= 0 or total <= 0:
        raise FinalPropsError("fps, dimensions, and duration must be positive")
    scenes = props.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise FinalPropsError("scenes must be a non-empty list")
    footage = props.get("footage")
    if not isinstance(footage, dict):
        raise FinalPropsError("footage must be an object")

    expected_from = 0
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise FinalPropsError(f"scenes[{index}] must be an object")
        prefix = f"scenes[{index}]"
        expected_from = _validate_range(scene, expected_from, prefix)
        key = scene.get("footageKey")
        if not isinstance(key, str) or key not in footage:
            raise FinalPropsError(f"{prefix}.footageKey is not declared in footage")
        nested = scene.get("segments")
        if isinstance(nested, list) and nested:
            nested_from = int(scene["fromFrame"])
            for sub_index, segment in enumerate(nested):
                if not isinstance(segment, dict):
                    raise FinalPropsError(f"{prefix}.segments[{sub_index}] must be an object")
                nested_from = _validate_range(segment, nested_from, f"{prefix}.segments[{sub_index}]")
                _validate_source_window(segment, fps, probe_map=probe_map, prefix=f"{prefix}.segments[{sub_index}]")
            if nested_from != int(scene["toFrameExclusive"]):
                raise FinalPropsError(f"{prefix}.segments do not cover scene range")
        else:
            _validate_source_window(scene, fps, probe_map=probe_map, prefix=prefix)

    if expected_from != total:
        raise FinalPropsError("top-level duration disagrees with scene timeline")

    for index, caption in enumerate(props.get("captions", [])):
        if not isinstance(caption, dict):
            raise FinalPropsError(f"captions[{index}] must be an object")
        start = _number(caption.get("startMs"), f"captions[{index}].startMs")
        end = _number(caption.get("endMs"), f"captions[{index}].endMs")
        if start < 0 or end <= start or end > total * 1000 / fps + 1:
            raise FinalPropsError(f"captions[{index}] is outside the timeline")

    audio = props.get("audio")
    if not isinstance(audio, dict) or not isinstance(audio.get("mix"), str) or not audio["mix"]:
        raise FinalPropsError("audio.mix is required")
    if project_dir is not None:
        root = Path(project_dir).resolve()
        for key, relative in footage.items():
            if not isinstance(relative, str):
                raise FinalPropsError(f"footage.{key} must be a relative path")
            path = (root / "public" / relative).resolve()
            if root not in path.parents and path != root:
                raise FinalPropsError(f"footage.{key} escapes project public directory")
            if not path.is_file():
                raise FinalPropsError(f"footage.{key} does not exist: {relative}")
        audio_path = (root / "public" / audio["mix"]).resolve()
        if not audio_path.is_file():
            raise FinalPropsError(f"audio.mix does not exist: {audio['mix']}")
    return props
