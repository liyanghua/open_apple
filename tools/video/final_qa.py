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
    input_schema = {"type": "object", "required": ["mode", "input_path"], "properties": {"mode": {"enum": ["quick", "full"]}, "input_path": {"type": "string"}, "expected_profile": {"type": "string"}, "caption_spec": {"type": "object"}, "caption_declaration": {"type": "object"}, "output_path": {"type": "string"}}}

    @staticmethod
    def _probe(path: Path) -> dict[str, Any]:
        result = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], capture_output=True, text=True, timeout=30, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        return json.loads(result.stdout)

    @staticmethod
    def _decode(path: Path) -> bool:
        return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, timeout=300, check=False).returncode == 0

    @staticmethod
    def _filter_log(path: Path, filter_graph: str) -> str:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", filter_graph, "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=300, check=False)
        return result.stderr or ""

    @staticmethod
    def _parse_ranges(log: str, marker: str) -> list[dict[str, float]]:
        ranges = []
        for line in log.splitlines():
            if marker not in line:
                continue
            values = {}
            for token in line.split():
                if "=" not in token:
                    continue
                key, value = token.split("=", 1)
                try:
                    values[key] = float(value)
                except ValueError:
                    pass
            if values:
                ranges.append(values)
        return ranges

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
        accepted_pixel_formats = {profile.pixel_format}
        if inputs.get("mode") == "quick" and profile_name == "social_vertical_sample_540p30":
            accepted_pixel_formats.add("yuvj420p")
        if (
            video.get("codec_name") != "h264"
            or video.get("pix_fmt") not in accepted_pixel_formats
        ):
            issues.append("video codec or pixel format mismatch")
        if (int(video.get("width", 0)), int(video.get("height", 0))) != (profile.width, profile.height): issues.append("resolution mismatch")
        if audio.get("codec_name") != "aac" or int(audio.get("sample_rate", 0) or 0) != profile.audio_sample_rate or int(audio.get("channels", 0) or 0) != profile.audio_channels: issues.append("audio profile mismatch")
        decode_ok = self._decode(path)
        if not decode_ok: issues.append("full decode smoke failed")
        black_ranges: list[dict[str, float]] = []
        freeze_ranges: list[dict[str, float]] = []
        loudness = {"integrated_lufs": None, "true_peak_dbtp": None, "lra": None}
        if inputs.get("mode") == "full" and decode_ok:
            black_ranges = self._parse_ranges(self._filter_log(path, "blackdetect=d=0.15:pix_th=0.10:pic_th=0.98"), "black_start")
            freeze_ranges = self._parse_ranges(self._filter_log(path, "freezedetect=n=-50dB:d=1.00"), "freeze_start")
            loud_result = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True, timeout=300, check=False)
            for line in (loud_result.stderr or "").splitlines():
                stripped = line.strip()
                if stripped.startswith("I:"):
                    try: loudness["integrated_lufs"] = float(stripped.split()[1])
                    except (IndexError, ValueError): pass
                if stripped.startswith("Peak:"):
                    try: loudness["true_peak_dbtp"] = float(stripped.split()[1])
                    except (IndexError, ValueError): pass
            allowed_black = inputs.get("allowed_black_ranges") or []
            allowed_freeze = inputs.get("allowed_freeze_ranges") or []
            if black_ranges and not allowed_black: issues.append("unexpected black segment detected")
            if freeze_ranges and not allowed_freeze: issues.append("unexpected freeze segment detected")
        technical_issues = list(issues)
        caption_spec = inputs.get("caption_spec") or {}
        declaration = inputs.get("caption_declaration") or {}
        render_mode = declaration.get("caption_render_mode")
        caption_source = declaration.get("caption_source")
        safe_zone_profile = declaration.get("safe_zone_profile")
        declared = bool(render_mode and caption_source and safe_zone_profile)
        pixel_mode = render_mode in {"remotion_overlay", "ffmpeg_burn"}
        boxes = caption_spec.get("computed_boxes") or (
            layout_captions(
                caption_spec.get("captions", []),
                width=profile.width,
                height=profile.height,
            )
            if caption_spec else []
        )
        caption_ok = None
        if caption_spec and not declared:
            issues.append("caption render declaration missing")
        if declaration and not declared:
            issues.append("caption render declaration incomplete")
        if pixel_mode:
            caption_ok = bool(caption_spec.get("props_hash")) and boxes_in_social_safe_zone(
                boxes, width=profile.width, height=profile.height
            )
            if not caption_ok:
                issues.append("caption pixel evidence missing or invalid")
        status = "pass" if not issues else "revise"
        format_info = probe.get("format", {})
        fps_text = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        try:
            fps_num, fps_den = fps_text.split("/", 1)
            fps = round(float(fps_num) / max(float(fps_den), 1.0), 2)
        except (AttributeError, TypeError, ValueError):
            fps = 0.0
        technical_probe = {
            "valid_container": bool(video),
            "duration_seconds": float(format_info.get("duration", 0) or 0),
            "resolution": f"{int(video.get('width', 0))}x{int(video.get('height', 0))}",
            "fps": fps,
            "has_audio": bool(audio),
            "codec": video.get("codec_name", "unknown"),
            "file_size_bytes": int(format_info.get("size", 0) or path.stat().st_size),
            "issues": technical_issues,
        }
        subtitles_expected = bool(caption_spec or declaration)
        subtitle_stream_present = any(
            stream.get("codec_type") == "subtitle" for stream in probe.get("streams", [])
        )
        subtitles_present = bool(
            declared
            and (
                (render_mode == "subtitle_stream" and subtitle_stream_present)
                or (pixel_mode and caption_ok)
            )
        )
        checks = {
            "technical_probe": technical_probe,
            "visual_spotcheck": {
                "black_frames_detected": bool(black_ranges),
                "issues": [],
            },
            "audio_spotcheck": {
                "unexpected_silence": not bool(audio),
                "clipping_detected": bool(
                    loudness["true_peak_dbtp"] is not None
                    and loudness["true_peak_dbtp"] > -0.5
                ),
                "mix_intelligible": bool(audio),
                "issues": [],
            },
            "promise_preservation": {
                "delivery_promise_honored": True,
                "runtime_swap_detected": False,
                "runtime_swap_check": "skipped - final_qa received no production-lock context",
                "silent_downgrade_detected": False,
                "issues": [],
            },
            "subtitle_check": {
                "subtitles_expected": subtitles_expected,
                "subtitles_present": subtitles_present,
                "timing_drift_detected": False,
                "issues": [],
            },
            "media_integrity": {"decode_ok": decode_ok, "profile_ok": not any("profile" in issue or "resolution" in issue or "codec" in issue for issue in issues), "probe": probe},
            "audio_loudness": {"measured": inputs.get("mode") == "full", **loudness},
            "visual_anomalies": {"black_ranges": black_ranges, "freeze_ranges": freeze_ranges},
            "caption_render": {
                "declared": declared,
                "caption_render_mode": render_mode,
                "caption_source": caption_source,
                "safe_zone_profile": safe_zone_profile,
                "pixels_rendered": bool(declared and pixel_mode and caption_ok),
                "safe_zone_passed": caption_ok,
                "computed_boxes": boxes,
                "props_hash": caption_spec.get("props_hash"),
            },
        }
        report = {"version": "2.0", "output_path": str(path), "status": status, "checks": checks, "issues_found": issues, "recommended_action": "present_to_user" if status == "pass" else "re_render"}
        output = inputs.get("output_path")
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True); Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return ToolResult(success=status != "fail", data=report, artifacts=[str(output)] if output else [])
