"""Normalize measured tool evidence without converting missing checks to passes."""
from __future__ import annotations

import math
from jsonschema import ValidationError
from pathlib import Path
from typing import Mapping

from lib.production_evidence import REQUIRED_CHECKS, file_sha256, project_file, read_object
from lib.production_measurements import produce_narration_evidence, run_narration_evidence, produce_brand_dom_evidence, evaluate_measurement


def collect_production_quality(root: Path, record: Mapping, evidence_refs: Mapping[str, str]) -> dict:
    root = Path(root)
    render = record.get("render") or {}
    opening_scope = record["opening"].get("scope") if isinstance(record.get("opening"), Mapping) else None
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

    if "opening" in record and technical.get("media_sha256") == actual_sha and technical.get("scope") == opening_scope:
        from fractions import Fraction
        try:
            raw = technical.get("measurements", {})
            if not isinstance(raw, Mapping) or not isinstance(raw.get("probe"), Mapping):
                raise ValueError("Invalid technical measurements/probe object")
            probe = raw["probe"]
            streams = probe.get("streams", [])
            if not isinstance(streams, list) or any(not isinstance(stream, Mapping) for stream in streams):
                raise ValueError("Invalid technical stream rows")
            if not isinstance(probe.get("format"), Mapping):
                raise ValueError("Invalid technical format object")
            video = next((s for s in streams if s.get("codec_type") == "video"), {})
            audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
            profile_ok = (video.get("width") == 1080 and video.get("height") == 1920 and video.get("codec_name") == "h264"
                and video.get("pix_fmt") == "yuv420p" and float(Fraction(video.get("avg_frame_rate", "0"))) == 30
                and audio.get("codec_name") == "aac")
            technical = {"scope": technical["scope"], "metadata": {"media_sha256": actual_sha}, "checks": {
                "media_integrity": {"decode_ok": raw.get("decode_ok"), "profile_ok": profile_ok},
                "technical_probe": {"has_audio": bool(audio), "duration_seconds": float(probe["format"]["duration"])}}}
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            for name in ("decode", "video_profile", "duration", "audio_track"):
                put(name, "error", "technical_validator", [evidence_refs["technical"]], [str(exc)])
            technical = {}
    current_bound = mapping(technical.get("metadata")).get("media_sha256") == actual_sha
    if "opening" in record:
        current_bound = current_bound and technical.get("scope") == opening_scope
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
            if "opening" in record:
                try:
                    declared = read_object(root, record["canonical_artifacts"]["final_props"])
                    expected = declared["durationInFrames"] / declared["fps"]
                except (ValueError, OSError, KeyError, TypeError, ZeroDivisionError):
                    expected = None
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
            if "opening" in record:
                from schemas.artifacts import validate_artifact
                from lib.artifact_hashing import verify_hashes
                canonical = read_object(root, record["canonical_artifacts"]["final_props"])
                validate_artifact("final_props", canonical)
                if not verify_hashes(canonical).valid:
                    raise ValueError("Canonical final_props hashes are invalid")
            put("dependency_integrity", "pass", "file_inventory_bound_at_final_review", dependency_refs)
        except (ValueError, OSError, KeyError, TypeError, ValidationError) as exc:
            put("dependency_integrity", "fail", "file_inventory", [render["path"]], ["invalid_canonical_dependency: " + str(exc).splitlines()[0]])
    # These adapters accept only explicit check results measured on this render.
    # TTS timestamps alone are not an independent transcription. A brand source
    # preflight is not proof that the rendered browser loaded the required font.
    for source, names in {
        "brand_dom": ("font_identity", "text_layout"),
        "narration": ("narration_content", "caption_alignment", "slogan_tail"),
        "alignment": ("caption_alignment",),
        "product_review": ("fact_source", "product_identity"),
        "continuity": ("visual_continuity",),
        "video_judge": ("video_judge",),
    }.items():
        data = document(source)
        if data.get("render_sha256") != actual_sha:
            continue
        if "opening" in record and source in {"product_review", "continuity"}:
            try:
                from lib.production_measurements import binding, strict_load
                _, bound = binding(root, record)
                if data.get("scope") != bound["scope"] or data.get("props_ref") != bound["props_ref"]:
                    raise ValueError("Semantic evidence scope/props binding mismatch")
                strict_load(root, data["props_ref"])
                from lib.opening_contracts import _identified_observer
                if not isinstance(data.get("reviewer"), Mapping) or not _identified_observer(data) or data.get("method") != "independent_semantic_review":
                    raise ValueError("Identified independent semantic evidence required")
            except (ValueError, OSError, KeyError, TypeError) as exc:
                for name in names:
                    put(name, "not_run", data.get("method", source), [evidence_refs[source]], [str(exc)])
                continue
        if source == "narration" and data.get("method") != "independent_asr":
            continue
        if source == "brand_dom" and data.get("method") != "rendered_browser_measurement":
            continue
        if "opening" in record and source == "video_judge":
            from lib.opening_quality_adapters import judge_check
            checks["video_judge"] = judge_check(root, record, data, evidence_refs[source])
            continue
        values = data.get("checks") or []
        if "opening" in record and source in {"brand_dom", "narration", "alignment"}:
            if source == "alignment":
                continue  # Caption alignment comes from the same independent ASR.
            try:
                values = evaluate_measurement(root, record, data)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                for name in names:
                    put(name, "error", data.get("method", source), [evidence_refs[source]], [str(exc)])
                continue
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
    from lib.opening_contracts import evaluate_opening_checks

    opening_checks = evaluate_opening_checks(root, record)
    for check in opening_checks.values():
        observations = check.get("observations", [])
        applicable = [o for o in observations if o.get("basis") != "motion_not_required"]
        if observations and not applicable:
            check["status"] = "not_run"
            check["effective_status"] = "not_applicable"
            check["applicability_reason"] = "; ".join(o["reason"] for o in observations)
        elif check["status"] == "pass" and any(o.get("method") == "human_review" for o in applicable):
            check["status"] = "not_run"
            check["effective_status"] = "manual_verified"
    checks.update(opening_checks)
    from lib.opening_freeze_checks import evaluate_freeze_checks
    from lib.opening_quality_scope import quality_applicability
    if isinstance(record.get("opening"), Mapping):
        checks.update(evaluate_freeze_checks(root, record))
    if "opening" in record:
        from lib.opening_quality_adapters import mix_origin_check
        checks["mix_origin"] = mix_origin_check(root, record)
    scope, applicability = quality_applicability(root, record)
    for name, check in opening_checks.items():
        if check.get("effective_status") == "not_applicable":
            applicability[name] = {"applies": False, "required": False, "reason": check["applicability_reason"]}
    for name in applicability:
        checks.setdefault(name, {"id": name, "status": "not_run", "method": "unmeasured", "evidence_refs": [], "issues": []})
    dependency_fingerprint = None
    if "opening" in record:
        from lib.production_dependency_graph import dependency_closure
        from lib.production_evidence import production_subject_hash
        try:
            closure = dependency_closure(root, document={"canonical_artifacts": record.get("canonical_artifacts", {}),
                "opening": record.get("opening"), "source_refs": dict(evidence_refs)})
            dom = document("brand_dom")
            if dom:
                from lib.production_measurements import strict_load
                snapshot = strict_load(root, dom['renderer_props_ref'])
                pins = snapshot.get('render_input_refs')
                if not isinstance(pins, list) or not pins or any(not isinstance(pin, dict) or not pin.get('sha256') or not pin.get('path') for pin in pins):
                    raise ValueError('render_input_pins_missing')
            dependency_fingerprint = production_subject_hash(closure)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            put("dependency_integrity", "error", "hash_validated_dependency_closure", [], [str(exc)])
    required = [name for name, rule in applicability.items() if rule["required"]]
    return {"version": "1.0", "scope": scope, "applicability": applicability,
            "render_sha256": actual_sha, "dependency_fingerprint": dependency_fingerprint, "required_checks": required,
            "checks": list(checks.values()), "certification_eligible": scope not in {"preview", "invalid"} and all(checks[name]["status"] == "pass" for name in required),
            "provenance": record.get("provenance", "canonical"), "source_refs": dict(evidence_refs)}
