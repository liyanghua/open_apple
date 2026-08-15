from __future__ import annotations

import json
import os
import time

import pytest

from lib.cache_io import atomic_write_json, exclusive_lock, link_or_copy_atomic


def test_exclusive_lock_rejects_concurrent_writer(tmp_path) -> None:
    lock = tmp_path / "cache.lock"
    with exclusive_lock(lock):
        with pytest.raises(TimeoutError):
            with exclusive_lock(lock, timeout_seconds=0.02, poll_seconds=0.005):
                pass


def test_exclusive_lock_reclaims_stale_owner(tmp_path) -> None:
    lock = tmp_path / "cache.lock"
    lock.write_text('{"pid":1}', encoding="utf-8")
    old = time.time() - 700
    os.utime(lock, (old, old))
    with exclusive_lock(lock, stale_seconds=600):
        assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
    assert not lock.exists()


def test_old_owner_does_not_remove_replacement_lock(tmp_path) -> None:
    lock = tmp_path / "cache.lock"
    with exclusive_lock(lock, stale_seconds=600):
        original = json.loads(lock.read_text(encoding="utf-8"))
        replacement = {"pid": 999, "created_at": time.time(), "token": "replacement"}
        lock.write_text(json.dumps(replacement), encoding="utf-8")
        assert original["token"] != replacement["token"]
    assert json.loads(lock.read_text(encoding="utf-8")) == replacement


def test_atomic_json_replace_preserves_previous_file_on_failure(tmp_path, monkeypatch) -> None:
    target = tmp_path / "record.json"
    target.write_text('{"old":true}', encoding="utf-8")
    monkeypatch.setattr("lib.cache_io.os.replace", lambda *_: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(OSError, match="fail"):
        atomic_write_json(target, {"new": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}


def test_link_or_copy_atomic_materializes_complete_file(tmp_path) -> None:
    source = tmp_path / "source.bin"
    target = tmp_path / "project" / "output.bin"
    source.write_bytes(b"content")
    link_or_copy_atomic(source, target)
    assert target.read_bytes() == b"content"
