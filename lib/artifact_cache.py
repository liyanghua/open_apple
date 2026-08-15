"""Validated content-addressed cache for deterministic tool artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from lib.cache_io import atomic_write_json, exclusive_lock, link_or_copy_atomic

_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SECRET_KEYS = {
    "api_key", "authorization", "access_token", "secret", "signature", "signed_url"
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact(child)
            for key, child in value.items()
            if key.lower() not in _SECRET_KEYS
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


@dataclass(frozen=True)
class CacheLookup:
    hit: bool
    key: str
    artifacts: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True)
class CacheRecord:
    key: str
    artifacts: tuple[str, ...]
    metadata: dict[str, Any]


class ArtifactCache:
    SCHEMA_VERSION = 1

    def __init__(
        self,
        root: Path,
        *,
        validators: Mapping[str, Callable[[Path], bool]] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks = self.root / ".locks"
        self._validators = dict(validators or {})

    def _entry(self, key: str) -> Path:
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
            raise ValueError("Cache key must contain only letters, digits, dot, underscore, or dash")
        return self.root / key

    def _lock(self, key: str):
        self._entry(key)
        return exclusive_lock(self._locks / f"{key}.lock")

    @staticmethod
    def _artifact_name(value: str | os.PathLike[str]) -> str:
        raw = os.fspath(value)
        path = Path(raw)
        if not raw or path.is_absolute() or path.parent != Path("."):
            raise ValueError("Expected artifact names must be basenames")
        return path.name

    def _evict_unlocked(self, key: str) -> None:
        shutil.rmtree(self._entry(key), ignore_errors=True)

    def _lookup_unlocked(self, key: str, expected: tuple[str, ...]) -> CacheLookup:
        entry = self._entry(key)
        try:
            record = json.loads((entry / "record.json").read_text(encoding="utf-8"))
            if record.get("schema_version") != self.SCHEMA_VERSION or record.get("key") != key:
                raise ValueError("record version or key mismatch")
            by_name = {item["name"]: item for item in record["artifacts"]}
            paths: list[str] = []
            for requested in expected:
                name = self._artifact_name(requested)
                item = by_name[name]
                relative = Path(item["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("cache artifact path escapes entry")
                path = (entry / relative).resolve()
                if entry.resolve() not in path.parents:
                    raise ValueError("cache artifact path escapes entry")
                if path.stat().st_size != item["size_bytes"] or _sha256(path) != item["sha256"]:
                    raise ValueError("cache artifact digest mismatch")
                validator = self._validators.get(name) or self._validators.get(path.suffix)
                if validator is not None and not validator(path):
                    raise ValueError("cache artifact validator failed")
                paths.append(str(path))
            return CacheLookup(True, key, tuple(paths), record.get("metadata", {}))
        except Exception:
            self._evict_unlocked(key)
            return CacheLookup(False, key, reason="missing_or_invalid")

    def lookup(self, key: str, expected_artifacts: Iterable[str]) -> CacheLookup:
        expected = tuple(expected_artifacts)
        with self._lock(key):
            return self._lookup_unlocked(key, expected)

    def store(
        self,
        key: str,
        artifacts: Iterable[Path],
        metadata: Mapping[str, Any],
    ) -> CacheRecord:
        sources = tuple(Path(path) for path in artifacts)
        names = tuple(path.name for path in sources)
        if len(names) != len(set(names)):
            raise ValueError("Cache artifact basenames must be unique")
        if not sources or any(not path.is_file() for path in sources):
            raise ValueError("Every cache artifact must be an existing file")
        with self._lock(key):
            entry = self._entry(key)
            staging = self.root / f".{key}.{uuid.uuid4().hex}.staging"
            backup = self.root / f".{key}.{uuid.uuid4().hex}.backup"
            staging.mkdir()
            try:
                items = []
                for source in sources:
                    destination = staging / source.name
                    link_or_copy_atomic(source, destination)
                    items.append({
                        "name": source.name,
                        "path": source.name,
                        "size_bytes": destination.stat().st_size,
                        "sha256": _sha256(destination),
                    })
                clean_metadata = _redact(dict(metadata))
                record = {
                    "schema_version": self.SCHEMA_VERSION,
                    "key": key,
                    "created_at": time.time(),
                    "artifacts": items,
                    "metadata": clean_metadata,
                }
                atomic_write_json(staging / "record.json", record)
                if entry.exists():
                    os.replace(entry, backup)
                os.replace(staging, entry)
                shutil.rmtree(backup, ignore_errors=True)
                return CacheRecord(key, tuple(str(entry / name) for name in names), clean_metadata)
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                if backup.exists() and not entry.exists():
                    os.replace(backup, entry)
                raise

    def materialize(self, lookup: CacheLookup, destinations: Mapping[str, Path]) -> tuple[str, ...]:
        if not lookup.hit:
            raise ValueError("Cannot materialize a cache miss")
        source_by_name = {Path(path).name: Path(path) for path in lookup.artifacts}
        outputs = []
        with self._lock(lookup.key):
            current = self._lookup_unlocked(lookup.key, tuple(destinations))
            if not current.hit:
                raise ValueError("Cache entry became invalid before materialization")
            source_by_name = {Path(path).name: Path(path) for path in current.artifacts}
            for name, destination in destinations.items():
                source = source_by_name[name]
                link_or_copy_atomic(source, Path(destination))
                outputs.append(str(destination))
        return tuple(outputs)

    def invalidate(self, key: str, reason: str) -> None:
        del reason
        with self._lock(key):
            self._evict_unlocked(key)
