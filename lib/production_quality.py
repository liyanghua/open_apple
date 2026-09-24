"""Normalize measured tool evidence without converting missing checks to passes."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Mapping

from lib.production_evidence import REQUIRED_CHECKS, file_sha256, project_file, read_object


def collect_production_quality(root: Path, record: Mapping, evidence_refs: Mapping[str, str]) -> dict:
    root = Path(root)
    render = record.get("render") or {}
    actual_sha = file_sha256(project_file(root, render.get("path")))
    checks = {name: {"id": name, "status": "not_run", "method": "unmeasured", "evidence_refs": [], "issues": []}
              for name in REQUIRED_CHECKS}

    def put(name, status, method, refs, issues=()):
        checks[name] = {"id": name, "status": status, "method": method, "evidence_refs": list(refs), "issues": list(issues)}

    def document(key):
        try:
            return read_object(root, evidence_refs.get(key))
        except (ValueError, OSError):
            return {}

    put("file_integrity", "pass" if actual_sha == render.get("sha256") else "fail", "sha256", [render["path"]])
    technical = document("technical")
    def mapping(value):
        return value if isinstance(value, Mapping) else {}

    current_bound = mapping(technical.get("metadata")).get("media_sha256") == actual_sha
    if current_bound:
        old = mapping(technical.get("checks"))
        media, probe = mapping(old.get("media_integrity")), mapping(old.get("technical_probe"))
        method = "final_qa"
        for name, value in (("decode", media.get("decode_ok")), ("video_profile", media.get("profile_ok")),
                            ("audio_track", probe.get("has_audio"))):
            if isinstance(value, bool):
                put(name, "pass" if value else "fail", method, [evidence_refs["technical"]])
        duration = probe.get("duration_seconds")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration > 0:
            expected = render.get("seconds", duration)
            valid = (isinstance(expected, (int, float)) and not isinstance(expected, bool)
                     and math.isfinite(expected) and abs(duration - expected) <= 1 / 30 + 1e-6)
            put("duration", "pass" if valid else "fail", method, [evidence_refs["technical"]])
    elif technical and record.get("provenance") == "legacy_import":
        for name in ("decode", "video_profile", "duration", "audio_track"):
            put(name, "not_run", "historical_tool_report", [evidence_refs["technical"]],
                ["historical_report_not_bound_to_current_media"])
    dependency_refs = list((record.get("canonical_artifacts") or {}).values())
    if dependency_refs:
        try:
            for ref in dependency_refs:
                project_file(root, ref)
            put("dependency_integrity", "pass", "file_inventory_bound_at_final_review", dependency_refs)
        except (ValueError, OSError):
            put("dependency_integrity", "fail", "file_inventory", [render["path"]], ["missing_canonical_dependency"])
    # These adapters accept only explicit check results measured on this render.
    # TTS timestamps alone are not an independent transcription. A brand source
    # preflight is not proof that the rendered browser loaded the required font.
    for source, names in {
        "brand_dom": ("font_identity", "text_layout"),
        "narration": ("narration_content",),
        "alignment": ("caption_alignment",),
        "product_review": ("fact_source", "product_identity"),
        "continuity": ("visual_continuity",),
        "video_judge": ("video_judge",),
    }.items():
        data = document(source)
        if data.get("render_sha256") != actual_sha:
            continue
        if source == "narration" and data.get("method") != "independent_asr":
            continue
        if source == "brand_dom" and data.get("method") != "rendered_browser_measurement":
            continue
        values = data.get("checks") or []
        for name in names:
            candidates = [c for c in values if isinstance(c, dict) and c.get("id") == name] if isinstance(values, list) else []
            if len(candidates) != 1:
                continue
            check = candidates[0]
            status = check.get("status")
            if not isinstance(status, str) or status not in {"pass", "fail", "not_run", "error"}:
                status = "error"
            issues = check.get("issues")
            put(name, status, data.get("method", source), [evidence_refs[source]], issues if isinstance(issues, list) else [])
    return {"version": "1.0", "render_sha256": actual_sha, "required_checks": list(REQUIRED_CHECKS),
            "checks": list(checks.values()), "certification_eligible": all(checks[name]["status"] == "pass" for name in REQUIRED_CHECKS),
            "provenance": record.get("provenance", "canonical"), "source_refs": dict(evidence_refs)}
