from __future__ import annotations

from typing import Any

from .base import BaseAdapter, invalid, item_by_id


class EditAdapter(BaseAdapter):
    """Typed controls for the post-sample "edit and trim" stage."""

    stage = "edit"
    adapter_id = "edit-v1"
    artifact_name = "edit_decisions"
    operation_fields = {
        "set_shot_enabled": frozenset({"op", "shot_id", "enabled"}),
        "set_source_range": frozenset({"op", "shot_id", "in_seconds", "out_seconds"}),
        "set_shot_speed": frozenset({"op", "shot_id", "speed"}),
        "set_caption": frozenset({"op", "shot_id", "text"}),
        "set_audio_mix": frozenset({"op", "music_volume", "sfx_volume", "narration_enabled"}),
    }
    field_labels = {
        "cuts": "镜头取舍或节奏已调整",
        "caption_overrides": "字幕文案已调整",
        "audio": "声音配置已调整",
    }

    def _cut(self, snapshot: dict[str, Any], shot_id: str) -> dict[str, Any]:
        return item_by_id(snapshot.setdefault("cuts", []), shot_id, "镜头")

    def _apply_one(self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]) -> None:
        if name == "set_audio_mix":
            audio = snapshot.setdefault("audio", {})
            music = audio.setdefault("music", {})
            music["volume"] = operation["music_volume"]
            sfx = audio.setdefault("sfx", [])
            if sfx:
                sfx[0]["volume"] = operation["sfx_volume"]
            else:
                sfx.append({"asset_id": "impact-sfx", "start_seconds": 0, "volume": operation["sfx_volume"]})
            narration = audio.setdefault("narration", {})
            narration["enabled"] = operation["narration_enabled"]
            return
        if name == "set_caption":
            overrides = snapshot.setdefault("caption_overrides", [])
            existing = next((item for item in overrides if item.get("shot_id") == operation["shot_id"]), None)
            if existing is None:
                overrides.append({"shot_id": operation["shot_id"], "text": operation["text"]})
            else:
                existing["text"] = operation["text"]
            return
        cut = self._cut(snapshot, operation["shot_id"])
        if name == "set_shot_enabled":
            cut["enabled"] = operation["enabled"]
        elif name == "set_source_range":
            if operation["out_seconds"] <= operation["in_seconds"]:
                raise invalid("素材时间范围无效", f"cuts.{operation['shot_id']}")
            cut.update(in_seconds=operation["in_seconds"], out_seconds=operation["out_seconds"])
        elif name == "set_shot_speed":
            if operation["speed"] <= 0:
                raise invalid("镜头速度必须大于 0", f"cuts.{operation['shot_id']}")
            cut["speed"] = operation["speed"]

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        if name == "set_caption":
            return f"caption_overrides.{operation['shot_id']}"
        if name == "set_audio_mix":
            return "audio"
        return f"cuts.{operation['shot_id']}"

    def validate(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        cuts = snapshot.get("cuts") if isinstance(snapshot.get("cuts"), list) else []
        if cuts and not any(item.get("enabled", True) for item in cuts if isinstance(item, dict)):
            raise invalid("至少保留一个镜头", "cuts")
        return []

    def diff(self, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        changes = []
        if before.get("cuts") != after.get("cuts"):
            changes.append(self.field_labels["cuts"])
        if before.get("caption_overrides") != after.get("caption_overrides"):
            changes.append(self.field_labels["caption_overrides"])
        if before.get("audio") != after.get("audio"):
            changes.append(self.field_labels["audio"])
        return changes

    def change_signals(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        names = {self._check_operation(item) for item in operations}
        audio_only = names == {"set_audio_mix"}
        return {
            "reopen_creative": False,
            "reopen_sample": True,
            "render_route": "mux_only" if audio_only else "full_render",
        }
