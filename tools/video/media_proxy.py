"""Content-addressed, validated proxy media for Remotion inputs."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from lib.artifact_cache import ArtifactCache
from lib.cache_io import link_or_copy_atomic
from lib.cache_keys import canonical_digest, ffmpeg_revision, file_identity
from tools.base_tool import (
    BaseTool, Determinism, ExecutionMode, ResourceProfile, ToolResult,
    ToolStability, ToolTier,
)


class MediaProxy(BaseTool):
    name = "media_proxy"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "ffmpeg"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = "FFmpeg and ffprobe are required."
    capabilities = ["proxy", "content_addressed_media"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=512, vram_mb=0, disk_mb=500)

    input_schema = {
        "type": "object",
        "required": ["input_path", "output_path"],
        "properties": {
            "input_path": {"type": "string"}, "output_path": {"type": "string"},
            "project_dir": {"type": "string"}, "cache_dir": {"type": "string"},
            "profile": {"type": "string"}, "width": {"type": "integer"},
            "height": {"type": "integer"}, "fit": {"type": "string", "enum": ["cover", "contain"]},
            "codec": {"type": "string"}, "pixel_format": {"type": "string"},
        },
    }

    def _profile(self, inputs: dict[str, Any]) -> dict[str, Any]:
        profile = inputs.get("profile")
        if isinstance(profile, str):
            from lib.media_profiles import get_profile
            p = get_profile(profile)
            return {"name": p.name, "width": p.width, "height": p.height, "fps": p.fps,
                    "codec": p.codec, "pixel_format": p.pixel_format, "fit": inputs.get("fit", "cover")}
        result = dict(profile or {}) if isinstance(profile, dict) else {}
        result.update({k: inputs[k] for k in ("width", "height", "fit", "codec", "pixel_format") if k in inputs})
        result.setdefault("fit", "cover")
        return result

    def idempotency_key(self, inputs: dict[str, Any]) -> str:
        return canonical_digest({
            "tool": self.name, "tool_version": self.version,
            "ffmpeg_revision": ffmpeg_revision(),
            "source": file_identity(inputs.get("input_path")),
            "profile": self._profile(inputs),
        })

    @staticmethod
    def _probe(path: Path) -> dict[str, Any]:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise RuntimeError("ffprobe not found")
        result = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        return json.loads(result.stdout)

    def _cache_context(self, inputs: dict[str, Any]):
        output = Path(inputs["output_path"])
        root = Path(inputs.get("cache_dir") or Path(inputs.get("project_dir", output.parent)) / ".cache" / "media_proxy")
        name = f"proxy{output.suffix or '.mp4'}"
        cache = ArtifactCache(root, validators={name: lambda p: p.is_file() and p.stat().st_size > 0})
        return cache, self.idempotency_key(inputs), name, output

    def _run_ffmpeg(self, source: Path, output: Path, profile: dict[str, Any]) -> None:
        width, height = int(profile.get("width", 1080)), int(profile.get("height", 1920))
        fit = profile.get("fit", "cover")
        if fit == "contain":
            vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        else:
            vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        cmd = ["ffmpeg", "-y", "-i", str(source), "-vf", vf,
               "-c:v", profile.get("codec", "libx264"), "-pix_fmt", profile.get("pixel_format", "yuv420p"),
               "-an", str(output)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip()[-500:] or "ffmpeg failed")

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        source = Path(inputs["input_path"])
        output = Path(inputs["output_path"])
        if not source.is_file():
            return ToolResult(success=False, error=f"Input media not found: {source}")
        cache, key, name, output = self._cache_context(inputs)
        lookup = cache.lookup(key, [name])
        if lookup.hit:
            try:
                cache.materialize(lookup, {name: output})
                self._probe(output)
                return ToolResult(success=True, data={"cache_status": "hit", "cache_hit": True, "cache_key": key, "proxy_cache_key": key, "profile": self._profile(inputs), "source_content_sha256": file_identity(str(source))["content_sha256"]}, artifacts=[str(output)], cost_usd=0.0)
            except (OSError, ValueError, RuntimeError, KeyError):
                cache.invalidate(key, "proxy validation failed")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache.root) as temp:
            staged = Path(temp) / name
            try:
                self._run_ffmpeg(source, staged, self._profile(inputs))
                probe = self._probe(staged)
                cache.store(key, [staged], {"source_path": str(source), "source_content_sha256": file_identity(str(source))["content_sha256"], "profile": self._profile(inputs), "probe": probe})
                cache.materialize(cache.lookup(key, [name]), {name: output})
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                return ToolResult(success=False, data={"cache_status": "miss", "cache_hit": False, "cache_key": key}, error=str(exc))
        return ToolResult(success=True, data={"cache_status": "miss", "cache_hit": False, "cache_key": key, "proxy_cache_key": key, "profile": self._profile(inputs), "source_path": str(source), "source_content_sha256": file_identity(str(source))["content_sha256"]}, artifacts=[str(output)])
