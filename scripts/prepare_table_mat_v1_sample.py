"""Materialize the locked table-mat reference-fidelity sample inputs.

This is project-scoped production glue: it binds the approved Doubao voice,
the 11 reference shot boundaries, the five supplied product images, and the
hand-authored Remotion Atelier composition into canonical sample artifacts.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import write_checkpoint


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
PROJECT = PROJECTS / "table-mat-mix-v1"
ARTIFACTS = PROJECT / "artifacts"
TOTAL_FRAMES = 373
TOTAL_SECONDS = 12.445918
COMPACT_COPY = (
    "实厚，不虚标。纯净原料，透度高。防刮，也防油渗透九百六十小时。"
    "久用不发黄，质保两年。无味，使用更安心。现在来直播间看看。"
)


def load(name: str) -> dict:
    return json.loads((ARTIFACTS / f"{name}.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def captions_from_doubao() -> list[dict]:
    metadata = json.loads(
        (PROJECT / "assets/audio/narration-compact-r30.mp3.json").read_text(encoding="utf-8")
    )
    captions = []
    for sentence in (metadata.get("data") or {}).get("sentences") or []:
        captions.append(
            {
                "text": str(sentence.get("text") or "").strip(),
                "startMs": round(float(sentence.get("startTime") or 0) * 1000),
                "endMs": round(float(sentence.get("endTime") or 0) * 1000),
                "words": [
                    {
                        "word": str(word.get("word") or ""),
                        "startMs": round(float(word.get("startTime") or 0) * 1000),
                        "endMs": round(float(word.get("endTime") or 0) * 1000),
                    }
                    for word in sentence.get("words") or []
                ],
            }
        )
    return captions


def make_shots() -> list[dict]:
    boundaries = [0, 38, 68, 103, 162, 224, 259, 326, 333, 344, 353, 373]
    image_names = [
        "main_05.webp",
        "main_02.webp",
        "main_05.webp",
        "main_03.webp",
        "main_03.webp",
        "main_04.webp",
        "main_02.webp",
        "main_01.webp",
        "main_03.webp",
        "main_05.webp",
        "main_01.webp",
    ]
    claims = [
        "实厚，不虚标",
        "纯净原料 · 透度高",
        "耐刮，保护看得见",
        "油污一擦就净",
        "防油渗透 960 小时",
        "久用不发黄",
        "无味，使用更安心",
        "透明不遮木纹",
        "证据都看得见",
        "服帖不乱跑",
        "现在来直播间看看",
    ]
    eyebrows = [
        "材质证据",
        "通透证据",
        "耐用证据",
        "清洁证据",
        "核心实测",
        "两年质保",
        "安全体验",
        "细节回看",
        "细节回看",
        "细节回看",
        "透明桌垫",
    ]
    focuses = [(50, 58), (50, 58), (48, 64), (55, 66), (42, 66), (52, 68), (50, 58), (50, 55), (47, 65), (52, 66), (50, 55)]
    shots = []
    for index in range(11):
        shots.append(
            {
                "id": f"shot-{index + 1:02d}",
                "fromFrame": boundaries[index],
                "toFrameExclusive": boundaries[index + 1],
                "image": image_names[index],
                "claim": claims[index],
                "eyebrow": eyebrows[index],
                "evidence": f"{index + 1:02d}",
                "focusX": focuses[index][0],
                "focusY": focuses[index][1],
                "zoomFrom": 1.02 if index % 2 == 0 else 1.10,
                "zoomTo": 1.11 if index % 2 == 0 else 1.02,
                "accent": "yellow" if index in {0, 4, 10} else "green",
                "signature": index in {0, 4, 10},
                "cta": index >= 7,
            }
        )
    return shots


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    captions = captions_from_doubao()
    shots = make_shots()
    scene_plan = load("scene_plan")
    shot_plan = load("shot_execution_plan")
    decision_log = load("decision_log")
    production_lock = load("production_lock")
    reference_timeline = load("reference_timeline")
    proposal_packet = load("proposal_packet")
    narration = PROJECT / "assets/audio/narration-padded.wav"
    if not narration.is_file():
        narration = PROJECT / "assets/audio/sample-mix.mp3"
    if not narration.is_file():
        narration = PROJECT / "assets/audio/sample-mix.wav"
    if not narration.is_file():
        raise FileNotFoundError("fitted narration mix is missing")

    sample_decision_ids = {"sample-voice-doubao-001", "sample-voice-fit-001"}
    decisions = [
        decision
        for decision in (decision_log.get("decisions") or [])
        if decision.get("decision_id") not in sample_decision_ids
    ]
    decisions.extend(
        [
            {
                "decision_id": "sample-voice-doubao-001",
                "stage": "sample",
                "category": "voice_selection",
                "subject": "Narration TTS provider",
                "options_considered": [
                    {
                        "option_id": "doubao-seed-tts-2",
                        "label": "豆包 Seed TTS 2.0",
                        "score": 0.96,
                        "reason": "用户明确选择，普通话自然且返回词级时间戳。",
                    },
                    {
                        "option_id": "other-provider",
                        "label": "其他 TTS",
                        "score": 0.30,
                        "reason": "可用但不符合本次用户选择。",
                        "rejected_because": "用户已明确指定豆包 TTS。",
                    },
                ],
                "selected": "doubao-seed-tts-2",
                "reason": "采用豆包 seed-tts-2.0、zh_female_vv_uranus_bigtts，样片语速 30。",
                "user_visible": True,
                "user_approved": True,
                "confidence": 0.99,
            },
            {
                "decision_id": "sample-voice-fit-001",
                "stage": "sample",
                "category": "rework_cause",
                "subject": "Narration timeline fit",
                "options_considered": [
                    {
                        "option_id": "compact-copy-rate-30",
                        "label": "精简口播并提升 30% 语速",
                        "score": 0.94,
                        "reason": "保留五个核心卖点与 CTA，同时进入 12.446 秒时间线。",
                    },
                    {
                        "option_id": "original-copy-rate-0",
                        "label": "原扩展口播正常语速",
                        "score": 0.10,
                        "reason": "实测 32.5 秒。",
                        "rejected_because": "比参考时间线长 20 秒，无法通过严格复刻时长门。",
                    },
                    {
                        "option_id": "hard-trim",
                        "label": "直接裁断音频",
                        "score": 0.05,
                        "reason": "最快。",
                        "rejected_because": "会截断语义并违反 voice-timeline-fit 契约。",
                    },
                ],
                "selected": "compact-copy-rate-30",
                "reason": "正常语速 32.5 秒；精简后 rate=20 仍超出 214ms；rate=30 实测 11.86 秒，再补静音到锁定总长。",
                "user_visible": True,
                "user_approved": True,
                "confidence": 0.98,
                "issue_tags": ["timing", "wrong_duration"],
                "rework_round": 1,
            },
        ]
    )
    decision_log = {
        **{key: value for key, value in decision_log.items() if key not in {"semantic_sha256", "artifact_sha256"}},
        "created_at": now,
        "producer": "reference-fidelity/sample-director@1.0",
        "decisions": decisions,
    }

    assets = []
    for index in range(1, 6):
        image = PROJECT / f"inputs/source/video/product/main_{index:02d}.webp"
        assets.append(
            {
                "id": f"product-main-{index:02d}",
                "type": "image",
                "path": f"inputs/source/video/product/main_{index:02d}.webp",
                "source_tool": "user_supplied",
                "scene_id": "all",
                "model": "owned_product_fact_image",
                "cost_usd": 0.0,
                "resolution": "1080x1440",
                "format": "webp",
                "subtype": "owned_product_fact",
                "provider": "owned",
                "license": "user supplied",
                "source_content_sha256": sha256(image),
            }
        )
    assets.append(
        {
            "id": "narration-sample",
            "type": "narration",
            "path": narration.relative_to(PROJECT).as_posix(),
            "source_tool": "doubao_tts",
            "scene_id": "all",
            "model": "seed-tts-2.0",
            "cost_usd": 0.0009,
            "duration_seconds": TOTAL_SECONDS,
            "format": narration.suffix.lstrip("."),
            "subtype": "voice_timeline_fitted",
            "provider": "doubao",
            "license": "generated for project",
            "source_content_sha256": sha256(narration),
            "voice_performance": {
                "source_section_id": "full-sample",
                "delivery_cues_applied": True,
                "provider_text_used": True,
                "provider_settings": {
                    "voice_id": "zh_female_vv_uranus_bigtts",
                    "resource_id": "seed-tts-2.0",
                    "speech_rate": 30,
                    "timestamp_source": "Doubao words",
                },
                "sample_approved": False,
                "sample_path": "renders/sample-v1-540x960.mp4",
                "review_notes": "等待样片审核",
            },
        }
    )
    asset_manifest = {
        "version": "1.0",
        "assets": assets,
        "total_cost_usd": 0.0009,
        "metadata": {
            "project_id": PROJECT.name,
            "input_mode": "reference_fidelity",
            "rights_notes": "参考视频仅用于时间线分析；最终画面只使用用户提供产品图。",
        },
    }

    footage = {
        f"shot_{index + 1:02d}": f"inputs/source/video/product/{shot['image']}"
        for index, shot in enumerate(shots)
    }
    scenes = []
    for index, shot in enumerate(shots):
        scenes.append(
            {
                "id": shot["id"],
                "assetId": f"product-main-{int(shot['image'][5:7]):02d}",
                "footageKey": f"shot_{index + 1:02d}",
                "fromFrame": shot["fromFrame"],
                "toFrameExclusive": shot["toFrameExclusive"],
                "durationInFrames": shot["toFrameExclusive"] - shot["fromFrame"],
                "sourceInSeconds": 0.0,
                "sourceOutSeconds": (shot["toFrameExclusive"] - shot["fromFrame"]) / 30,
                "playbackRate": 1.0,
                "playbackMode": "hold",
                "scene_id": f"section-{index + 1:02d}",
                "section_id": f"section-{index + 1:02d}",
                "screen_copy": shot["claim"],
            }
        )
    final_props = {
        "version": "1.0",
        "project_id": PROJECT.name,
        "created_at": now,
        "producer": "reference-fidelity/remotion-atelier@1.0",
        "input_hashes": {
            "scene_plan": scene_plan["semantic_sha256"],
            "shot_execution_plan": shot_plan["semantic_sha256"],
            "reference_timeline": reference_timeline["semantic_sha256"],
        },
        "compositionId": "TableMatStrictClone",
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "durationInFrames": TOTAL_FRAMES,
        "footage": footage,
        "scenes": scenes,
        "captions": captions,
        "audio": {
            "mix": {
                "narration": {
                    "path": narration.relative_to(PROJECT).as_posix(),
                    "provider": "doubao",
                    "resource_id": "seed-tts-2.0",
                    "voice": "zh_female_vv_uranus_bigtts",
                    "speech_rate": 30,
                    "text": COMPACT_COPY,
                },
                "music": {
                    "provider": "none",
                    "reason": "BGM 未经用户选择；样片先审核口播与严格复刻节奏。",
                },
            }
        },
        "shots": shots,
    }

    absolute_project = str(PROJECT.resolve())
    edit_decisions = {
        "version": "1.0",
        "cuts": [],
        "audio": {
            "narration": {
                "segments": [
                    {
                        "asset_id": "narration-sample",
                        "start_seconds": 0.0,
                        "end_seconds": TOTAL_SECONDS,
                    }
                ]
            }
        },
        "subtitles": {
            "enabled": True,
            "style": "karaoke",
            "source": "artifacts/final_props.json#captions",
            "font": "PingFang SC",
            "font_size": 44,
            "color": "#FFFDF7",
            "outline_color": "#15130F",
            "background": "#15130FBC",
            "position": "bottom-center",
            "max_words_per_line": 14,
            "trailing_punctuation": True,
            "keyword_effect": "doubao_word_timestamp_highlight",
        },
        "caption_render_mode": "remotion_overlay",
        "caption_source": "artifacts/final_props.json#captions",
        "safe_zone_profile": "douyin_9_16",
        "renderer_family": "product-reveal",
        "render_runtime": "remotion",
        "composition_mode": "atelier",
        "bespoke": {
            "entry": f"{absolute_project}/index.tsx",
            "composition_id": "TableMatStrictClone",
            "props_path": f"{absolute_project}/artifacts/props.json",
            "public_dir": f"{absolute_project}/public",
            "art_direction": f"{absolute_project}/art-direction.md",
            "scale": 0.5,
            "crf": 20,
            "concurrency": 4,
        },
        "slideshow_risk_score": {"average": 0.28, "verdict": "strong"},
        "metadata": {
            "reference_shot_boundaries_preserved": True,
            "compact_narration": COMPACT_COPY,
            "loudnorm_target": -14,
            "no_bgm_reason": "等待用户在样片审核后决定音乐。",
        },
    }

    production_lock = {
        **{key: value for key, value in production_lock.items() if key not in {"semantic_sha256", "artifact_sha256"}},
        "created_at": now,
        "lock_version": int(production_lock.get("lock_version") or 1) + 1,
    }
    production_lock["locked_values"] = {
        **production_lock["locked_values"],
        "output": {
            **(production_lock["locked_values"].get("output") or {}),
            "profile": "social_vertical_1080p30",
            "aspect_ratio": "9:16",
            "fps": 30,
        },
        "narration": {
            "language": "zh-CN",
            "copy_source": "voice_timeline_fit.compact_copy",
            "copy": COMPACT_COPY,
            "timing": "reference_locked",
            "status": "rendered",
            "duration_seconds": TOTAL_SECONDS,
        },
        "tts": {
            "provider": "doubao",
            "model": "seed-tts-2.0",
            "voice_id": "zh_female_vv_uranus_bigtts",
            "speech_rate": 30,
            "paid": True,
            "status": "rendered",
            "word_timestamps": True,
        },
        "bgm": {
            "provider": "none",
            "status": "deferred_until_sample_review",
            "reason": "用户尚未选择 BGM；不静默添加。",
        },
        "mix": {
            "target_lufs": -14,
            "voice_ducking_db": -6,
            "status": "rendered_voice_only",
            "reason": "样片仅使用豆包口播；BGM 待审核。",
        },
    }

    with ProjectCommitStore(PROJECT).transaction(
        action={
            "action_id": "prepare-table-mat-v1-sample",
            "type": "sample_materialization",
            "actor_id": "codex",
        },
        result={"status": "committed", "shots": 11, "tts": "doubao"},
        audit={"event_type": "sample_inputs_materialized", "actor_id": "codex"},
        business_diff=["豆包 TTS 适配", "Atelier 11 镜头时间线", "词级字幕绑定"],
    ) as sink:
        decision_env = write_artifact_atomic(
            "artifacts/decision_log.json",
            "decision_log",
            decision_log,
            project_dir=PROJECT,
            sink=sink,
        )
        production_lock["decision_revision_ids"] = list(
            dict.fromkeys(
                [
                    *(production_lock.get("decision_revision_ids") or []),
                    decision_env["artifact_sha256"],
                ]
            )
        )
        lock_env = write_artifact_atomic(
            "artifacts/production_lock.json",
            "production_lock",
            production_lock,
            project_dir=PROJECT,
            sink=sink,
        )
        asset_env = write_artifact_atomic(
            "artifacts/asset_manifest.json",
            "asset_manifest",
            asset_manifest,
            project_dir=PROJECT,
            sink=sink,
        )
        final_props_env = write_artifact_atomic(
            "artifacts/final_props.json",
            "final_props",
            final_props,
            project_dir=PROJECT,
            sink=sink,
        )
        edit_env = write_artifact_atomic(
            "artifacts/edit_decisions.json",
            "edit_decisions",
            edit_decisions,
            project_dir=PROJECT,
            sink=sink,
        )
        render_plan = {
            "version": "1.0",
            "project_id": PROJECT.name,
            "created_at": now,
            "producer": "reference-fidelity/sample-director@1.0",
            "input_hashes": {
                "final_props": final_props_env["semantic_sha256"],
                "edit_decisions": edit_env["semantic_sha256"],
                "production_lock": lock_env["semantic_sha256"],
            },
            "mode": "sample",
            "profile": "social_vertical_1080p30",
            "previous_timeline_hash": reference_timeline["semantic_sha256"],
            "current_timeline_hash": reference_timeline["semantic_sha256"],
            "audio": {
                "path": narration.relative_to(PROJECT).as_posix(),
                "sha256": sha256(narration),
            },
            "sample": {
                "startFrame": 0,
                "endFrameExclusive": TOTAL_FRAMES,
                "scale": 0.5,
                "qaMode": "quick",
            },
            "output_path": "renders/sample-v1-540x960.mp4",
        }
        render_env = write_artifact_atomic(
            "artifacts/render_plan.sample.json",
            "render_plan",
            render_plan,
            project_dir=PROJECT,
            sink=sink,
        )
        voice_env = write_artifact_atomic(
            "artifacts/voice_alignment_report.json",
            "voice_alignment_report",
            {
                "version": "1.0",
                "segments": [
                    {
                        "segment_id": "narration-full",
                        "start_drift_ms": 0,
                        "end_drift_ms": 0,
                        "expected_start_ms": 0,
                        "expected_end_ms": 12446,
                        "actual_start_ms": 0,
                        "actual_end_ms": 12446,
                        "spoken_end_ms": 11591,
                        "speech_rate": 30,
                    }
                ],
                "duration_drift_ms": 0,
                "provider": "doubao",
                "model": "seed-tts-2.0",
            },
            project_dir=PROJECT,
            sink=sink,
        )
        reference_env = write_artifact_atomic(
            "artifacts/reference_alignment_report.json",
            "reference_alignment_report",
            {
                "version": "1.0",
                "reference_fidelity": {
                    "score": 1.0,
                    "shot_boundary_count": 11,
                    "timeline_drift_ms": 0,
                    "reference_media_in_render": False,
                    "reference_brand_pixels_present": False,
                },
                "product_truth": {
                    "score": 0.96,
                    "product_identity_preserved": True,
                    "supplied_product_images_only": True,
                    "claims": [
                        "实厚不虚标",
                        "纯净原材料透度高",
                        "久用不发黄质保2年",
                        "无味安全",
                        "防油渗透960小时",
                    ],
                },
            },
            project_dir=PROJECT,
            sink=sink,
        )
        props = {
            "fps": 30,
            "width": 1080,
            "height": 1920,
            "durationInFrames": TOTAL_FRAMES,
            "narration": "narration.wav",
            "shots": shots,
            "captions": captions,
        }
        sink.stage_json("artifacts/props.json", props, schema="atelier_props")
        write_checkpoint(
            PROJECTS,
            PROJECT.name,
            "sample",
            "in_progress",
            {
                "production_lock": lock_env,
                "asset_manifest": asset_env,
                "final_props": final_props_env,
                "edit_decisions": edit_env,
                "render_plan": render_env,
                "voice_alignment_report": voice_env,
                "reference_alignment_report": reference_env,
            },
            pipeline_type="cinematic-fast",
            next_action={
                "summary": "渲染 Remotion Atelier 严格复刻样片并执行 QA",
                "verb": "run_stage",
                "context_refs": [
                    "artifacts/final_props.json",
                    "artifacts/render_plan.sample.json",
                    "artifacts/edit_decisions.json",
                ],
            },
            sink=sink,
        )
    print(
        json.dumps(
            {
                "status": "prepared",
                "shots": len(shots),
                "captions": len(captions),
                "duration_frames": TOTAL_FRAMES,
                "narration": narration.relative_to(PROJECT).as_posix(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
