"""L3 creative-quality VLM advisory judge (Design_Review D3: L1a gate + VLM advisory).

Samples uniform frames from a rendered video and asks a DashScope Qwen-VL model
to score the eight L3 dimensions (Hook Clarity / Visual Hierarchy / Rhythm /
Shot Quality / Story Coherence / Audio Quality / Text Readability / Product
Presence) on a 0-10 scale with a short reason each. The result is advisory: it
fills `evaluation_report.creative_advisory` and never blocks publish. Audio
dimensions are scored from the frames plus the caller-provided audio facts.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, Determinism, ExecutionMode, ResourceProfile, ToolResult, ToolRuntime, ToolStability, ToolTier

L3_DIMENSIONS = [
    ("hook_clarity", "Hook Clarity", "前 1-3 秒钩子是否清晰抓人"),
    ("visual_hierarchy", "Visual Hierarchy", "主体是否突出、画面层级是否清楚"),
    ("rhythm", "Rhythm", "节奏是否拖沓或过赶"),
    ("shot_quality", "Shot Quality", "镜头质量（曝光/对焦/构图）"),
    ("story_coherence", "Story Coherence", "逻辑是否顺畅连贯"),
    ("audio_quality", "Audio Quality", "口播/BGM 是否清晰、搭配合理"),
    ("text_readability", "Text Readability", "字幕是否易读、不遮挡主体"),
    ("product_presence", "Product Presence", "商品出现是否及时、展示是否到位"),
]

_RUBRIC_PROMPT = """你是电商短视频创意质量评审。按以下 8 个维度给这段视频打分（0-10，可保留一位小数），每维用一句中文说明理由：
1. hook_clarity 钩子清晰度：前 1-3 秒是否清晰抓人
2. visual_hierarchy 视觉层级：主体是否突出
3. rhythm 节奏：是否拖沓或过赶
4. shot_quality 镜头质量：曝光/对焦/构图
5. story_coherence 叙事连贯：逻辑是否顺畅
6. audio_quality 音频质量：口播与背景音乐是否清晰、搭配合理（结合音频说明判断）
7. text_readability 字幕可读性：字幕是否易读、不遮挡主体
8. product_presence 商品呈现：商品是否及时且到位地出现

只输出 JSON，不要多余文字，格式：
{"dimensions":[{"id":"hook_clarity","score":8.5,"note":"..."}, ...], "summary":"一句话总体评价"}"""


class VideoJudge(BaseTool):
    name = "video_judge"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "dashscope"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API
    dependencies = []
    install_instructions = "Set DASHSCOPE_API_KEY to call Qwen-VL for the L3 advisory judge."
    agent_skills = ["video-understand"]
    best_for = [
        "L3 creative quality advisory scoring for e-commerce short videos",
        "hook / rhythm / caption readability feedback before human review",
    ]
    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {"type": "string"},
            "output_path": {"type": "string"},
            "project_id": {"type": "string"},
            "scope": {"enum": ["sample", "final"]},
            "rubric_version": {"type": "string", "default": "l3-v1.0"},
            "frame_count": {"type": "integer", "default": 8, "minimum": 2, "maximum": 16},
            "model": {"type": "string", "default": "qwen-vl-max"},
            "audio_facts": {"type": "string", "description": "音频事实说明（口播/BGM 提供者、响度），辅助 Audio Quality 评分"},
        },
    }

    def get_status(self):
        import os
        from tools.base_tool import ToolStatus
        return ToolStatus.AVAILABLE if os.environ.get("DASHSCOPE_API_KEY") else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.02

    def _sample_frames(self, path: Path, count: int, workdir: Path) -> list[Path]:
        import math
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True)
        duration = float(probe.stdout.strip())
        frames: list[Path] = []
        for i in range(count):
            t = duration * (i + 0.5) / count
            out = workdir / f"frame_{i:02d}.jpg"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
                 "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4", str(out)],
                check=True)
            frames.append(out)
        return frames

    def _call_vlm(self, frames: list[Path], audio_facts: str, model: str) -> dict[str, Any]:
        import os
        import requests
        api_key = os.environ["DASHSCOPE_API_KEY"]
        content: list[dict[str, Any]] = [
            {"type": "text", "text": _RUBRIC_PROMPT},
        ]
        if audio_facts:
            content.append({"type": "text", "text": f"音频事实：{audio_facts}"})
        for frame in frames:
            data_url = "data:image/jpeg;base64," + base64.b64encode(frame.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        resp = requests.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.2},
            timeout=120,
        )
        resp.raise_for_status()
        body = resp.json()
        text = body["choices"][0]["message"]["content"]
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise RuntimeError(f"VLM 未返回 JSON: {text[:200]}")
        return json.loads(match.group(0))

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        path = Path(inputs["input_path"])
        if not path.is_file():
            return ToolResult(success=False, error=f"judge input not found: {path}")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                frames = self._sample_frames(path, int(inputs.get("frame_count", 8)), Path(tmp))
                parsed = self._call_vlm(frames, inputs.get("audio_facts") or "", inputs.get("model", "qwen-vl-max"))
        except Exception as exc:
            return ToolResult(success=False, error=f"video_judge failed: {exc}")

        names = {dim_id: name for dim_id, name, _ in L3_DIMENSIONS}
        dimensions = []
        for item in parsed.get("dimensions") or []:
            dim_id = str(item.get("id") or "")
            if dim_id not in names:
                continue
            try:
                score = float(item.get("score"))
                score = max(0.0, min(10.0, score))
            except (TypeError, ValueError):
                score = 0.0
            dimensions.append({"id": dim_id, "name": names[dim_id], "score": score,
                               "note": str(item.get("note") or "")})
        advisory = {
            "scored": True,
            "summary": str(parsed.get("summary") or ""),
            "dimensions": dimensions,
        }
        output = inputs.get("output_path")
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(advisory, ensure_ascii=False, indent=2))
        return ToolResult(success=True, data=advisory, artifacts=[str(output)] if output else [])
