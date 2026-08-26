"""模板 run 的 sample 渲染制品构建：final_props / edit_decisions / render_plan，并驱动 video_compose。

主链路 compose 路径（遵守 compose-director + render gradient 阶梯）：先 build 三件 canonical
制品（均为 schema-strict），再用 video_compose operation='render'（Remotion / renderer_family
映射到 Explainer）渲染 10-15s sample。不旁路、不静默改 runtime。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.artifact_io import write_artifact_atomic

PIPELINE = "cinematic-fast"


def _load(p: Path) -> dict | None:
    import json
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_final_props(project: Path, script: dict, shots: list[dict], *,
                      narration_mix: str = "assets/audio/sample-mix.mp3",
                      bgm_path: str = "assets/music/bgm-16s.mp3") -> dict:
    """final_props：footage={shot_NN: proxy path}, scenes（按 shot 时长），captions（词级/句级），audio{mix}。
    narration_mix / bgm_path 必须与实际资产一致（不再硬编码 16s，避免 BGM 文件名不匹配导致渲染失败）。"""
    fps = 30
    width, height = 1080, 1920
    footage: dict[str, str] = {}
    scenes = []
    captions = []
    cursor_frames = 0
    for s in shots:
        shot_id = str(s["id"])  # shot-01
        key = shot_id.replace("-", "_")  # shot_01
        dur = float(s["duration_seconds"])
        dur_frames = int(round(dur * fps))
        proxy = f"assets/video/shot-{shot_id.split('-')[-1]}-proxy.mp4"
        footage[key] = proxy
        scenes.append({
            "id": shot_id, "assetId": f"proxy-{shot_id}", "footageKey": key,
            "fromFrame": cursor_frames, "toFrameExclusive": cursor_frames + dur_frames,
            "durationInFrames": dur_frames, "playbackMode": "normal", "playbackRate": 1.0,
            "sourceInSeconds": 0.0, "sourceOutSeconds": dur,
        })
        # caption：该 shot 的 screen_copy（取自 script section）
        text = str(s.get("screen_copy") or "").strip()
        if text:
            captions.append({"startMs": int(round(cursor_frames / fps * 1000)),
                             "endMs": int(round((cursor_frames + dur_frames) / fps * 1000)), "text": text})
        cursor_frames += dur_frames
    audio = {"mix": {
        "narration": {"path": narration_mix, "provider": "doubao",
                      "resource_id": "seed-tts-2.0", "voice": "zh_female_vv_uranus_bigtts"},
        "music": {"path": bgm_path, "profile": "轻快电商节奏", "provider": "suno"},
    }}
    return {
        "version": "1.0", "project_id": project.name, "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-compose-director@1.0", "input_hashes": {"script": "a" * 64},
        "compositionId": "Explainer", "fps": fps, "width": width, "height": height,
        "durationInFrames": cursor_frames, "footage": footage, "scenes": scenes,
        "captions": captions, "audio": audio,
    }


def build_edit_decisions(project: Path, shots: list[dict], render_runtime: str = "remotion", *,
                         narration_mix: str = "assets/audio/sample-mix.mp3",
                         bgm_path: str = "assets/music/bgm-16s.mp3",
                         scene_plan: dict | None = None) -> dict:
    """edit_decisions：引用**实际**资产名（评审 P1-7——不得硬编码 narration-mix/bgm-16s）。

    narration_mix / bgm_path 必须与 build_final_props 一致（真实混音产物 + 按片长裁切的 BGM）。
    transition_in 由 scene_plan 的 transition_recipe_intent 派生（评审 P1-1：不再全员 cut）；
    按 shot.scene_id 键控匹配，避免位置错位。
    """
    bgm_id = Path(bgm_path).stem
    scene_by_id = {str((s or {}).get("id") or ""): s for s in ((scene_plan or {}).get("scenes") or [])}
    cuts = []
    timeline = 0.0
    for s in shots:
        shot_id = str(s["id"])
        dur = float(s["duration_seconds"])
        # 转场意图 → 渲染级规格 → cut 层 token（scene_id 键控；无意图 = cut 硬切）
        scene = scene_by_id.get(str(s.get("scene_id") or "")) or {}
        intent = scene.get("transition_recipe_intent")
        token = "cut"
        if intent:
            try:
                from lib.recipe_router import transition_render_spec

                spec_type = transition_render_spec(str(intent), render_runtime).get("type")
                token = {"flash": "flash", "impact": "impact", "dissolve": "dissolve"}.get(spec_type, "cut")
            except Exception:
                token = "cut"
        cuts.append({
            "id": shot_id, "source": f"assets/video/shot-{shot_id.split('-')[-1]}-proxy.mp4",
            "in_seconds": round(timeline, 3), "out_seconds": round(timeline + dur, 3),
            "speed": 1.0, "layer": "primary", "transition_in": token,
            "transition_out": "cut", "transition_duration": 0.0, "reason": "自有素材镜头",
        })
        timeline += dur
    return {
        "version": "1.0", "cuts": cuts, "render_runtime": render_runtime,
        "renderer_family": "product-reveal", "composition_mode": "templated",
        "caption_render_mode": "remotion_overlay", "caption_source": "artifacts/final_props.json#captions",
        "safe_zone_profile": "douyin_9_16",
        "audio": {"narration": {"segments": [{"asset_id": "sample-mix", "start_seconds": 0.0}]},
                  "music": {"asset_id": bgm_id, "ducking": False, "volume": 1.0}},
        "subtitles": {"enabled": True, "font": "Noto Sans CJK SC", "font_size": 42,
                      "color": "#FFFFFF", "outline_color": "#000000", "position": "bottom-center",
                      "max_words_per_line": 6, "background": "#12100ECC"},
        "metadata": {"durationInFrames": int(round(timeline * 30))},
    }


def build_change_impact(
    project: Path,
    *,
    previous_lock_hash: str,
    current_lock_hash: str,
    route: str = "no_render",
    reasons: list[str] | None = None,
    dirty_scene_ids: list[str] | None = None,
    reopen_creative_lock: bool = False,
    reopen_sample: bool = False,
) -> dict:
    return {
        "version": "1.0", "project_id": project.name, "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-edit-director@1.0",
        "input_hashes": {"production_lock": current_lock_hash},
        "previous_lock_hash": previous_lock_hash, "current_lock_hash": current_lock_hash,
        "route": route, "reasons": reasons or [], "dirty_scene_ids": dirty_scene_ids or [],
        "reopen_creative_lock": reopen_creative_lock, "reopen_sample": reopen_sample,
    }


def build_render_plan(project: Path, *, mode: str, total_frames: int, audio_path: Path, profile: str = "tiktok") -> dict:
    if mode == "sample":
        plan = {"mode": "sample", "profile": profile,
                "sample": {"startFrame": 0, "endFrameExclusive": total_frames, "scale": 0.5, "qaMode": "quick"}}
    elif mode == "window":
        plan = {"mode": "window", "profile": profile,
                "window": {"startFrame": 0, "endFrameExclusive": min(total_frames, 120), "scale": 0.5}}
    elif mode == "still":
        plan = {"mode": "still", "profile": profile,
                "still": {"frames": [0], "totalFrames": total_frames, "scale": 0.5}}
    else:
        plan = {"mode": mode, "profile": profile}
    plan.update({
        "version": "1.0", "project_id": project.name, "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-compose-director@1.0", "input_hashes": {},
        "previous_timeline_hash": "a" * 64, "current_timeline_hash": "b" * 64,
        "audio": {"path": audio_path.name, "sha256": _sha256(audio_path)},
        "output_path": f"renders/sample-v1.mp4",
    })
    return plan
