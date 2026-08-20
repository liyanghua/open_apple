"""Load and validate the built-in Research analysis dimension profiles."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from lib.artifact_hashing import canonical_bytes


ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "knowledge" / "analysis_profiles"
PROFILE_SCHEMA = ROOT / "schemas" / "knowledge" / "analysis_dimension_profile.schema.json"
PRIOR_DIR = ROOT / "knowledge" / "industry_priors"
PRIOR_SCHEMA = ROOT / "schemas" / "knowledge" / "industry_prior.schema.json"


@lru_cache(maxsize=16)
def load_analysis_profile(profile_id: str, version: str = "1.0") -> dict[str, Any]:
    """Return a validated built-in profile by id and version."""
    if not profile_id or "/" in profile_id or "\\" in profile_id:
        raise ValueError("Invalid analysis profile id")
    major = version.split(".", 1)[0]
    path = PROFILE_DIR / f"{profile_id}.v{major}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Analysis profile not found: {profile_id}@{version}")
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    schema = json.loads(PROFILE_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(value, schema)
    if value["version"] != version:
        raise ValueError(f"Profile version mismatch: expected {version}, got {value['version']}")
    return value


def list_analysis_profiles() -> list[dict[str, str]]:
    """List profile ids and versions without loading arbitrary files."""
    profiles = []
    for path in sorted(PROFILE_DIR.glob("*.v*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(value, dict) and value.get("profile_id") and value.get("version"):
            profiles.append({"profile_id": str(value["profile_id"]), "version": str(value["version"])})
    return profiles


def analysis_profile_ref(profile_id: str, version: str = "1.0") -> dict[str, str]:
    """Return the immutable identity locked into Research artifacts."""
    profile = load_analysis_profile(profile_id, version)
    return {
        "profile_id": profile_id,
        "version": version,
        "sha256": hashlib.sha256(canonical_bytes(profile)).hexdigest(),
    }


def validate_analysis_profile_ref(profile_ref: dict[str, Any]) -> None:
    """Fail when an artifact claims a built-in profile with the wrong digest."""
    if not isinstance(profile_ref, dict):
        raise ValueError("profile_ref must identify a locked analysis profile")
    expected = analysis_profile_ref(
        str(profile_ref.get("profile_id", "")),
        str(profile_ref.get("version", "")),
    )
    if profile_ref != expected:
        raise ValueError("profile_ref does not match the locked built-in profile")


def research_projection_cache_key(
    upstream_semantic_hashes: dict[str, str],
    *,
    profile_ref: dict[str, str],
    projector_version: str,
    model_version: str,
    prompt_version: str,
    taxonomy_version: str,
) -> str:
    """Hash every semantic dependency of the lightweight Research projection."""
    validate_analysis_profile_ref(profile_ref)
    if not upstream_semantic_hashes or any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value.lower())
        for value in upstream_semantic_hashes.values()
    ):
        raise ValueError("upstream semantic hashes must be non-empty SHA-256 values")
    versions = {
        "projector": projector_version,
        "model": model_version,
        "prompt": prompt_version,
        "taxonomy": taxonomy_version,
    }
    if any(not isinstance(value, str) or not value for value in versions.values()):
        raise ValueError("projection dependency versions must be non-empty")
    payload = {
        "upstream_semantic_hashes": dict(sorted(upstream_semantic_hashes.items())),
        "profile_ref": profile_ref,
        "versions": versions,
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


@lru_cache(maxsize=16)
def load_industry_prior(prior_id: str, version: str = "1.0") -> dict[str, Any]:
    """Return a validated, reviewed industry reminder pack."""
    if not prior_id or "/" in prior_id or "\\" in prior_id:
        raise ValueError("Invalid industry prior id")
    major = version.split(".", 1)[0]
    path = PRIOR_DIR / f"{prior_id}.v{major}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Industry prior not found: {prior_id}@{version}")
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    schema = json.loads(PRIOR_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(value, schema)
    if value["version"] != version:
        raise ValueError(f"Industry prior version mismatch: expected {version}, got {value['version']}")
    return value
