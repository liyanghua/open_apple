"""Cross-stage binding checks for template-driven sample renders.

These checks are deliberately small and fail closed.  A render is only
reusable when the current script, shot plan, and generated narration all
identify the same scene/section and the optional visual alignment review is
fully positive.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _content_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shot_execution_plan_errors(
    shot_plan: Mapping[str, Any],
    script: Mapping[str, Any],
    scene_plan: Mapping[str, Any],
    *,
    audio_dir: Path | None = None,
) -> list[str]:
    """Return deterministic cross-artifact binding errors for every shot."""
    sections = {
        str(item.get("id")): item for item in script.get("sections", [])
        if isinstance(item, Mapping) and item.get("id")
    }
    scenes = {
        str(item.get("id")): item for item in scene_plan.get("scenes", [])
        if isinstance(item, Mapping) and item.get("id")
    }
    mappings = {
        str(item.get("scene_id")): item
        for item in (scene_plan.get("metadata") or {}).get("source_mapping", [])
        if isinstance(item, Mapping) and item.get("scene_id")
    }
    require_evidence = any(
        isinstance(item, Mapping) and item.get("evidence_row_ids")
        for item in script.get("sections", [])
    )
    errors: list[str] = []
    seen_shots: set[str] = set()
    seen_scenes: set[str] = set()
    for shot in shot_plan.get("shots", []):
        if not isinstance(shot, Mapping):
            errors.append("shot entry is not an object")
            continue
        shot_id = str(shot.get("id") or "<unknown-shot>")
        if shot_id in seen_shots:
            errors.append(f"{shot_id}: duplicate shot id")
        seen_shots.add(shot_id)
        scene_id = str(shot.get("scene_id") or "")
        section_id = str(shot.get("section_id") or "")
        scene = scenes.get(scene_id)
        section = sections.get(section_id)
        mapping = mappings.get(scene_id)
        if scene is None:
            errors.append(f"{shot_id}: scene_id {scene_id or '<missing>'} not found")
            continue
        if section is None and not require_evidence:
            section = next((
                item for item in sections.values()
                if float(item.get("start_seconds") or 0)
                == float(scene.get("start_seconds") or 0)
            ), None)
            if section is not None:
                section_id = str(section.get("id") or "")
        if section is None:
            errors.append(f"{shot_id}: section_id {section_id or '<missing>'} not found")
            continue
        if mapping is None:
            errors.append(f"{shot_id}: source mapping for {scene_id} not found")
            continue
        if scene_id in seen_scenes:
            errors.append(f"{shot_id}: duplicate shot binding for scene_id {scene_id}")
        seen_scenes.add(scene_id)
        if require_evidence and section.get("scene_id") != scene_id:
            errors.append(f"{shot_id}: section_id does not bind back to scene_id")
        if require_evidence and scene.get("script_section_id") != section_id:
            errors.append(f"{shot_id}: scene script_section_id mismatch")
        if require_evidence and mapping.get("script_section_id") != section_id:
            errors.append(f"{shot_id}: mapping script_section_id mismatch")
        if require_evidence:
            for field in ("claim_ids", "action_keys", "evidence_row_ids"):
                expected = set(section.get(field) or [])
                if set(scene.get(field) or []) != expected:
                    errors.append(f"{shot_id}.{field} scene drift")
                if set(mapping.get(field) or []) != expected:
                    errors.append(f"{shot_id}.{field} mapping drift")
                if set(shot.get(field) or []) != expected:
                    errors.append(f"{shot_id}.{field} does not match section")
            visual_route = str(section.get("visual_route") or "")
            if visual_route:
                for field in (
                    "visual_route", "claim_visual_requirements", "generation_reference",
                ):
                    expected = section.get(field)
                    if scene.get(field) != expected:
                        errors.append(f"{shot_id}.{field} scene drift")
                    if mapping.get(field) != expected:
                        errors.append(f"{shot_id}.{field} mapping drift")
                    if shot.get(field) != expected:
                        errors.append(f"{shot_id}.{field} does not match section")
            if visual_route == "generated_from_product_image":
                for field in ("source_hash", "source_interval"):
                    if field in mapping or field in shot:
                        errors.append(f"{shot_id}.{field} must be absent for generated route")
            else:
                expected_source_hash = str(mapping.get("source_hash") or "")
                if str(shot.get("source_hash") or "") != expected_source_hash:
                    errors.append(f"{shot_id}.source_hash does not match mapping")
                if shot.get("source_interval") != mapping.get("source_interval"):
                    errors.append(f"{shot_id}.source_interval does not match mapping")
        narration = str(section.get("narration") or section.get("text") or "")
        screen_copy = str(section.get("screen_copy") or "")
        if str(shot.get("narration") or "") != narration:
            errors.append(f"{shot_id}.narration does not match {section_id}")
        if str(shot.get("screen_copy") or "") != screen_copy:
            errors.append(f"{shot_id}.screen_copy does not match {section_id}")
        expected_narration_hash = _content_hash({"section_id": section_id, "text": narration})
        expected_copy_hash = _content_hash({"section_id": section_id, "text": screen_copy})
        expected_caption_hash = _content_hash({
            "section_id": section_id,
            "screen_copy": screen_copy,
            "start_seconds": section.get("start_seconds"),
            "end_seconds": section.get("end_seconds"),
        })
        if require_evidence:
            for field, expected in (
                ("narration_hash", expected_narration_hash),
                ("screen_copy_hash", expected_copy_hash),
                ("caption_timeline_hash", expected_caption_hash),
            ):
                if shot.get(field) != expected:
                    errors.append(f"{shot_id}.{field} does not match current section")
        tts_hash = shot.get("tts_asset_hash")
        tts_duration = shot.get("tts_measured_duration")
        if require_evidence and (tts_hash is None) != (tts_duration is None):
            errors.append(f"{shot_id}: TTS hash/duration binding must be set together")
        if tts_hash is not None:
            if audio_dir is None:
                errors.append(f"{shot_id}: audio_dir required for TTS binding")
                continue
            number = section_id.rsplit("-", 1)[-1].zfill(3)
            audio = audio_dir / f"narration-s{number}.mp3"
            meta = audio_dir / f"narration-s{number}.mp3.json"
            lock_path = audio_dir / f"narration-s{number}.mp3.lock.json"
            if not audio.is_file() or _file_sha(audio) != tts_hash:
                errors.append(f"{shot_id}.tts_asset_hash does not match narration asset")
            try:
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                lock = {}
            if lock.get("text_sha") != _text_sha(narration):
                errors.append(f"{shot_id}: TTS text binding mismatch")
            try:
                meta_data = json.loads(meta.read_text(encoding="utf-8"))
                sentences = (meta_data.get("data") or {}).get("sentences") or meta_data.get("sentences") or []
                end_value = max(float(item.get("endTime", 0)) for item in sentences)
                # 单位自适应：doubao(seed-tts-2.0) endTime 以秒计（如 2.815），
                # 部分 provider 以毫秒计（如 2815）；>=100 视为毫秒。
                measured = end_value / 1000.0 if end_value >= 100 else end_value
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                measured = 0.0
            if measured <= 0 or abs(float(tts_duration) - measured) > 0.02:
                errors.append(f"{shot_id}.tts_measured_duration does not match TTS metadata")
            section_duration = float(section.get("end_seconds") or 0) - float(section.get("start_seconds") or 0)
            if measured > section_duration + 1e-6:
                errors.append(f"{shot_id}.tts_measured_duration exceeds section duration")
    if seen_scenes != set(scenes):
        errors.append("shot_execution_plan requires exactly one shot per scene")
    return errors


def tts_binding_errors(script: Mapping[str, Any], audio_dir: Path) -> list[str]:
    """Return errors when narration files/locks do not match current script text."""
    errors: list[str] = []
    for section in script.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        text = str(section.get("narration") or section.get("text") or "").strip()
        if not text:
            continue
        section_id = str(section.get("id") or "")
        if not section_id:
            errors.append("narration section missing id")
            continue
        number = section_id.rsplit("-", 1)[-1].zfill(3)
        audio = audio_dir / f"narration-s{number}.mp3"
        lock_path = audio_dir / f"narration-s{number}.mp3.lock.json"
        if not audio.is_file():
            errors.append(f"{section_id}: narration file missing")
            continue
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"{section_id}: narration lock missing or invalid")
            continue
        expected = {
            "text_sha": _text_sha(text),
            "voice_id": "zh_female_vv_uranus_bigtts",
            "resource_id": "seed-tts-2.0",
            "format": "mp3",
        }
        for key, value in expected.items():
            if lock.get(key) != value:
                errors.append(f"{section_id}: narration {key} binding mismatch")
        if not isinstance(lock.get("speech_rate"), int):
            errors.append(f"{section_id}: narration speech_rate missing")
    return errors


def shot_alignment_errors(shot_plan: Mapping[str, Any], script: Mapping[str, Any]) -> list[str]:
    """Check shot narration and screen copy by explicit section ID."""
    sections = {
        str(section.get("id") or ""): section
        for section in (script.get("sections") or [])
        if isinstance(section, Mapping) and section.get("id")
    }
    errors: list[str] = []
    for shot in shot_plan.get("shots") or []:
        if not isinstance(shot, Mapping):
            errors.append("shot entry is not an object")
            continue
        shot_id = str(shot.get("id") or "<unknown-shot>")
        section_id = str(shot.get("section_id") or "")
        if not section_id:
            errors.append(f"{shot_id}: section_id missing")
            continue
        section = sections.get(section_id)
        if section is None:
            errors.append(f"{shot_id}: section_id {section_id} not found")
            continue
        expected_narration = str(section.get("narration") or section.get("text") or "")
        expected_copy = str(section.get("screen_copy") or "")
        if str(shot.get("narration") or "") != expected_narration:
            errors.append(f"{shot_id}.narration does not match {section_id}")
        if str(shot.get("screen_copy") or "") != expected_copy:
            errors.append(f"{shot_id}.screen_copy does not match {section_id}")
    return errors


def alignment_gate_errors(checks: list[Mapping[str, Any]]) -> list[str]:
    """Require every machine visual alignment check to be an explicit yes."""
    errors: list[str] = []
    for check in checks:
        if not isinstance(check, Mapping):
            errors.append("alignment check is not an object")
            continue
        match = str(check.get("match") or "").lower()
        if match != "yes":
            errors.append(
                f"alignment {check.get('section_id') or '<unknown>'}: match={match or 'missing'}"
            )
    return errors


def current_alignment_checks(
    report: Mapping[str, Any], *, sample_sha256: str, script_sha256: str,
) -> list[Mapping[str, Any]] | None:
    """Return checks only when the report is bound to the current sample/script."""
    if not isinstance(report, Mapping):
        return None
    if report.get("sample_sha256") != sample_sha256 or report.get("script_sha256") != script_sha256:
        return None
    checks = report.get("checks")
    return checks if isinstance(checks, list) else None


def adapt_legacy_alignment_report(
    report: Mapping[str, Any], *, sample_sha256: str, script_sha256: str,
) -> list[dict[str, Any]] | None:
    """Bind a legacy report without inventing semantic dimension results."""
    checks = current_alignment_checks(
        report, sample_sha256=sample_sha256, script_sha256=script_sha256,
    )
    if checks is None:
        return None
    adapted: list[dict[str, Any]] = []
    dimension_fields = (
        "action_match", "result_support", "narration_caption_match",
        "product_identity_match", "crop_completeness", "caption_conflict",
    )
    for item in checks:
        if not isinstance(item, Mapping):
            continue
        row = {
            key: item.get(key)
            for key in ("shot_id", "section_id")
            if item.get(key)
        }
        row["legacy_match"] = str(item.get("match") or "")
        for field in dimension_fields:
            if field in item:
                row[field] = item[field]
        adapted.append(row)
    return adapted


def alignment_report_semantic_checks(
    report: Mapping[str, Any], *, sample_sha256: str, script_sha256: str,
    input_mode: str,
) -> list[dict[str, Any]] | None:
    """Read a hash-bound alignment report without upgrading coarse legacy matches.

    Source-led reports must already contain the canonical per-dimension fields.
    Reference-driven reports retain the legacy adapter for backward compatibility.
    """
    checks = current_alignment_checks(
        report, sample_sha256=sample_sha256, script_sha256=script_sha256,
    )
    if checks is None:
        return None
    if input_mode not in {"source_led", "source_led_template"}:
        return adapt_legacy_alignment_report(
            report, sample_sha256=sample_sha256, script_sha256=script_sha256,
        )
    return [dict(item) for item in checks if isinstance(item, Mapping)]


def _dimension(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return {
        "pass": "pass", "yes": "pass",
        "partial": "revise", "revise": "revise",
        "fail": "fail", "no": "fail", "error": "fail",
    }.get(normalized)


def build_semantic_alignment(
    artifacts: Mapping[str, Any],
    *,
    scope: str = "sample",
    expected_product_id: str | None = None,
    semantic_checks: list[Mapping[str, Any]] | None = None,
    audio_dir: Path | None = None,
) -> dict[str, Any]:
    """Build strict, hash-bound alignment for the rendered sample/final."""
    input_mode = str(artifacts.get("input_mode") or "reference_driven")
    source_led = input_mode in {"source_led", "source_led_template"}
    plan = artifacts.get("shot_execution_plan") if isinstance(artifacts.get("shot_execution_plan"), Mapping) else {}
    script = artifacts.get("script") if isinstance(artifacts.get("script"), Mapping) else {}
    scene_plan = artifacts.get("scene_plan") if isinstance(artifacts.get("scene_plan"), Mapping) else {}
    final_props = artifacts.get("final_props") if isinstance(artifacts.get("final_props"), Mapping) else {}
    render = artifacts.get("render") if isinstance(artifacts.get("render"), Mapping) else {}
    sections = {str(s.get("id")): s for s in script.get("sections", []) if isinstance(s, Mapping) and s.get("id")}
    actual_rows = final_props.get("shots") or final_props.get("scenes") or []
    actual_by_id = {str(s.get("id") or s.get("shot_id")): s for s in actual_rows if isinstance(s, Mapping) and (s.get("id") or s.get("shot_id"))}
    included_ids: set[str] | None = None
    trace = artifacts.get("sample_execution_trace")
    if scope == "sample" and isinstance(trace, Mapping):
        included_ids = {str(item.get("shot_id")) for item in trace.get("shots", []) if isinstance(item, Mapping) and isinstance(item.get("sample_window"), Mapping) and item["sample_window"].get("included") is True}
    selected_shots = [shot for shot in plan.get("shots", []) if isinstance(shot, Mapping) and (included_ids is None or str(shot.get("id") or shot.get("shot_id") or "") in included_ids)]
    selected_ids = {str(shot.get("id") or shot.get("shot_id") or "") for shot in selected_shots}
    section_to_shot = {str(shot.get("section_id") or ""): str(shot.get("id") or shot.get("shot_id") or "") for shot in selected_shots}
    provided: dict[str, Mapping[str, Any]] = {}
    unmatched_checks = duplicate_checks = 0
    for check in semantic_checks or []:
        if not isinstance(check, Mapping):
            unmatched_checks += 1
            continue
        key = str(check.get("shot_id") or "")
        if key not in selected_ids:
            key = section_to_shot.get(str(check.get("section_id") or ""), "")
        if not key:
            unmatched_checks += 1
        elif key in provided:
            duplicate_checks += 1
        else:
            provided[key] = check
    selected_scene_ids = {str(shot.get("scene_id") or "") for shot in selected_shots}
    selected_section_ids = {str(shot.get("section_id") or "") for shot in selected_shots}
    metadata = scene_plan.get("metadata") if isinstance(scene_plan.get("metadata"), Mapping) else {}
    selected_plan = {**plan, "shots": selected_shots}
    selected_script = {**script, "sections": [s for s in script.get("sections", []) if isinstance(s, Mapping) and str(s.get("id") or "") in selected_section_ids]}
    selected_scene_plan = {**scene_plan, "scenes": [s for s in scene_plan.get("scenes", []) if isinstance(s, Mapping) and str(s.get("id") or "") in selected_scene_ids], "metadata": {**metadata, "source_mapping": [m for m in metadata.get("source_mapping", []) if isinstance(m, Mapping) and str(m.get("scene_id") or "") in selected_scene_ids]}}
    lineage_errors = shot_execution_plan_errors(selected_plan, selected_script, selected_scene_plan, audio_dir=audio_dir)
    facts = artifacts.get("product_facts") if isinstance(artifacts.get("product_facts"), Mapping) else {}
    canonical_product_id = str(expected_product_id or facts.get("product_id") or facts.get("sku") or facts.get("product_name") or "").strip()
    results: list[dict[str, Any]] = []
    has_proof = any(shot.get("action_keys") or shot.get("evidence_row_ids") or shot.get("evidence_type") == "real_proof" for shot in selected_shots)
    if source_led and (not selected_shots or not has_proof):
        results.append({"scene_id": "", "shot_id": "<sample>", "action_match": "fail", "result_support": "fail", "narration_caption_match": "fail", "crop_completeness": "fail", "product_identity_match": "fail", "status": "fail", "reason_codes": ["sample_proof_missing"]})
    coverage_mismatch = source_led and (unmatched_checks > 0 or duplicate_checks > 0 or set(provided) != selected_ids)
    required_dimensions = ("action_match", "result_support", "narration_caption_match", "product_identity_match", "crop_completeness")
    for shot in selected_shots:
        shot_id = str(shot.get("id") or shot.get("shot_id") or "")
        section = sections.get(str(shot.get("section_id") or ""), {})
        actual = actual_by_id.get(shot_id, {})
        reasons: list[str] = []
        repair_reasons: list[str] = []
        if any(error.startswith(f"{shot_id}.") or error.startswith(f"{shot_id}:") for error in lineage_errors) or any(not error.startswith("shot-") for error in lineage_errors):
            reasons.append("lineage_drift")
        if not actual:
            reasons.append("actual_shot_missing")
        check = provided.get(shot_id) or {}
        dimensions = {field: _dimension(check.get(field)) for field in required_dimensions}
        if source_led and not check:
            reasons.append("semantic_review_missing")
        if source_led and any(value is None for value in dimensions.values()):
            reasons.append("semantic_dimensions_missing")
        if coverage_mismatch:
            reasons.append("semantic_coverage_mismatch")
        planned_actions = set(str(value) for value in (shot.get("action_keys") or section.get("action_keys") or []))
        actual_actions = set(str(value) for value in (actual.get("action_keys") or []))
        action_match = dimensions["action_match"] or ("fail" if source_led else "pass")
        if planned_actions and not planned_actions <= actual_actions:
            action_match = "fail"
        if action_match == "fail":
            reasons.append("action_missing")
        elif action_match == "revise":
            repair_reasons.append("action_support_weak")
        product_match = dimensions["product_identity_match"] or ("fail" if source_led else "pass")
        actual_product_id = str(actual.get("product_id") or actual.get("product_name") or actual.get("sku") or "").strip()
        if source_led and planned_actions:
            if not canonical_product_id:
                product_match = "fail"
                reasons.append("product_identity_unverified")
            elif product_match != "pass" or (actual_product_id and actual_product_id != canonical_product_id):
                product_match = "fail"
                reasons.append("product_identity_mismatch")
        caption_match = dimensions["narration_caption_match"] or ("fail" if source_led else "pass")
        if check.get("caption_conflict") is True or caption_match == "fail":
            caption_match = "fail"
            reasons.append("caption_conflict")
        elif caption_match == "revise":
            repair_reasons.append("caption_match_weak")
        result_support = dimensions["result_support"] or ("fail" if source_led else "pass")
        if result_support == "fail":
            reasons.append("result_unsupported")
        elif result_support == "revise":
            repair_reasons.append("result_support_weak")
        crop = dimensions["crop_completeness"] or ("fail" if source_led else "pass")
        if crop == "fail":
            reasons.append("crop_incomplete")
        elif crop == "revise":
            repair_reasons.append("crop_incomplete")
        status = "fail" if reasons else "revise" if repair_reasons or product_match == "revise" else "pass"
        results.append({"scene_id": str(shot.get("scene_id") or ""), "shot_id": shot_id, "action_match": action_match, "result_support": result_support, "narration_caption_match": caption_match, "crop_completeness": crop, "product_identity_match": product_match, "status": status, "reason_codes": reasons + repair_reasons})
    hashes = {}
    for key, artifact_key in (("script", "script"), ("scene_plan", "scene_plan"),
                              ("shot_execution_plan", "shot_execution_plan"), ("final_props", "final_props")):
        value = artifacts.get(artifact_key)
        if isinstance(value, Mapping):
            digest = value.get("artifact_sha256") or value.get("semantic_sha256")
            if digest:
                hashes[key] = str(digest)
    render_hash = render.get("sha256") or render.get("artifact_sha256") or render.get("semantic_sha256")
    if render_hash:
        hashes["render"] = str(render_hash)
    required_hashes = {"script", "scene_plan", "shot_execution_plan", "final_props", "render"}
    missing_hashes = sorted(required_hashes - set(hashes))
    if missing_hashes:
        for item in results:
            item["status"] = "fail"
            item["reason_codes"].append("missing_lineage_hash")
        status = "fail"
    else:
        status = "fail" if any(item["status"] == "fail" for item in results) else (
        "revise" if any(item["status"] == "revise" for item in results) else "pass"
        )
    return {
        "contract_version": "1.0",
        "scope": scope,
        "status": status,
        "input_hashes": hashes,
        "per_shot_results": results,
        "repair_targets": ([{"shot_id": item["shot_id"], "reason_codes": item["reason_codes"]}
                            for item in results if item["status"] in {"fail", "revise"}]),
    }


# 人工确认通道码表：样片门只拦截硬性冲突，其余部分性/静态/机器未复核判定
# 转人工确认通道（repair_targets 呈现给用户复核）。
HUMAN_REVIEW_CODES = frozenset({
    "action_support_weak", "result_support_weak", "caption_match_weak",
})
HARD_CONFLICT_CODES = frozenset({
    "product_identity_mismatch", "product_identity_unverified",
    "lineage_drift", "missing_lineage_hash",
    "sample_proof_missing", "actual_shot_missing",
    "action_missing", "result_unsupported", "crop_incomplete",
    "caption_conflict", "semantic_review_missing",
    "semantic_coverage_mismatch", "semantic_dimensions_missing",
})


def route_human_review_channel(alignment: Mapping[str, Any]) -> dict[str, Any]:
    """仅将低置信度的 weak 结果转为 revise，保留已知语义失败。

    - action_missing/result_unsupported/caption_conflict/crop_incomplete 等已知错配保持 fail；
    - 仅 action/result/caption weak 可进入 revise 修复路由；
    - 全部 pass → status=pass。
    """
    results: list[dict[str, Any]] = []
    hard = False
    any_revise = False
    for item in (alignment.get("per_shot_results") or []):
        if not isinstance(item, Mapping):
            results.append(dict(item) if isinstance(item, dict) else item)
            continue
        row = dict(item)
        reasons = [str(code) for code in (row.get("reason_codes") or [])]
        codes = set(reasons)
        if codes & HARD_CONFLICT_CODES:
            hard = True
            results.append(row)
            continue
        if codes & HUMAN_REVIEW_CODES:
            any_revise = True
            if row.get("status") == "fail":
                row["status"] = "revise"
            for dim in ("action_match", "result_support", "narration_caption_match",
                        "crop_completeness", "product_identity_match"):
                if row.get(dim) == "fail":
                    row[dim] = "revise"
        results.append(row)
    out = dict(alignment)
    out["per_shot_results"] = results
    if hard:
        out["status"] = "fail"
    elif any_revise:
        out["status"] = "revise"
    else:
        out["status"] = "pass"
    out["repair_targets"] = ([
        {"shot_id": str(item.get("shot_id") or ""), "reason_codes": list(item.get("reason_codes") or [])}
        for item in results
        if isinstance(item, Mapping) and str(item.get("status") or "") in {"fail", "revise"}
        and (item.get("reason_codes") or [])
    ] if out["status"] != "pass" else [])
    return out


def alignment_checkpoint_gate(
    evaluation: Mapping[str, Any] | None, *, input_mode: str, stage: str,
    current_hashes: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return checkpoint blockers for canonical sample/final alignment.

    source-led 的 sample/compose/publish 都必须 status == "pass"。revise 只能
    退回 edit/reopen，不能被普通 sample approval 覆盖。
    """
    if stage not in {"sample", "compose", "publish"}:
        return []
    alignment = evaluation.get("alignment") if isinstance(evaluation, Mapping) else None
    source_led = input_mode in {"source_led", "source_led_template"}
    migrated_reference = isinstance(alignment, Mapping) and alignment.get("contract_version") == "1.0"
    if not source_led and not migrated_reference:
        return []
    if not isinstance(alignment, Mapping):
        return [f"{stage} gate: source-led evaluation_report.alignment is required"] if source_led else []
    required_alignment_fields = {
        "contract_version", "scope", "status", "input_hashes",
        "per_shot_results", "repair_targets",
    }
    if set(alignment) != required_alignment_fields:
        return [f"{stage} gate: alignment canonical shape is incomplete"]
    if alignment.get("contract_version") != "1.0":
        return [f"{stage} gate: alignment.contract_version must be 1.0"]
    expected_scope = "sample" if stage == "sample" else "final"
    if alignment.get("scope") != expected_scope:
        return [f"{stage} gate: alignment.scope must be {expected_scope}"]
    status = str(alignment.get("status") or "")
    allowed_statuses = {"pass"} if source_led else ({"pass", "revise"} if stage == "sample" else {"pass"})
    if status not in allowed_statuses:
        return [f"{stage} gate: alignment.status={status or 'missing'} must be "
                "pass"]
    per_shot = alignment.get("per_shot_results")
    if not isinstance(per_shot, list) or not per_shot:
        return [f"{stage} gate: alignment.per_shot_results must cover at least one shot"]
    required_result_fields = {
        "scene_id", "shot_id", "action_match", "result_support",
        "narration_caption_match", "crop_completeness",
        "product_identity_match", "status", "reason_codes",
    }
    # 人工确认通道：仅"部分性/静态/机器未复核"判定码允许进样片门（revise，
    # 裁决权交人工）；硬性冲突码（产品身份/血统漂移/无证据）无论 stage 一律拦截。
    # 语义复核未绑定（coverage/dimensions missing）不视为样片硬伤——样片门本就
    # 存在，是为了让机器复核在渲染后跑一遍（stage51）。
    _HUMAN_REVIEW_CODES = HUMAN_REVIEW_CODES
    _HARD_CODES = HARD_CONFLICT_CODES
    seen_shots: set[str] = set()
    seen_scenes: set[str] = set()
    for item in per_shot:
        if not isinstance(item, Mapping) or set(item) != required_result_fields:
            return [f"{stage} gate: alignment per_shot canonical shape is incomplete"]
        shot_id = str(item.get("shot_id") or "")
        scene_id = str(item.get("scene_id") or "")
        if not shot_id or not scene_id or shot_id in seen_shots or scene_id in seen_scenes:
            return [f"{stage} gate: alignment per_shot coverage is invalid"]
        seen_shots.add(shot_id)
        seen_scenes.add(scene_id)
        dimensions = (
            item.get("action_match"), item.get("result_support"),
            item.get("narration_caption_match"), item.get("crop_completeness"),
            item.get("product_identity_match"),
        )
        reasons = [str(code) for code in (item.get("reason_codes") or [])]
        hard = [code for code in reasons if code in _HARD_CODES]
        if stage != "sample":
            if item.get("status") != "pass" or any(value != "pass" for value in dimensions) or reasons:
                return [f"{stage} gate: alignment per_shot status must be exactly pass"]
            continue
        # ---- 参考模式的兼容分支；source-led 在上方已要求总体 pass ----
        if hard:
            return [f"{stage} gate: alignment per_shot carries hard conflict: {', '.join(sorted(hard))}"]
        unknown = [code for code in reasons if code not in _HUMAN_REVIEW_CODES]
        if unknown:
            return [f"{stage} gate: alignment per_shot carries unknown reason codes: {', '.join(sorted(unknown))}"]
        if item.get("status") == "pass":
            if any(value != "pass" for value in dimensions) or reasons:
                return [f"{stage} gate: passing per_shot cannot carry non-pass dimensions or reason_codes"]
            continue
        if item.get("status") not in {"revise", "partial"}:
            return [f"{stage} gate: alignment per_shot status must be pass or revise"]
        # 人工确认通道：revise 允许部分维度非 pass，但不得出现 fail（冲突裁决归人工）
        if reasons == [] and any(value != "pass" for value in dimensions):
            return [f"{stage} gate: revise per_shot must carry partial reason_codes"]
        if any(value == "fail" for value in dimensions):
            return [f"{stage} gate: alignment per_shot cannot carry fail dimensions"]
    repair_targets = alignment.get("repair_targets") or []
    if stage != "sample" and repair_targets:
        return [f"{stage} gate: passing alignment cannot contain repair_targets"]
    for item in repair_targets:
        if not isinstance(item, Mapping):
            return [f"{stage} gate: alignment repair_targets entries must be objects"]
        codes = [str(code) for code in (item.get("reason_codes") or [])]
        if any(code in _HARD_CODES for code in codes):
            return [f"{stage} gate: sample alignment repair_targets cannot carry hard codes"]
        if any(code not in _HUMAN_REVIEW_CODES for code in codes):
            return [f"{stage} gate: sample alignment repair_targets carry unknown codes"]
    if source_led or migrated_reference:
        required = {"script", "scene_plan", "shot_execution_plan", "final_props", "render"}
        bound = alignment.get("input_hashes") if isinstance(alignment.get("input_hashes"), Mapping) else {}
        current = current_hashes or {}
        if set(bound) != required or set(current) != required:
            return [f"{stage} gate: alignment canonical hashes are incomplete"]
        stale = [name for name in sorted(required) if str(bound.get(name)) != str(current.get(name))]
        if stale:
            return [f"{stage} gate: stale alignment hashes: {', '.join(stale)}"]
    return []


