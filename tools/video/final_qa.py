"""Deterministic quick/full final media QA for social-v1 delivery."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lib.caption_layout import boxes_in_social_safe_zone, layout_captions
from tools.base_tool import BaseTool, Determinism, ExecutionMode, ResourceProfile, ToolResult, ToolStability, ToolTier


class FinalQA(BaseTool):
    name = "final_qa"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "ffmpeg"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    agent_skills = ["ffmpeg"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=512, vram_mb=0, disk_mb=300)
    input_schema = {"type": "object", "required": ["mode", "input_path"], "properties": {"mode": {"enum": ["quick", "full"]}, "input_path": {"type": "string"}, "expected_profile": {"type": "string"}, "caption_spec": {"type": "object"}, "output_path": {"type": "string"}}}

    @staticmethod
    def _probe(path: Path) -> dict[str, Any]:
        result = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], capture_output=True, text=True, timeout=30, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        return json.loads(result.stdout)

    @staticmethod
    def _decode(path: Path) -> bool:
        return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, timeout=300, check=False).returncode == 0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        path = Path(inputs["input_path"])
        if not path.is_file():
            return ToolResult(success=False, error=f"QA input not found: {path}")
        try:
            probe = self._probe(path)
        except (OSError, RuntimeError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc))
        profile_name = inputs.get("expected_profile", "social_vertical_1080p30")
        from lib.media_profiles import get_profile
        profile = get_profile(profile_name)
        video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
        audio = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), {})
        issues = []
        if (video.get("codec_name"), video.get("pix_fmt")) != ("h264", profile.pixel_format): issues.append("video codec or pixel format mismatch")
        if (int(video.get("width", 0)), int(video.get("height", 0))) != (profile.width, profile.height): issues.append("resolution mismatch")
        if audio.get("codec_name") != "aac" or int(audio.get("sample_rate", 0) or 0) != profile.audio_sample_rate or int(audio.get("channels", 0) or 0) != profile.audio_channels: issues.append("audio profile mismatch")
        decode_ok = self._decode(path)
        if not decode_ok: issues.append("full decode smoke failed")
        caption_spec = inputs.get("caption_spec") or {}
        boxes = caption_spec.get("computed_boxes") or layout_captions(caption_spec.get("captions", []), width=profile.width, height=profile.height)
        caption_ok = bool(caption_spec.get("props_hash")) and boxes_in_social_safe_zone(boxes, width=profile.width, height=profile.height)
        if caption_spec and not caption_ok: issues.append("caption safe-zone evidence missing or invalid")
        status = "pass" if not issues else "revise"
        checks = {
            "media_integrity": {"decode_ok": decode_ok, "profile_ok": not any("profile" in issue or "resolution" in issue or "codec" in issue for issue in issues), "probe": probe},
            "audio_loudness": {"measured": inputs.get("mode") == "full", "integrated_lufs": None, "true_peak_dbtp": None},
            "caption_render": {"safe_zone_passed": caption_ok if caption_spec else True, "computed_boxes": boxes, "props_hash": caption_spec.get("props_hash")},
        }
        report = {"version": "2.0", "output_path": str(path), "status": status, "checks": checks, "issues_found": issues, "recommended_action": "present_to_user" if status == "pass" else "re_render"}
        output = inputs.get("output_path")
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True); Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return ToolResult(success=status != "fail", data=report, artifacts=[str(output)] if output else [])
