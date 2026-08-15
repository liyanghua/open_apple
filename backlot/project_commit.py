"""Atomic, recoverable commits for operator-managed project state."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator

from backlot.operator_errors import OperatorError


_MISSING_HASH = "missing"


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _write_status(generation_dir: Path, status: str) -> None:
    _atomic_write(generation_dir / "status", status.encode("ascii"))


def _file_hash(path: Path) -> str:
    if not path.exists():
        return _MISSING_HASH
    if not path.is_file():
        return "invalid"
    return _sha256(path.read_bytes())


@dataclass
class _StagedWrite:
    relative_path: str
    operation: str
    payload: bytes | None
    descriptor: str | None


class _TransactionSink:
    def __init__(
        self,
        store: "ProjectCommitStore",
        generation_id: str,
        token: str,
    ) -> None:
        self.project_id = store.project_id
        self.generation_id = generation_id
        self._store = store
        self._token = token
        self._active = True
        self._writes: dict[str, _StagedWrite] = {}
        self._events: list[dict[str, Any]] = []

    def _check(self, relative_path: str | None = None) -> None:
        if not self._active or self._store._active_token != self._token:
            raise OperatorError("invalid_write_context", "项目写入上下文已失效", 409)
        if relative_path is not None:
            self._store._canonical_path(relative_path)

    def stage_json(self, relative_path: str, value: object, *, schema: str) -> None:
        self._check(relative_path)
        if not isinstance(schema, str) or not schema:
            raise OperatorError("invalid_write_context", "项目写入上下文无效", 409)
        self._writes[relative_path] = _StagedWrite(
            relative_path, "write", _json_bytes(value), schema
        )

    def stage_bytes(
        self, relative_path: str, source_path: Path, *, media_type: str
    ) -> None:
        self._check(relative_path)
        source = Path(source_path)
        if not source.is_file() or not isinstance(media_type, str) or not media_type:
            raise OperatorError("invalid_write_context", "待写入文件无效", 409)
        self._writes[relative_path] = _StagedWrite(
            relative_path, "write", source.read_bytes(), media_type
        )

    def stage_delete(self, relative_path: str) -> None:
        self._check(relative_path)
        self._writes[relative_path] = _StagedWrite(
            relative_path, "delete", None, None
        )

    def append_event(self, stream: str, event: object) -> None:
        self._check()
        if not isinstance(stream, str) or not stream or "/" in stream:
            raise OperatorError("invalid_write_context", "事件写入上下文无效", 409)
        if not isinstance(event, dict):
            raise OperatorError("invalid_write_context", "事件内容无效", 409)
        self._events.append({"stream": stream, "event": event})

    def _deactivate(self) -> None:
        self._active = False


class ProjectCommitStore:
    """Own the one project lock and immutable commit generations."""

    def __init__(
        self,
        project_dir: str | os.PathLike[str],
        *,
        fault_injector: Callable[[str], None] | None = None,
        outbox_materializer: Callable[[str, dict[str, Any]], None] | None = None,
        publish: Callable[[str], None] | None = None,
    ) -> None:
        raw = Path(project_dir)
        if raw.is_symlink():
            raise OperatorError("invalid_write_context", "项目目录无效", 409)
        self.project_dir = raw.resolve()
        self.operator_dir = self.project_dir / "operator"
        self.generations_dir = self.operator_dir / "generations"
        self.pointer_path = self.operator_dir / "current-generation.json"
        self.lock_path = self.operator_dir / "project.lock"
        self._fault = fault_injector or (lambda _point: None)
        self._materialize = outbox_materializer
        self._publish = publish
        self._active_token: str | None = None
        self.project_id = self._load_project_id()

    def _load_project_id(self) -> str:
        try:
            value = json.loads((self.project_dir / "project.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        project_id = value.get("project_id", self.project_dir.name)
        if not isinstance(project_id, str) or not project_id:
            raise OperatorError("invalid_write_context", "项目标识无效", 409)
        return project_id

    @contextlib.contextmanager
    def _lock(self) -> Iterator[None]:
        self.operator_dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def initialize(self) -> dict[str, Any]:
        with self._lock():
            if self.pointer_path.exists():
                return self._read_pointer()
            self.generations_dir.mkdir(parents=True, exist_ok=True)
            generation_id = "generation-000000"
            generation_dir = self.generations_dir / generation_id
            generation_dir.mkdir()
            manifest = {
                "schema_version": "1.0",
                "project_id": self.project_id,
                "generation_id": generation_id,
                "base_generation_id": None,
                "status": "committed",
                "write_set": [],
                "action": {"action_id": "initialize", "type": "initialize"},
                "result": {"status": "committed"},
                "audit": {},
                "draft_transition": None,
                "outbox": [],
            }
            manifest_bytes = _json_bytes(manifest)
            _atomic_write(generation_dir / "manifest.json", manifest_bytes)
            _write_status(generation_dir, "committed")
            _atomic_write(generation_dir / "outbox-drained", b"1\n")
            pointer = {
                "generation_id": generation_id,
                "manifest_sha256": _sha256(manifest_bytes),
            }
            _atomic_write(self.pointer_path, _json_bytes(pointer))
            _atomic_write(self.operator_dir / "operator-managed", b"1\n")
            return pointer

    def _read_pointer(self) -> dict[str, Any]:
        try:
            pointer = json.loads(self.pointer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OperatorError("recovery_required", "项目版本状态需要管理员恢复", 503) from exc
        if not isinstance(pointer.get("generation_id"), str):
            raise OperatorError("recovery_required", "项目版本状态需要管理员恢复", 503)
        return pointer

    def _next_generation_id(self) -> str:
        highest = 0
        for item in self.generations_dir.glob("generation-*"):
            try:
                highest = max(highest, int(item.name.rsplit("-", 1)[1]))
            except ValueError:
                continue
        return f"generation-{highest + 1:06d}"

    def _canonical_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or "\\" in relative_path:
            raise OperatorError("invalid_write_context", "项目写入路径无效", 409)
        relative = PurePosixPath(relative_path)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.parts[:2] == ("operator", "generations")
            or relative.as_posix() in {
                "operator/current-generation.json",
                "operator/project.lock",
                "operator/recovery-required",
            }
        ):
            raise OperatorError("invalid_write_context", "项目写入路径无效", 409)
        candidate = self.project_dir.joinpath(*relative.parts)
        parent = candidate.parent.resolve()
        resolved = candidate.resolve()
        if (
            (self.project_dir != parent and self.project_dir not in parent.parents)
            or (self.project_dir != resolved and self.project_dir not in resolved.parents)
        ):
            raise OperatorError("invalid_write_context", "项目写入路径超出项目范围", 409)
        return candidate

    @contextlib.contextmanager
    def transaction(
        self,
        *,
        action: dict[str, Any],
        result: dict[str, Any] | None = None,
        audit: dict[str, Any] | None = None,
        draft_transition: dict[str, Any] | None = None,
        business_diff: list[str] | None = None,
    ) -> Iterator[_TransactionSink]:
        self.initialize()
        with self._lock():
            self._recover_locked()
            generation_id = self._next_generation_id()
            token = secrets.token_hex(24)
            sink = _TransactionSink(self, generation_id, token)
            self._active_token = token
            try:
                yield sink
                self._commit_locked(
                    sink,
                    action=action,
                    result=result or {"status": "committed"},
                    audit=audit or {},
                    draft_transition=draft_transition,
                    business_diff=business_diff or [],
                )
            finally:
                sink._deactivate()
                self._active_token = None

    def _commit_locked(
        self,
        sink: _TransactionSink,
        *,
        action: dict[str, Any],
        result: dict[str, Any],
        audit: dict[str, Any],
        draft_transition: dict[str, Any] | None,
        business_diff: list[str],
    ) -> None:
        base = self._read_pointer()["generation_id"]
        generation_dir = self.generations_dir / sink.generation_id
        generation_dir.mkdir()
        write_set: list[dict[str, Any]] = []
        for staged in sink._writes.values():
            target = self._canonical_path(staged.relative_path)
            before = target.read_bytes() if target.is_file() else None
            before_hash = _sha256(before) if before is not None else _MISSING_HASH
            after_hash = (
                _sha256(staged.payload)
                if staged.operation == "write" and staged.payload is not None
                else _MISSING_HASH
            )
            snapshot = Path(*PurePosixPath(staged.relative_path).parts)
            if before is not None:
                _atomic_write(generation_dir / "before" / snapshot, before)
            if staged.payload is not None:
                _atomic_write(generation_dir / "after" / snapshot, staged.payload)
            write_set.append({
                "relative_path": staged.relative_path,
                "operation": staged.operation,
                "descriptor": staged.descriptor,
                "before_missing": before is None,
                "before_sha256": before_hash,
                "after_sha256": after_hash,
            })
        outbox = []
        for index, item in enumerate(sink._events):
            outbox.append({
                "outbox_id": f"{sink.generation_id}:{index}",
                "stream": item["stream"],
                "event": item["event"],
            })
        manifest = {
            "schema_version": "1.0",
            "project_id": self.project_id,
            "generation_id": sink.generation_id,
            "base_generation_id": base,
            "status": "prepared",
            "write_set": write_set,
            "action": action,
            "result": result,
            "audit": audit,
            "draft_transition": draft_transition,
            "business_diff": business_diff,
            "outbox": outbox,
        }
        manifest_bytes = _json_bytes(manifest)
        _atomic_write(generation_dir / "manifest.json", manifest_bytes)
        _write_status(generation_dir, "prepared")
        self._fault("after_prepare")
        _write_status(generation_dir, "applying")
        self._apply_images(generation_dir, manifest, after=True)
        self._verify_images(manifest, after=True)
        _write_status(generation_dir, "applying-complete")
        self._fault("after_apply")
        pointer = {
            "generation_id": sink.generation_id,
            "manifest_sha256": _sha256(manifest_bytes),
        }
        _atomic_write(self.pointer_path, _json_bytes(pointer))
        self._fault("after_pointer")
        _write_status(generation_dir, "committed")
        self._drain_outbox(generation_dir, manifest)
        if self._publish is not None:
            self._publish(self.project_id)

    def _apply_images(
        self, generation_dir: Path, manifest: dict[str, Any], *, after: bool
    ) -> None:
        image_dir = "after" if after else "before"
        hash_key = "after_sha256" if after else "before_sha256"
        for item in manifest["write_set"]:
            target = self._canonical_path(item["relative_path"])
            # Resolve again immediately before replace to catch a newly inserted symlink.
            self._canonical_path(item["relative_path"])
            expected = item[hash_key]
            if expected == _MISSING_HASH:
                with contextlib.suppress(FileNotFoundError):
                    target.unlink()
                continue
            source = generation_dir / image_dir / Path(*PurePosixPath(item["relative_path"]).parts)
            if _file_hash(source) != expected:
                self._freeze()
            _atomic_write(target, source.read_bytes())

    def _verify_images(self, manifest: dict[str, Any], *, after: bool) -> None:
        key = "after_sha256" if after else "before_sha256"
        for item in manifest["write_set"]:
            if _file_hash(self._canonical_path(item["relative_path"])) != item[key]:
                self._freeze()

    def _freeze(self) -> None:
        _atomic_write(self.operator_dir / "recovery-required", b"1\n")
        raise OperatorError("recovery_required", "检测到外部修改，需要管理员恢复", 503)

    def _drain_outbox(self, generation_dir: Path, manifest: dict[str, Any]) -> None:
        marker = generation_dir / "outbox-drained"
        if marker.exists():
            return
        self._fault("during_outbox")
        for item in manifest.get("outbox", []):
            if self._materialize is not None:
                self._materialize(item["stream"], item)
                continue
            target = self.operator_dir / f"{item['stream']}.jsonl"
            delivered: set[str] = set()
            if target.exists():
                for line in target.read_text(encoding="utf-8").splitlines():
                    with contextlib.suppress(json.JSONDecodeError):
                        delivered.add(json.loads(line).get("_outbox_id", ""))
            if item["outbox_id"] in delivered:
                continue
            event = dict(item["event"])
            event["_outbox_id"] = item["outbox_id"]
            existing = target.read_bytes() if target.exists() else b""
            _atomic_write(target, existing + _json_bytes(event) + b"\n")
        _atomic_write(marker, b"1\n")

    def recover(self) -> str:
        self.initialize()
        with self._lock():
            return "recovered" if self._recover_locked() else "clean"

    def _recover_locked(self) -> bool:
        if (self.operator_dir / "recovery-required").exists():
            raise OperatorError("recovery_required", "检测到外部修改，需要管理员恢复", 503)
        if not self.pointer_path.exists():
            return False
        pointer = self._read_pointer()["generation_id"]
        changed = False
        for generation_dir in sorted(self.generations_dir.glob("generation-*")):
            status_path = generation_dir / "status"
            if not status_path.exists() or not (generation_dir / "manifest.json").exists():
                continue
            status = status_path.read_text(encoding="ascii")
            manifest = json.loads((generation_dir / "manifest.json").read_text(encoding="utf-8"))
            if status in {"prepared", "applying", "applying-complete"}:
                roll_forward = pointer == manifest["generation_id"]
                for item in manifest["write_set"]:
                    current = _file_hash(self._canonical_path(item["relative_path"]))
                    if current not in {item["before_sha256"], item["after_sha256"]}:
                        self._freeze()
                self._apply_images(generation_dir, manifest, after=roll_forward)
                self._verify_images(manifest, after=roll_forward)
                _write_status(generation_dir, "committed" if roll_forward else "aborted")
                if roll_forward:
                    self._drain_outbox(generation_dir, manifest)
                changed = True
            elif status == "committed" and pointer == manifest["generation_id"]:
                if not (generation_dir / "outbox-drained").exists():
                    self._drain_outbox(generation_dir, manifest)
                    changed = True
        return changed
