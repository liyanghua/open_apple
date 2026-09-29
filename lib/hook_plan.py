"""Hook plan builder (Design_Review P1-1).

Writes the per-candidate hook plan into the creative contract: what the first
1-1.5s shows, the first audible information, the promise, the real evidence
that backs it, the hook pattern and how this candidate differs from siblings.
Derives from the creative control plan and script; explicit overrides win.
Version 1 remains the default. Explicit v2 requires a complete [0, 3) package.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

HOOK_PATTERNS = ("problem_first", "result_first", "contrast", "contradiction", "scene_pain", "other")


def _section_summary(section: Mapping[str, Any] | None) -> str:
    if not isinstance(section, Mapping):
        return ""
    return str(section.get("summary") or section.get("title") or "")


def build_hook_plan(
    project_id: str,
    *,
    version: str = "1.0",
    creative_control_plan: Mapping[str, Any] | None = None,
    script: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if version not in {"1.0", "2.0"}:
        raise ValueError("Unsupported hook plan version")
    sections = creative_control_plan.get("sections") if isinstance(creative_control_plan, Mapping) and isinstance(creative_control_plan.get("sections"), Mapping) else {}
    content = sections.get("content_direction") if isinstance(sections.get("content_direction"), Mapping) else {}
    script_sections = [s for s in (script.get("sections") or []) if isinstance(s, Mapping)] if isinstance(script, Mapping) else []
    first_section = script_sections[0] if script_sections else {}

    first_audio = str(first_section.get("narration") or first_section.get("text") or "")
    first_frame_visual = str(first_section.get("visual_intent") or "")
    promise = _section_summary(content) or str(first_section.get("section_goal") or "")
    evidence_refs = content.get("evidence_refs") or []
    proof_evidence = "；".join(str(item) for item in evidence_refs)

    base: dict[str, Any] = {
        "version": version,
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hook_window_seconds": [0.0, 3.0 if version == "2.0" else 1.5],
        "first_frame_visual": first_frame_visual,
        "first_audio": first_audio,
        "promise": promise,
        "proof_evidence": proof_evidence,
        "hook_pattern": "other",
        "candidate_variants": [],
        "revision_round": 0,
    }
    if overrides:
        for key, value in overrides.items():
            if key == "hook_pattern" and value not in HOOK_PATTERNS:
                raise ValueError(f"hook_pattern must be one of {HOOK_PATTERNS}")
            if value is not None:
                base[key] = value
    if base["version"] == "2.0":
        from schemas.artifacts import validate_artifact
        validate_artifact("hook_plan", base)
    return base
