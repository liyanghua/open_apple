"""File-bound production evidence. Pure validation; no creative or stage decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

MACHINE_CHECKS = (
    "file_integrity", "decode", "video_profile", "duration", "audio_track",
    "font_identity", "text_layout", "dependency_integrity",
)
CONTENT_CHECKS = (
    "fact_source", "product_identity", "narration_content", "caption_alignment", "visual_continuity",
)
REQUIRED_CHECKS = MACHINE_CHECKS + CONTENT_CHECKS
MANUAL_ALLOWED = (frozenset(CONTENT_CHECKS) - {"fact_source", "product_identity", "caption_alignment"}) | {"video_judge"}
CHECK_STATUSES = frozenset({"pass", "fail", "not_run", "error"})


def project_file(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Expected a project-relative file")
    path = (Path(root) / value).resolve()
    try:
        path.relative_to(Path(root).resolve())
    except ValueError as exc:
        raise ValueError("File escapes project") from exc
    if not path.is_file():
        raise ValueError(f"Missing project file: {value}")
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(root: Path, value: Any) -> dict:
    result = json.loads(project_file(root, value).read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Expected JSON object")
    return result


def production_subject_hash(subject: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(subject, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_production_subject(root: Path, record_path: str) -> dict:
    """Snapshot actual bytes, including record, facts, QA and all named evidence.

    Historical artifact semantic hashes remain untouched. A new final approval
    uses file hashes and is therefore invalidated by any dependent file change.
    """
    root = Path(root)
    record = read_object(root, record_path)
    if record.get("version") == "1.1":
        from schemas.artifacts import validate_artifact
        try:
            validate_artifact("production_record", record)
        except Exception as exc:
            raise ValueError(f"Invalid versioned production record: {exc}") from exc
    slot = record.get("content_slot_id")
    if not isinstance(slot, str) or not slot:
        raise ValueError("Production record has no content_slot_id")
    render = record.get("render") or {}
    path = project_file(root, render.get("path"))
    sha = file_sha256(path)
    if sha != render.get("sha256"):
        raise ValueError("Production render hash mismatch")
    from lib.production_dependency_graph import dependency_closure
    closure = dependency_closure(root, record_path)
    dependencies = {"file:" + name: ref for name, ref in closure.items()}
    dependencies["production_record"] = closure[project_file(root, record_path).relative_to(root.resolve()).as_posix()]
    return {
        "version": "1.0", "content_slot_id": slot, "record_path": record_path,
        "render": {"path": render["path"], "sha256": sha},
        "dependencies": dependencies,
    }


def verify_production_subject(root: Path, subject: Mapping[str, Any]) -> bool:
    try:
        actual = build_production_subject(root, subject["record_path"])
        return production_subject_hash(actual) == production_subject_hash(subject)
    except (ValueError, OSError, KeyError, TypeError):
        return False


def _evidence_exists(root: Path, refs: Any) -> bool:
    if not isinstance(refs, list) or not refs:
        return False
    try:
        return all(project_file(root, ref).is_file() for ref in refs)
    except (ValueError, OSError):
        return False


def _identified_verification(value: Mapping[str, Any]) -> bool:
    reviewer, when = value.get("reviewer_id"), value.get("verified_at")
    if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(when, str):
        return False
    try:
        return datetime.fromisoformat(when.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def quality_summary(root: Path, record: Mapping[str, Any]) -> dict:
    """Never turn absent measurements or legacy overall pass into certification."""
    root = Path(root)
    report, report_sha, manual = {}, None, []
    try:
        report = read_object(root, record.get("quality_report_ref"))
        report_sha = file_sha256(project_file(root, record["quality_report_ref"]))
    except (ValueError, OSError, KeyError):
        pass
    try:
        manual = read_object(root, record.get("manual_verifications_ref")).get("items", [])
    except (ValueError, OSError):
        pass
    render = record.get("render") or {}
    render_sha = render.get("sha256")
    try:
        actual_sha = file_sha256(project_file(root, render.get("path")))
    except (ValueError, OSError):
        actual_sha = None
    report_bound = bool(actual_sha and render_sha == actual_sha == report.get("render_sha256"))
    # A cached pass and an existing evidence file are insufficient. Re-project
    # the identified tool sources against the actual media on every read.
    measured = {}
    current = {}
    source_refs = report.get("source_refs")
    if report_bound and isinstance(source_refs, dict):
        from lib.production_quality import collect_production_quality

        try:
            current = collect_production_quality(root, record, source_refs)
            measured = {item["id"]: item for item in current["checks"]}
        except (ValueError, OSError, KeyError, TypeError):
            pass
    raw = report.get("checks", [])
    entries, duplicates = {}, set()
    for check in raw if isinstance(raw, list) else []:
        if not isinstance(check, dict) or not isinstance(check.get("id"), str):
            continue
        name = check["id"]
        if name in entries:
            duplicates.add(name)
        entries[name] = check
    for name in duplicates:
        entries[name] = {"status": "error", "evidence_refs": [], "issues": ["duplicate_check_id"]}
    extra = report.get("required_checks")
    extra = [name for name in extra if isinstance(name, str) and name] if isinstance(extra, list) else []
    from lib.opening_quality_scope import quality_applicability
    scope, applicability = quality_applicability(root, record)
    if current:
        applicability = current["applicability"]
    category_ids: set[str] = set()
    category_error = False
    if record.get("version") == "1.1":
        try:
            from lib.category_profile import load_category_profile_ref
            category = load_category_profile_ref(root, record.get("category_profile_ref"))
            category_ids = {item["id"] for item in category["qa_checks"]}
        except (ValueError, OSError, TypeError, KeyError):
            category_error = True
    required = list(dict.fromkeys(
        [name for name, rule in applicability.items() if rule["required"]] + extra + sorted(category_ids)
    ))
    checks, blockers = {}, []
    for name in list(dict.fromkeys(required + list(applicability) + list(entries))):
        item = entries.get(name, {})
        status = item.get("status", "not_run")
        if not isinstance(status, str) or status not in CHECK_STATUSES:
            status = "error"
        measurement = measured.get(name, {})
        evidenced = (report_bound and measurement.get("status") == "pass"
                     and item.get("method") == measurement.get("method")
                     and _evidence_exists(root, item.get("evidence_refs"))
                     and sorted(item["evidence_refs"]) == sorted(measurement.get("evidence_refs", [])))
        if "opening" in record:
            status = "error" if name in duplicates else measurement.get("status", "not_run")
        effective = "pass" if status == "pass" and evidenced else (status if status != "pass" else "unverified")
        for verification in manual if isinstance(manual, list) else []:
            if (name in (MANUAL_ALLOWED | (category_ids - {"product_identity", "fact_source", "caption_alignment"}))
                    and name not in duplicates and isinstance(verification, dict)
                    and verification.get("check_id") == name and verification.get("decision") == "pass"
                    and _identified_verification(verification)
                    and verification.get("render_sha256") == render_sha
                    and verification.get("qa_report_sha256") == report_sha and report_bound
                    and (name not in category_ids or verification.get("category_profile_sha256") ==
                         (record.get("category_profile_ref") or {}).get("artifact_sha256"))
                    and ("opening" not in record or current.get("dependency_fingerprint") is not None
                         and current.get("dependency_fingerprint") == report.get("dependency_fingerprint"))
                    and _evidence_exists(root, verification.get("evidence_refs"))):
                effective = "manual_verified"
                break
        rule = applicability.get(name, {"applies": True, "required": True, "reason": "Additional required check."})
        if name not in duplicates and report_bound and measurement.get("effective_status") == "manual_verified" and name in {"opening_motion", "opening_framing"}:
            effective = "manual_verified"
        if rule.get("applies") is False and rule.get("reason"):
            effective = "not_applicable"
        checks[name] = {"machine_status": status, "applicability": rule,
                        "method": measurement.get("method", item.get("method")),
                        **{key: measurement[key] for key in ("execution_status", "source_provenance_status", "observations") if key in measurement}, "effective_status": effective,
                        "evidence_refs": measurement.get("evidence_refs", item.get("evidence_refs", [])), "issues": measurement.get("issues", item.get("issues", []))}
        if name in required and effective not in {"pass", "manual_verified", "not_applicable"}:
            blockers.append(name)
    if scope in {"preview", "invalid"}:
        blockers.append("opening_scope_not_final")
    if category_error:
        blockers.append("category_profile")
    completed = not blockers
    aggregate = "manual_verified" if completed and any(c["effective_status"] == "manual_verified" for c in checks.values()) else "pass"
    return {"eligible": completed, "scope": scope, "applicability": applicability, "status": aggregate if completed else "incomplete",
            "checks": checks, "blocking_checks": blockers, "qa_report_sha256": report_sha,
            "report_bound": report_bound, "historical_import": record.get("provenance") == "legacy_import"}