def apply_alignment_to_evaluation(
    evaluation: Mapping[str, Any], alignment: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach alignment and promote failures into the evaluation hard gate."""
    merged = dict(evaluation)
    hard_gate = dict(merged.get("hard_gate") or {})
    checks = [item for item in (hard_gate.get("checks") or []) if not isinstance(item, Mapping) or item.get("id") != "semantic_alignment"]
    alignment_status = str(alignment.get("status") or "fail")
    check_status = "pass" if alignment_status == "pass" else "fail"
    checks.append({
        "id": "semantic_alignment", "name": "画面、口播与花字语义一致",
        "status": check_status, "severity": "fatal" if alignment_status == "fail" else "warning" if alignment_status == "revise" else "info",
        "message": "逐镜语义对齐通过" if check_status == "pass" else "存在关键动作、产品身份或字幕冲突",
        "evidence": {"alignment_status": alignment_status},
        "affected_shots": [str(item.get("shot_id")) for item in alignment.get("repair_targets", []) if isinstance(item, Mapping) and item.get("shot_id")],
        "fixable": alignment_status == "revise",
        "fix_suggestion": "按 repair_targets 返回 Script 或 Scene Plan 修复" if check_status == "fail" else "",
    })
    hard_gate["checks"] = checks
    hard_gate["pass"] = bool(hard_gate.get("pass", True)) and check_status == "pass"
    merged["hard_gate"] = hard_gate
    merged["alignment"] = dict(alignment)
    existing_repairs = [item for item in (merged.get("repair_targets") or []) if not isinstance(item, Mapping) or item.get("check_id") != "semantic_alignment"]
    for item in alignment.get("repair_targets", []):
        if not isinstance(item, Mapping):
            continue
        reasons = [str(value) for value in item.get("reason_codes", [])]
        caption_only = reasons and all(value in {"caption_conflict", "caption_match_weak"} for value in reasons)
        lineage_only = reasons and all(value in {"lineage_drift", "missing_lineage_hash"} for value in reasons)
        action = "edit_caption" if caption_only else "replace_asset"
        upstream = "script" if caption_only else "assets" if lineage_only else "scene_plan"
        existing_repairs.append({
            "check_id": "semantic_alignment", "action": action,
            "affected_shots": [str(item.get("shot_id"))] if item.get("shot_id") else [],
            "scene_id": str(item.get("scene_id")) if item.get("scene_id") else None,
            "upstream_stage": upstream, "rerun_scope": "preview",
            "note": ", ".join(reasons),
        })
    for item in existing_repairs:
        if item.get("scene_id") is None:
            item.pop("scene_id", None)
    merged["repair_targets"] = existing_repairs
    if alignment_status == "fail":
        merged["status"], merged["recommended_action"] = "fail", "reject"
    elif alignment_status == "revise" and merged.get("status") == "pass":
        merged["status"], merged["recommended_action"] = "revise", "repair"
    return merged
