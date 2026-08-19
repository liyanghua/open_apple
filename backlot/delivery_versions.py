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
            sink.stage_json(
                f"operator/delivery-versions/{version_id}/manifest.json",
                value,
                schema="delivery_version",
            )
            sink.stage_json(
                "operator/current-delivery.json", pointer, schema="current_delivery"
            )
        return {"version_id": version_id, "manifest_sha256": digest, "status": "certified"}
