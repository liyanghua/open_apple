from __future__ import annotations

from typing import Any

from .base import BaseAdapter


class ResearchAdapter(BaseAdapter):
    stage = "research"
    adapter_id = "research-v1"
    artifact_name = "research_annotations"
    operation_fields = {
        "set_media_disposition": frozenset({"op", "media_id", "disposition"}),
        "set_business_note": frozenset({"op", "target_id", "text"}),
        "set_logo_usage": frozenset({"op", "media_id", "allowed"}),
        "set_claim_boundary": frozenset({"op", "claim_id", "text"}),
        "set_reference_method": frozenset({"op", "method_id", "selected"}),
        "set_direction_preference": frozenset({"op", "direction_id", "preference", "rationale"}),
        "resolve_matrix_row": frozenset({"op", "matrix_row_id", "resolution", "source_media_id", "note"}),
        "request_local_reanalysis": frozenset({"op", "target_type", "target_id", "dimensions", "reason"}),
    }
    field_labels = {"research_annotations": "素材使用意见"}

    _artifact_markers = frozenset({
        "base_research_revision",
        "media_dispositions",
        "logo_usage",
        "claim_boundaries",
        "reference_methods",
        "direction_preferences",
        "matrix_resolutions",
        "local_reanalysis_requests",
        "business_notes",
    })

    def _annotations(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        nested = snapshot.get("research_annotations")
        if isinstance(nested, dict):
            return nested
        if self._artifact_markers.intersection(snapshot):
            return snapshot
        return snapshot.setdefault("research_annotations", {})

    def _apply_one(self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]) -> None:
        annotations = self._annotations(snapshot)
        mapping = {
            "set_media_disposition": ("media_dispositions", "media_id", "disposition"),
            "set_business_note": ("business_notes", "target_id", "text"),
            "set_logo_usage": ("logo_usage", "media_id", "allowed"),
            "set_claim_boundary": ("claim_boundaries", "claim_id", "text"),
            "set_reference_method": ("reference_methods", "method_id", "selected"),
        }
        if name == "set_direction_preference":
            annotations.setdefault("direction_preferences", {})[operation["direction_id"]] = {
                "preference": operation["preference"],
                "rationale": operation["rationale"],
            }
            return
        if name == "resolve_matrix_row":
            annotations.setdefault("matrix_resolutions", {})[operation["matrix_row_id"]] = {
                "resolution": operation["resolution"],
                "source_media_id": operation["source_media_id"],
                "note": operation["note"],
            }
            return
        if name == "request_local_reanalysis":
            annotations.setdefault("local_reanalysis_requests", []).append({
                "target_type": operation["target_type"],
                "target_id": operation["target_id"],
                "dimensions": list(operation["dimensions"]),
                "reason": operation["reason"],
            })
            return
        collection, key, value = mapping[name]
        annotations.setdefault(collection, {})[operation[key]] = operation[value]

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        paths = {
            "set_media_disposition": ("media_dispositions", "media_id"),
            "set_business_note": ("business_notes", "target_id"),
            "set_logo_usage": ("logo_usage", "media_id"),
            "set_claim_boundary": ("claim_boundaries", "claim_id"),
            "set_reference_method": ("reference_methods", "method_id"),
            "set_direction_preference": ("direction_preferences", "direction_id"),
            "resolve_matrix_row": ("matrix_resolutions", "matrix_row_id"),
        }
        if name == "request_local_reanalysis":
            return "local_reanalysis_requests"
        collection, target_key = paths[name]
        return f"{collection}.{operation[target_key]}"

    def change_signals(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        for operation in operations:
            self._check_operation(operation)
        reopens_creative = any(
            item["op"] in {"set_direction_preference", "resolve_matrix_row"}
            for item in operations
        )
        return {
            "reopen_creative": reopens_creative,
            "reopen_sample": False,
            "render_route": "no_render",
        }
