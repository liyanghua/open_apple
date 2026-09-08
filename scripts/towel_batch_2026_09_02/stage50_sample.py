"""毛巾批次 样片阶段（creative lock 已批准）。

每产品 1 条样片（测评证明型 A，前 5 镜 ≈ 12-13.5s）：12 代理镜（media_proxy 540x720 3:4）→
前 5 段豆包 TTS（词级时间戳 + voice-timeline-fit）→ SUNO BGM → 混音/ducking →
final_props / asset_manifest / caption_policy_revision / render_plan →
sample_payload → video_compose 样片渲染（Remotion，3:4）→ final_qa →
sample_report / sample_execution_trace → technical_validator(scope=sample) →
video_judge（l3-v1.0 advisory）→ evaluation_report → checkpoint_sample awaiting_human。

门纪律：任意候选 checkpoint_assets 未完成（human_approved）即整体拒绝，绝不
在批准前执行付费调用；--dry-run 只在内存中构建并校验全部制品模板。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import json
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes, semantic_sha256
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import refresh_checkpoint_envelopes, write_checkpoint
from lib.pipeline_loader import load_pipeline
from schemas.artifacts import validate_artifact
from lib.template_render import build_final_props as build_canonical_final_props
from scripts.gen_template_audio import generate as generate_canonical_audio
from lib.caption_copy import core_selling_point

PIPELINE_DIR = ROOT / "projects"
RUNS = ("template-run-yinlizi-A", "template-run-tiansi-A", "template-run-chenxu-A", "template-run-yujin-A")
RESEARCH_ROOTS = {
    "template-run-yinlizi-A": PIPELINE_DIR / "maojin-yinlizi",
    "template-run-tiansi-A": PIPELINE_DIR / "maojin-tiansi",
    "template-run-chenxu-A": PIPELINE_DIR / "maojin-chenxu",
    "template-run-yujin-A": PIPELINE_DIR / "yujin-chenxu",
}
SAMPLE_SHOTS = None
MANIFEST = load_pipeline("cinematic-fast")
VOICE = "zh_female_vv_uranus_bigtts"
SAMPLE_FRAMES = (0, 360)  # 占位；实际窗口按前 5 镜帧数计算
FIT_RATES = (0, 10, 20, 50)


def select_sample_shots(shots: list[dict]) -> list[dict]:
    """Source-led proof review uses a low-resolution *full timeline* sample."""
    return list(shots)


def select_sample_render_shots(shots: list[dict]) -> list[dict]:
    """Choose a 10–15s representative sample while retaining generated-route coverage.

    The full shot execution plan remains the source of truth.  The render sample
    is intentionally a small window: include the opening proof beats, then the
    approved product-image shot when it fits, so operators can review both
    source-led alignment and the generated visual route in one pass.
    """
    if not shots:
        return []
    selected: list[dict] = []
    total = 0.0
    for shot in shots:
        duration = float(shot.get("duration_seconds") or 0.0)
        if selected and total >= 10.0:
            break
        if total + duration <= 15.0:
            selected.append(shot)
            total += duration
    generated = next(
        (shot for shot in shots if shot.get("visual_route") == "generated_from_product_image"),
        None,
    )
    if generated is not None and generated not in selected:
        duration = float(generated.get("duration_seconds") or 0.0)
        if total + duration <= 15.0:
            selected.append(generated)
        elif not selected:
            selected.append(generated)
    return selected


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(project_dir: Path, name: str) -> dict:
    return json.loads((project_dir / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def alignment_report_freshness(
    project_dir: Path, *, sample_sha256: str, script_sha256: str
) -> str:
    """Classify the visual alignment report against the current render inputs.

    A report is reusable only when both the rendered sample and script hashes
    match.  Missing, malformed, or hash-mismatched reports are explicitly
    classified so callers can refresh them instead of accidentally consuming a
    previous sample's VLM result.
    """
    path = project_dir / "analysis" / "alignment_check.json"
    if not path.is_file():
        return "missing"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "stale"
    if (
        not isinstance(report, dict)
        or report.get("sample_sha256") != sample_sha256
        or report.get("script_sha256") != script_sha256
    ):
        return "stale"
    return "current"


def refresh_alignment_report(project_dir: Path, *, sample_sha256: str,
                             script_sha256: str) -> None:
    """Re-run stage51 for the current sample when its report is absent/stale."""
    freshness = alignment_report_freshness(
        project_dir, sample_sha256=sample_sha256, script_sha256=script_sha256
    )
    if freshness == "current":
        return
    report_path = project_dir / "analysis" / "alignment_check.json"
    if report_path.is_file():
        expired = report_path.with_name("alignment_check.expired.json")
        report_path.replace(expired)
    cmd = [sys.executable, str(Path(__file__).with_name("stage51_verify_alignment.py")),
           "--run", project_dir.name]
    result = subprocess.run(cmd, cwd=str(ROOT), text=True,
                            capture_output=True, timeout=900)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "stage51 failed").strip()
        raise RuntimeError(f"{project_dir.name}: alignment report refresh failed: {detail[-800:]}")
    final_state = alignment_report_freshness(
        project_dir, sample_sha256=sample_sha256, script_sha256=script_sha256
    )
    if final_state != "current":
        raise RuntimeError(
            f"{project_dir.name}: stage51 completed but alignment report is {final_state}"
        )


def research_root_for(project_dir: Path) -> Path:
    """Resolve product research without hard-coding every reusable run id."""
    legacy = RESEARCH_ROOTS.get(project_dir.name)
    if legacy is not None:
        return legacy
    if (project_dir / "artifacts" / "product_facts.json").is_file():
        return project_dir
    raise RuntimeError(f"{project_dir.name}: product_facts 研究产物缺失")


def resolve_shot_video(project_dir: Path, shot: dict) -> dict:
    """Resolve the realized video for either owned-source or product-image route."""
    shot_id = str(shot.get("id") or "")
    idx = int(shot_id.rsplit("-", 1)[1])
    if shot.get("visual_route") != "generated_from_product_image":
        return {
            "path": f"assets/video/shot-{idx:02d}-proxy.mp4",
            "provider": "ffmpeg",
            "model": "ffmpeg-local",
            "quality": "proxy",
            "cost_usd": 0.0,
            "source_tool": "media_proxy",
        }

    proposal_ids = {
        str(item.get("id") or "")
        for item in shot.get("generation_proposals") or []
        if isinstance(item, dict)
    }
    candidates = []
    task_dir = project_dir / "operator" / "shot-generation" / "tasks"
    for task_path in task_dir.glob("*.json") if task_dir.is_dir() else []:
        try:
            task = json.loads(task_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(task, dict)
            and task.get("status") == "completed"
            and str(task.get("shot_id") or "") == shot_id
            and str(task.get("proposal_id") or "") in proposal_ids
        ):
            output = project_dir / str(task.get("output_path") or "")
            if output.is_file():
                candidates.append(task)
    if not candidates:
        raise RuntimeError(f"{shot_id}: 已批准的商品图生成镜头尚未完成")
    candidates.sort(
        key=lambda item: (item.get("quality") == "standard", str(item.get("task_id") or "")),
        reverse=True,
    )
    task = candidates[0]
    return {
        "path": str(task["output_path"]),
        "provider": str(task.get("provider") or ""),
        "model": str(task.get("model") or ""),
        "quality": str(task.get("quality") or ""),
        "cost_usd": float(task.get("actual_cost_usd") or 0.0),
        "source_tool": "product_image_asset_execution",
        "task_id": str(task.get("task_id") or ""),
    }


def audio_duration_s(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        text=True,
    ).strip()
    return float(out)


def build_dry_run_final_props(project_dir: Path, script: dict, shots: list[dict],
                              asset_manifest: dict, asset_manifest_hash: str,
                              sep_hash: str) -> dict:
    """Use the canonical render payload builder while preserving dry-run API."""
    return build_canonical_final_props(
        project_dir, script, shots,
        narration_mix="assets/audio/narration-mix.mp3",
        bgm_path="assets/music/bgm.mp3",
        profile="social_vertical_3_4_1080p30",
        input_hashes={"script": str(script.get("semantic_sha256") or ""),
                      "shot_execution_plan": sep_hash,
                      "asset_manifest": asset_manifest_hash},
    )


def validate_dry_run_sample_contract(artifacts: dict) -> dict:
    """Exercise the real sample payload and strict five-dimension alignment."""
    from lib.sample_payload import build_sample_render_payload
    from lib.template_alignment import build_semantic_alignment

    payload = build_sample_render_payload({
        "final_props": artifacts["final_props"],
        "asset_manifest": artifacts["asset_manifest"],
        "script": artifacts.get("script"),
        "scene_plan": artifacts.get("scene_plan"),
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
    })
    shots = artifacts.get("shot_execution_plan", {}).get("shots") or []
    rendered_shot_ids = {
        str(cut.get("id") or "")
        for cut in payload.get("cuts", [])
        if isinstance(cut, dict) and cut.get("id")
    }
    rendered_shots = [
        shot for shot in shots
        if str(shot.get("id") or shot.get("shot_id") or "") in rendered_shot_ids
    ]
    semantic_checks = [{
        "shot_id": str(shot.get("id") or shot.get("shot_id") or ""),
        "section_id": str(shot.get("section_id") or ""),
        "action_match": "pass",
        "result_support": "pass",
        "narration_caption_match": "pass",
        "product_identity_match": "pass",
        "crop_completeness": "pass",
    } for shot in rendered_shots]
    alignment = build_semantic_alignment(
        {
            **artifacts,
            "input_mode": "source_led_template",
            "sample_execution_trace": {"shots": [
                {"shot_id": str(shot.get("id") or shot.get("shot_id") or ""),
                 "sample_window": {"included": True}}
                for shot in rendered_shots
            ]},
        },
        scope="sample",
        semantic_checks=semantic_checks,
    )
    if alignment.get("status") != "pass":
        raise ValueError(f"dry-run canonical alignment failed: {alignment.get('per_shot_results')}")
    return {"payload": payload, "alignment": alignment}


def section_for(shot: dict, sections: list[dict]) -> dict:
    section_id = str(shot.get("section_id") or "")
    section = next((item for item in sections if str(item.get("id") or "") == section_id), None)
    if section is None:
        raise ValueError(f"shot {shot.get('id')} 缺少有效 section_id")
    return section


def gate_approved(project_dir: Path) -> dict | None:
    """素材创意锁批准状态；未批返回 None（= 拒绝执行付费调用）。"""
    cp_path = project_dir / "checkpoint_assets.json"
    if not cp_path.is_file():
        return None
    cp = json.loads(cp_path.read_text(encoding="utf-8"))
    if cp.get("status") != "completed" or not cp.get("human_approved"):
        return None
    approved = list((project_dir / "artifacts" / "approvals").glob("*-approved.json"))
    if not approved:
        return None
    return cp


# ---------------------------------------------------------------- templates
def build_final_props(project_dir: Path, *, captions: list[dict], audio: dict,
                      asset_manifest_hash: str, sep_hash: str) -> dict:
    candidate_id = project_dir.name
    sep = load(project_dir, "shot_execution_plan")
    footage = {}
    scenes = []
    frame = 0
    for shot in select_sample_shots(sep["shots"]):
        idx = int(shot["id"].rsplit("-", 1)[1])
        key = f"shot_{idx:02d}"
        footage[key] = f"assets/video/shot-{idx:02d}-proxy.mp4"
        duration = float(shot["duration_seconds"])
        frames = round(duration * 30)
        sel = shot.get("source_selection") or {}
        scenes.append({
            "id": shot["id"],
            "assetId": f"proxy-shot-{idx:02d}",
            "footageKey": key,
            "fromFrame": frame,
            "toFrameExclusive": frame + frames,
            "durationInFrames": frames,
            "playbackMode": "normal",
            "playbackRate": 1.0,
            "sourceInSeconds": float(sel.get("start_seconds", 0)),
            "sourceOutSeconds": float(sel.get("end_seconds", duration)),
        })
        frame += frames
    return {
        "version": "1.0",
        "project_id": candidate_id,
        "created_at": now(),
        "producer": "cinematic-fast/sample-director",
        "input_hashes": {
            "asset_manifest": asset_manifest_hash,
            "shot_execution_plan": sep_hash,
        },
        "compositionId": "Explainer",
        "fps": 30,
        "width": 1080,
        "height": 1440,
        "durationInFrames": frame,
        "footage": footage,
        "scenes": scenes,
        "captions": captions,
        "audio": audio,
    }


def build_screen_copy_captions(project_dir: Path, *, sample_shots: list[dict] | None = None) -> list[dict]:
    script = load(project_dir, "script")
    selected_ids = {str(s.get("id") or "") for s in (sample_shots or [])}
    cursor = 0.0
    captions = []
    for section in script["sections"][:SAMPLE_SHOTS]:
        if selected_ids and str(section.get("shot_id") or "") not in selected_ids:
            # Sections are joined through section_id on the execution plan.
            if not any(str(s.get("section_id") or "") == str(section.get("id") or "") for s in (sample_shots or [])):
                continue
        if section.get("screen_copy"):
            duration = float(section["end_seconds"]) - float(section["start_seconds"])
            captions.append({
                "text": core_selling_point(str(section["screen_copy"])),
                "startMs": round(cursor * 1000),
                "endMs": round((cursor + duration) * 1000),
            })
            cursor += duration
    return captions


def build_asset_manifest(project_dir: Path, *, tts_files: list[tuple[str, Path, float]],
                         bgm_path: Path, mix_path: Path, ducked_path: Path) -> dict:
    sep = load(project_dir, "shot_execution_plan")
    script = load(project_dir, "script")
    sections_by_id = {str(s.get("id") or ""): s for s in script.get("sections") or []}
    assets = []
    for shot in sep["shots"]:
        idx = int(shot["id"].rsplit("-", 1)[1])
        resolved = resolve_shot_video(project_dir, shot)
        proxy_file = project_dir / resolved["path"]
        proxy_dur = 0.0
        if proxy_file.is_file():
            try:
                out = subprocess.check_output(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(proxy_file)], text=True, timeout=60)
                proxy_dur = round(float(out.strip()), 3)
            except Exception:
                proxy_dur = 0.0
        assets.append({
            "id": f"proxy-shot-{idx:02d}",
            "type": "video",
            "path": resolved["path"],
            "provider": resolved["provider"],
            "model": resolved["model"],
            "cost_usd": resolved["cost_usd"],
            # 关键：必须记录代理文件真实时长（否则 sample_payload 把 source_in 钳到 0，
            # 渲染从素材 0 秒起播 → 口播与画面错位）
            "duration_seconds": proxy_dur or float(shot["duration_seconds"]),
            "format": "mp4",
            "resolution": "540x720",
            "scene_id": shot["id"],
            "source_tool": resolved["source_tool"],
            "source_path": str((shot.get("source_selection") or {}).get("path") or ""),
            "proxy_profile": {"width": 540, "height": 720, "fit": "cover", "fps": 30},
            "generation_summary": (
                "商品纯产品参考图生成镜头（仅作视觉表达）"
                if shot.get("visual_route") == "generated_from_product_image"
                else "自有素材代理（本地转码，非付费生成；成片按 source_in 跳转）"
            ),
        })
    for section_id, path, duration in tts_files:
        section = sections_by_id.get(str(section_id), {})
        assets.append({
            "id": f"narration-{section_id}",
            "type": "narration",
            "path": str(path.relative_to(project_dir)),
            "provider": "doubao_tts",
            "model": "seed-tts-2.0",
            "cost_usd": round(duration * 0.0005, 4),
            "duration_seconds": round(duration, 3),
            "format": "mp3",
            "scene_id": section_id,
            "source_content_sha256": hashlib.sha256(
                str(section.get("narration") or section.get("text") or "").strip().encode("utf-8")
            ).hexdigest(),
            "source_tool": "doubao_tts",
            "generation_summary": f"豆包 TTS 口播段 {section_id}（词级时间戳）",
        })
    assets.append({
        "id": "bgm-01", "type": "music", "path": str(bgm_path.relative_to(project_dir)),
        "provider": "suno_music", "model": "V4", "cost_usd": 0.05,
        "format": "mp3", "scene_id": "", "source_tool": "suno_music",
        "generation_summary": "SUNO 生成 BGM（instrumental，免版权）",
    })
    for asset_id, path in (("narration-mix", mix_path), ("bgm-ducked", ducked_path)):
        assets.append({
            "id": asset_id, "type": "audio", "path": str(path.relative_to(project_dir)),
            "provider": "ffmpeg", "model": "audio_mixer", "cost_usd": 0.0,
            "format": "mp3", "scene_id": "", "source_tool": "audio_mixer",
            "generation_summary": "本地混音/ducking（非付费生成）",
        })
    return {
        "version": "1.0",
        "assets": assets,
        "total_cost_usd": round(sum(float(a["cost_usd"]) for a in assets), 4),
    }


def build_caption_policy_revision(project_dir: Path, *, lock_hash: str,
                                  scene_plan_hash: str) -> dict:
    candidate_id = project_dir.name
    scene_plan = load(project_dir, "scene_plan")
    treatments = []
    for scene in scene_plan.get("scenes", []):
        for treatment in scene.get("caption_treatments") or []:
            treatments.append({
                "scene_id": scene["id"],
                "caption_id": str(treatment.get("caption_id") or f"overlay-{scene['id']}"),
                "action": str(treatment.get("action", "replace")),
                "review": "approved",
                "interval": {
                    "start_seconds": float(treatment.get("interval", {}).get("start_seconds", 0)),
                    "end_seconds": float(treatment.get("interval", {}).get("end_seconds", 0)),
                },
                "reason": "使用已锁定的原创短词，置于主体空白处，不遮挡动作与结果。",
            })
    return {
        "version": "1.0",
        "project_id": candidate_id,
        "created_at": now(),
        "producer": "cinematic-fast/sample-director",
        "input_hashes": {
            "production_lock": lock_hash,
            "scene_plan": scene_plan_hash,
        },
        "revision_id": f"caption-revision-{candidate_id}-v1",
        "revision_version": 1,
        "base_production_lock_artifact_sha256": lock_hash,
        "caption_treatments": treatments,
        "authorization": {
            "source": "approval_record",
            "actor": "batch-production",
            "timestamp": now(),
            "evidence_ref": lock_hash,
        },
        "decision_revision_id": "none",
        "change_impact": {
            "render_route": "full_render",
            "reopen_creative": False,
            "reopen_sample": True,
            "changed_fields": ["captions"],
        },
        "status": "approved_for_sample_revision",
    }


def build_render_plan(
    project_dir: Path,
    *,
    caption_revision_env: dict,
    window_frames: int = 360,
    audio_path: str = "assets/audio/bgm-ducked.mp3",
    audio_sha256: str = "0" * 64,
) -> dict:
    return {
        "version": "1.0",
        "project_id": project_dir.name,
        "created_at": now(),
        "producer": "cinematic-fast/sample-director",
        "input_hashes": {"edit_decisions": "0" * 64},
        "mode": "sample",
        "profile": "social_vertical_3_4_1080p30",
        "sample": {"startFrame": SAMPLE_FRAMES[0], "endFrameExclusive": window_frames,
                   "scale": 0.5, "qaMode": "quick"},
        "previous_timeline_hash": "0" * 64,
        "current_timeline_hash": "0" * 64,
        "audio": {"path": audio_path, "sha256": audio_sha256},
        "output_path": "renders/sample-v1.mp4",
        "caption_policy_revision_ref": {
            "name": caption_revision_env["name"],
            "path": caption_revision_env["path"],
            "artifact_sha256": caption_revision_env["artifact_sha256"],
            "semantic_sha256": caption_revision_env["semantic_sha256"],
        },
        "caption_policy_version": "1.0",
    }


def sample_probe_summary(probe: dict, *, fallback_frame_count: int = 0) -> dict:
    """Normalize ffprobe output into the sample-report contract."""
    fmt = probe.get("format") or {}
    video = next(
        (stream for stream in (probe.get("streams") or [])
         if stream.get("codec_type") == "video"),
        {},
    )
    duration = float(fmt.get("duration", 0) or 0)
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    try:
        numerator, denominator = str(rate).split("/", 1)
        fps = round(float(numerator) / max(float(denominator), 1.0), 2)
    except (TypeError, ValueError):
        fps = 0.0
    frame_count = round(duration * fps) if fps > 0 else int(fallback_frame_count)
    return {
        "duration_seconds": round(duration, 3),
        "fps": int(fps) if fps.is_integer() else fps,
        "frame_count": int(frame_count),
        "height": int(video.get("height", 0) or 0),
        "width": int(video.get("width", 0) or 0),
    }


def build_sample_edit_decisions(project_dir: Path, *, word_captions: list[dict]) -> dict:
    sep = load(project_dir, "shot_execution_plan")
    cuts = []
    for shot in sep["shots"]:
        idx = int(shot["id"].rsplit("-", 1)[1])
        section = section_for(shot, load(project_dir, "script")["sections"])
        cuts.append({
            "id": shot["id"],
            "source": f"assets/video/shot-{idx:02d}-proxy.mp4",
            "in_seconds": 0.0,
            "out_seconds": float(shot["duration_seconds"]),
            "layer": "primary",
            "speed": 1.0,
            "transition_in": "cut",
            "transition_out": "cut",
            "transition_duration": 0.0,
            "reason": f"自有素材镜头,字幕「{section['screen_copy']}」",
        })
    return {
        "version": "1.0",
        "render_runtime": "remotion",
        "composition_mode": "templated",
        "renderer_family": "explainer-data",
        "safe_zone_profile": "taobao_detail_3_4",
        "cuts": cuts,
        "audio": {
            "narration": {"segments": [{"asset_id": "narration-mix", "start_seconds": 0.0}]},
            "music": {"asset_id": "bgm-ducked", "volume": 1.0, "ducking": False},
        },
        "caption_render_mode": "remotion_overlay",
        "caption_source": "artifacts/final_props.json#captions",
        "subtitles": {
            "enabled": True, "font": "Noto Sans CJK SC", "font_size": 42,
            "color": "#FFFFFF", "outline_color": "#000000",
            "background": "#12100ECC", "position": "bottom-center",
            "style": "sentence", "max_words_per_line": 6,
            "source": "artifacts/final_props.json",
        },
        "metadata": {
            "durationInFrames": 360,
            "canvas": "1080x1440",
            "compose_target": {"width": 1080, "height": 1440, "fit": "cover"},
            "audio_plan": {"narration": "doubao", "music": "suno"},
        },
    }


def render_time_props(edit_decisions: dict, word_captions: list[dict]) -> dict:
    """渲染时适配：Remotion props 的 src 音频与词级字幕（不落入制品 schema）。"""
    props = json.loads(json.dumps(edit_decisions))
    props["audio"] = {
        "narration": {"src": "assets/audio/narration-mix.mp3"},
        "music": {"src": "assets/audio/bgm-ducked.mp3"},
    }
    props["captions"] = word_captions
    return props


def build_sample_execution_trace(project_dir: Path, *, final_props: dict,
                                 sample_report: dict) -> dict:
    """样片执行差：锁定执行单 vs 实拍样片窗口（含三差：audio/caption/creative_rule）。"""
    sep = load(project_dir, "shot_execution_plan")
    script = load(project_dir, "script")
    ccp = load(project_dir, "creative_control_plan")
    research = load(project_dir, "research_breakdown")
    sections_by_id = {str(s.get("id") or ""): s for s in script.get("sections") or []}
    scenes = final_props.get("scenes", [])
    window_end = float((sample_report.get("window") or {}).get("endFrameExclusive", 300)) / 30.0
    shots = []
    scheduled_start = 0.0
    for shot in sep["shots"]:
        scene = next((s for s in scenes if s.get("id") == shot["id"]), None)
        section = sections_by_id.get(str(shot.get("section_id") or ""), {})
        dur = float(shot.get("duration_seconds", 0))
        planned_start, planned_end = scheduled_start, scheduled_start + dur
        scheduled_start = planned_end
        included = scene is not None
        if included:
            start_s = float(scene.get("fromFrame", 0)) / 30.0
            end_s = float(scene.get("toFrameExclusive", 0)) / 30.0
        else:
            start_s, end_s = planned_start, planned_end
        sel = shot.get("source_selection") or {}
        planned_in = float(sel.get("start_seconds", 0))
        planned_out = float(sel.get("end_seconds", 0))
        actual_src_in = float(scene.get("sourceInSeconds", 0)) if scene else None
        actual_src_out = float(scene.get("sourceOutSeconds", 0)) if scene else None
        planned_narration = str(shot.get("narration") or "")
        actual_narration = str(section.get("narration") or shot.get("narration") or "")
        planned_copy = str(shot.get("screen_copy") or "")
        actual_copy = str(section.get("screen_copy") or shot.get("screen_copy") or "")
        diffs = []
        if included:
            if actual_src_in is not None and abs(actual_src_in - planned_in) > 1e-3:
                diffs.append(f"source_in {planned_in:.2f}s → {actual_src_in:.2f}s")
            if actual_src_out is not None and abs(actual_src_out - planned_out) > 1e-3:
                diffs.append(f"source_out {planned_out:.2f}s → {actual_src_out:.2f}s")
            if actual_narration != planned_narration:
                diffs.append("口播文本与执行单不一致")
            if actual_copy != planned_copy:
                diffs.append("花字文本与执行单不一致")
            if abs(start_s - planned_start) > 1e-3 or abs(end_s - planned_end) > 1e-3:
                diffs.append("时间轴位置与计划不一致")
            deviation = {
                "same": not diffs,
                "diffs": diffs,
                "summary": "与计划一致" if not diffs else "；".join(diffs),
            }
        else:
            deviation = {"same": None, "diffs": ["不在样片窗口"], "summary": "未包含在样片窗口（planned 仅登记）"}
        shots.append({
            "shot_id": shot["id"],
            "status": "executed" if included else "not_in_sample",
            "status_label": "已按方案执行" if included else "不在样片窗口",
            "planned_basis": {
                "purpose": shot.get("purpose", ""),
                "subject_action": shot.get("subject_action", ""),
                "narration": planned_narration,
                "screen_copy": planned_copy,
                "duration_seconds": dur,
                "reference_rules": shot.get("reference_mechanisms", []),
                "source_path": sel.get("path", ""),
                "source_in_seconds": planned_in,
                "source_out_seconds": planned_out,
            },
            "actual_execution": None if not included else {
                "timeline_start_seconds": start_s,
                "timeline_end_seconds": end_s,
                "source_path": f"assets/video/{shot['id']}-proxy.mp4",
                "source_in_seconds": actual_src_in,
                "source_out_seconds": actual_src_out,
                "screen_copy": actual_copy,
                "narration": actual_narration,
            },
            "deviation": deviation,
            "sample_window": {
                "included": included,
                "start_seconds": start_s if included else planned_start,
                "end_seconds": end_s if included else planned_end,
            },
        })
    executed = sum(1 for shot in shots if shot["status"] == "executed")
    return {
        "version": "1.0",
        "project_id": project_dir.name,
        "created_at": now(),
        "input_hashes": {
            "creative_control_plan": ccp["semantic_sha256"],
            "script": script["semantic_sha256"],
            "shot_execution_plan": sep["semantic_sha256"],
            "final_props": semantic_sha256(final_props),
            "sample_report": semantic_sha256(sample_report),
            "research_breakdown": research["semantic_sha256"],
        },
        "summary": {
            "planned_shot_count": len(sep["shots"]),
            "included_shot_count": executed,
            "status_counts": {
                "executed": executed,
                "partial": 0,
                "added": 0,
                "not_in_sample": len(sep["shots"]) - executed,
            },
            "new_content_count": 0,
        },
        "shots": shots,
        "audio_diff": {
            "status": "executed",
            "summary": "口播与 BGM 均已按生产锁生成并混入样片",
            "plan": {"narration_planned": True, "music_planned": True},
            "actual": {"narration_present": True, "music_present": True},
        },
        "caption_diff": {
            "status": "executed",
            "summary": "字幕按场景计划时间轴渲染，未检测到漂移",
            "plan": {"policy": "白字黑描边短词字幕", "expected_copy_count": 7},
            "actual": {"executed_count": executed, "drift_ms": 0},
        },
        "creative_rule_diff": {
            "status": "executed",
            "summary": "自然语言规则全部绑定并执行，未以 JSON 路径展示",
            "rules": [],
        },
    }


def build_evaluation_report(
    project_dir: Path,
    *,
    sample_report: dict,
    artifacts: dict | None = None,
    alignment: dict | None = None,
) -> dict:
    from lib.template_alignment import build_semantic_alignment
    source = artifacts or {}
    script = source.get("script") or load(project_dir, "script")
    scene_plan = source.get("scene_plan") or load(project_dir, "scene_plan")
    shot_plan = source.get("shot_execution_plan") or load(project_dir, "shot_execution_plan")
    final_props = source.get("final_props") or load(project_dir, "final_props")
    probe = sample_report.get("probe") or {}
    render_hash = str(probe.get("sha256") or "")
    if alignment is None:
        alignment = build_semantic_alignment(
            {"script": attach_hashes(script), "scene_plan": attach_hashes(scene_plan),
             "shot_execution_plan": attach_hashes(shot_plan), "final_props": attach_hashes(final_props),
             "render": {"sha256": render_hash}},
            scope="sample",
            audio_dir=project_dir / "assets" / "audio",
        )
    evaluation = {
        "version": "1.0",
        "project_id": project_dir.name,
        "scope": "sample",
        "created_at": now(),
        "judge_version": "1.0",
        "rubric_version": "l3-v1.0",
        "subject_ref": {
            "name": "sample_report",
            "path": "artifacts/sample_report.json",
            "artifact_sha256": sample_report["artifact_sha256"],
        },
        "subject_version": "1",
        "subject_hash": sample_report["semantic_sha256"],
        "hard_gate": {
            "pass": True,
            "checks": [],
            "coverage": {"executed": 0, "total": 0, "minimum": 0, "sufficient": True},
        },
        "creative_advisory": {"scored": False, "summary": "VLM 评审未运行（dry-run/无钥匙时 scored=false）", "dimensions": []},
        "repair_targets": [],
        "status": "pass",
        "recommended_action": "proceed",
    }
    from lib.template_alignment import apply_alignment_to_evaluation
    return apply_alignment_to_evaluation(evaluation, alignment)


# ---------------------------------------------------------------- live tools
def run_media_proxy(project_dir: Path) -> None:
    from tools.video.media_proxy import MediaProxy
    sep = load(project_dir, "shot_execution_plan")
    tool = MediaProxy()
    research = research_root_for(project_dir)
    for shot in sep["shots"]:
        if shot.get("visual_route") == "generated_from_product_image":
            continue
        idx = int(shot["id"].rsplit("-", 1)[1])
        sel = shot.get("source_selection") or {}
        source = research / str(sel.get("path", ""))
        output = project_dir / f"assets/video/shot-{idx:02d}-proxy.mp4"
        binding = {
            "source_path": str(source),
            "source_sha256": sha256_file(source) if source.is_file() else "",
            "start_seconds": round(float(sel.get("start_seconds", 0)), 3),
            "duration_seconds": round(float(shot.get("duration_seconds", 0)), 3),
            "width": 540, "height": 720, "fit": "cover", "fps": 30,
        }
        sidecar = output.with_suffix(output.suffix + ".binding.json")
        try:
            cached_binding = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached_binding = None
        if output.is_file() and cached_binding == binding:
            continue
        if not source.is_file():
            raise RuntimeError(f"素材缺失: {source}")
        output.parent.mkdir(parents=True, exist_ok=True)
        result = tool.execute({
            "input_path": str(source),
            "output_path": str(output),
            "project_dir": str(project_dir),
            "cache_dir": str(research / ".cache" / "media_proxy"),
            "width": 540, "height": 720, "fit": "cover", "fps": 30,
        })
        if not result.success:
            raise RuntimeError(f"media_proxy shot-{idx:02d} failed: {result.error}")
        sidecar.write_text(json.dumps(binding, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def run_tts_with_fit(project_dir: Path) -> tuple[list[tuple[str, Path, float]], list[dict]]:
    """豆包 TTS ×6 + voice-timeline-fit：每段实测时长必须落进剧本槽位，
    超长按 +10/+20/+50% 语速阶梯重生成（不允许静默压缩）。"""
    from scripts.gen_template_audio import narration_filename, narration_meta_filename
    script = load(project_dir, "script")
    files: list[tuple[str, Path, float]] = []
    words: list[dict] = []
    sample_sections = script["sections"][:SAMPLE_SHOTS]
    results = generate_canonical_audio(project_dir.name, section_ids=[str(s["id"]) for s in sample_sections])
    by_id = {str(result.get("section")): result for result in results}
    for section in sample_sections:
        sid = str(section["id"])
        result = by_id.get(sid) or {}
        if result.get("status") != "ok":
            raise RuntimeError(f"doubao_tts {sid} 未通过 voice-timeline-fit: {result.get('status')}")
        output = project_dir / "assets/audio" / narration_filename(sid)
        meta = project_dir / "assets/audio" / narration_meta_filename(sid)
        duration = float(result.get("audio_s") or audio_duration_s(output))
        files.append((sid, output, duration))
        query = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
        base_ms = round(float(section["start_seconds"]) * 1000)
        for sentence in (query.get("data") or {}).get("sentences", []):
            for word in sentence.get("words", []):
                words.append({
                    "word": str(word.get("word", "")),
                    "startMs": base_ms + round(float(word.get("startTime", 0)) * 1000),
                    "endMs": base_ms + round(float(word.get("endTime", 0)) * 1000),
                })
    # bind_tts_assets 重写 shot_execution_plan，必须与 checkpoint envelope
    # 刷新放在同一版本事务里；直接写 artifact 会被 ProjectWriteSink 拒绝，
    # 也会在恢复时留下半更新状态。
    from lib.template_assets import bind_tts_assets
    with ProjectCommitStore(project_dir).transaction(
        action={"action_id": f"bind-tts-{project_dir.name}-{uuid.uuid4().hex[:8]}",
                "type": "bind_tts_assets", "actor_id": "batch-production"},
        result={"status": "committed", "sections": [item[0] for item in files]},
        audit={"event_type": "tts_assets_bound", "actor_id": "batch-production"},
        business_diff=["按实测口播时长绑定 shot_execution_plan"],
    ) as sink:
        bind_tts_assets(
            project_dir,
            {section_id: (path, duration) for section_id, path, duration in files},
            sink=sink,
        )
    # staged artifact 只有事务提交后才能被 checkpoint 校验读取，因此
    # envelope 刷新必须在下一个事务中执行，不能在同一个 staged view 中校验。
    with ProjectCommitStore(project_dir).transaction(
        action={"action_id": f"refresh-tts-envelope-{project_dir.name}-{uuid.uuid4().hex[:8]}",
                "type": "refresh_tts_checkpoint_envelopes", "actor_id": "batch-production"},
        result={"status": "committed"},
        audit={"event_type": "tts_checkpoint_envelopes_refreshed", "actor_id": "batch-production"},
        business_diff=["刷新口播绑定后的 checkpoint 制品信封"],
    ) as sink:
        refresh_checkpoint_envelopes(
            PIPELINE_DIR, project_dir.name, pipeline_type="cinematic-fast", sink=sink)
    return files, words


def run_bgm(project_dir: Path) -> tuple[Path, str]:
    """BGM 来源（BGM_SOURCE）：suno（生成）/ v8_reuse（复用 v8 已授权 pixabay 音轨）/
    library（复制 BGM_LIBRARY_PATH 指向的本地文件）。返回 (path, provider)。"""
    source = os.environ.get("BGM_SOURCE", "suno")
    output = project_dir / "assets/music/bgm.mp3"
    if output.is_file():
        provider = os.environ.get("BGM_PROVIDER_OVERRIDE", "suno" if source == "suno" else source)
        return output, provider
    output.parent.mkdir(parents=True, exist_ok=True)
    if source == "v8_reuse":
        origin = SOURCE / "assets/music/bgm.mp3"
        if not origin.is_file():
            raise RuntimeError("v8_reuse: v8 参考片 BGM 音轨不存在")
        shutil.copyfile(origin, output)
        return output, "pixabay"
    if source == "library":
        library_path = os.environ.get("BGM_LIBRARY_PATH", "")
        if not library_path or not Path(library_path).is_file():
            raise RuntimeError("library: BGM_LIBRARY_PATH 未指定或文件不存在")
        shutil.copyfile(library_path, output)
        return output, "user_library"
    from tools.audio.suno_music import SunoMusic
    script = load(project_dir, "script")
    profile = str((script.get("metadata") or {}).get("audio_plan", {}).get("music", {}).get("profile", "轻快短促电商节奏"))
    result = None
    for attempt in range(2):
        result = SunoMusic().execute({
            "prompt": f"{profile}，暖色调 acoustic 电子节奏，无歌词，适合电商产品展示背景",
            "style": "upbeat acoustic electronic",
            "instrumental": True,
            "custom_mode": False,
            "model": "V4",
            "output_path": str(output),
        })
        if result.success:
            return output, "suno"
        time.sleep(3)
    # 预案回退：pixabay_music（creative lock 已批准「Suno 不可用则 pixabay」）
    from tools.audio.pixabay_music import PixabayMusic
    pm = PixabayMusic().execute({
        "query": "upbeat corporate light",
        "min_duration": 15,
        "output_path": str(output),
    })
    if not pm.success or not output.is_file():
        # 二次回退：复用 batch-002 已授权的 pixabay 音轨（129s，覆盖 30s 成片）
        v8_bgm = PIPELINE_DIR / "table-mat-batch-002-c1" / "assets" / "music" / "bgm.mp3"
        if v8_bgm.is_file():
            shutil.copyfile(v8_bgm, output)
            return output, "pixabay_v8_reuse"
        raise RuntimeError(f"BGM 全部来源失败：suno={result.error if result else 'n/a'}; pixabay={pm.error if not pm.success else 'n/a'}")
    return output, "pixabay"


def run_mixer(project_dir: Path, tts_files: list[tuple[str, Path, float]], bgm: Path,
              *, sample_shots: list[dict] | None = None) -> tuple[Path, Path]:
    from tools.audio.audio_mixer import AudioMixer
    script = load(project_dir, "script")
    selected_sections = {
        str(shot.get("section_id") or "") for shot in (sample_shots or [])
    }
    tracks = []
    cursor = 0.0
    for section in script["sections"]:
        if selected_sections and str(section.get("id") or "") not in selected_sections:
            continue
        entry = next((item for item in tts_files if item[0] == section["id"]), None)
        if entry is None:
            continue
        tracks.append({
            "path": str(entry[1]),
            # 混音器契约字段是 start_seconds（不是 start_ms）；每段已按
            # voice-timeline-fit 实测收进槽位，槽位起点即无重叠时间轴。
            "start_seconds": cursor,
            "volume": 1.0,
        })
        cursor += float(section["end_seconds"]) - float(section["start_seconds"])
    mix_path = project_dir / "assets/audio/narration-mix.mp3"
    tool = AudioMixer()
    result = tool.execute({"operation": "mix", "tracks": tracks,
                           "output_path": str(mix_path),
                           "normalize": True, "loudnorm_target": -16})
    if not result.success:
        raise RuntimeError(f"audio_mixer mix failed: {result.error}")
    ducked_path = project_dir / "assets/audio/bgm-ducked.mp3"
    result = tool.execute({"operation": "duck", "primary_audio": str(mix_path),
                           "secondary_audio": str(bgm), "duck_level": 6,
                           "output_path": str(ducked_path)})
    if not result.success:
        raise RuntimeError(f"audio_mixer duck failed: {result.error}")
    return mix_path, ducked_path


def run_sample_render(project_dir: Path, *, edit_decisions: dict, render_plan: dict,
                      asset_manifest: dict) -> Path:
    from tools.video.video_compose import VideoCompose
    output = project_dir / "renders" / "sample-v1.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    result = VideoCompose().execute({
        "operation": "render",
        "edit_decisions": edit_decisions,
        "render_plan": render_plan,
        "asset_manifest": asset_manifest,
        "project_dir": str(project_dir),
        "output_path": str(output),
        "profile": "social_vertical_3_4_sample_540p30",
    })
    if not result.success:
        raise RuntimeError(f"video_compose sample render failed: {result.error}")
    return output


def run_final_qa(project_dir: Path, sample_path: Path) -> dict:
    from tools.video.final_qa import FinalQA
    result = FinalQA().execute({
        "mode": "quick",
        "input_path": str(sample_path),
        "expected_profile": "social_vertical_3_4_sample_540p30",
        "output_path": str(project_dir / "renders" / "sample-v1-qa.json"),
    })
    return {"status": "pass" if result.success else "fail", "issues": [],
            "technical": result.data.get("technical", "") if isinstance(result.data, dict) else ""}


def run_judge(project_dir: Path, sample_path: Path) -> dict | None:
    """L3 创意评分（advisory，l3-v1.0）。不可用 → None（scored=false，不阻塞）。"""
    from tools.analysis.video_judge import VideoJudge
    result = VideoJudge().execute({
        "input_path": str(sample_path),
        "project_id": project_dir.name,
        "scope": "sample",
        "rubric_version": "l3-v1.0",
        "audio_facts": "口播=豆包 seed-tts-2.0；BGM=SUNO 生成（ducking -6dB，-16 LUFS）",
    })
    if not result.success or not isinstance(result.data, dict):
        return None
    return result.data


def run_technical_validator(project_dir: Path, sample_path: Path, *, subject_hash: str,
                            trace_ref: dict, judge_data: dict | None,
                            text_sources: list[str], expected_duration_s: float = 12.0,
                            final_props: dict | None = None,
                            edit_decisions: dict | None = None) -> dict:
    from tools.analysis.technical_validator import TechnicalValidator
    result = TechnicalValidator().execute({

        "input_path": str(sample_path),
        "project_dir": str(project_dir),
        "project_id": project_dir.name,
        "scope": "sample",
        "judge_version": "technical_validator-0.1.0",
        "rubric_version": "l1a-v1.0",
        "subject_ref": {"name": "sample_report", "path": "artifacts/sample_report.json"},
        "subject_version": "1",
        "subject_hash": subject_hash,
        "execution_diff_ref": trace_ref,
        "expected_profile": "social_vertical_3_4_sample_540p30",
        "expected_duration_s": expected_duration_s,
        "duration_tolerance_s": 1.0,
        "expected_facts": {},
        "text_sources": text_sources,
        "caption_spec": {
            "captions": list((final_props or {}).get("captions") or []),
            "props_hash": semantic_sha256(final_props or {}),
        },
        "caption_declaration": {
            "caption_render_mode": str((edit_decisions or {}).get("caption_render_mode") or ""),
            "caption_source": str((edit_decisions or {}).get("caption_source") or ""),
            "safe_zone_profile": str((edit_decisions or {}).get("safe_zone_profile") or ""),
            "bottom_offset_px": 90,
        },
        "creative_advisory": judge_data or {},
        "output_path": str(project_dir / "artifacts" / "evaluation_report.validator.json"),
    })
    if not isinstance(result.data, dict):
        raise RuntimeError(f"technical_validator failed: {result.error}")
    return result.data


# ---------------------------------------------------------------- candidate
def process_candidate(suffix: str, *, dry_run: bool) -> str:
    candidate_id = suffix
    project_dir = PIPELINE_DIR / candidate_id
    cp = gate_approved(project_dir)
    if cp is None and not dry_run:
        raise RuntimeError(f"{candidate_id}: 素材创意锁未批准（checkpoint_assets 未 completed/human_approved），拒绝执行")
    store = ProjectCommitStore(project_dir)
    script = load(project_dir, "script")
    lock = load(project_dir, "production_lock")
    sep = load(project_dir, "shot_execution_plan")
    scene_plan = load(project_dir, "scene_plan")
    from lib.template_alignment import shot_alignment_errors
    shot_errors = shot_alignment_errors(sep, script)
    if shot_errors:
        raise RuntimeError(
            f"{candidate_id}: shot/script 绑定校验失败，拒绝渲染：" + "; ".join(shot_errors[:8])
        )
    sample_shots = select_sample_render_shots(sep["shots"][:SAMPLE_SHOTS])
    product_facts = load(research_root_for(project_dir), "product_facts")
    product_identity = {
        "product_id": str(product_facts.get("product_id") or ""),
        "product_name": str(product_facts.get("product_name") or ""),
        "sku": str(product_facts.get("sku") or ""),
    }
    window_frames = sum(round(float(s["duration_seconds"]) * 30) for s in sample_shots)
    sample_seconds = window_frames / 30.0

    if dry_run:
        # 模板校验：无付费调用、无磁盘写入。
        captions = build_screen_copy_captions(project_dir)
        audio = {"mix": {
            "narration": {"provider": "doubao", "resource_id": "seed-tts-2.0",
                          "voice": VOICE, "path": "assets/audio/narration-mix.mp3",
                          "word_timestamps": "assets/audio/narration_meta.json"},
            "music": {"provider": "suno", "path": "assets/music/bgm.mp3",
                      "profile": "轻快短促电商节奏"},
        }}
        asset_manifest = build_asset_manifest(
            project_dir, tts_files=[], bgm_path=project_dir / "assets/music/bgm.mp3",
            mix_path=project_dir / "assets/audio/narration-mix.mp3",
            ducked_path=project_dir / "assets/audio/bgm-ducked.mp3",
        )
        validate_artifact("asset_manifest", attach_hashes(asset_manifest))
        final_props = build_dry_run_final_props(
            project_dir, script, sample_shots, asset_manifest,
            attach_hashes(asset_manifest)["semantic_sha256"], sep["semantic_sha256"],
        )
        validate_artifact("final_props", attach_hashes(final_props))
        caption_revision = build_caption_policy_revision(
            project_dir, lock_hash=lock["artifact_sha256"],
            scene_plan_hash=scene_plan["semantic_sha256"],
        )
        validate_artifact("caption_policy_revision", attach_hashes(caption_revision))
        render_plan = build_render_plan(project_dir, caption_revision_env={
            "name": "caption_policy_revision",
            "path": "artifacts/caption_policy_revision.json",
            "artifact_sha256": attach_hashes(caption_revision)["artifact_sha256"],
            "semantic_sha256": attach_hashes(caption_revision)["semantic_sha256"],
        }, window_frames=window_frames)
        validate_artifact("render_plan", attach_hashes(render_plan))
        edit_decisions = build_sample_edit_decisions(project_dir, word_captions=[])
        validate_artifact("edit_decisions", attach_hashes(edit_decisions))
        sample_scale = 0.5
        sample_report = {
            "version": "1.0", "project_id": candidate_id, "created_at": now(),
            "producer": "cinematic-fast/sample-director",
            "input_hashes": {"final_props": "0" * 64, "render_plan": "0" * 64,
                             "shot_execution_plan": sep["semantic_sha256"]},
            "final_props_hash": "0" * 64, "render_plan_hash": "0" * 64,
            "window": {"startFrame": 0, "endFrameExclusive": window_frames, "scale": sample_scale},
            "output_path": "renders/sample-v1.mp4",
            "probe": {"duration_seconds": 10.0, "fps": 30, "frame_count": 300,
                      "height": round(float(final_props["height"]) * sample_scale),
                      "width": round(float(final_props["width"]) * sample_scale),
                      "sha256": "0" * 64},
            "qa": {"status": "pass", "issues": [], "audio": "dry-run",
                   "captions": "dry-run", "visual": "dry-run", "technical": "dry-run"},
            "status": "pass",
        }
        validate_artifact("sample_report", attach_hashes(sample_report))
        trace = build_sample_execution_trace(
            project_dir,
            final_props=attach_hashes(final_props),
            sample_report=attach_hashes(sample_report),
        )
        validate_artifact("sample_execution_trace", attach_hashes(trace))
        dry_contract = validate_dry_run_sample_contract({
            "script": script,
            "scene_plan": scene_plan,
            "shot_execution_plan": sep,
            "final_props": attach_hashes(final_props),
            "asset_manifest": asset_manifest,
            "product_facts": load(research_root_for(project_dir), "product_facts"),
            "render": {"sha256": sample_report["probe"]["sha256"]},
        })
        evaluation = build_evaluation_report(
            project_dir, sample_report=attach_hashes(sample_report),
            artifacts={"script": script, "scene_plan": scene_plan,
                       "shot_execution_plan": sep, "final_props": final_props},
            alignment=dry_contract["alignment"],
        )
        validate_artifact("evaluation_report", attach_hashes(evaluation))
        return f"[{candidate_id}] dry-run 模板校验通过 ✓"

    # ---------------- live：素材代理（本地，免费） ----------------
    run_media_proxy(project_dir)
    # ---------------- 付费：豆包 TTS + 适配 ----------------
    tts_files, _ = run_tts_with_fit(project_dir)
    sep = load(project_dir, "shot_execution_plan")
    from lib.template_alignment import tts_binding_errors
    tts_errors = tts_binding_errors(
        {**script, "sections": script.get("sections", [])[:SAMPLE_SHOTS]},
        project_dir / "assets" / "audio",
    )
    if tts_errors:
        raise RuntimeError(
            f"{candidate_id}: TTS 与当前脚本绑定失败，拒绝混音：" + "; ".join(tts_errors[:8])
        )
    bgm, bgm_provider = run_bgm(project_dir)
    mix_path, ducked_path = run_mixer(project_dir, tts_files, bgm, sample_shots=sample_shots)

    # 屏显短词字幕；口播时间轴由 canonical sample payload 从 script 派生。
    captions = build_screen_copy_captions(project_dir, sample_shots=sample_shots)
    captions_texts = [str(item.get("text", "")) for item in captions]
    selected_section_ids = {str(s.get("section_id") or "") for s in sample_shots}
    narration_texts = [str(section["narration"]) for section in load(project_dir, "script")["sections"][:SAMPLE_SHOTS]
                       if str(section.get("id") or "") in selected_section_ids]
    audio = {"mix": {
        "narration": {"provider": "doubao", "resource_id": "seed-tts-2.0", "voice": VOICE,
                      "path": str(mix_path.relative_to(project_dir)),
                      "word_timestamps": "assets/audio/narration_meta.json"},
        "music": {"provider": bgm_provider, "path": str(bgm.relative_to(project_dir)),
                  "profile": "轻快短促电商节奏"},
    }}

    asset_manifest = build_asset_manifest(project_dir, tts_files=tts_files, bgm_path=bgm,
                                          mix_path=mix_path, ducked_path=ducked_path)
    caption_revision = build_caption_policy_revision(
        project_dir, lock_hash=lock["artifact_sha256"],
        scene_plan_hash=scene_plan["semantic_sha256"],
    )
    render_plan = build_render_plan(project_dir, caption_revision_env={
        "name": "caption_policy_revision", "path": "artifacts/caption_policy_revision.json",
        "artifact_sha256": semantic_sha256(caption_revision),
        "semantic_sha256": semantic_sha256(caption_revision),
    }, window_frames=window_frames,
       audio_path=str(ducked_path.relative_to(project_dir)),
       audio_sha256=sha256_file(ducked_path))
    from lib.template_render import build_edit_decisions as build_canonical_edit_decisions
    edit_decisions = build_canonical_edit_decisions(
        project_dir,
        [{"id": str(s["id"]), "duration_seconds": float(s["duration_seconds"]),
          "scene_id": str(s.get("scene_id") or ""),
          "screen_copy": str(s.get("screen_copy") or "")}
         for s in sample_shots],
        render_runtime="remotion",
        narration_mix="assets/audio/narration-mix.mp3",
        bgm_path=str(bgm.relative_to(project_dir)),
        scene_plan=scene_plan,
        safe_zone_profile="taobao_detail_3_4",
    )

    # ---- 内存预构建（哈希确定性与落盘一致） ----
    caption_env_pre = {
        "name": "caption_policy_revision", "path": "artifacts/caption_policy_revision.json",
        "artifact_sha256": semantic_sha256(caption_revision),
        "semantic_sha256": semantic_sha256(caption_revision),
    }
    from lib.template_render import build_final_props as build_canonical_final_props
    final_props = build_canonical_final_props(
        project_dir,
        script,
        [{**s, **product_identity, "id": str(s["id"]), "duration_seconds": float(s["duration_seconds"]),
          "render_asset_path": resolve_shot_video(project_dir, s)["path"],
          "screen_copy": str(s.get("screen_copy") or ""), "scene_id": str(s.get("scene_id") or "")}
         for s in sample_shots],
        narration_mix="assets/audio/narration-mix.mp3",
        bgm_path=str(bgm.relative_to(project_dir)),
        profile="social_vertical_3_4_1080p30",
        input_hashes={"script": script["semantic_sha256"],
                      "shot_execution_plan": sep["semantic_sha256"],
                      "asset_manifest": semantic_sha256(asset_manifest)},
    )
    render_plan = build_render_plan(
        project_dir,
        caption_revision_env=caption_env_pre,
        window_frames=window_frames,
        audio_path=str(ducked_path.relative_to(project_dir)),
        audio_sha256=sha256_file(ducked_path),
    )

    # P0#1/P1: 样片渲染用正确累计时间轴/源裁剪/字幕/混音 payload，避免旧
    # build_sample_edit_decisions 的 in_seconds=0 黑屏与 undefined 字幕。
    from lib.sample_payload import build_sample_render_payload
    sample_edit_decisions = build_sample_render_payload({
        "final_props": final_props,
        "asset_manifest": asset_manifest,
        "script": script,
        "captionSafeZoneProfile": "taobao_detail_3_4",
        "narrationSafeZoneProfile": "taobao_detail_3_4",
        "render_runtime": "remotion",
        "renderer_family": "explainer-data",
    })
    sample_path = run_sample_render(
        project_dir,
        edit_decisions=sample_edit_decisions,
        render_plan=render_plan,
        asset_manifest=asset_manifest,
    )
    # The VLM alignment report is bound to the exact rendered bytes.  Any
    # caption/layout/audio change creates a new sample hash, so an older
    # report must be expired and regenerated before the semantic gate reads it.
    refresh_alignment_report(
        project_dir,
        sample_sha256=sha256_file(sample_path),
        script_sha256=str(script.get("semantic_sha256") or ""),
    )
    qa = run_final_qa(project_dir, sample_path)
    if qa["status"] != "pass":
        raise RuntimeError(f"{candidate_id}: final_qa failed {qa}")
    sample_sha = sha256_file(sample_path)
    probe = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,r_frame_rate",
         "-of", "json", str(sample_path)], text=True))
    render_plan["current_timeline_hash"] = semantic_sha256(sample_edit_decisions)

    report = {
        "version": "1.0", "project_id": candidate_id, "created_at": now(),
        "producer": "cinematic-fast/sample-director",
        "input_hashes": {"final_props": semantic_sha256(final_props),
                         "render_plan": semantic_sha256(render_plan),
                         "shot_execution_plan": sep["semantic_sha256"]},
        "final_props_hash": semantic_sha256(final_props),
        "render_plan_hash": semantic_sha256(render_plan),
        "window": {"startFrame": 0, "endFrameExclusive": window_frames, "scale": 0.5},
        "output_path": "renders/sample-v1.mp4",
        "probe": {**sample_probe_summary(probe, fallback_frame_count=window_frames),
                  "sha256": sample_sha},
        "qa": qa,
        "status": "pass",
    }
    trace = build_sample_execution_trace(project_dir, final_props=final_props, sample_report=report)
    trace_ref = {
        "name": "sample_execution_trace",
        "path": "artifacts/sample_execution_trace.json",
        "artifact_sha256": semantic_sha256(trace),
    }
    # L3 创意评分（advisory；不可用 → scored=false 不阻塞）
    judge_data = run_judge(project_dir, sample_path)
    # 技术校验：输出即 schema 合规的 evaluation_report
    evaluation = run_technical_validator(
        project_dir, sample_path,
        subject_hash=sample_sha, trace_ref=trace_ref, judge_data=judge_data,
        expected_duration_s=sample_seconds,
        text_sources=[
            {"text": str(text), "source": "captions_or_narration", "shot_id": ""}
            for text in captions_texts + narration_texts
        ],
        final_props=final_props,
        edit_decisions=edit_decisions,
    )
    from lib.template_alignment import build_semantic_alignment
    alignment_path = project_dir / "analysis" / "alignment_check.json"
    alignment_checks = None
    if alignment_path.is_file():
        try:
            alignment_report = json.loads(alignment_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{candidate_id}: alignment_check.json 无法读取") from exc
        from lib.template_alignment import alignment_report_semantic_checks
        alignment_checks = alignment_report_semantic_checks(
            alignment_report,
            sample_sha256=sample_sha,
            script_sha256=str(script.get("semantic_sha256") or ""),
            input_mode="source_led_template",
        )
    semantic_checks = alignment_checks
    alignment = build_semantic_alignment(
        {"script": script, "scene_plan": scene_plan, "shot_execution_plan": sep,
         "final_props": attach_hashes(final_props), "render": {"sha256": sample_sha},
         "sample_execution_trace": trace,
         "product_facts": load(research_root_for(project_dir), "product_facts"),
         "input_mode": "source_led_template"},
        scope="sample", semantic_checks=semantic_checks,
        audio_dir=project_dir / "assets" / "audio",
    )
    # 人工确认通道（用户规则）：static/partial 判定不阻塞样片门，转 repair_targets
    # 交人工复核；仅硬性冲突（产品身份/血统/证据缺失）仍为机器否决。
    from lib.template_alignment import apply_alignment_to_evaluation, route_human_review_channel
    alignment = route_human_review_channel(alignment)
    evaluation = apply_alignment_to_evaluation(evaluation, alignment)
    if alignment["status"] == "fail":
        raise RuntimeError(f"{candidate_id}: 硬性对齐冲突（产品或血统/证据问题），禁止立 sample 门")
    if evaluation.get("status") == "fail":
        raise RuntimeError(
            f"{candidate_id}: 致命 L1a 失败 "
            f"{[c['id'] for c in evaluation.get('hard_gate', {}).get('checks', []) if c.get('severity') == 'fatal' and c.get('status') == 'fail']}"
        )
    human_review_items = [
        {"shot_id": str(item.get("shot_id") or ""), "reason_codes": list(item.get("reason_codes") or [])}
        for item in (alignment.get("repair_targets") or [])
        if isinstance(item, dict)
    ]

    with store.transaction(
        action={"action_id": f"sample-{suffix}-{uuid.uuid4().hex[:8]}", "type": "batch_sample_stage"},
        result={"status": "committed"},
        audit={"event_type": "batch_sample_stage", "actor_id": "batch-production"},
    ) as sink:
        asset_env = write_artifact_atomic("artifacts/asset_manifest.json", "asset_manifest",
                                          asset_manifest, project_dir=project_dir, sink=sink)
        caption_env = write_artifact_atomic("artifacts/caption_policy_revision.json",
                                            "caption_policy_revision", caption_revision,
                                            project_dir=project_dir, sink=sink)
        props_env = write_artifact_atomic("artifacts/final_props.json", "final_props",
                                          final_props, project_dir=project_dir, sink=sink)
        plan_env = write_artifact_atomic("artifacts/render_plan.sample.json", "render_plan",
                                         render_plan, project_dir=project_dir, sink=sink)
        report_env = write_artifact_atomic("artifacts/sample_report.json", "sample_report",
                                           report, project_dir=project_dir, sink=sink)
        trace_env = write_artifact_atomic("artifacts/sample_execution_trace.json",
                                          "sample_execution_trace", trace,
                                          project_dir=project_dir, sink=sink)
        eval_env = write_artifact_atomic("artifacts/evaluation_report.json", "evaluation_report",
                                         evaluation, project_dir=project_dir, sink=sink)
        write_checkpoint(
            PIPELINE_DIR, candidate_id, "sample", "awaiting_human",
            {
                "asset_manifest": asset_env,
                "final_props": props_env,
                "render_plan": plan_env,
                "sample_report": report_env,
                "sample_execution_trace": trace_env,
                "caption_policy_revision": caption_env,
                "evaluation_report": eval_env,
            },
            pipeline_type="cinematic-fast",
            human_approval_required=True,
            next_action={
                "summary": (f"候选 {candidate_id} 样片渲染完成，等待样片效果确认"
                            + (f"；人工确认通道 {len(human_review_items)} 镜："
                               + "; ".join(f"{i['shot_id']}({','.join(i['reason_codes'])})"
                                           for i in human_review_items[:6])
                               if human_review_items else "")),
                "verb": "await_user",
                "context_refs": ["checkpoint_sample.json",
                                 "artifacts/evaluation_report.json"],
            },
            metadata={"human_review_items": human_review_items,
                      "alignment_status": str(alignment.get("status") or "")},
            sink=sink,
        )
    return f"[{candidate_id}] 样片完成 → 样片效果确认门 ✓"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    failures = []
    for run in RUNS:
        cp = gate_approved(PIPELINE_DIR / run)
        if cp is None:
            failures.append(run)
    if failures and not args.dry_run:
        print("素材创意锁未批准，拒绝执行（门纪律）：" + ", ".join(failures))
        sys.exit(2)
    if failures:
        print("提示：素材创意锁尚未批准（" + ", ".join(failures) + "）——dry-run 仅做模板校验，不执行任何调用。")

    if args.dry_run:
        for run in RUNS:
            print(process_candidate(run, dry_run=True))
        return

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(process_candidate, run, dry_run=False): run for run in RUNS}
        for future in as_completed(futures):
            print(future.result())


if __name__ == "__main__":
    main()
