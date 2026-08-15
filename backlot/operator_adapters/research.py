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
    }
    field_labels = {"research_annotations": "素材使用意见"}

    def _apply_one(self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]) -> None:
        annotations = snapshot.setdefault("research_annotations", {})
        mapping = {
            "set_media_disposition": ("media_dispositions", "media_id", "disposition"),
            "set_business_note": ("business_notes", "target_id", "text"),
            "set_logo_usage": ("logo_usage", "media_id", "allowed"),
            "set_claim_boundary": ("claim_boundaries", "claim_id", "text"),
            "set_reference_method": ("reference_methods", "method_id", "selected"),
        }
        collection, key, value = mapping[name]
        annotations.setdefault(collection, {})[operation[key]] = operation[value]

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        target = operation.get("media_id", operation.get("target_id", operation.get("claim_id", operation.get("method_id"))))
        return f"research_annotations.{name}.{target}"

