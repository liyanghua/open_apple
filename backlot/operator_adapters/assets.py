from __future__ import annotations

from typing import Any

from .base import BaseAdapter


class AssetsAdapter(BaseAdapter):
    stage = "assets"
    adapter_id = "assets-v1"
    artifact_name = "asset_plan"
    operation_fields = {
        "set_tts": frozenset({"op", "provider", "model", "voice", "rate"}),
        "set_bgm": frozenset({"op", "source", "track_id"}),
        "set_subtitle_profile": frozenset({"op", "profile_id"}),
        "set_runtime": frozenset({"op", "runtime"}),
        "set_composition_mode": frozenset({"op", "mode"}),
        "authorize_paid_generation": frozenset({"op", "approved", "estimated_cost_usd"}),
        "set_asset_gap": frozenset({"op", "gap_id", "strategy"}),
    }
    field_labels = {
        "tts": "口播声音",
        "bgm": "背景音乐",
        "subtitle_profile_id": "字幕样式",
        "render_runtime": "合成方式",
        "composition_mode": "画面制作模式",
        "paid_generation": "付费生成授权",
        "asset_gaps": "素材缺口处理",
    }

    def _apply_one(self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]) -> None:
        if name == "set_tts":
            snapshot["tts"] = {key: operation[key] for key in ("provider", "model", "voice", "rate")}
        elif name == "set_bgm":
            snapshot["bgm"] = {key: operation[key] for key in ("source", "track_id")}
        elif name == "set_subtitle_profile":
            snapshot["subtitle_profile_id"] = operation["profile_id"]
        elif name == "set_runtime":
            snapshot["render_runtime"] = operation["runtime"]
        elif name == "set_composition_mode":
            snapshot["composition_mode"] = operation["mode"]
        elif name == "authorize_paid_generation":
            snapshot["paid_generation"] = {"approved": operation["approved"], "estimated_cost_usd": operation["estimated_cost_usd"]}
        elif name == "set_asset_gap":
            snapshot.setdefault("asset_gaps", {})[operation["gap_id"]] = operation["strategy"]

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        return {
            "set_tts": "tts", "set_bgm": "bgm", "set_subtitle_profile": "subtitle_profile_id",
            "set_runtime": "render_runtime", "set_composition_mode": "composition_mode",
            "authorize_paid_generation": "paid_generation",
            "set_asset_gap": f"asset_gaps.{operation.get('gap_id', '')}",
        }[name]

    def change_signals(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        names = {self._check_operation(item) for item in operations}
        creative = bool(names & {"set_tts", "set_bgm", "set_runtime", "set_composition_mode"})
        render = bool(names & {"set_tts", "set_bgm", "set_subtitle_profile", "set_runtime", "set_composition_mode"})
        return {
            "reopen_creative": creative,
            "reopen_sample": render,
            "render_route": "full_render" if render else "no_render",
        }

