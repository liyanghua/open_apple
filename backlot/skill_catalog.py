"""Validated, immutable operator skill catalog."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from backlot.operator_errors import OperatorError
from lib.cache_io import atomic_write_json


class SkillCatalog:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    @staticmethod
    def _contained(root: Path, relative: str) -> Path:
        value = Path(relative)
        if value.is_absolute() or ".." in value.parts:
            raise OperatorError.validation_failed("Skill 文件路径不安全")
        target = (root / value).resolve()
        if target != root and root not in target.parents:
            raise OperatorError.validation_failed("Skill 文件路径不安全")
        if target.is_symlink():
            raise OperatorError.validation_failed("Skill 文件不能使用符号链接")
        return target

    @staticmethod
    def _digest(directory: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def resolve(self, skill_id: str, version: str | None = None) -> dict[str, Any]:
        skill_root = self._contained(self.root, skill_id)
        index_path = skill_root / "index.yaml"
        if not index_path.is_file():
            raise OperatorError.validation_failed("找不到指定运营 Skill")
        index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        selected = version or str(index.get("default_version") or "")
        registered = {str(item.get("version")): item for item in index.get("versions", [])}
        if selected not in registered:
            raise OperatorError.validation_failed("该 Skill 版本未注册")
        directory = self._contained(skill_root / "versions", selected)
        manifest_path = directory / "skill.yaml"
        if not manifest_path.is_file():
            raise OperatorError.validation_failed("Skill 配置不完整")
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        required = {
            "id", "version", "name_zh", "description_zh", "pipeline",
            "supported_platforms", "default_profile", "approval_policy",
            "intake_schema", "benchmark_policy",
        }
        if required - set(manifest) or manifest.get("id") != skill_id or str(manifest.get("version")) != selected:
            raise OperatorError.validation_failed("Skill 配置不符合发布要求")
        schema_path = self._contained(directory, str(manifest["intake_schema"]))
        profile_path = self._contained(directory / "profiles", f"{manifest['default_profile']}.yaml")
        if not schema_path.is_file() or not profile_path.is_file():
            raise OperatorError.validation_failed("Skill 输入表单或品类规则缺失")
        actual_digest = self._digest(directory)
        expected = str(registered[selected].get("digest") or "")
        if expected not in {"", "pending", actual_digest}:
            raise OperatorError.validation_failed("Skill 版本内容与注册摘要不一致")
        return {
            "id": skill_id, "version": selected, "manifest": manifest,
            "intake_schema": json.loads(schema_path.read_text(encoding="utf-8")),
            "profile": yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {},
            "digest": actual_digest, "directory": directory,
        }

    def list(self) -> list[dict[str, Any]]:
        result = []
        if not self.root.exists():
            return result
        for index in sorted(self.root.glob("*/index.yaml")):
            try:
                resolved = self.resolve(index.parent.name)
            except (OSError, ValueError, OperatorError):
                continue
            manifest = resolved["manifest"]
            result.append({
                "id": resolved["id"], "version": resolved["version"],
                "name": manifest["name_zh"], "description": manifest["description_zh"],
                "platforms": manifest["supported_platforms"], "status": "trial",
                "performance_promise": None,
            })
        return result

    def validate_intake(self, resolved: dict[str, Any], intake: dict[str, Any]) -> None:
        errors = sorted(Draft202012Validator(resolved["intake_schema"]).iter_errors(intake), key=lambda item: list(item.path))
        if errors:
            fields = [{"field": ".".join(map(str, error.path)) or "form", "message": error.message} for error in errors]
            raise OperatorError("validation_failed", "建单信息不完整", 422, field_errors=fields)

    def write_snapshot(self, project_dir: Path, resolved: dict[str, Any], intake: dict[str, Any]) -> None:
        target = Path(project_dir) / "operator" / "skill-snapshot"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("skill.yaml", "SKILL.md", "intake.schema.json"):
            shutil.copy2(resolved["directory"] / name, target / name)
        shutil.copytree(resolved["directory"] / "profiles", target / "profiles")
        atomic_write_json(target / "intake.json", intake)
        atomic_write_json(target / "resolved.json", {
            "id": resolved["id"], "version": resolved["version"],
            "digest": resolved["digest"], "profile": resolved["manifest"]["default_profile"],
        })
