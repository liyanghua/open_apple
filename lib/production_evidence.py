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
MANUAL_ALLOWED = frozenset(CONTENT_CHECKS) - {"fact_source"}
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
    slot = record.get("content_slot_id")
    if not isinstance(slot, str) or not slot:
        raise ValueError("Production record has no content_slot_id")
    render = record.get("render") or {}
    path = project_file(root, render.get("path"))
    sha = file_sha256(path)
    if sha != render.get("sha256"):
        raise ValueError("Production render hash mismatch")
    refs = {"production_record": record_path}
    for namespace in ("canonical_artifacts", "review_dependencies"):
        for key, ref in (record.get(namespace) or {}).items():
            refs[f"{namespace}:{key}"] = ref
    for key in ("baseline", "fact_snapshot_ref", "quality_report_ref", "manual_verifications_ref"):
        if record.get(key):
            refs[key] = record[key]
    for role in ("quality_report_ref", "manual_verifications_ref"):
        if record.get(role):
            document = read_object(root, record[role])
            checks = document.get("checks", document.get("items", []))
            if isinstance(checks, list):
                for check in checks:
                    for ref in check.get("evidence_refs", []) if isinstance(check, dict) else []:
                        refs[f"evidence:{ref}"] = ref
    dependencies = {}
    for key, ref in sorted(refs.items()):
        if isinstance(ref, dict):
            ref = ref.get("path")
        dependency = project_file(root, ref)
        dependencies[key] = {"path": ref, "sha256": file_sha256(dependency)}
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
    required = list(dict.fromkeys(REQUIRED_CHECKS + tuple(extra)))
    checks, blockers = {}, []
    for name in list(dict.fromkeys(required + list(entries))):
        item = entries.get(name, {})
        status = item.get("status", "not_run")
        if not isinstance(status, str) or status not in CHECK_STATUSES:
            status = "error"
        measurement = measured.get(name, {})
        evidenced = (report_bound and measurement.get("status") == "pass"
                     and item.get("method") == measurement.get("method")
                     and _evidence_exists(root, item.get("evidence_refs"))
                     and sorted(item["evidence_refs"]) == sorted(measurement.get("evidence_refs", [])))
        effective = "pass" if status == "pass" and evidenced else (status if status != "pass" else "unverified")
        for verification in manual if isinstance(manual, list) else []:
            if (name in MANUAL_ALLOWED and name not in duplicates and isinstance(verification, dict)
                    and verification.get("check_id") == name and verification.get("decision") == "pass"
                    and _identified_verification(verification)
                    and verification.get("render_sha256") == render_sha
                    and verification.get("qa_report_sha256") == report_sha and report_bound
                    and _evidence_exists(root, verification.get("evidence_refs"))):
                effective = "manual_verified"
                break
        checks[name] = {"machine_status": status, "effective_status": effective,
                        "evidence_refs": item.get("evidence_refs", []), "issues": item.get("issues", [])}
        if name in required and effective not in {"pass", "manual_verified"}:
            blockers.append(name)
    return {"eligible": not blockers, "status": "pass" if not blockers else "incomplete",
            "checks": checks, "blocking_checks": blockers, "qa_report_sha256": report_sha,
            "report_bound": report_bound, "historical_import": record.get("provenance") == "legacy_import"}
