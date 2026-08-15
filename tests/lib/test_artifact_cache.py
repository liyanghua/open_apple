from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lib.artifact_cache import ArtifactCache


def _source(tmp_path: Path, name: str = "audio.wav", data: bytes = b"valid") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_store_then_lookup_round_trip(tmp_path) -> None:
    cache = ArtifactCache(tmp_path / ".cache")
    assert cache.lookup("key", ["audio.wav"]).hit is False
    cache.store("key", [_source(tmp_path)], {"tool": "fake", "version": "1"})
    hit = cache.lookup("key", ["audio.wav"])
    assert hit.hit is True
    assert Path(hit.artifacts[0]).read_bytes() == b"valid"


def test_corrupt_cached_artifact_is_evicted(tmp_path) -> None:
    cache = ArtifactCache(tmp_path / ".cache")
    cache.store("key", [_source(tmp_path)], {"tool": "fake", "version": "1"})
    cached = cache.lookup("key", ["audio.wav"])
    Path(cached.artifacts[0]).write_bytes(b"changed")
    assert cache.lookup("key", ["audio.wav"]).hit is False
    assert not (tmp_path / ".cache" / "key").exists()


def test_corrupt_sidecar_is_evicted(tmp_path) -> None:
    cache = ArtifactCache(tmp_path / ".cache")
    cache.store("key", [_source(tmp_path)], {"tool": "fake", "version": "1"})
    (tmp_path / ".cache" / "key" / "record.json").write_text("not-json")
    assert cache.lookup("key", ["audio.wav"]).hit is False


def test_project_link_deletion_does_not_remove_cache(tmp_path) -> None:
    cache = ArtifactCache(tmp_path / ".cache")
    cache.store("key", [_source(tmp_path)], {"tool": "fake", "version": "1"})
    hit = cache.lookup("key", ["audio.wav"])
    project_output = tmp_path / "project" / "audio.wav"
    cache.materialize(hit, {"audio.wav": project_output})
    project_output.unlink()
    assert cache.lookup("key", ["audio.wav"]).hit is True


def test_invalidate_never_deletes_project_output(tmp_path) -> None:
    cache = ArtifactCache(tmp_path / ".cache")
    cache.store("key", [_source(tmp_path)], {"tool": "fake", "version": "1"})
    hit = cache.lookup("key", ["audio.wav"])
    project_output = tmp_path / "project" / "audio.wav"
    cache.materialize(hit, {"audio.wav": project_output})
    cache.invalidate("key", "test")
    assert project_output.read_bytes() == b"valid"


def test_materialize_rejects_cache_corrupted_after_lookup(tmp_path) -> None:
    cache = ArtifactCache(tmp_path / ".cache")
    cache.store("key", [_source(tmp_path)], {"tool": "fake", "version": "1"})
    hit = cache.lookup("key", ["audio.wav"])
    Path(hit.artifacts[0]).write_bytes(b"changed")
    project_output = tmp_path / "project" / "audio.wav"
    try:
        cache.materialize(hit, {"audio.wav": project_output})
    except ValueError as exc:
        assert "invalid" in str(exc)
    else:
        raise AssertionError("corrupt cache should not materialize")
    assert not project_output.exists()
    assert not (tmp_path / ".cache" / "key").exists()


def test_secret_metadata_is_not_persisted(tmp_path) -> None:
    cache = ArtifactCache(tmp_path / ".cache")
    cache.store("key", [_source(tmp_path)], {"tool": "fake", "api_key": "secret"})
    record = json.loads((tmp_path / ".cache" / "key" / "record.json").read_text())
    assert "secret" not in json.dumps(record)


def test_concurrent_writers_never_publish_partial_record(tmp_path) -> None:
    cache = ArtifactCache(tmp_path / ".cache")
    first = _source(tmp_path / "first", data=b"first")
    second = _source(tmp_path / "second", data=b"second")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(cache.store, "key", [first], {"writer": "first"}),
            pool.submit(cache.store, "key", [second], {"writer": "second"}),
        ]
        for future in futures:
            future.result()
    hit = cache.lookup("key", ["audio.wav"])
    assert hit.hit is True
    assert Path(hit.artifacts[0]).read_bytes() in {b"first", b"second"}
