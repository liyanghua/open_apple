"""Execute one approved product-image video task through an exact registry tool.

This adapter deliberately makes no routing or creative decisions.  It accepts
only a provider/model choice already present in the approved proposal, maps the
canonical I2V request to that tool's input schema, and records immutable output
lineage for idempotent recovery.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from lib.artifact_hashing import semantic_sha256


class ProductImageAssetExecutor:
    def __init__(
        self,
        project_dir: Path,
        *,
        tool_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        if tool_resolver is None:
            from tools.tool_registry import registry

            registry.ensure_discovered()
            tool_resolver = registry.get
        self._tool_resolver = tool_resolver

    @property
    def receipt_dir(self) -> Path:
        return self.project_dir / "operator/product-image-execution"

    def _receipt_path(self, idempotency_key: str) -> Path:
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self.receipt_dir / f"{key_hash}.json"

    @staticmethod
    def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".product-image-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(dict(value), handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _project_path(self, relative: str, *, must_exist: bool) -> Path:
        path = (self.project_dir / relative).resolve()
        if self.project_dir not in path.parents:
            raise ValueError("asset path is outside the project")
        if must_exist and not path.is_file():
            raise ValueError("reference asset does not exist")
        return path

    def execute(
        self,
        *,
        shot: Mapping[str, Any],
        proposal: Mapping[str, Any],
        quality: str,
        idempotency_key: str,
        output_path: str,
        status_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if proposal.get("operation") != "image_to_video":
            raise ValueError("product image executor only supports image_to_video")
        if proposal.get("provider_selection_status") != "locked":
            raise ValueError("product image provider is not locked")
        selected = proposal.get("selected_provider_candidate")
        if not isinstance(selected, Mapping):
            raise ValueError("locked provider candidate is missing")
        candidates = [item for item in proposal.get("provider_candidates") or [] if isinstance(item, Mapping)]
        if dict(selected) not in [dict(item) for item in candidates]:
            raise ValueError("locked provider candidate is not in the approved shortlist")
        if selected.get("supports_local_reference") is not True or selected.get("supports_native_3_4") is not True:
            raise ValueError("locked provider lacks local-reference or native 3:4 support")
        references = proposal.get("reference_paths") or []
        if len(references) != 1 or not isinstance(references[0], str):
            raise ValueError("image_to_video requires exactly one local reference")
        reference_path = self._project_path(references[0], must_exist=True)
        reference_hash = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        if reference_hash != proposal.get("reference_hash"):
            raise ValueError("reference hash changed after approval")
        resolved_output = self._project_path(output_path, must_exist=False)

        request = {
            "shot_id": shot.get("id"),
            "proposal_id": proposal.get("id"),
            "prompt": proposal.get("prompt"),
            "reference_hash": reference_hash,
            "selected_provider_candidate": dict(selected),
            "duration_seconds": proposal.get("duration_seconds"),
            "aspect_ratio": proposal.get("aspect_ratio"),
            "quality": quality,
            "output_path": output_path,
        }
        request_digest = semantic_sha256(request)
        receipt_path = self._receipt_path(idempotency_key)
        if receipt_path.is_file():
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
            if existing.get("request_digest") != request_digest:
                raise ValueError("idempotency key was already used for a different request")
            return existing

        tool_name = str(selected.get("tool") or "")
        tool = self._tool_resolver(tool_name)
        if tool is None:
            raise ValueError(f"locked registry tool is unavailable: {tool_name}")
        info = tool.get_info()
        if info.get("status") not in {None, "available"}:
            raise ValueError(f"locked registry tool is unavailable: {tool_name}")
        if str(info.get("name") or tool_name) != tool_name:
            raise ValueError("registry tool identity does not match the approved candidate")
        if str(info.get("provider") or "") != str(selected.get("provider") or ""):
            raise ValueError("registry provider does not match the approved candidate")
        properties = ((info.get("input_schema") or {}).get("properties") or {})
        inputs: dict[str, Any] = {
            "prompt": str(proposal.get("prompt") or ""),
            "operation": "image_to_video",
            "aspect_ratio": "3:4",
            "resolution": "480p" if quality == "fast" else "720p",
            "output_path": str(resolved_output),
        }
        duration = int(proposal.get("duration_seconds") or 4)
        duration_spec = properties.get("duration") or {}
        inputs["duration"] = str(duration) if duration_spec.get("type") == "string" else duration
        if "image_path" in properties:
            inputs["image_path"] = str(reference_path)
        elif "reference_image_path" in properties:
            inputs["reference_image_path"] = str(reference_path)
        else:
            raise ValueError("locked registry tool no longer accepts a local reference")
        model = str(selected.get("model") or "")
        model_input_key = None
        if "model" in properties and model:
            inputs["model"] = model
            model_input_key = "model"
        elif "model_variant" in properties and model:
            inputs["model_variant"] = model
            model_input_key = "model_variant"
        if "generate_audio" in properties:
            inputs["generate_audio"] = False
        if status_callback is not None:
            inputs["_status_callback"] = status_callback

        result = tool.execute(inputs)
        if not result.success:
            raise RuntimeError(str(result.error or "product image video generation failed"))
        data = result.data or {}
        returned_tool = str(data.get("selected_tool") or tool_name)
        returned_provider = str(data.get("selected_provider") or selected.get("provider") or "")
        returned_model = str(data.get("model") or model)
        if returned_tool != tool_name:
            raise ValueError("provider substitution detected: tool changed")
        if returned_provider != str(selected.get("provider") or ""):
            raise ValueError("provider substitution detected: provider changed")
        if model_input_key == "model" and model and returned_model != model:
            raise ValueError("provider substitution detected: model changed")
        actual_output = Path(str(data.get("output_path") or data.get("output") or resolved_output)).resolve()
        if self.project_dir not in actual_output.parents or not actual_output.is_file():
            raise ValueError("provider did not return a valid project output")
        receipt = {
            "idempotency_key": idempotency_key,
            "request_digest": request_digest,
            "shot_id": str(shot.get("id") or ""),
            "proposal_id": str(proposal.get("id") or ""),
            "tool": tool_name,
            "provider": returned_provider,
            "model": returned_model,
            "reference_path": references[0],
            "reference_hash": reference_hash,
            "output_path": actual_output.relative_to(self.project_dir).as_posix(),
            "output_sha256": hashlib.sha256(actual_output.read_bytes()).hexdigest(),
            "actual_cost_usd": float(result.cost_usd or 0),
        }
        self._atomic_write(receipt_path, receipt)
        return receipt
