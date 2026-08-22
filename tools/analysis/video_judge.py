"""L3 creative-quality VLM judge (Design_Review D3 + Autoresearch §2.3).

Samples uniform frames from a rendered video and asks a DashScope Qwen-VL model
to score the rubric dimensions on a 0-10 scale with a short reason each.

Fail-closed (评审 #2)：非法分数（非数值 / 超出 [0,10]）直接拒绝该次评分，
必评维度缺失直接失败，绝不静默钳制或降级。rubric 感知：
`l3-v1.0`（旧项目 advisory）与 `ecommerce-remix-v1.0`（Autoresearch 优化
门禁）各有固定维度集；rubric_version 不一致的报告不可比较。
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

# Autoresearch ecommerce-remix-v1.0（Autoresearch_Video_Remix_Integration_
# Design_2026-08-23.md §2.1）：权重由 optimization_policy 声明，judge 只评分。
REMIX_DIMENSIONS = [
    ("hook_clarity", "Hook Clarity", "前 1-3 秒钩子是否清晰"),
    ("reference_mechanism_fidelity", "Reference Mechanism Fidelity", "是否复刻参考片的有效机制而非像素"),
    ("product_evidence", "Product Evidence", "产品证明是否充分、及时、可信"),
    ("rhythm_pacing", "Rhythm Pacing", "镜头密度、切点和节奏"),
    ("visual_coherence", "Visual Coherence", "构图、裁切、转场和连续性"),
    ("caption_readability", "Caption Readability", "字幕可读性和安全区"),
    ("audio_quality", "Audio Quality", "旁白、BGM、ducking 和响度"),
    ("commercial_originality", "Commercial Originality", "商业表达的差异化和原创边界"),
]

RUBRICS = {
    "l3-v1.0": L3_DIMENSIONS,
    "ecommerce-remix-v1.0": REMIX_DIMENSIONS,
}


def _rubric_prompt(dimensions: list[tuple[str, str, str]]) -> str:
    lines = [
        f"{index}. {dim_id} {name}：{description}"
        for index, (dim_id, name, description) in enumerate(dimensions, start=1)
    ]
    return (
        "你是电商短视频创意质量评审。按以下维度给这段视频打分（0-10，可保留一位小数），每维用一句中文说明理由：\n"
        + "\n".join(lines)
        + '\n\n只输出 JSON，不要多余文字，格式：\n{"dimensions":[{"id":"hook_clarity","score":8.5,"note":"..."}, ...], "summary":"一句话总体评价"}'
    )


def _parse_dimensions(parsed: Any, rubric: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Strict, fail-closed parse: every required dimension must carry a numeric
    score in [0, 10]; anything else raises instead of being clamped/skipped."""
    names = {dim_id: name for dim_id, name, _ in rubric}
    items = parsed.get("dimensions") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("VLM 输出缺少 dimensions 数组")
    by_id: dict[str, tuple[float, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        dim_id = str(item.get("id") or "")
        if dim_id not in names:
            continue  # rubric 之外的额外维度：容忍，不采用
        if dim_id in by_id:
            raise RuntimeError(f"VLM 输出重复维度 {dim_id}，拒绝该次评分")
        raw = item.get("score")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise RuntimeError(
                f"维度 {dim_id} 分数非法（{raw!r}），拒绝该次评分（fail-closed）"
            )
        score = float(raw)
        if score < 0.0 or score > 10.0:
            raise RuntimeError(
                f"维度 {dim_id} 分数 {score} 超出 [0, 10]，拒绝该次评分（fail-closed）"
            )
        by_id[dim_id] = (score, str(item.get("note") or ""))
    missing = [dim_id for dim_id, _, _ in rubric if dim_id not in by_id]
    if missing:
        raise RuntimeError(
            f"VLM 缺少必评维度：{', '.join(missing)}（fail-closed）"
        )
    return [
        {"id": dim_id, "name": names[dim_id], "score": score, "note": note}
        for dim_id, _, _ in rubric
        for score, note in (by_id[dim_id],)
    ]


class VideoJudge(BaseTool):
    name = "video_judge"
    version = "0.2.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "dashscope"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API
    dependencies = []
    install_instructions = "Set DASHSCOPE_API_KEY to call Qwen-VL for the L3 judge."
    agent_skills = ["video-understand"]
    best_for = [
        "L3 creative quality scoring for e-commerce short videos",
        "Autoresearch optimization gate dimensions (ecommerce-remix-v1.0)",
    ]
    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {"type": "string"},
            "output_path": {"type": "string"},
            "project_id": {"type": "string"},
            "scope": {"enum": ["sample", "final"]},
            "rubric_version": {"type": "string", "default": "l3-v1.0",
                               "description": "l3-v1.0（advisory）/ ecommerce-remix-v1.0（Autoresearch 门禁）"},
            "frame_count": {"type": "integer", "default": 8, "minimum": 2, "maximum": 16},
            "model": {"type": "string", "default": "qwen-vl-max"},
            "seed": {"type": "integer", "description": "随机种子（§2.3 要求记录随机性）"},
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

    def _call_vlm(
        self,
        frames: list[Path],
        audio_facts: str,
        model: str,
        rubric_version: str,
        seed: int | None,
    ) -> dict[str, Any]:
        import os
        import requests
        api_key = os.environ["DASHSCOPE_API_KEY"]
        rubric = RUBRICS[rubric_version]
        content: list[dict[str, Any]] = [
            {"type": "text", "text": _rubric_prompt(rubric)},
        ]
        if audio_facts:
            content.append({"type": "text", "text": f"音频事实：{audio_facts}"})
        for frame in frames:
            data_url = "data:image/jpeg;base64," + base64.b64encode(frame.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        request_body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
        }
        if seed is not None:
            request_body["seed"] = int(seed)
        resp = requests.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=request_body,
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
        rubric_version = str(inputs.get("rubric_version", "l3-v1.0"))
        if rubric_version not in RUBRICS:
            return ToolResult(success=False, error=f"未知 rubric_version: {rubric_version}")
        model = str(inputs.get("model", "qwen-vl-max"))
        seed = inputs.get("seed")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                frames = self._sample_frames(path, int(inputs.get("frame_count", 8)), Path(tmp))
                parsed = self._call_vlm(
                    frames, inputs.get("audio_facts") or "", model, rubric_version,
                    int(seed) if seed is not None else None,
                )
                dimensions = _parse_dimensions(parsed, RUBRICS[rubric_version])
        except Exception as exc:
            return ToolResult(success=False, error=f"video_judge failed: {exc}")

        advisory = {
            "scored": True,
            "summary": str(parsed.get("summary") or ""),
            "dimensions": dimensions,
        }
        output = inputs.get("output_path")
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(advisory, ensure_ascii=False, indent=2))
        data: dict[str, Any] = {
            **advisory,
            "rubric_version": rubric_version,
            "model": model,
            "judge_version": "video_judge-0.2.0",
        }
        if seed is not None:
            data["seed"] = int(seed)
        return ToolResult(success=True, data=data, artifacts=[str(output)] if output else [])
