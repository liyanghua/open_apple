"""Server-owned OpenReel V2 editorial session and revision lifecycle.

The editor submits typed, idempotent deltas; it never advances production
state directly.  Every state change is an immutable ProjectCommitStore
generation and executor reports are the only source of render/QA state.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import jsonschema

from backlot.delivery_versions import DeliveryVersionService
from backlot.operator_errors import OperatorError
from backlot.project_commit import ProjectCommitStore
from lib.cache_keys import canonical_digest
from lib.editorial_timeline import EditorialDeltaError, apply_delta
from schemas.artifacts import validate_artifact


_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_TERMINAL = {"promoted", "discarded"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EditorialSessionService:
    """Own one candidate's V2 sessions and immutable delivery transitions."""

    def __init__(
        self,
        project_dir: str | Path,
        *,
        actor_id: str,
        store: ProjectCommitStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise OperatorError("forbidden", "当前用户没有编辑权限", 403)
        self.project_dir = Path(project_dir).resolve()
        self.actor_id = actor_id
        self.store = store or ProjectCommitStore(self.project_dir)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.delivery = DeliveryVersionService(self.project_dir, store=self.store)

    @property
    def sessions_dir(self) -> Path:
        return self.project_dir / "operator" / "editorial" / "sessions"

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", session_id):
            raise OperatorError.validation_failed("编辑会话标识无效")
        return self.sessions_dir / f"{session_id}.json"

    def _read(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise OperatorError("not_found", "编辑会话不存在", 404) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise OperatorError("recovery_required", "编辑会话状态需要管理员恢复", 503) from exc
        if not isinstance(value, dict):
            raise OperatorError("recovery_required", "编辑会话状态需要管理员恢复", 503)
        return value

    def load_session(self, session_id: str) -> dict[str, Any]:
        session = self._read(session_id)
        if session.get("actor_id") != self.actor_id:
            raise OperatorError("forbidden", "该编辑会话属于其他运营人员", 403)
        return session

    # Historical/API-friendly aliases.
    load = load_session

    @staticmethod
    def _timeline_hash(timeline: Mapping[str, Any]) -> str:
        value = dict(timeline)
        value.pop("timeline_hash", None)
        return canonical_digest(value)

    def _project_candidate_id(self) -> str:
        """Resolve the server-owned candidate identity for this project."""
        try:
            marker = json.loads((self.project_dir / "project.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            marker = {}
        if isinstance(marker, Mapping):
            value = marker.get("candidate_id") or marker.get("project_id")
            if isinstance(value, str) and value.strip():
                return value
        return self.store.project_id

    def _validate_catalogue(
        self,
        catalogue: Mapping[str, Any],
        timeline: Mapping[str, Any],
        *,
        requested_candidate_id: str | None,
    ) -> None:
        required = (
            "version", "project_id", "candidate_id", "timeline_id",
            "base_generation_id", "base_edit_revision", "timeline_hash",
            "source_artifact_hashes", "assets", "catalogue_hash",
        )
        missing = [field for field in required if field not in catalogue]
        if missing:
            raise OperatorError("recovery_required", "商品素材目录字段不完整，需要重新物化候选", 503)
        string_fields = (
            "version", "project_id", "candidate_id", "timeline_id",
            "base_generation_id", "base_edit_revision", "timeline_hash", "catalogue_hash",
        )
        if any(not isinstance(catalogue.get(field), str) or not catalogue[field].strip() for field in string_fields):
            raise OperatorError.validation_failed("商品素材目录字段类型无效")
        if not isinstance(catalogue.get("source_artifact_hashes"), Mapping) or not isinstance(catalogue.get("assets"), list):
            raise OperatorError.validation_failed("商品素材目录字段类型无效")
        unsigned = dict(catalogue)
        supplied = unsigned.pop("catalogue_hash", None)
        if supplied != canonical_digest(unsigned):
            raise OperatorError("revision_conflict", "商品素材目录校验失败，请重新加载候选", 409)
        expected_candidate = self._project_candidate_id()
        if catalogue["candidate_id"] != expected_candidate or catalogue["project_id"] != self.store.project_id:
            raise OperatorError("revision_conflict", "商品素材目录候选归属不匹配", 409)
        if requested_candidate_id is not None and requested_candidate_id != catalogue["candidate_id"]:
            raise OperatorError.validation_failed("请求候选与服务端商品素材目录不匹配")
        bindings = {
            "timeline_id": timeline.get("timeline_id"),
            "base_generation_id": timeline.get("base_generation_id"),
            "base_edit_revision": timeline.get("base_edit_revision"),
            "timeline_hash": self._timeline_hash(timeline),
            "source_artifact_hashes": timeline.get("source_artifact_hashes"),
        }
        if any(catalogue.get(field) != expected for field, expected in bindings.items()):
            raise OperatorError("revision_conflict", "商品素材目录与时间轴基座不匹配", 409)

    def _commit_session(
        self,
        session: dict[str, Any],
        *,
        action_type: str,
        expected_generation: str | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = deepcopy(session)
        session["updated_at"] = self.clock().isoformat()
        expected = expected_generation or str(session.get("base_generation_id") or "")
        if not expected:
            expected = self.store.initialize()["generation_id"]
        with self.store.transaction(
            action={"action_id": f"editorial-{action_type}-{session['session_id']}-{uuid.uuid4().hex[:10]}", "type": action_type},
            result=dict(result or {"status": session.get("status"), "session_id": session["session_id"]}),
            audit={"event_type": action_type, "actor_id": self.actor_id},
            expected_generation=expected,
        ) as sink:
            session["base_generation_id"] = sink.generation_id
            sink.stage_json(
                f"operator/editorial/sessions/{session['session_id']}.json",
                session,
                schema="operator_state",
            )
        return session

    def create_session(
        self,
        *,
        base_timeline: Mapping[str, Any] | None = None,
        session_id: str | None = None,
        idempotency_key: str,
        candidate_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise OperatorError.validation_failed("创建会话需要幂等键")
        artifact_path = self.project_dir / "artifacts" / "editorial_timeline.json"
        try:
            timeline = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OperatorError("recovery_required", "编辑时间轴缺失或无效", 503) from exc
        if not isinstance(timeline, dict):
            raise OperatorError("recovery_required", "编辑时间轴缺失或无效", 503)
        try:
            validate_artifact("editorial_timeline", timeline)
        except (jsonschema.ValidationError, KeyError, TypeError, ValueError) as exc:
            raise OperatorError("recovery_required", "编辑时间轴格式无效，需要重新物化候选", 503) from exc
        # Client content is never used as the canonical snapshot.  A legacy
        # caller may send it only as an equality assertion; mismatches fail
        # closed rather than allowing a forged timeline into a session.
        if base_timeline:
            if canonical_digest(dict(base_timeline)) != canonical_digest(timeline):
                raise OperatorError("revision_conflict", "客户端时间轴不是服务端当前版本", 409)
        self.store.initialize()
        sid = session_id or f"editorial-{uuid.uuid4().hex[:20]}"
        if self._path(sid).exists():
            raise OperatorError("revision_conflict", "编辑会话标识已存在", 409)
        pointer = self.store.initialize()
        if str(timeline.get("base_generation_id") or "") != str(pointer["generation_id"]):
            raise OperatorError("revision_conflict", "时间轴基座已更新，请重新加载候选", 409)
        catalogue = None
        catalogue_path = self.project_dir / "operator" / "editorial" / "asset-catalogue.json"
        if not catalogue_path.is_file():
            raise OperatorError("recovery_required", "批准素材目录缺失，需要重新物化候选", 503)
        if catalogue_path.is_file():
            try:
                catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OperatorError("recovery_required", "商品素材目录需要管理员恢复", 503) from exc
            if not isinstance(catalogue, dict):
                raise OperatorError.validation_failed("商品素材目录格式无效")
            self._validate_catalogue(
                catalogue,
                timeline,
                requested_candidate_id=candidate_id,
            )
        resolved_candidate_id = candidate_id or str((catalogue or {}).get("candidate_id") or self._project_candidate_id())
        request_digest = canonical_digest({"candidate_id": candidate_id, "timeline": timeline, "catalogue": catalogue, "idempotency_key": idempotency_key, "actor_id": self.actor_id})
        for path in self.sessions_dir.glob("*.json") if self.sessions_dir.exists() else []:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if existing.get("create_idempotency_key") != idempotency_key:
                continue
            if existing.get("create_request_digest") != request_digest:
                raise OperatorError("idempotency_conflict", "同一创建编号对应不同内容", 409)
            if existing.get("actor_id") != self.actor_id:
                raise OperatorError("forbidden", "该编辑会话属于其他运营人员", 403)
            return existing
        session: dict[str, Any] = {
            "schema_version": "2.0",
            "session_id": sid,
            "project_id": self.store.project_id,
            "candidate_id": resolved_candidate_id,
            "actor_id": self.actor_id,
            "create_idempotency_key": idempotency_key,
            "create_request_digest": request_digest,
            "base_generation_id": pointer["generation_id"],
            "timeline": timeline,
            "timeline_hash": self._timeline_hash(timeline),
            "asset_catalogue": catalogue,
            "revision": 0,
            "revision_id": "edit-000000",
            "deltas": [],
            "preview": None,
            "final": None,
            "status": "draft",
            "created_at": self.clock().isoformat(),
            "updated_at": self.clock().isoformat(),
        }
        return self._commit_session(session, action_type="editorial_session_created", expected_generation=pointer["generation_id"], result={"status": "draft", "session_id": sid})

    create = create_session

    def save_draft(
        self,
        session_id: str,
        delta: Mapping[str, Any],
        *,
        idempotency_key: str,
        base_timeline_hash: str | None = None,
        expected_generation: str | None = None,
    ) -> dict[str, Any]:
        session = self.load_session(session_id)
        if session.get("status") in _TERMINAL:
            raise OperatorError.validation_failed("当前编辑会话已结束")
        if not isinstance(delta, Mapping) or not delta:
            raise OperatorError.validation_failed("编辑增量不能为空")
        current_hash = str(session.get("timeline_hash") or "")
        payload = dict(delta)
        request_hash = canonical_digest(payload)
        # Compatibility shorthand from the shell is normalized into the
        # canonical EditorialTimeline delta envelope before validation.
        if "operations" not in payload and payload.get("op") == "set_caption":
            payload = {"version": "1.0", "delta_id": f"delta-{canonical_digest({'session_id': session_id, 'idempotency_key': idempotency_key, 'text': payload.get('text')})[:24]}", "session_id": session_id,
                       "base_generation_id": session.get("timeline", {}).get("base_generation_id"),
                       "base_timeline_hash": current_hash,
                       "operation_sequence": int(session.get("revision") or 0) + 1,
                       "idempotency_key": idempotency_key,
                       "operations": [{"op": "set_caption_text", "track_id": "subtitle", "clip_id": "subtitle-1", "text": str(payload.get("text") or "")}]}
        payload_hash = canonical_digest(payload)
        for item in session.get("deltas") or []:
            if item.get("idempotency_key") != idempotency_key:
                continue
            if item.get("request_hash", item.get("payload_hash")) != request_hash:
                raise OperatorError("idempotency_conflict", "同一提交编号对应不同编辑内容", 409)
            return session
        if base_timeline_hash is not None and base_timeline_hash != current_hash:
            raise OperatorError("revision_conflict", "编辑基座已变化，请刷新后重试", 409)
        expected = expected_generation or str(session.get("base_generation_id") or "")
        pointer = self.store.initialize()
        if pointer["generation_id"] != expected:
            raise OperatorError("revision_conflict", "候选项目已更新，请重新打开编辑会话", 409)
        timeline = deepcopy(dict(session.get("timeline") or {}))
        try:
            applied = apply_delta(
                timeline,
                payload,
                asset_catalogue=session.get("asset_catalogue"),
            )
        except EditorialDeltaError as exc:
            raise OperatorError.validation_failed("编辑操作未通过时间轴约束") from exc
        except (ImportError, KeyError, TypeError) as exc:
            raise OperatorError.validation_failed("编辑时间轴格式无效") from exc
        timeline = applied["timeline"]
        timeline_hash = applied["timeline_hash"]
        revision = int(session.get("revision") or 0) + 1
        session.update({
            "timeline": timeline,
            "timeline_hash": timeline_hash,
            "revision": revision,
            "revision_id": f"edit-{revision:06d}",
            "deltas": list(session.get("deltas") or []) + [{"idempotency_key": idempotency_key, "payload_hash": payload_hash, "request_hash": request_hash}],
            "preview": None,
            "preview_approval": None,
            "final": None,
            "status": "draft",
        })
        return self._commit_session(session, action_type="editorial_delta_saved", expected_generation=expected, result={"status": "draft", "session_id": session_id, "revision": revision})

    add_delta = save_draft

    def _report(self, report: Mapping[str, Any], *, kind: str, session: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(report, Mapping):
            raise OperatorError.validation_failed("执行报告格式无效")
        value = dict(report)
        # Never trust status/gates supplied by the caller.  The only accepted
        # input is a path to an executor report written under this project;
        # loading it here stamps the in-memory copy as server-owned.
        report_path = value.get("report_path")
        if not report_path:
            raise OperatorError("forbidden", "渲染状态只能来自服务端执行报告", 403)
        try:
            path = self.store._canonical_path(str(report_path))
            expected_dir = self.project_dir / "operator" / "editorial" / "versions" / str(session.get("revision_id"))
            expected_name = f"{kind}-execution_report.json"
            if path.parent != expected_dir or path.name != expected_name:
                raise OperatorError("forbidden", "执行报告路径不属于当前编辑版本", 403)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise OperatorError.validation_failed("执行报告格式无效")
            value = loaded
        except OperatorError:
            raise
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise OperatorError("forbidden", "渲染状态只能来自服务端执行报告", 403) from exc
        value["report_path"] = str(report_path)
        value["server_owned"] = True
        if str(value.get("revision")) != str(session.get("revision_id")):
            raise OperatorError("revision_conflict", "渲染结果不属于当前编辑版本", 409)
        if value.get("kind") != kind:
            raise OperatorError("revision_conflict", "执行报告类型与当前操作不匹配", 409)
        failed = value.get("status") in {"failed", "fail"}
        if kind == "preview":
            if value.get("status") not in {"pass", "failed", "fail"}:
                raise OperatorError.validation_failed("预览执行报告状态无效")
        else:
            gates = value.get("gates") or {}
            if value.get("status") != "pass" or not all(gates.get(name) == "pass" for name in ("alignment", "l1a", "final_qa")):
                value["status"] = "fail"
        if failed:
            return value
        output_hash = value.get("output_sha256")
        if not isinstance(output_hash, str) or not _HEX64.fullmatch(output_hash):
            raise OperatorError.validation_failed("渲染输出哈希无效")
        output_path = value.get("output_path")
        if not isinstance(output_path, str):
            raise OperatorError.validation_failed("执行报告缺少输出文件")
        try:
            output_file = self.store._canonical_path(output_path)
        except OperatorError as exc:
            raise OperatorError.validation_failed("执行报告输出路径无效") from exc
        expected_dir = self.project_dir / "operator" / "editorial" / "versions" / str(session.get("revision_id"))
        if output_file.parent != expected_dir or not output_file.is_file() or _sha256_file(output_file) != output_hash:
            raise OperatorError("revision_conflict", "执行报告输出文件校验失败", 409)
        return value

    def record_preview(self, session_id: str, report: Mapping[str, Any], *, expected_generation: str | None = None) -> dict[str, Any]:
        session = self.load_session(session_id)
        if session.get("status") in _TERMINAL:
            raise OperatorError.validation_failed("当前编辑会话已结束")
        value = self._report(report, kind="preview", session=session)
        session["preview"] = value
        session["preview_approval"] = None
        session["status"] = "preview_ready" if value.get("status") == "pass" else "preview_failed"
        return self._commit_session(session, action_type="editorial_preview_recorded", expected_generation=expected_generation)

    save_preview = record_preview

    def approve_preview(self, session_id: str, *, output_sha256: str, actor_id: str | None = None) -> dict[str, Any]:
        session = self.load_session(session_id)
        if actor_id is not None and actor_id != self.actor_id:
            raise OperatorError("forbidden", "该编辑会话属于其他运营人员", 403)
        preview = session.get("preview") or {}
        if session.get("status") != "preview_ready" or preview.get("status") != "pass" or preview.get("output_sha256") != output_sha256:
            raise OperatorError.validation_failed("只能批准当前版本的成功预览")
        output_path = preview.get("output_path")
        try:
            output_file = self.store._canonical_path(str(output_path))
        except OperatorError as exc:
            raise OperatorError.validation_failed("预览输出文件无效") from exc
        if not output_file.is_file() or _sha256_file(output_file) != output_sha256:
            raise OperatorError("revision_conflict", "预览输出文件已变化，请重新生成", 409)
        session["preview_approval"] = {"revision": session["revision"], "revision_id": session["revision_id"], "output_sha256": output_sha256, "actor_id": self.actor_id, "approved_at": self.clock().isoformat()}
        session["status"] = "preview_approved"
        return self._commit_session(session, action_type="editorial_preview_approved")

    def request_final(self, session_id: str) -> dict[str, Any]:
        session = self.load_session(session_id)
        approval = session.get("preview_approval") or {}
        if session.get("status") != "preview_approved" or approval.get("revision") != session.get("revision") or approval.get("output_sha256") != (session.get("preview") or {}).get("output_sha256"):
            raise OperatorError.validation_failed("完整成片前必须先批准当前版本预览")
        session["status"] = "final_queued"
        return self._commit_session(session, action_type="editorial_final_queued")

    queue_final = request_final

    def record_final(self, session_id: str, report: Mapping[str, Any], *, expected_generation: str | None = None) -> dict[str, Any]:
        session = self.load_session(session_id)
        if session.get("status") != "final_queued":
            raise OperatorError.validation_failed("当前版本未进入完整成片执行")
        value = self._report(report, kind="final", session=session)
        session["final"] = value
        session["status"] = "final_review" if value.get("status") == "pass" else "final_failed"
        return self._commit_session(session, action_type="editorial_final_recorded", expected_generation=expected_generation)

    save_final = record_final

    def current_delivery(self) -> dict[str, Any] | None:
        return self.delivery.current()

    def _manifest_for_final(self, session: Mapping[str, Any]) -> dict[str, Any]:
        final = dict(session.get("final") or {})
        output_path = final.get("output_path")
        if not output_path:
            raise OperatorError.validation_failed("完整成片缺少服务端输出文件")
        try:
            path = self.store._canonical_path(str(output_path))
        except OperatorError as exc:
            raise OperatorError.validation_failed("完整成片路径无效") from exc
        if not path.is_file():
            raise OperatorError.validation_failed("完整成片文件不存在")
        output_hash = _sha256_file(path)
        if output_hash != final.get("output_sha256"):
            raise OperatorError("revision_conflict", "完整成片文件校验失败", 409)
        version_id = f"editorial-{session['session_id']}-{session['revision']}"
        relative = path.relative_to(self.project_dir).as_posix()
        return {
            "schema_version": "1.0", "project_id": self.store.project_id, "version_id": version_id,
            "created_at": self.clock().isoformat(), "review_revision_id": str(session.get("revision_id")),
            "video": {"path": relative, "poster_path": None, "subtitles_path": None},
            "audio_mix": {}, "qa": {"status": "pass", "issues": []},
            "change_summary": "OpenReel V2 服务端审核通过", "video_master_sha256": output_hash,
        }

    def promote(self, session_id: str, *, expected_generation: str | None = None) -> dict[str, Any]:
        session = self.load_session(session_id)
        if session.get("status") != "final_review":
            raise OperatorError.validation_failed("只有服务端审核通过的完整成片才能发布")
        final = session.get("final") or {}
        if final.get("server_owned") is not True:
            raise OperatorError("forbidden", "发布状态只能来自服务端执行报告", 403)
        manifest = self._manifest_for_final(session)
        errors = list(self.delivery.manifest_validator.iter_errors(manifest))
        if errors:
            raise OperatorError.validation_failed("成片版本内容不符合要求")
        payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest_hash = hashlib.sha256(payload).hexdigest()
        pointer = {"schema_version": "1.0", "project_id": self.store.project_id, "version_id": manifest["version_id"], "manifest_sha256": manifest_hash}
        self.delivery.pointer_validator.validate(pointer)
        expected = expected_generation or str(session.get("base_generation_id") or "")
        session["status"] = "promoted"
        session["delivery_version_id"] = manifest["version_id"]
        session["final_manifest_sha256"] = manifest_hash
        with self.store.transaction(
            action={"action_id": f"editorial-promote-{session_id}", "type": "editorial_promote"},
            result={"status": "promoted", "version_id": manifest["version_id"]},
            audit={"event_type": "editorial_promoted", "actor_id": self.actor_id},
            expected_generation=expected,
        ) as sink:
            session["base_generation_id"] = sink.generation_id
            sink.stage_json(f"operator/editorial/sessions/{session_id}.json", session, schema="operator_state")
            sink.stage_json(f"operator/delivery-versions/{manifest['version_id']}/manifest.json", manifest, schema="delivery_version")
            sink.stage_json("operator/current-delivery.json", pointer, schema="current_delivery")
        return session

    def discard(self, session_id: str, *, reason: str = "") -> dict[str, Any]:
        session = self.load_session(session_id)
        if session.get("status") in _TERMINAL:
            return session
        session["status"] = "discarded"
        session["discard_reason"] = reason
        return self._commit_session(session, action_type="editorial_discarded")

    def install_delivery_revision(self, version_id: str, *, output_path: Path, qa_report: Mapping[str, Any]) -> dict[str, Any]:
        if qa_report.get("server_owned") is not True or qa_report.get("status") != "pass":
            raise OperatorError("forbidden", "成片状态只能来自服务端执行报告", 403)
        path = Path(output_path).resolve()
        try:
            relative = path.relative_to(self.project_dir).as_posix()
        except ValueError as exc:
            raise OperatorError.validation_failed("成片文件必须位于项目目录内") from exc
        manifest = {"schema_version": "1.0", "project_id": self.store.project_id, "version_id": version_id, "created_at": self.clock().isoformat(), "review_revision_id": None, "video": {"path": relative, "poster_path": None, "subtitles_path": None}, "audio_mix": {}, "qa": {"status": "pass", "issues": []}, "change_summary": "历史交付版本", "video_master_sha256": _sha256_file(path)}
        return self.delivery.certify(manifest, actor_id=self.actor_id)

    def delivery_manifest_hash(self, version_id: str) -> str:
        return self.delivery.manifest_hash(version_id)

    def restore_delivery_revision(self, version_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.delivery.restore(version_id, **kwargs)
