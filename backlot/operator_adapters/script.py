from __future__ import annotations

import re
from typing import Any

from .base import BaseAdapter, invalid, item_by_id, reorder


class ScriptAdapter(BaseAdapter):
    stage = "script"
    adapter_id = "script-v1"
    artifact_name = "script"
    operation_fields = {
        "replace_section_narration": frozenset({"op", "section_id", "text"}),
        "replace_section_screen_copy": frozenset({"op", "section_id", "text"}),
        "reorder_sections": frozenset({"op", "section_ids"}),
        "set_section_delivery": frozenset({"op", "section_id", "tone", "rate"}),
        "set_subtitle_profile": frozenset({"op", "profile_id"}),
        "set_emphasis_words": frozenset({"op", "section_id", "words"}),
        "set_strip_trailing_punctuation": frozenset({"op", "enabled"}),
        "review_script_section": frozenset({"op", "section_id", "decision", "feedback"}),
        "approve_production_script": frozenset({"op"}),
    }
    field_labels = {
        "sections": "口播与字幕段落",
        "subtitle_profile_id": "字幕样式",
        "strip_trailing_punctuation": "字幕尾部标点",
    }

    def _section(self, snapshot: dict[str, Any], section_id: str) -> dict[str, Any]:
        return item_by_id(snapshot.setdefault("sections", []), section_id, "section")

    def _apply_one(self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]) -> None:
        if name == "approve_production_script":
            if not snapshot.get("sections") or any(
                section.get("review") != "approved" for section in snapshot.get("sections", [])
            ):
                raise invalid("请先确认制作剧本的每一段，再锁定整份剧本", "sections")
            snapshot["status"] = "approved"
            return
        if name == "reorder_sections":
            snapshot["sections"] = reorder(snapshot.get("sections", []), operation["section_ids"], "section")
            return
        if name == "set_subtitle_profile":
            snapshot["subtitle_profile_id"] = operation["profile_id"]
            return
        if name == "set_strip_trailing_punctuation":
            snapshot["strip_trailing_punctuation"] = operation["enabled"]
            return
        section = self._section(snapshot, operation["section_id"])
        if name == "review_script_section":
            decision = operation["decision"]
            if decision not in {"approved", "needs_adjustment"}:
                raise invalid("请选择“这段可以”或“这段要调整”", "decision")
            if decision == "needs_adjustment" and not str(operation["feedback"]).strip():
                raise invalid("请说明这段要怎么调整", "feedback")
            section["review"] = decision
            section["feedback"] = str(operation["feedback"]).strip()
            snapshot["status"] = "needs_revision" if decision == "needs_adjustment" else "draft"
        elif name == "replace_section_narration":
            section["narration"] = operation["text"]
        elif name == "replace_section_screen_copy":
            section["screen_copy"] = operation["text"]
        elif name == "set_section_delivery":
            section["delivery"] = {"tone": operation["tone"], "rate": operation["rate"]}
        elif name == "set_emphasis_words":
            section["emphasis_words"] = operation["words"]

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        if name == "approve_production_script":
            return "status"
        if name == "reorder_sections":
            return "sections.order"
        if name == "set_subtitle_profile":
            return "subtitle_profile_id"
        if name == "set_strip_trailing_punctuation":
            return "strip_trailing_punctuation"
        suffix = {
            "replace_section_narration": "narration",
            "replace_section_screen_copy": "screen_copy",
            "set_section_delivery": "delivery",
            "set_emphasis_words": "emphasis_words",
            "review_script_section": "review",
        }[name]
        return f"sections.{operation['section_id']}.{suffix}"

    def validate(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        sections = snapshot.get("sections", [])
        durations = [
            float(item.get("end_seconds", 0)) - float(item.get("start_seconds", 0))
            for item in sections
        ]
        declared = float(snapshot.get("total_duration_seconds", sum(durations) or 0))
        if durations and abs(sum(durations) - declared) > 0.25:
            warnings.append({"code": "duration_mismatch", "message": "段落总时长与成片时长不一致"})
        for index, item in enumerate(sections):
            text = str(item.get("screen_copy", ""))
            if len(re.sub(r"\s+", "", text)) > 18:
                warnings.append({"code": "caption_too_long", "message": f"第{index + 1}段字幕偏长"})
            if len(text) > 28 or "\n\n" in text:
                warnings.append({"code": "caption_safe_zone_risk", "message": f"第{index + 1}段字幕存在安全区风险"})
        if len(sections) >= 2:
            previous = float((sections[-2].get("delivery") or {}).get("rate", 1))
            final = float((sections[-1].get("delivery") or {}).get("rate", 1))
            if final > max(1.25, previous * 1.25):
                warnings.append({"code": "tail_delivery_too_fast", "message": "最后一段语速明显偏快"})
        return warnings

    def change_signals(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        names = {self._check_operation(item) for item in operations}
        creative = bool(names & {"replace_section_narration", "reorder_sections", "review_script_section"})
        return {"reopen_creative": creative, "reopen_sample": True, "render_route": "full_render"}
