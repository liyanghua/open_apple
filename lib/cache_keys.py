"""Canonical cache-key helpers shared by deterministic and provider tools."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def file_identity(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    path = Path(value)
    if not path.is_file():
        return value
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"content_sha256": digest.hexdigest(), "size_bytes": path.stat().st_size}


def canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ffmpeg_revision() -> str:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5, check=False
        )
        return (result.stdout or result.stderr).splitlines()[0].strip()
    except Exception:
        return "ffmpeg-unavailable"

