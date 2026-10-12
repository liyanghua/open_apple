"""Load and verify pinned, versioned product-category policy profiles."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import ValidationError

from lib.artifact_hashing import verify_hashes
from schemas.artifacts import validate_artifact


ROOT = Path(__file__).resolve().parents[1]
TOWEL_PROFILE_PATH = "config/category_profiles/towel-v1.json"
REF_FIELDS = frozenset({"path", "profile_id", "category_id", "version", "artifact_sha256"})


def _profile_path(project_dir: Path, raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise ValueError("category_profile_ref.path must be a non-empty POSIX path")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".json":
        raise ValueError("category_profile_ref.path must be a safe relative JSON path")
    if relative.parts[:2] == ("config", "category_profiles") and len(relative.parts) == 3:
        base = ROOT
    elif relative.parts[0] == "artifacts" and len(relative.parts) >= 2:
        base = Path(project_dir)
    else:
        raise ValueError("category_profile_ref.path must be in artifacts/ or config/category_profiles/")
    base_resolved = base.resolve()
    candidate = (base / Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(base_resolved):
        raise ValueError("category_profile_ref.path escapes its allowed root")
    return candidate


def _load_verified_profile(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"category profile cannot be loaded: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError("category profile must be an object")
    try:
        validate_artifact("category_profile", data)
    except ValidationError as exc:
        raise ValueError(f"category profile schema invalid: {exc.message}") from exc
    if not verify_hashes(data).valid:
        raise ValueError("category profile integrity hashes do not match its contents")

    actions = set(data["action_keys"])
    visible_actions = set(data["action_visible_results"])
    if visible_actions != actions:
        raise ValueError(
            "category profile action_visible_results must cover action_keys exactly"
        )
    if data["default_action"] not in actions:
        raise ValueError("category profile default_action is not an action_key")
    evidence_ids = set(data["evidence_action_map"])
    if set(data["evidence_requirements"]) != evidence_ids:
        raise ValueError(
            "category profile evidence_requirements must cover evidence_action_map exactly"
        )
    unknown_mappings = set(data["evidence_action_map"].values()) - actions
    if unknown_mappings:
        raise ValueError(f"category profile evidence map uses unknown actions: {sorted(unknown_mappings)}")
    for direction, rule in data["direction_action_rules"].items():
        unknown = set(rule.get("any_of") or []) | set(rule.get("all_of") or [])
        unknown -= actions
        if unknown:
            raise ValueError(f"category profile {direction} rule uses unknown actions: {sorted(unknown)}")
    timing = data["shot_timing"]
    unknown_structures = set(timing["by_structure"]) - set(data["allowed_structures"])
    if unknown_structures:
        raise ValueError(f"category profile timing uses disallowed structures: {sorted(unknown_structures)}")
    for name in ("raw_action_seconds", "body_cut_seconds"):
        if timing[name]["min"] > timing[name]["max"]:
            raise ValueError(f"category profile {name} min exceeds max")
    raw = timing["raw_action_seconds"]
    if not raw["min"] <= timing["default_raw_seconds"] <= raw["max"]:
        raise ValueError("category profile default_raw_seconds is outside raw_action_seconds")
    for structure, overrides in timing["by_structure"].items():
        for name, interval in overrides.items():
            if interval["min"] > interval["max"]:
                raise ValueError(f"category profile {structure}.{name} min exceeds max")
    qa_ids = [item["id"] for item in data["qa_checks"]]
    if len(qa_ids) != len(set(qa_ids)):
        raise ValueError("category profile qa_checks IDs must be unique")
    return data


def load_category_profile_ref(project_dir: Path, ref: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a project or bundled profile and verify its exact frozen binding.

    Project-local ``artifacts/...`` refs stay inside ``project_dir``; bundled
    ``config/category_profiles/<file>.json`` refs stay inside this repository.
    Any missing, malformed, moved or edited profile fails closed.
    """
    if not isinstance(ref, Mapping) or set(ref) != REF_FIELDS:
        raise ValueError("category_profile_ref must contain exactly path, profile_id, category_id, version and artifact_sha256")
    for field in REF_FIELDS:
        if not isinstance(ref[field], str) or not ref[field].strip():
            raise ValueError(f"category_profile_ref.{field} must be a non-empty string")
    sha = str(ref["artifact_sha256"])
    if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError("category_profile_ref.artifact_sha256 must be a lowercase SHA-256")
    profile = _load_verified_profile(_profile_path(Path(project_dir), str(ref["path"])))
    for field in ("profile_id", "category_id", "version", "artifact_sha256"):
        if ref[field] != profile[field]:
            raise ValueError(f"category_profile_ref.{field} does not match the profile")
    return profile


def load_legacy_towel_profile() -> dict[str, Any]:
    """Preserve the v1.0 towel contract without requiring a new ref."""
    return _load_verified_profile(_profile_path(ROOT, TOWEL_PROFILE_PATH))


def bundled_towel_profile_ref() -> dict[str, str]:
    """Return the exact bundled ref for new towel artifacts."""
    profile = load_legacy_towel_profile()
    return {"path": TOWEL_PROFILE_PATH, **{
        field: str(profile[field])
        for field in ("profile_id", "category_id", "version", "artifact_sha256")
    }}
