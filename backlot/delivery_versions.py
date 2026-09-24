"""Immutable, QA-gated delivery versions for the operator workbench."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from backlot.operator_errors import OperatorError
from backlot.project_commit import ProjectCommitStore


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DeliveryVersionService:
    """Register complete delivery versions and move the certified pointer."""

    def __init__(self, project_dir: Path, *, store: ProjectCommitStore | None = None) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.store = store or ProjectCommitStore(self.project_dir)
        schema_dir = Path(__file__).parents[1] / "schemas" / "backlot"
        self.manifest_validator = Draft202012Validator(
            json.loads((schema_dir / "delivery_version.schema.json").read_text(encoding="utf-8"))
        )
        self.pointer_validator = Draft202012Validator(
            json.loads((schema_dir / "current_delivery.schema.json").read_text(encoding="utf-8"))
        )

    @property
    def versions_dir(self) -> Path:
        return self.project_dir / "operator" / "delivery-versions"

    def _path(self, version_id: str) -> Path:
        if not isinstance(version_id, str) or not version_id or any(
            value in version_id for value in ("/", "\\", "..")
        ):
            raise OperatorError.validation_failed("成片版本标识不符合要求")
        return self.versions_dir / version_id / "manifest.json"

    def list(self) -> list[dict[str, Any]]:
        manifests = []
        for path in sorted(self.versions_dir.glob("*/manifest.json")) if self.versions_dir.exists() else []:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                self.manifest_validator.validate(value)
            except (OSError, json.JSONDecodeError, Exception):
                continue
            manifests.append(value)
        return manifests

    def current(self) -> dict[str, Any] | None:
        path = self.project_dir / "operator" / "current-delivery.json"
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            self.pointer_validator.validate(value)
        except (OSError, json.JSONDecodeError, Exception) as exc:
            raise OperatorError("recovery_required", "成片版本状态需要管理员恢复", 503) from exc
        return value

    def manifest(self, version_id: str) -> dict[str, Any]:
        path = self._path(version_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            self.manifest_validator.validate(value)
        except (OSError, json.JSONDecodeError, Exception) as exc:
            raise OperatorError.validation_failed("找不到完整的成片版本") from exc
        return value

    def manifest_hash(self, version_id: str) -> str:
        return hashlib.sha256(_canonical_bytes(self.manifest(version_id))).hexdigest()

    def _project_file(self, relative_path: str) -> Path:
        try:
            path = self.store._canonical_path(relative_path)
        except OperatorError as exc:
            raise OperatorError.validation_failed("成片文件路径不符合要求") from exc
        if not path.is_file():
            raise OperatorError.validation_failed("成片文件不存在或不可读取")
        return path

    def restore(
        self,
        version_id: str,
        *,
        actor_id: str,
        expected_generation: str,
        manifest_sha256: str,
        output_sha256: str,
        idempotency_key: str,
        request_digest: str | None = None,
        can_edit: bool = True,
    ) -> dict[str, Any]:
        """Atomically repoint delivery after verifying an immutable old version.

        The selected manifest and media hashes are supplied as an explicit CAS
        fence.  They are verified again while the project transaction owns the
        project lock; restoring never rewrites the immutable version itself.
        """
        if not can_edit or not isinstance(actor_id, str) or not actor_id.strip():
            raise OperatorError("forbidden", "当前用户没有恢复成片版本的权限", 403)
        if not all(isinstance(item, str) and item for item in (expected_generation, idempotency_key)):
            raise OperatorError.validation_failed("恢复请求缺少版本保护信息")
        request_digest = request_digest or hashlib.sha256(
            _canonical_bytes({
                "version_id": version_id,
                "manifest_sha256": manifest_sha256,
                "output_sha256": output_sha256,
            })
        ).hexdigest()
        selected = self.manifest(version_id)
        actual_manifest_hash = hashlib.sha256(_canonical_bytes(selected)).hexdigest()
        if actual_manifest_hash != manifest_sha256:
            raise OperatorError("revision_conflict", "所选历史成片版本已变化", 409)
        video = selected.get("video") or {}
        output = self._project_file(str(video.get("path") or ""))
        actual_output_hash = _file_sha256(output)
        if actual_output_hash != output_sha256 or actual_output_hash != selected.get("video_master_sha256"):
            raise OperatorError("revision_conflict", "所选历史成片文件校验失败", 409)
        self.validate_production_evidence(selected)

        for directory in sorted(self.store.generations_dir.glob("generation-*"), reverse=True):
            try:
                manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                status = (directory / "status").read_text(encoding="ascii")
            except (OSError, json.JSONDecodeError):
                continue
            action = manifest.get("action") or {}
            if status != "committed" or action.get("idempotency_key") != idempotency_key:
                continue
            if action.get("request_digest") != request_digest:
                raise OperatorError("idempotency_conflict", "该请求标识已用于其他内容", 409)
            return dict(manifest.get("result") or {})

        pointer = {
            "schema_version": "1.0",
            "project_id": self.store.project_id,
            "version_id": version_id,
            "manifest_sha256": actual_manifest_hash,
        }
        self.pointer_validator.validate(pointer)
        with self.store.transaction(
            action={
                "action_id": f"restore-delivery-{version_id}",
                "type": "restore_delivery_revision",
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
            },
            result={"status": "restored", **pointer},
            audit={"event_type": "delivery_restored", "actor_id": actor_id},
            expected_generation=expected_generation,
        ) as sink:
            # Recheck the files while the ProjectCommitStore lock is held.
            self.validate_production_evidence(selected)
            if hashlib.sha256(_canonical_bytes(self.manifest(version_id))).hexdigest() != manifest_sha256:
                raise OperatorError("revision_conflict", "所选历史成片版本已变化", 409)
            if _file_sha256(output) != output_sha256:
                raise OperatorError("revision_conflict", "所选历史成片文件校验失败", 409)
            sink.stage_json("operator/current-delivery.json", pointer, schema="current_delivery")
        return {"status": "restored", **pointer}

    def certify(
        self,
        manifest: Mapping[str, Any],
        *,
        actor_id: str,
        expected_generation: str | None = None,
    ) -> dict[str, Any]:
        value = dict(manifest)
        errors = list(self.manifest_validator.iter_errors(value))
        if errors or value.get("project_id") != self.store.project_id:
            raise OperatorError.validation_failed("成片版本内容不符合要求")
        if (value.get("qa") or {}).get("status") != "pass":
            raise OperatorError.validation_failed("完整检查通过后才能设为当前成片")
        self.validate_production_evidence(value)
        version_id = str(value["version_id"])
        manifest_path = self._path(version_id)
        payload = _canonical_bytes(value)
        digest = hashlib.sha256(payload).hexdigest()
        if manifest_path.exists():
            if manifest_path.read_bytes() == payload:
                return {"version_id": version_id, "manifest_sha256": digest, "status": "certified"}
            raise OperatorError("revision_conflict", "该成片版本已经存在，不能覆盖", 409)
        pointer = {
            "schema_version": "1.0",
            "project_id": self.store.project_id,
            "version_id": version_id,
            "manifest_sha256": digest,
        }
        self.pointer_validator.validate(pointer)
        with self.store.transaction(
            action={"action_id": f"certify-delivery-{version_id}", "type": "certify_delivery"},
            result={"status": "certified", "version_id": version_id},
            audit={"event_type": "delivery_certified", "actor_id": actor_id},
            expected_generation=expected_generation,
        ) as sink:
            self.validate_production_evidence(value)
            sink.stage_json(
                f"operator/delivery-versions/{version_id}/manifest.json",
                value,
                schema="delivery_version",
            )
            sink.stage_json(
                "operator/current-delivery.json", pointer, schema="current_delivery"
            )
        return {"version_id": version_id, "manifest_sha256": digest, "status": "certified"}

    def validate_production_evidence(self, manifest: Mapping[str, Any]) -> None:
        """All new certification paths require live evidence and exact approval.

        Old manifests remain readable; reading a historical version must not
        manufacture missing checks or upgrade it to the new certification gate.
        """
        from backlot.operator_reviews import ReviewService
        from lib.production_evidence import quality_summary, read_object

        record_path = manifest.get("production_record_path")
        review_id = manifest.get("final_review_id")
        if not record_path or not review_id:
            raise OperatorError.validation_failed("缺少单条生产记录及正式最终审核，不能认证交付")
        service = ReviewService(self.project_dir)
        review = service.review_state(str(review_id))
        if not review or review.get("kind") != "final_review" or review.get("status") != "approved":
            raise OperatorError.validation_failed("当前成片尚未获得正式最终审核批准")
        subject = review.get("production_subject") or {}
        if subject.get("record_path") != record_path:
            raise OperatorError.validation_failed("最终审核与单条生产记录不匹配")
        service._validate_final_subject(subject, review["subject_hash"], review["subject_id"])
        render = subject.get("render") or {}
        if (render.get("sha256") != manifest.get("video_master_sha256")
                or render.get("path") != (manifest.get("video") or {}).get("path")):
            raise OperatorError.validation_failed("最终审核与交付文件不匹配")
        try:
            record = read_object(self.project_dir, record_path)
            summary = quality_summary(self.project_dir, record)
        except (ValueError, OSError, TypeError) as exc:
            raise OperatorError.validation_failed("无法验证必要检查证据") from exc
        if not summary["eligible"]:
            raise OperatorError.validation_failed("必要检查尚未完成：" + "、".join(summary["blocking_checks"]))
