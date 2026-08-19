from __future__ import annotations

from typing import Any

from .base import BaseAdapter, invalid, item_by_id, reorder


class ScenePlanAdapter(BaseAdapter):
    stage = "scene_plan"
    adapter_id = "scene-plan-v1"
    artifact_name = "scene_plan"
    operation_fields = {
        "reorder_shots": frozenset({"op", "shot_ids"}),
        "set_shot_source": frozenset({"op", "shot_id", "source_id"}),
        "set_source_range": frozenset({"op", "shot_id", "in_seconds", "out_seconds"}),
        "set_timeline_range": frozenset({"op", "shot_id", "start_seconds", "end_seconds"}),
        "set_shot_speed": frozenset({"op", "shot_id", "speed"}),
        "set_shot_framing": frozenset({"op", "shot_id", "crop", "zoom"}),
        "set_shot_transition": frozenset({"op", "shot_id", "transition"}),
        "set_shot_audio": frozenset({"op", "shot_id", "source_audio", "sfx", "bgm", "narration"}),
        "set_shot_gap": frozenset({"op", "shot_id", "has_gap"}),
    }
    field_labels = {"shots": "分镜"}

    def _shot(self, snapshot: dict[str, Any], shot_id: str) -> dict[str, Any]:
        return item_by_id(snapshot.setdefault("shots", []), shot_id, "shot")

    def _apply_one(self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]) -> None:
        if name == "reorder_shots":
            snapshot["shots"] = reorder(snapshot.get("shots", []), operation["shot_ids"], "shot")
            return
        shot = self._shot(snapshot, operation["shot_id"])
        if name == "set_shot_source":
            shot["source_id"] = operation["source_id"]
        elif name == "set_source_range":
            shot.update(source_in_seconds=operation["in_seconds"], source_out_seconds=operation["out_seconds"])
        elif name == "set_timeline_range":
            shot.update(start_seconds=operation["start_seconds"], end_seconds=operation["end_seconds"])
        elif name == "set_shot_speed":
            shot["speed"] = operation["speed"]
        elif name == "set_shot_framing":
            shot["framing"] = {"crop": operation["crop"], "zoom": operation["zoom"]}
        elif name == "set_shot_transition":
            shot["transition"] = operation["transition"]
        elif name == "set_shot_audio":
            shot["audio"] = {key: operation[key] for key in ("source_audio", "sfx", "bgm", "narration")}
        elif name == "set_shot_gap":
            shot["has_gap"] = operation["has_gap"]

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        if name == "reorder_shots":
            return "shots.order"
        suffix = {
            "set_shot_source": "source_id", "set_source_range": "source_range",
            "set_timeline_range": "timeline_range", "set_shot_speed": "speed",
            "set_shot_framing": "framing", "set_shot_transition": "transition",
            "set_shot_audio": "audio", "set_shot_gap": "has_gap",
        }[name]
        return f"shots.{operation['shot_id']}.{suffix}"

    def validate(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        shots = sorted(snapshot.get("shots", []), key=lambda item: float(item.get("start_seconds", 0)))
        sources = snapshot.get("sources", {})
        cursor = 0.0
        errors = []
        for index, shot in enumerate(shots):
            start, end = float(shot.get("start_seconds", -1)), float(shot.get("end_seconds", -1))
            source_in = float(shot.get("source_in_seconds", -1))
            source_out = float(shot.get("source_out_seconds", -1))
            if start < 0 or end <= start or source_in < 0 or source_out <= source_in:
                errors.append({"field": f"shots.{index}", "message": "镜头时间范围无效"})
            if abs(start - cursor) > 0.001:
                errors.append({"field": f"shots.{index}.start", "message": "时间轴存在重叠或空洞"})
            cursor = end
            source = sources.get(shot.get("source_id"), {}) if isinstance(sources, dict) else {}
            if source and source_out > float(source.get("duration_seconds", 0)) + 0.001:
                errors.append({"field": f"shots.{index}.source", "message": "所选素材范围超出源视频"})
            speed = float(shot.get("speed", 1))
            if speed <= 0 or (source_out - source_in) / speed + 0.001 < end - start:
                errors.append({"field": f"shots.{index}.speed", "message": "素材长度不足以覆盖镜头"})
        declared = float(snapshot.get("total_duration_seconds", cursor))
        if shots and abs(cursor - declared) > 0.001:
            errors.append({"field": "total_duration_seconds", "message": "镜头总时长与交付时长不一致"})
        if errors:
            raise invalid(errors[0]["message"], errors[0]["field"])
        return []

    def change_signals(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        for item in operations:
            self._check_operation(item)
        return {"reopen_creative": False, "reopen_sample": True, "render_route": "full_render"}
