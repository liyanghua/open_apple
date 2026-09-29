"""Deterministic preflight for approved production branding, not a production director.

Results describe source-file preflight, never final rendered QA or human approval.
The optional production section extends the existing brand_profile artifact.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import Image, ImageFont

from schemas.artifacts import validate_artifact


def make_towel_brand_profile(*, profile_id: str = "playboy-production-v1", strict: bool = True,
                             font_files: list[dict] | None = None,
                             font_family: str = "Microsoft YaHei") -> dict:
    """Build merge_brand_defaults-compatible selections without inventing font assets.

    font_files entries: path (on disk), src (Remotion public URL), sha256, weight.
    Callers must bind these values to their approved dependency version.
    """
    return {
        "version": "1.0", "profile_id": profile_id,
        "font": {"family": font_family, "fallbacks": [], "files": copy.deepcopy(font_files or [])},
        "production": {
            "font_mode": "strict" if strict else "legacy_appearance",
            "legacy_font_stack": 'Arial, "Microsoft YaHei", STHeiti, sans-serif',
            "logo": {"right": 72, "top": 96, "width": 120, "clear_space": 16},
            "title": {"left": 72, "top": 220, "font_size": 64, "font_weight": 700,
                      "line_height": 1.15, "characters": [2, 4]},
            "underline": {"height": 8, "gap": 22, "color": "#4874CB", "width": "title"},
            "caption": {"left": 72, "right": 72, "top": 1470, "font_size": 38,
                        "font_weight": 400, "line_height": 1.25},
            "transition": {"frames": 5, "rule": "incoming_only"},
            "slogan": "PLAYBOY，让日常更有质感。", "min_tail_seconds": 0.4,
            "recipe": {"id": "display", "default_raw_seconds": 4,
                       "raw_action_seconds": [3, 5], "body_cut_seconds": [1.8, 2.6]},
        },
    }


def _check(check_id: str, status: str, **evidence: Any) -> dict:
    return {"check_id": check_id, "status": status, "evidence": evidence}


def _number(value: Any, minimum: float = 0, *, positive: bool = False) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (value > minimum if positive else value >= minimum))


def validate_motion_source_metadata(shot: dict, probe: dict) -> dict:
    """Compare declared geometry to actual ffprobe stream data, not container audio duration."""
    try:
        videos = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"]
        if len(videos) != 1:
            raise ValueError("source requires exactly one video stream")
        video = videos[0]
        width, height = int(video["width"]), int(video["height"])
        fps = float(Fraction(str(video.get("avg_frame_rate") or video["r_frame_rate"])))
        duration = float(video["duration"])
        if not all(_number(n, positive=True) for n in (width, height, fps, duration)):
            raise ValueError("source metadata must be finite and positive")
        rotation = video.get("tags", {}).get("rotate", 0)
        if float(rotation) % 360 or any(float(side.get("rotation", 0)) % 360 for side in video.get("side_data_list", [])):
            raise ValueError("source rotation requires normalization before motion framing")
        if video.get("r_frame_rate") and abs(float(Fraction(video["r_frame_rate"])) - fps) > 1e-6:
            raise ValueError("source requires a constant frame-rate baseline")
        declared = shot["framing"]["source"]
        if width != declared["width"] or height != declared["height"]:
            raise ValueError("source width/height differ from declared framing.source")
        if abs(fps - shot["sourceFps"]) > 1e-6:
            raise ValueError("source fps differs from declared sourceFps")
        if abs(duration - shot["sourceDurationSeconds"]) > 1e-6:
            raise ValueError("source duration differs from declared sourceDurationSeconds")
        frame_count = int(video["nb_frames"]) if video.get("nb_frames") not in (None, "N/A", "") else None
        if frame_count is not None and abs(frame_count - duration * fps) > 1e-3:
            raise ValueError("source frame count disagrees with its duration/fps baseline")
        return {"width": width, "height": height, "fps": fps, "duration_seconds": duration, "frame_count": frame_count}
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"motion source metadata: {exc}") from exc


def _input_issues(profile: dict, props: dict) -> list[str]:
    issues = []
    try:
        validate_artifact("brand_profile", profile)
        if "production" not in profile:
            issues.append("profile.production is required")
        if not profile.get("font", {}).get("family"):
            issues.append("profile.font.family is required for production")
    except Exception as exc:
        issues.append(f"brand_profile: {exc}")
    for key in ("width", "height", "fps", "durationInFrames"):
        if not _number(props.get(key), positive=True):
            issues.append(f"{key} must be finite and positive")
        elif key != "fps" and props[key] != int(props[key]):
            issues.append(f"{key} must be an integer")
    if not isinstance(props.get("logoSrc"), str) or not props.get("logoSrc"):
        issues.append("logoSrc is required")
    if not isinstance(props.get("footage"), dict):
        issues.append("footage mapping is required")
    for key in ("titles", "captions", "scenes", "words"):
        if not isinstance(props.get(key), list) or not props[key]:
            issues.append(f"{key} must be a nonempty list")
    for title in props.get("titles", []) if isinstance(props.get("titles"), list) else []:
        if not isinstance(title, dict) or not isinstance(title.get("text"), str) or not _number(title.get("fromFrame")):
            issues.append("invalid title text/fromFrame")
    for key in ("captions", "words"):
        for item in props.get(key, []) if isinstance(props.get(key), list) else []:
            if (not isinstance(item, dict) or not isinstance(item.get("text"), str)
                    or not _number(item.get("startMs")) or not _number(item.get("endMs"))):
                issues.append(f"invalid {key} text/startMs/endMs")
    for shot in props.get("scenes", []) if isinstance(props.get("scenes"), list) else []:
        if not isinstance(shot, dict):
            issues.append("invalid scene")
            continue
        for key in ("fromFrame", "sourceInSeconds"):
            if not _number(shot.get(key)):
                issues.append(f"scene.{key} must be finite and nonnegative")
        for key in ("durationInFrames", "sourceDurationSeconds", "playbackRate", "cropScale"):
            if not _number(shot.get(key), positive=True):
                issues.append(f"scene.{key} must be finite and positive")
        if shot.get("role") not in ("body", "hook", "tail"):
            issues.append("scene.role must be body, hook or tail")
        framing = shot.get("framing")
        if framing is not None:
            issues.extend(_framing_input_issues(framing))
            if shot.get("cropScale") != 1:
                issues.append("framing cannot combine with legacy cropScale; use cropScale 1")
    if "opening" in props:
        opening = props["opening"]
        if not isinstance(opening, dict) or opening.get("scope") not in ("preview", "full_variant"):
            issues.append("opening.scope must be preview or full_variant")
        else:
            if props.get("fps") != 30 or opening.get("endFrameExclusive") != 90 or opening.get("transitionFrames") != 5:
                issues.append("opening requires 90 frames at 30fps with a five-frame transition")
            if opening["scope"] == "preview" and props.get("durationInFrames") != 90:
                issues.append("opening preview must be exactly 90 frames; exemptions cannot apply to a full film")
            if opening["scope"] == "full_variant" and not _number(props.get("durationInFrames"), 90, positive=True):
                issues.append("opening full_variant must extend past frame 90")
            scenes = props.get("scenes")
            if isinstance(scenes, list):
                for shot in scenes:
                    if isinstance(shot, dict) and (not shot.get("framing") or not _number(shot.get("sourceFps"), positive=True)):
                        issues.append("every opening scene requires framing and sourceFps")
                    if isinstance(shot, dict) and _number(shot.get("fromFrame")) and _number(shot.get("durationInFrames")):
                        end = shot["fromFrame"] + shot["durationInFrames"]
                        if shot["fromFrame"] < 90 < end or (shot["fromFrame"] < 90 and shot.get("role") != "hook"):
                            issues.append("opening hooks must fit wholly in [0,90)")
                if opening["scope"] == "full_variant" and not any(isinstance(s, dict) and s.get("fromFrame") == 90 and s.get("role") == "body" for s in scenes):
                    issues.append("opening full_variant requires a body scene starting at frame 90")
        if "audio" in props:
            issues.append("opening forbids internal audio; use one externally muxed finalMix")
        mix = props.get("finalMix")
        if not (isinstance(mix, dict) and mix.get("mode") == "external_mux" and isinstance(mix.get("path"), str)
                and mix["path"] and isinstance(mix.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", mix["sha256"])):
            issues.append("opening requires finalMix path and sha256 bound to external_mux")
    recipe = props.get("recipe", profile.get("production", {}).get("recipe", {}))
    if not isinstance(recipe, dict) or not recipe.get("id"):
        issues.append("recipe requires an id and explicit duration ranges")
        return issues
    for key in ("raw_action_seconds", "body_cut_seconds"):
        pair = recipe.get(key)
        if not (isinstance(pair, list) and len(pair) == 2 and all(_number(x, positive=True) for x in pair) and pair[0] <= pair[1]):
            issues.append(f"recipe.{key} must be [minimum, maximum]")
    return issues


def _framing_input_issues(framing: Any) -> list[str]:
    if not isinstance(framing, dict):
        return ["scene.framing must be an object"]
    issues = []
    for key, fields in (("source", ("width", "height")), ("viewport", ("width", "height"))):
        item = framing.get(key)
        if not isinstance(item, dict) or not all(_number(item.get(field), positive=True) for field in fields):
            issues.append(f"framing.{key} requires finite positive dimensions")
    viewport, position = framing.get("viewport"), framing.get("position")
    if not isinstance(viewport, dict) or not all(_number(viewport.get(field)) for field in ("x", "y")):
        issues.append("framing.viewport requires nonnegative x/y")
    if not isinstance(position, dict) or not all(_number(position.get(field)) and position[field] <= 1 for field in ("x", "y")):
        issues.append("framing.position requires normalized x/y in [0,1]")
    if framing.get("fit") not in ("contain", "crop"):
        issues.append("framing.fit must be contain or crop")
    regions = framing.get("actionRegions")
    if framing.get("actionCoverage") != "whole_shot_envelope" or not isinstance(regions, list) or not regions:
        issues.append("framing requires nonempty whole_shot_envelope actionRegions")
    else:
        for region in regions:
            if not isinstance(region, dict) or not all(_number(region.get(k), positive=k in ("width", "height")) for k in ("x", "y", "width", "height")):
                issues.append("framing.actionRegions require finite nonnegative positions and positive dimensions")
    background = framing.get("background")
    if background is not None and (not isinstance(background, dict) or not _number(background.get("blurPx"))
            or not _number(background.get("opacity")) or background["opacity"] > 1 or not _number(background.get("scale"), 1)):
        issues.append("framing.background requires blurPx >= 0, opacity in [0,1], scale >= 1")
    return issues


def _fonts(profile: dict, base: Path) -> tuple[list[dict], dict[int, str]]:
    if profile["production"]["font_mode"] == "legacy_appearance":
        return [
            _check("font_files", "not_run", reason="legacy system font stack has no pinned font files"),
            _check("font_identity", "not_run", reason="approved appearance is not Microsoft YaHei identity certification"),
        ], {}
    files = profile.get("font", {}).get("files", [])
    inventory, issues, identities, identity_issues, valid = [], [], [], [], {}
    weights = [f["weight"] for f in files]
    if sorted(weights) != [400, 700]:
        issues.append("exactly one regular (400) and bold (700) font file is required")
    expected = profile["font"]["family"].casefold()
    aliases = {"microsoft yahei", "微软雅黑"} if expected in {"microsoft yahei", "微软雅黑"} else {expected}
    for item in files:
        path = base / item["path"]
        row = {"path": str(path), "weight": item["weight"], "expected_sha256": item["sha256"]}
        try:
            data = path.read_bytes()
            row["actual_sha256"] = hashlib.sha256(data).hexdigest()
            row["matches"] = row["actual_sha256"] == item["sha256"]
            if not row["matches"]:
                issues.append(f"font hash mismatch: {item['path']}")
            font = ImageFont.truetype(str(path), 38)
            family, style = font.getname()
            identities.append({"path": str(path), "family": family, "style": style, "weight": item["weight"]})
            bold = "bold" in style.casefold() or "粗" in style
            if family.casefold() not in aliases:
                identity_issues.append(f"expected {profile['font']['family']}, decoded {family}: {item['path']}")
            if bold != (item["weight"] == 700):
                identity_issues.append(f"font style {style} does not match weight {item['weight']}")
            if any(marker in style.casefold() for marker in ("italic", "oblique", "倾斜", "斜体")):
                identity_issues.append(f"font style {style} is not an upright normal face: {item['path']}")
            if row["matches"]:
                valid[item["weight"]] = str(path)
        except (OSError, ValueError) as exc:
            row["error"] = str(exc)
            issues.append(f"font unreadable: {item['path']}")
        inventory.append(row)
    return [
        _check("font_files", "fail" if issues else "pass", files=inventory, issues=issues),
        _check("font_identity", "fail" if issues or identity_issues else "pass", expected_family=profile["font"]["family"], fonts=identities, issues=identity_issues + issues),
    ], valid


def _rect(x: float, y: float, width: float, height: float) -> dict:
    return {"x": x, "y": y, "width": width, "height": height}


def _overlap(a: dict, b: dict) -> bool:
    return (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
            and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"])


def _geometry(profile: dict, props: dict, base: Path, fonts: dict) -> list[dict]:
    p, width, height = profile["production"], props["width"], props["height"]
    logo = p["logo"]
    logo_rect = None
    try:
        with Image.open(base / props["logoSrc"]) as im:
            im.load()
            source_width, source_height = im.size
        logo_rect = _rect(width - logo["right"] - logo["width"], logo["top"], logo["width"], logo["width"] * source_height / source_width)
        logo_check = _check("logo_asset", "pass" if source_width >= logo["width"] else "fail", source_size=[source_width, source_height], rect=logo_rect, scope="raster dimensions; scene-background contrast requires rendered review")
    except (OSError, ValueError) as exc:
        logo_check = _check("logo_asset", "fail", path=props["logoSrc"], error=str(exc))
    if not all(weight in fonts for weight in (400, 700)):
        return [logo_check, _check("text_geometry", "not_run", reason="pinned regular/bold files unavailable; cannot measure fallback as certified font")]
    title, caption, line = p["title"], p["caption"], p["underline"]
    bold = ImageFont.truetype(fonts[700], title["font_size"])
    regular = ImageFont.truetype(fonts[400], caption["font_size"])
    boxes, issues = [], []
    # Unsupported glyphs render as the .notdef mask in FreeType. Never certify a
    # browser's silent system fallback when the pinned font cannot draw the text.
    for name, font, texts in (("title", bold, props["titles"]), ("caption", regular, props["captions"])):
        missing_mask = font.getmask(chr(0x10FFFF))
        missing = {char for item in texts for char in item["text"] if not char.isspace()
                   and font.getmask(char).size == missing_mask.size
                   and bytes(font.getmask(char)) == bytes(missing_mask)}
        if missing:
            issues.append({"element": name, "reason": "glyph missing from pinned font", "characters": sorted(missing)})
    duration_ms = props["durationInFrames"] * 1000 / props["fps"]
    for i, item in enumerate(props["titles"]):
        n = len(item["text"].strip())
        if not title["characters"][0] <= n <= title["characters"][1] or "\n" in item["text"]:
            issues.append({"element": f"title-{i}", "reason": "title must be a single 2–4 character core keyword"})
        title_width = float(bold.getlength(item["text"].replace("\n", "")))
        end = props["titles"][i + 1]["fromFrame"] * 1000 / props["fps"] if i + 1 < len(props["titles"]) else duration_ms
        boxes.append({"element": f"title-{i}", "startMs": item["fromFrame"] * 1000 / props["fps"], "endMs": end,
                      **_rect(title["left"], title["top"], title_width, title["font_size"] * title["line_height"] + line["gap"] + line["height"])})
    for i, item in enumerate(props["captions"]):
        text_width = float(regular.getlength(item["text"].replace("\n", "")))
        available = width - caption["left"] - caption["right"]
        if text_width > available or "\n" in item["text"]:
            issues.append({"element": f"caption-{i}", "reason": "caption exceeds single-line safe width", "width": text_width, "available": available})
        boxes.append({"element": f"caption-{i}", "startMs": item["startMs"], "endMs": item["endMs"],
                      **_rect(caption["left"] + (available - text_width) / 2, caption["top"], text_width, caption["font_size"] * caption["line_height"])})
    if logo_rect:
        margin = logo["clear_space"]
        clear = _rect(logo_rect["x"] - margin, logo_rect["y"] - margin, logo_rect["width"] + 2 * margin, logo_rect["height"] + 2 * margin)
        boxes.append({"element": "logo-clear-zone", "startMs": 0, "endMs": duration_ms, **clear})
    for i, box in enumerate(boxes):
        if box["x"] < 0 or box["y"] < 0 or box["x"] + box["width"] > width or box["y"] + box["height"] > height:
            issues.append({"element": box["element"], "reason": "out of frame"})
        for other in boxes[i + 1:]:
            if max(box["startMs"], other["startMs"]) < min(box["endMs"], other["endMs"]) and _overlap(box, other):
                issues.append({"element": box["element"], "other": other["element"], "reason": "overlap"})
    return [logo_check, _check("text_geometry", "fail" if issues else "pass", measurement="font_file_preflight", boxes=boxes, issues=issues,
                              limitation="Pillow advances and CSS line boxes; final browser DOM bounds and scene/logo contrast require separate rendered QA")]


def _normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).casefold()


def _timing(profile: dict, props: dict) -> list[dict]:
    production = profile["production"]
    fps, end_ms = props["fps"], props["durationInFrames"] * 1000 / props["fps"]
    issues = []
    if props.get("timingSource") != "measured_word_timestamps":
        issues.append("word timestamps must be measured, not estimated")
    for key in ("words", "captions"):
        last_end = 0
        for i, item in enumerate(props[key]):
            if item["endMs"] <= item["startMs"] or item["startMs"] < last_end or item["endMs"] > end_ms:
                issues.append(f"{key}[{i}] overlaps, is unordered, empty or exceeds video duration")
            last_end = item["endMs"]
    title_starts = [t["fromFrame"] for t in props["titles"]]
    if title_starts[0] != 0 or title_starts != sorted(set(title_starts)) or title_starts[-1] >= props["durationInFrames"]:
        issues.append("titles must start at frame zero and advance within the video")
    word_text = _normalize("".join(w["text"] for w in props["words"]))
    caption_text = _normalize("".join(c["text"] for c in props["captions"]))
    if word_text != caption_text:
        issues.append("captions do not match the complete measured narration")
    else:
        # Bind each caption's normalized text span to the actual measured word
        # intervals. Equal transcript strings alone cannot establish alignment.
        spans, cursor = [], 0
        for word in props["words"]:
            length = len(_normalize(word["text"]))
            if length:
                spans.append((cursor, cursor + length, word))
                cursor += length
        cursor = 0
        tolerance_ms = 1000 / fps  # caption visibility is quantized to frames
        for i, caption in enumerate(props["captions"]):
            end = cursor + len(_normalize(caption["text"]))
            matching = [word for begin, finish, word in spans if max(begin, cursor) < min(finish, end)]
            if not matching:
                issues.append(f"captions[{i}] has no measured spoken text")
            elif (caption["startMs"] > matching[0]["startMs"] + tolerance_ms
                  or caption["endMs"] < matching[-1]["endMs"] - tolerance_ms):
                issues.append(f"captions[{i}] does not cover its measured word interval")
            cursor = end
    slogan = _normalize(production["slogan"])
    final_word_end = max(w["endMs"] for w in props["words"])
    tail_seconds = (end_ms - final_word_end) / 1000
    if props.get("opening", {}).get("scope") == "preview":
        return [
            _check("speech_timeline", "fail" if issues else "pass", timing_source=props.get("timingSource"), issues=issues),
            *[_check(name, "not_run", applicability="not_applicable", reason="three-second opening preview excludes the full-film slogan and speech-tail contract", scope="opening_preview_only")
              for name in ("slogan", "speech_tail")],
        ]
    return [
        _check("speech_timeline", "fail" if issues else "pass", timing_source=props.get("timingSource"), issues=issues),
        _check("slogan", "pass" if word_text.endswith(slogan) and caption_text.endswith(slogan) else "fail", expected=production["slogan"], measured_text="".join(w["text"] for w in props["words"]), scope="provided measured transcript, not independent audio transcription"),
        _check("speech_tail", "pass" if tail_seconds + 1e-9 >= production["min_tail_seconds"] else "fail", last_word_end_ms=final_word_end, video_end_ms=end_ms, tail_seconds=tail_seconds, minimum_seconds=production["min_tail_seconds"]),
    ]


def _shots(profile: dict, props: dict) -> list[dict]:
    recipe = props.get("recipe", profile["production"]["recipe"])
    fps, transition = props["fps"], profile["production"]["transition"]["frames"]
    rhythm, timeline, evidence = [], [], []
    expected_start = 0
    ids = set()
    for i, s in enumerate(props["scenes"]):
        seconds = s["durationInFrames"] / fps
        handle = transition if i + 1 < len(props["scenes"]) else 0
        if props.get("opening", {}).get("scope") == "full_variant" and s["fromFrame"] + s["durationInFrames"] == 90:
            handle = 0
        source_in = math.floor(s["sourceInSeconds"] * fps + .5) / fps if props.get("opening") else s["sourceInSeconds"]
        source_end = source_in + (s["durationInFrames"] + handle) / fps * s["playbackRate"]
        evidence.append({"shot_id": s.get("id", str(i)), "body_seconds": seconds, "raw_seconds": s["sourceDurationSeconds"], "source_end_with_handle": source_end})
        if s["role"] == "body" and not recipe["body_cut_seconds"][0] <= seconds <= recipe["body_cut_seconds"][1]:
            rhythm.append(f"scene {i}: body cut {seconds}s outside recipe")
        if not recipe["raw_action_seconds"][0] <= s["sourceDurationSeconds"] <= recipe["raw_action_seconds"][1]:
            rhythm.append(f"scene {i}: raw action outside recipe")
        if s["fromFrame"] != expected_start or s["durationInFrames"] != int(s["durationInFrames"]):
            timeline.append(f"scene {i}: scenes must cover contiguous integer-frame intervals")
        if source_end > s["sourceDurationSeconds"] + 1e-9:
            timeline.append(f"scene {i}: source does not cover outgoing transition handle")
        if not props["footage"].get(s.get("footageKey")):
            timeline.append(f"scene {i}: missing footage mapping")
        if not s.get("id") or s["id"] in ids:
            timeline.append(f"scene {i}: id must be nonempty and unique")
        ids.add(s.get("id"))
        expected_start = s["fromFrame"] + s["durationInFrames"]
    if expected_start != props["durationInFrames"]:
        timeline.append("scene coverage must equal durationInFrames")
    return [
        _check("shot_rhythm", "fail" if rhythm else "pass", recipe=recipe, shots=evidence, issues=rhythm),
        _check("shot_timeline", "fail" if timeline else "pass", transition_frames=transition, rule="incoming_only", issues=timeline),
    ]


def _opening_schedule(props: dict) -> dict:
    """Composition-frame quantization, including explicit source-time error.

    source_frame_position is a fractional position, not proof of the decoder's
    selected source frame. B4 verifies the actual decoded boundary separately.
    """
    shots, issues = [], []
    fps = props["fps"]
    full = props["opening"]["scope"] == "full_variant"
    for i, shot in enumerate(props["scenes"]):
        join = full and shot["fromFrame"] == 90
        before_join = full and shot["fromFrame"] + shot["durationInFrames"] == 90
        frame = math.floor(shot["sourceInSeconds"] * fps + .5)
        prehandle = 5 * shot["playbackRate"] if join else 0
        if join and (not float(prehandle).is_integer() or frame < prehandle):
            issues.append(f"scene {i}: body requires a compatible integer-frame prehandle; bind a common source baseline")
        shots.append({"shot_id": shot["id"], "render_from_frame": shot["fromFrame"] - (5 if join else 0),
            "render_duration_frames": shot["durationInFrames"] + (5 if join else 0) + (5 if i < len(props["scenes"]) - 1 and not before_join else 0),
            "source_start_frame": frame - prehandle,
            "quantization": {"requested_seconds": shot["sourceInSeconds"], "render_frame": frame,
                "resolved_seconds": frame / fps, "error_seconds": frame / fps - shot["sourceInSeconds"],
                "source_fps": shot["sourceFps"], "source_frame_position": frame / fps * shot["sourceFps"],
                "rule": "round_seconds_at_composition_fps"}})
    return _check("opening_schedule", "fail" if issues else "pass", opening_interval=[0, 90],
        body_interval=[90, props["durationInFrames"]] if full else None, join_interval=[85, 90] if full else None,
        shots=shots, issues=issues, limitation="nominal source-time mapping; decoded continuity requires separate B4 evidence")


def _motion_framing(profile: dict, props: dict, geometry: list[dict], schedule: dict | None) -> dict:
    width, height = props["width"], props["height"]
    p = profile["production"]
    text = next(c for c in geometry if c["check_id"] == "text_geometry")
    occupied = text["evidence"].get("boxes", [])
    if not occupied:
        # Legacy preview has no certified font metrics. Reserve the full safe
        # text corridors conservatively; font checks remain not_run/degraded.
        title, caption, line = p["title"], p["caption"], p["underline"]
        occupied = [dict(element="title-corridor", startMs=0, endMs=float("inf"),
                         **_rect(title["left"], title["top"], width - title["left"], title["font_size"] * title["line_height"] + line["gap"] + line["height"])),
                    dict(element="caption-corridor", startMs=0, endMs=float("inf"),
                         **_rect(caption["left"], caption["top"], width - caption["left"] - caption["right"], caption["font_size"] * caption["line_height"]))]
        logo = next(c for c in geometry if c["check_id"] == "logo_asset")
        rect = logo["evidence"].get("rect")
        if rect:
            margin = p["logo"]["clear_space"]
            occupied.append(dict(element="logo-clear-zone", startMs=0, endMs=float("inf"),
                                 **_rect(rect["x"] - margin, rect["y"] - margin, rect["width"] + 2 * margin, rect["height"] + 2 * margin)))
    evidence, issues = [], []
    for i, shot in enumerate(props["scenes"]):
        f = shot.get("framing")
        if not f:
            continue
        viewport, source = f["viewport"], f["source"]
        scale = (min if f["fit"] == "contain" else max)(viewport["width"] / source["width"], viewport["height"] / source["height"])
        media = _rect(viewport["x"] + (viewport["width"] - source["width"] * scale) * f["position"]["x"],
                      viewport["y"] + (viewport["height"] - source["height"] * scale) * f["position"]["y"], source["width"] * scale, source["height"] * scale)
        if viewport["x"] + viewport["width"] > width or viewport["y"] + viewport["height"] > height:
            issues.append(f"scene {i}: viewport exceeds composition")
        interval = schedule["evidence"]["shots"][i] if schedule else {"render_from_frame": shot["fromFrame"], "render_duration_frames": shot["durationInFrames"] + (p["transition"]["frames"] if i < len(props["scenes"]) - 1 else 0)}
        start_ms = interval["render_from_frame"] * 1000 / props["fps"]
        end_ms = (interval["render_from_frame"] + interval["render_duration_frames"]) * 1000 / props["fps"]
        mapped = []
        for region in f["actionRegions"]:
            if region["x"] + region["width"] > source["width"] or region["y"] + region["height"] > source["height"]:
                issues.append(f"scene {i}: action region exceeds source bounds")
            action = _rect(media["x"] + region["x"] * scale, media["y"] + region["y"] * scale, region["width"] * scale, region["height"] * scale)
            mapped.append(action)
            if (action["x"] < viewport["x"] - 1e-6 or action["y"] < viewport["y"] - 1e-6
                    or action["x"] + action["width"] > viewport["x"] + viewport["width"] + 1e-6
                    or action["y"] + action["height"] > viewport["y"] + viewport["height"] + 1e-6):
                issues.append(f"scene {i}: crop removes part of action envelope")
            for box in occupied:
                if max(start_ms, box["startMs"]) < min(end_ms, box["endMs"]) and _overlap(action, box):
                    issues.append(f"scene {i}: action envelope overlaps {box['element']}")
        evidence.append({"shot_id": shot["id"], "fit": f["fit"], "declared_source": source, "media_rect": media, "viewport": viewport,
                         "mapped_actions": mapped, "coverage": f["actionCoverage"]})
    return _check("motion_framing", "fail" if issues else "pass", shots=evidence, issues=issues,
                  brand_occupancy="font_file_metrics" if text["status"] != "not_run" else "conservative_profile_corridors",
                  semantic_action_verified=False, source_metadata_verified=False,
                  limitation="caller-declared whole-shot envelopes; formal renderer separately probes source metadata; does not prove product identity or action semantics")


def _final_mix(props: dict, base: Path) -> dict:
    mix = props["finalMix"]
    path = base / mix["path"]
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        return _check("final_mix", "pass" if actual == mix["sha256"] else "fail", path=str(path),
                      expected_sha256=mix["sha256"], actual_sha256=actual, mode="external_mux")
    except OSError as exc:
        return _check("final_mix", "fail", path=str(path), reason=str(exc))


def preflight_production_brand(profile: dict, props: dict, *, project_dir: Path | str) -> dict:
    """Read assets and return JSON-serializable checks; never render, mutate or approve.

    props is the ProductionBrandFilm payload excluding its redundant profile field.
    A passed preflight does not replace font-loading/DOM evidence from final rendering.
    """
    issues = _input_issues(profile, props)
    checks = [_check("input_contract", "fail" if issues else "pass", issues=issues, profile_id=profile.get("profile_id"))]
    if not issues:
        font_checks, fonts = _fonts(profile, Path(project_dir))
        checks.extend(font_checks)
        geometry = _geometry(profile, props, Path(project_dir), fonts)
        checks.extend(geometry)
        checks.extend(_timing(profile, props))
        checks.extend(_shots(profile, props))
        schedule = _opening_schedule(props) if props.get("opening") else None
        if schedule:
            checks.append(schedule)
            checks.append(_final_mix(props, Path(project_dir)))
        if any(s.get("framing") for s in props["scenes"]):
            checks.append(_motion_framing(profile, props, geometry, schedule))
    failed = any(c["status"] in ("fail", "error") for c in checks)
    missing = any(c["status"] == "not_run" and c["evidence"].get("applicability") != "not_applicable" for c in checks)
    strict = profile.get("production", {}).get("font_mode") == "strict"
    status = "blocked" if failed or (strict and missing) else "degraded" if missing else "passed"
    return {"version": "1.0", "profile_id": profile.get("profile_id"), "status": status,
            "strict_ready": strict and status == "passed", "scope": "production_brand_preflight", "checks": checks}
