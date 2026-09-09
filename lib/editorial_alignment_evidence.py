"""Hash-bound alignment evidence for an editorial render version.

The editor never supplies a reusable alignment report.  This module creates a
new evidence envelope from the rendered file and the current timeline/source
bindings so a baseline report cannot accidentally certify a changed edit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from lib.cache_keys import canonical_digest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_hash(value: Any, field: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text.lower()):
        raise ValueError(f"{field} must be a 64-character sha256")
    return text


def build_editorial_alignment_evidence(
    *,
    timeline: Mapping[str, Any],
    output_path: str | Path,
    output_probe: Mapping[str, Any] | None,
    frame_samples: list[Mapping[str, Any]] | None,
    fact_bindings: list[Mapping[str, Any]],
    script_hash: str,
    product_facts_hash: str,
    visual_requirements: list[Mapping[str, Any]],
    checks: list[Mapping[str, Any]] | None = None,
    baseline_alignment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a fresh, output-bound source-led alignment report.

    ``output_probe`` and ``frame_samples`` are mandatory proof inputs.  A
    baseline report is deliberately never accepted, even when its hashes look
    current: every render revision must produce new evidence.
    """
    if baseline_alignment is not None:
        raise ValueError("baseline alignment report cannot be reused")
    if not isinstance(timeline, Mapping):
        raise ValueError("timeline is required")
    declared_timeline_hash = timeline.get("timeline_hash")
    timeline_payload = {key: value for key, value in timeline.items() if key != "timeline_hash"}
    timeline_hash = canonical_digest(timeline_payload)
    if declared_timeline_hash is not None:
        declared_timeline_hash = _valid_hash(declared_timeline_hash, "timeline_hash")
        # Version snapshots may carry the server-derived hash for transport,
        # but it must describe the exact payload received by this builder.
        if declared_timeline_hash != timeline_hash:
            raise ValueError("timeline_hash is stale or does not match the rendered timeline")
    script_hash = _valid_hash(script_hash, "script_hash")
    product_facts_hash = _valid_hash(product_facts_hash, "product_facts_hash")
    if not isinstance(output_probe, Mapping):
        raise ValueError("output_probe is required for fresh alignment evidence")
    if not isinstance(frame_samples, list) or not frame_samples:
        raise ValueError("frame_samples are required for fresh alignment evidence")
    if not isinstance(fact_bindings, list):
        raise ValueError("fact_bindings must be a list")
    if not isinstance(visual_requirements, list):
        raise ValueError("visual_requirements must be a list")
    output = Path(output_path)
    if not output.is_file():
        raise ValueError(f"alignment output not found: {output}")
    output_hash = _sha256(output)
    rows = [dict(item) for item in (checks or []) if isinstance(item, Mapping)]
    status = "pass" if rows and all(str(row.get("status")) == "pass" for row in rows) else "fail"
    report = {
        "contract_version": "editorial-alignment-1.0",
        "scope": str(timeline.get("scope") or "editorial"),
        "status": status,
        "timeline_hash": timeline_hash,
        "output_sha256": output_hash,
        "source_hashes": {"script": script_hash, "product_facts": product_facts_hash},
        "fact_bindings": [dict(item) for item in fact_bindings],
        "visual_requirements": [dict(item) for item in visual_requirements],
        "output_probe": dict(output_probe),
        "frame_samples": [dict(item) for item in frame_samples],
        "checks": rows,
        "alignment": {
            "status": status,
            "timeline_hash": timeline_hash,
            "output_sha256": output_hash,
            "checks": rows,
        },
    }
    report["evidence_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return report
