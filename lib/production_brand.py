"""Deterministic preflight for approved production branding, not a production director.

Results describe source-file preflight, never final rendered QA or human approval.
The optional production section extends the existing brand_profile artifact.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
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
    recipe = props.get("recipe", profile.get("production", {}).get("recipe", {}))
    if not isinstance(recipe, dict) or not recipe.get("id"):
        issues.append("recipe requires an id and explicit duration ranges")
        return issues
    for key in ("raw_action_seconds", "body_cut_seconds"):
        pair = recipe.get(key)
        if not (isinstance(pair, list) and len(pair) == 2 and all(_number(x, positive=True) for x in pair) and pair[0] <= pair[1]):
            issues.append(f"recipe.{key} must be [minimum, maximum]")
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
        source_end = s["sourceInSeconds"] + (s["durationInFrames"] + handle) / fps * s["playbackRate"]
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
        checks.extend(_geometry(profile, props, Path(project_dir), fonts))
        checks.extend(_timing(profile, props))
        checks.extend(_shots(profile, props))
    failed = any(c["status"] in ("fail", "error") for c in checks)
    missing = any(c["status"] == "not_run" for c in checks)
    strict = profile.get("production", {}).get("font_mode") == "strict"
    status = "blocked" if failed or (strict and missing) else "degraded" if missing else "passed"
    return {"version": "1.0", "profile_id": profile.get("profile_id"), "status": status,
            "strict_ready": strict and status == "passed", "scope": "production_brand_preflight", "checks": checks}
