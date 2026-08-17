"""Signature-based cache for the read-only Backlot board state."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, Callable


BoardLoader = Callable[[Path], dict[str, Any]]

_lock = RLock()
_cache: dict[str, tuple[tuple[tuple[str, int, int], ...], dict[str, Any]]] = {}


def _signature(project_dir: Path) -> tuple[tuple[str, int, int], ...]:
    project_dir = Path(project_dir)
    candidates: list[Path] = []
    for name in ("project.json", "meta.json", "events.jsonl", "review_notes.jsonl"):
        candidates.append(project_dir / name)
    candidates.extend(project_dir.glob("checkpoint_*.json"))
    history = project_dir / "history"
    if history.is_dir():
        candidates.extend(history.glob("checkpoint_*.json"))
    artifacts = project_dir / "artifacts"
    if artifacts.is_dir():
        candidates.extend(artifacts.rglob("*.json"))
    reviews = project_dir / "operator" / "reviews"
    if reviews.is_dir():
        candidates.extend(reviews.glob("*.json"))

    signature: list[tuple[str, int, int]] = []
    for path in sorted(set(candidates)):
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            relative = path.relative_to(project_dir).as_posix()
        except ValueError:
            relative = path.name
        signature.append((relative, stat.st_size, stat.st_mtime_ns))
    return tuple(signature)


def get_cached_board_state(project_dir: Path, loader: BoardLoader) -> dict[str, Any]:
    """Return cached state while its complete state-file signature is unchanged."""
    project_dir = Path(project_dir)
    key = str(project_dir.resolve())
    signature = _signature(project_dir)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] == signature:
            return cached[1]

    state = loader(project_dir)
    with _lock:
        _cache[key] = (signature, state)
    return state


def invalidate_state_cache(project_dir: Path | str) -> None:
    try:
        key = str(Path(project_dir).resolve())
    except OSError:
        return
    with _lock:
        _cache.pop(key, None)


def clear_state_cache() -> None:
    with _lock:
        _cache.clear()
