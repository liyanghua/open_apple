from __future__ import annotations

from typing import Any

from .base import BaseAdapter, invalid, item_by_id


class SampleAdapter(BaseAdapter):
    stage = "sample"
    adapter_id = "sample-v1"
    artifact_name = "sample_review"
    operation_fields = {
        "add_timecode_comment": frozenset({"op", "start_seconds", "end_seconds", "text"}),
        "replace_section_narration": frozenset({"op", "section_id", "text"}),
        "replace_section_screen_copy": frozenset({"op", "section_id", "text"}),
        "set_source_range": frozenset({"op", "shot_id", "in_seconds", "out_seconds"}),
        "set_shot_speed": frozenset({"op", "shot_id", "speed"}),
        "set_shot_transition": frozenset({"op", "shot_id", "transition"}),
    }
    field_labels = {"comments": "样片意见", "sections": "口播字幕", "shots": "镜头剪辑"}

    def _apply_one(self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]) -> None:
        if name == "add_timecode_comment":
            if operation["end_seconds"] <= operation["start_seconds"]:
                raise invalid("评论时间范围无效", "comments")
            snapshot.setdefault("comments", []).append({key: operation[key] for key in ("start_seconds", "end_seconds", "text")})
            return
        if "section_id" in operation:
            section = item_by_id(snapshot.setdefault("sections", []), operation["section_id"], "section")
            section["narration" if name == "replace_section_narration" else "screen_copy"] = operation["text"]
            return
        shot = item_by_id(snapshot.setdefault("shots", []), operation["shot_id"], "shot")
        if name == "set_source_range":
            if operation["out_seconds"] <= operation["in_seconds"]:
                raise invalid("素材时间范围无效", f"shots.{operation['shot_id']}")
            shot.update(source_in_seconds=operation["in_seconds"], source_out_seconds=operation["out_seconds"])
        elif name == "set_shot_speed":
            shot["speed"] = operation["speed"]
        else:
            shot["transition"] = operation["transition"]

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        if name == "add_timecode_comment":
            return "comments"
        if "section_id" in operation:
            suffix = "narration" if name == "replace_section_narration" else "screen_copy"
            return f"sections.{operation['section_id']}.{suffix}"
        suffix = {"set_source_range": "source_range", "set_shot_speed": "speed", "set_shot_transition": "transition"}[name]
        return f"shots.{operation['shot_id']}.{suffix}"

    def change_signals(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        names = {self._check_operation(item) for item in operations}
        editing = names != {"add_timecode_comment"}
        return {"reopen_creative": False, "reopen_sample": editing, "render_route": "full_render" if editing else "no_render"}

