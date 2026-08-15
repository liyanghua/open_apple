"""Shared crash-safe filesystem primitives for reusable caches."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def exclusive_lock(
    path: Path,
    *,
    timeout_seconds: float = 60.0,
    stale_seconds: float = 600.0,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Acquire a cross-process O_EXCL lock with stale-owner recovery."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    owner_token = uuid.uuid4().hex
    while not acquired:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                payload = json.dumps({
                    "pid": os.getpid(),
                    "created_at": time.time(),
                    "token": owner_token,
                })
                os.write(fd, payload.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            acquired = True
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > stale_seconds:
                    path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not acquire cache lock {path}")
            time.sleep(poll_seconds)
    try:
        yield
    finally:
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if current.get("token") == owner_token:
                path.unlink()
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            pass


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(
        path,
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )


def link_or_copy_atomic(source: Path, destination: Path) -> None:
    """Materialize a cache object without exposing a partial destination."""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    os.unlink(temp_name)
    temp = Path(temp_name)
    try:
        try:
            os.link(source, temp)
        except (OSError, NotImplementedError):
            shutil.copy2(source, temp)
            with open(temp, "rb") as handle:
                os.fsync(handle.fileno())
        os.replace(temp, destination)
    except BaseException:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise
