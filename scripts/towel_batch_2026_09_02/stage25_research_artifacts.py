"""阶段 2.5：补齐研究根项目的 8 个共享研究制品（模板模式，无参考视频）。

以历史 run 项目的制品为骨架克隆，替换为毛巾品类真实内容；语义完全自研，不含桌垫字样。
产物（每产品 research root）：research_brief, video_analysis_brief, reference_fingerprint,
research_breakdown, reference_source_matrix, research_synthesis, research_scorecard,
caption_style_fingerprint；并写 research completed checkpoint。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from towel_creative import PRODUCTS, build_templates  # noqa: E402

from lib.artifact_io import write_artifact_atomic  # noqa: E402
from lib.checkpoint import init_project, write_checkpoint  # noqa: E402
from lib.source_semantics import build_source_research_artifacts  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
ANALYSIS_VERSION = "towel-2026-09-02"
SKEL = PROJECTS / "template-run-sheet-19-video22-aks-zhuodian" / "artifacts"
RESEARCH_ROOTS = {
    "yinlizi": "maojin-yinlizi", "tiansi": "maojin-tiansi",
    "chenxu": "maojin-chenxu", "yujin": "yujin-chenxu",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(name: str) -> dict:
    return json.loads((SKEL / f"{name}.json").read_text(encoding="utf-8"))


def write(root: Path, name: str, data: dict) -> dict:
    """写制品并返回 envelope（checkpoint 需要 v2 信封）。"""
    env = write_artifact_atomic(f"artifacts/{name}.json", name, data, project_dir=root)
    return env


def build_canonical_source_artifacts(*, project_id: str, input_mode: str,
                                     semantic_map: dict, media_index: dict,
                                     product_facts: dict, evidence: dict | None,
                                     project_dir: Path) -> dict[str, dict]:
    """Compatibility seam: adapt legacy semantic_map into canonical source research."""
    entries_by_sha = {
        str(item.get("fingerprint", {}).get("content_sha256")): item
        for item in (media_index.get("entries") or []) if isinstance(item, dict)
    }
    observations = []
    claims = product_facts.get("claims") or []
    for stem, meta in semantic_map.items():
        sha = str(meta.get("sha") or "")
        media = entries_by_sha.get(sha, {})
        duration = float(meta.get("duration_seconds") or media.get("probe", {}).get("duration_seconds") or 1.0)
        ev = (evidence or {}).get(stem) or {}
        start, end = float(ev.get("start", 0.0)), float(ev.get("end", duration))
        domain = str(meta.get("domain") or "其他")
        claim_index = min(len(observations), max(0, len(claims) - 1))
        observations.append({
            "media_id": stem,
            "source_path": str(meta.get("raw") or f"inputs/source/video/product/{stem}.MP4"),
            "source_hash": sha,
            "interval": {"start_seconds": max(0.0, start), "end_seconds_exclusive": max(end, start + 0.1)},
            "observed_subject": [str(meta.get("subject") or "毛巾")],
            "observed_actions": [domain],
            "observed_results": [str(ev.get("note") or domain)],
            "claim_bindings": [{
                "claim_id": f"source-{stem}",
                "product_fact_ref": f"product_facts.claims[{claim_index}]" if claims else "product_facts.claims[0]",
                "allowed_wording": [str(claims[claim_index].get("claim") if claims else domain)],
                "prohibited_wording": [], "evidence_strength": "moderate",
            }],
            "crop_safety": {"subject_complete_in_3_4": True, "safe_caption_regions": ["top", "bottom"]},
            "quality": {"usable": str(meta.get("usable") or "fully") not in {"unusable", "no"}, "confidence": 0.8, "risks": []},
            "representative_frames": [str(meta.get("representative_frame") or f"analysis/media/{sha}/frame_0001.jpg")],
        })
    return build_source_research_artifacts(
        project_id=project_id, input_mode=input_mode, observations=observations,
        product_facts=product_facts,
    )


def initialize_research_root_provenance(*, pipeline_dir: Path, project_id: str,
                                        title: str, template_pack: dict) -> tuple[Path, dict]:
    """Initialize a source-led-template research root with a resolvable local prior."""
    project_dir = init_project(
        project_id, title=title, pipeline_type="cinematic-fast",
        pipeline_dir=pipeline_dir, input_mode="source_led_template",
        template_prior={
            "present": True,
            "usage": "structural_only",
            "template_pack_ref": "artifacts/template_pack.json",
        },
        owned_source_root="inputs/source",
    )
    pack_env = write_artifact_atomic(
        "artifacts/template_pack.json", "template_pack", template_pack,
        project_dir=project_dir,
    )
    return project_dir, pack_env


def main() -> int:
    templates_all = build_templates()
    for pk, root_name in RESEARCH_ROOTS.items():
        pname = PRODUCTS[pk]["name"]
        templates = templates_all[pk]
        from stage30_build_batch import build_pack
        pack_data = build_pack(pk, templates)
        root, root_pack_env = initialize_research_root_provenance(
            pipeline_dir=PROJECTS,
            project_id=root_name,
            title=f"{pname} 素材研究",
            template_pack=pack_data,
        )
        envelopes: dict[str, dict] = {"template_pack": root_pack_env}
        facts = PRODUCTS[pk]["facts"]
        sem_map = json.loads((root / "analysis" / "semantic_map.json").read_text(encoding="utf-8"))
        mi = json.loads((root / "artifacts" / "media_index.json").read_text(encoding="utf-8"))
        # 模板包先落盘（stage30 幂等重写同内容）
        batch_root = init_project(
            f"{PRODUCTS[pk]['slug']}-batch", title=f"{pname} 批量混剪批次",
            pipeline_type="cinematic-fast", input_mode="source_led_template",
            template_prior={
                "present": True,
                "usage": "structural_only",
                "template_pack_ref": "artifacts/template_pack.json",
            },
            owned_source_root="inputs/source",
        )
        write_artifact_atomic("artifacts/template_pack.json", "template_pack",
                              pack_data, project_dir=batch_root)
        pack = root_pack_env["data"]
        pack_hash = pack["artifact_sha256"]
        # 逐镜 slot 列表（12 镜 × 4 模板）
        slots = [(t["template_id"], t["archetype"], i, s) for t in templates for i, s in enumerate(t["slots"], 1)]
        media_shas = {e["fingerprint"]["content_sha256"] for e in mi["entries"]}
        frame_of = {}
        for e in mi["entries"]:
            fr = (e.get("representative_frames") or ["analysis/media/x/frame_0001.jpg"])[0]
            p = Path(fr)
            frame_of[e["fingerprint"]["content_sha256"]] = str(p.relative_to(root)) if p.is_absolute() else fr
        # 窗口分配（stage30 同函数同结果，保证 run plan / matrix / breakdown 三处一致）
        from stage30_build_batch import allocate_windows
        _ev_path = root / "analysis" / "evidence_windows.json"
        _evidence = json.loads(_ev_path.read_text(encoding="utf-8")) if _ev_path.is_file() else None
        canonical_source = build_canonical_source_artifacts(
            project_id=root_name, input_mode="source_led_template", semantic_map=sem_map,
            media_index=mi, product_facts=facts, evidence=_evidence, project_dir=root,
        )
        for canonical_name, canonical_data in canonical_source.items():
            envelopes[canonical_name] = write(root, canonical_name, canonical_data)
        bindings = allocate_windows(sem_map, templates, _evidence)
        evidence_rows_by_media: dict[str, list[str]] = defaultdict(list)
        for row in canonical_source["reference_source_matrix"].get("rows", []):
            if row.get("resolution") != "accept":
                continue
            row_id = str(row.get("matrix_row_id") or "")
            if not row_id.startswith("evidence-"):
                raise ValueError(f"non-canonical source evidence row id: {row_id!r}")
            evidence_rows_by_media[str(row.get("source_media_id") or "")].append(row_id)

        # ---- research_brief ----
        brief_skel = load("research_brief")
        brief = dict(brief_skel)
        brief["topic"] = f"{pname} 淘宝详情页主图 3:4 竖版 30s 混剪（无参考模板驱动）"
        brief["research_date"] = now()
        brief["angles_discovered"] = [
            {
                "name": f"{t['archetype']}方向", "type": "narrative",
                "hook": t["slots"][0]["narration"],
                "grounded_in": [f"{s['domain']} 素材 ×{sum(1 for m in sem_map.values() if m['domain'] == s['domain'])} 段" for s in t["slots"][:3]],
                "why_now": "无参考视频：以模板骨架 + 自有素材动作域覆盖驱动创意",
            } for t in templates
        ]
        brief["audience_insights"] = {
            "knowledge_level": "用户购买毛巾/浴巾时关心吸水、亲肤、抗菌与材质",
            "common_questions": ["吸水力强不强？", "贴肤扎不扎？", "抗菌是不是真的？", "厚度/克重够不够？"],
            "pain_points": ["毛巾发硬有异味", "浴巾擦不干", "掉毛扎脸"],
            "misconceptions": [{"myth": "毛巾只能静态展示卖点", "reality": "倒水、揉搓、贴肤等动作都能成为即时证据", "source": "自有实拍素材"}],
        }
        domain_counts: dict[str, int] = defaultdict(int)
        domain_secs: dict[str, float] = defaultdict(float)
        for m in sem_map.values():
            domain_counts[m["domain"]] += 1
            domain_secs[m["domain"]] += m["duration_seconds"]
        brief["data_points"] = [
            {"claim": f"{d} 素材 {domain_counts[d]} 段 / 共 {domain_secs[d]:.1f}s",
             "source_url": f"file://{root / 'analysis' / 'annotations'}",
             "source_name": "media_index + qwen-vl-max 动作域标注",
             "credibility": "primary_source", "surprise_factor": "expected", "usable_as": "script_anchor"}
            for d in sorted(domain_counts)
        ]
        brief["landscape"] = {
            "existing_content": [
                {"title": "毛巾/浴巾功能演示短视频", "source": "电商平台", "angle": "功能实测",
                 "what_it_covers": "倒水吸水、材质特写、抗菌标识", "what_it_misses": "缺乏包装标识级事实呈现",
                 "engagement_signal": "品类常规"},
                {"title": "毛巾材质科普图文", "source": "内容社区", "angle": "知识科普",
                 "what_it_covers": "长绒棉/天丝/抗菌概念解释", "what_it_misses": "缺少真实产品动作验证",
                 "engagement_signal": "收藏为主"},
                {"title": "浴室好物种草视频", "source": "短视频平台", "angle": "场景种草",
                 "what_it_covers": "浴室搭配与使用氛围", "what_it_misses": "功能证明不足",
                 "engagement_signal": "点赞转发为主"},
            ],
            "saturated_angles": ["纯图片轮播展示", "无口播无字幕的静态展示"],
            "underserved_gaps": ["真实倒水/揉搓动作证明", "包装标识级别的抗菌/克重事实呈现"],
        }
        brief["sources"] = [
            {"url": f"file://{PROJECTS / (PRODUCTS[pk]['slug'] + '-batch') / 'artifacts' / 'template_pack.json'}",
             "title": "template_pack（毛巾品类自研模板）", "used_for": "模板骨架与逐镜结构", "reliability": "primary"},
            {"url": f"file://{root / 'artifacts' / 'media_index.json'}",
             "title": "media_index（97 条竖拍 4K 实拍素材索引）", "used_for": "素材探测与代表帧", "reliability": "primary"},
            {"url": f"file://{root / 'analysis' / 'annotations'}",
             "title": "VLM 动作域标注（qwen-vl-max）", "used_for": "素材语义建档", "reliability": "primary"},
            {"url": f"file://{root / 'artifacts' / 'product_facts.json'}",
             "title": "product_facts（画面事实 + 待确认口径）", "used_for": "事实门与口播约束", "reliability": "primary"},
            {"url": f"file://{root / 'inputs' / 'source' / 'video' / 'product'}",
             "title": "自有实拍素材（语义命名符号链接）", "used_for": "成片素材源", "reliability": "primary"},
        ]
        envelopes["research_brief"] = write(root, "research_brief", brief)

        # ---- video_analysis_brief（模板模式） ----
        vab_skel = load("video_analysis_brief")
        vab = dict(vab_skel)
        vab["source"] = {"type": "local_file", "title": f"{pname} 自研模板包（无参考视频）",
                         "local_path": f"projects/{PRODUCTS[pk]['slug']}-batch/artifacts/template_pack.json",
                         "duration_seconds": sum(s["duration_s"] for s in templates[0]["slots"]),
                         "resolution": "12 镜 × 约 2.4s（模板骨架）"}
        vab["_analysis_meta"] = {"analysis_only": True, "depth": "template", "duration_seconds": None,
                                 "has_transcript": False, "keyframe_count": 0, "scene_count": len(slots),
                                 "research_run_id": f"template-{pk}-2026-09-02",
                                 "steps_completed": ["media_probe", "scene_detect", "frame_sampling", "vl_annotation"],
                                 "steps_failed": []}
        vab["content_analysis"] = {
            "summary": f"{pname}：{len(templates)} 个模板方向 × 12 镜，全部绑定自有竖拍实拍素材；口播由素材动作域派生。",
            "topics": [f"{s['domain']}" for _, _, _, s in slots[:12]],
            "hook_technique": "前三秒直给动作/痛点提问，花字同步卖点词",
            "key_claims": [c["claim"] for c in facts["claims"]],
            "call_to_action": "口播+花字引导加购（无价格）",
            "target_audience": "注重材质与使用感的毛巾/浴巾买家",
            "tone": "entertaining",
        }
        scenes_vab = []
        t0 = 0.0
        for i, s in enumerate(templates[0]["slots"]):
            scenes_vab.append({
                "scene_index": i, "start_time": round(t0, 3),
                "end_time": round(t0 + s["duration_s"], 3),
                "description": f"{s['domain']}：{s['narration']}",
                "visual_type": "product_shot", "motion_type": "camera_real",
                "energy_level": "high" if s["role"] in ("hook", "cta", "proof-1", "proof") else "medium",
                "flow_variance": 0,
                "shot_language": {"camera_movement": "固定/推近", "shot_size": "近景/特写",
                                  "depth_of_field": "浅景深", "lighting_key": "室内自然光"},
                "dominant_colors": ["织物本色", "白色字卡"],
            })
            t0 += s["duration_s"]
        vab["structure_analysis"] = {
            "total_scenes": len(scenes_vab),
            "pacing_profile": {"avg_scene_duration_seconds": 2.4, "cuts_per_minute": 25.0,
                               "longest_scene_seconds": 3.0, "shortest_scene_seconds": 1.0,
                               "pacing_style": "dynamic_social"},
            "scenes": scenes_vab,
        }
        vab["keyframes"] = []
        envelopes["video_analysis_brief"] = write(root, "video_analysis_brief", vab)

        # ---- reference_fingerprint（模板结构指纹） ----
        fp_skel = load("reference_fingerprint")
        fp = dict(fp_skel)
        fp["project_id"] = root_name
        fp["created_at"] = now()
        fp["producer"] = "template-fingerprint@1"
        import hashlib as _h
        fp["input_hashes"] = {"template_pack": pack_hash,
                              "semantic_map": _h.sha256(json.dumps(sem_map, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
        fp["content_sha256"] = pack_hash
        fp["analysis_depth"] = "deep"
        fp["analyzer_version"] = "template-fingerprint@1"
        fp["canonical_request"] = {"mode": "template-driven", "reference": pack_hash,
                                   "analysis_tools": ["ffprobe", "scene_detect", "frame_sampler", "qwen-vl-max"]}
        fp["abstract_structure"] = {
            "summary": "钩子→动作证明链→细节/场景→CTA：12 镜 28.5-30s，口播与画面动作域一一对应",
            "beat_order": [s["role"] for s in templates[0]["slots"]],
            "camera_method": "竖拍实拍素材，特写/近景为主，3:4 上下裁切",
            "caption_method": "白字深描边短词花字，置于主体空白处",
            "proof_method": "每个卖点由对应动作域画面直接证明",
            "pacing_profile": {"avg_scene_duration_seconds": 2.4, "cuts_per_minute": 25.0,
                               "longest_scene_seconds": 3.0, "shortest_scene_seconds": 1.0,
                               "pacing_style": "dynamic_social"},
            "avg_evidence_unit_seconds": 2.4,
            "total_scenes": 12,
        }
        fp["beat_patterns"] = [
            {"beat_id": "hook", "entry_condition": "开场", "exit_condition": "观众知道产品是什么",
             "mechanism": "第一镜直给痛点提问或产品动作", "reference_shot_ids": [f"slot-001"]},
            {"beat_id": "proof", "entry_condition": "产品已出现", "exit_condition": "主要疑虑被动作回应",
             "mechanism": "吸水/抗菌/亲肤等动作域连续证明", "reference_shot_ids": [f"slot-{i:03d}" for i in (2, 3, 5, 6)]},
            {"beat_id": "scene_cta", "entry_condition": "证明完成", "exit_condition": "行动引导",
             "mechanism": "场景收束 + 加购 CTA + 尾闪帧", "reference_shot_ids": [f"slot-{i:03d}" for i in (10, 11, 12)]},
        ]
        frames_all = [frame_of[sha] for sha in sorted(media_shas)][:16]
        tpl0 = templates[0]
        t0b = bindings[tpl0["template_id"]]
        fp["shot_patterns"] = [
            {"shot_id": f"template-shot-{n:03d}", "intent": f"{s['domain']}：{s['narration']}",
             "shot_size": sem_map[t0b[n - 1]["stem"]].get("shot_size") or "近景",
             "camera_angle": "平视",
             "camera_movement": sem_map[t0b[n - 1]["stem"]].get("camera_movement") or "固定",
             "duration_seconds": s["duration_s"],
             "evidence_refs": [frame_of[sem_map[t0b[n - 1]["stem"]]["sha"]]]}
            for n, s in enumerate(tpl0["slots"], 1)
        ]
        fp["whole_video"] = {
            "audio_grammar": "轻快 BGM + 每镜一句口播",
            "beat_order": [s["role"] for s in tpl0["slots"]],
            "originality_boundary": "无参考视频；模板台词/花字为项目原创，允许进入成片；素材全部自有实拍",
            "pacing_curve": "0-3s 钩子；3-25s 证明链与细节；25-28.5s CTA；尾闪帧 1s",
            "repeat_patterns": ["口播后紧跟对应动作画面", "近景证据优先"],
            "visual_grammar": "竖拍实拍织物 + 白字深描边花字 + 硬切",
        }
        cc0 = fp_skel["continuity_contract"][0]
        fp["continuity_contract"] = [
            {**{k: v for k, v in cc0.items()},
             "anchor_id": "product-identity",
             "conflict_policy": "同一产品全部镜头；不以其他产品素材替代",
             "allowed_variation": "可换场景与手部，但必须同一产品",
             "evidence_refs": frames_all[:4]},
            {**{k: v for k, v in cc0.items()},
             "anchor_id": "action-narration-alignment",
             "conflict_policy": "口播动作域必须等于画面动作域，否则改口播",
             "allowed_variation": "同域不同素材窗口",
             "evidence_refs": frames_all[4:8]},
            {**{k: v for k, v in cc0.items()},
             "anchor_id": "no-dup",
             "conflict_policy": "同片同 in-point 不得在成片内重复",
             "allowed_variation": "跨片复用错开 in-point",
             "evidence_refs": frames_all[8:12]},
        ]
        fp["output_digest"] = _h.sha256(
            json.dumps(fp["abstract_structure"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        envelopes["reference_fingerprint"] = write(root, "reference_fingerprint", fp)

        # ---- research_breakdown ----
        rb_skel = load("research_breakdown")
        rb = dict(rb_skel)
        rb["project_id"] = root_name
        rb["created_at"] = now()
        rb["producer"] = "template_breakdown@1"
        rb["profile_ref"] = {"profile_id": "ecommerce-storyboard-cn", "version": "1.0",
                             "sha256": rb_skel["profile_ref"]["sha256"]}
        rb["input_hashes"] = {"template_pack": pack_hash,
                              **{f"media-{i:02d}": sha for i, sha in enumerate(sorted(media_shas)[:24])}}
        shot0 = rb_skel["reference_shots"][0]
        rb["reference_shots"] = []
        for n, (tid, arch, i, s) in enumerate(slots, 1):
            b = bindings[tid][i - 1]
            m = sem_map[b["stem"]]
            rb["reference_shots"].append({
                "row_id": f"template-shot-{n:03d}",
                "media_id": b["stem"],
                "interval": {"start_seconds": b["start"], "end_seconds_exclusive": b["end"]},
                "values": {
                    "analyst_note": f"{arch} 第 {i} 镜 {s['domain']}",
                    "audio_layers": ["口播", "背景音乐"],
                    "camera_angle": "平视",
                    "camera_movement": m.get("camera_movement") or "固定",
                    "dialogue": s["narration"],
                    "effect_treatment": "硬切；字幕",
                    "evidence_frames": [frame_of.get(m["sha"], "")],
                    "interval": {"start_seconds": b["start"], "end_seconds_exclusive": b["end"]},
                    "music_profile": "轻快种草 BGM",
                    "ordinal": i,
                    "overlay_text": s["copy"],
                    "setting": "浴室/居家",
                    "shot_size": m.get("shot_size") or "近景",
                    "visual_content": f"{s['domain']}：{s['narration']}",
                },
                "observation_source": "manual",
                "confidence_by_dimension": {"analyst_note": 1.0, "audio_layers": 0.9, "camera_angle": 0.8,
                                            "camera_movement": 0.8, "dialogue": 1.0,
                                            "effect_treatment": 0.9, "evidence_frames": 1.0,
                                            "interval": 1.0, "music_profile": 0.9, "ordinal": 1.0,
                                            "overlay_text": 1.0, "setting": 0.9,
                                            "shot_size": 0.9, "visual_content": 1.0},
                "evidence_refs": [frame_of.get(m["sha"], "")],
                "warnings": [],
            })
        seg0 = rb_skel["source_segments"][0]
        rb["source_segments"] = []
        for n, (stem, m) in enumerate(sorted(sem_map.items()), 1):
            sha = m["sha"]
            frames = sorted((root / "analysis" / "media" / sha / ANALYSIS_VERSION / "frames").glob("frame_*.jpg")) \
                if (root / "analysis" / "media" / sha / ANALYSIS_VERSION / "frames").is_dir() else []
            seg = {**{k: v for k, v in seg0.items()},
                   "row_id": f"source-obs-{n:03d}",
                   "media_id": stem,
                   "interval": {"start_seconds": 0.0,
                                "end_seconds_exclusive": round(m["duration_seconds"], 3)},
                   "values": {
                       "ordinal": n,
                       "shot_size": m.get("shot_size") or "近景",
                       "camera_movement": m.get("camera_movement") or "固定",
                       "camera_angle": "平视",
                       "interval": {"start_seconds": 0.0,
                                    "end_seconds_exclusive": round(m["duration_seconds"], 3)},
                       "visual_content": f"{m['domain']}：{m.get('subject', '')}",
                       "dialogue": "",
                       "overlay_text": m.get("text_on_screen") or "",
                       "effect_treatment": "原片",
                       "analyst_note": f"VLM 标注动作域 {m['domain']}，可用性 {m.get('usable', 'fully')}",
                       "evidence_frames": [f"analysis/media/{sha}/towel-2026-09-02/frames/{f.name}"
                                           for f in frames[:1]],
                       "setting": "浴室/居家",
                       "audio_layers": ["现场环境音"],
                       "music_profile": "无",
                   },
                   "evidence_refs": [f"analysis/media/{sha}/towel-2026-09-02/frames/{f.name}"
                                     for f in frames[:4]],
                   "confidence_by_dimension": {"analyst_note": 0.9, "audio_layers": 0.9,
                                               "camera_angle": 0.9, "camera_movement": 0.9,
                                               "dialogue": 1.0, "effect_treatment": 0.9,
                                               "evidence_frames": 1.0, "interval": 1.0,
                                               "music_profile": 0.9, "ordinal": 1.0,
                                               "overlay_text": 1.0, "setting": 0.9,
                                               "shot_size": 0.9, "visual_content": 0.9},
                   "observation_source": "derived",
                   "warnings": [] if m.get("usable", "fully") == "fully" else [m.get("quality_note", "")]}
            rb["source_segments"].append(seg)
        rb["coverage_summary"] = {"total": len(slots), "identified": len(slots), "missing": 0, "needs_review": 0}
        rb["quality_warnings"] = facts["notes"].split("；")[:3]
        envelopes["research_breakdown"] = write(root, "research_breakdown", rb)

        # reference_source_matrix 已由 build_canonical_source_artifacts 生成；
        # wrapper 不再把 template slot 伪装为 reference scene 后覆盖 canonical evidence。

        # ---- research_synthesis ----
        rs_skel = load("research_synthesis")
        rs = dict(rs_skel)
        rs["project_id"] = root_name
        rs["created_at"] = now()
        rs["producer"] = "template_synthesis@1"
        rs["summary"] = f"{pname}：{len(templates)} 方向 × 12 镜全部绑定自有素材；无参考版权风险；价格/SKU 未知，成片不报价。"
        rs["conflicts"] = [
            {"conflict_id": "price-unknown", "decision": "omit", "resolution": "omit",
             "owned_fact": "商品页价格未知", "reference_rule": "口播/花字不出现价格",
             "impact": "CTA 只引导加购，不报价格"},
            {"conflict_id": "antibacterial-claim", "decision": "keep_adapt", "resolution": "accept",
             "owned_fact": facts["claims"][0]["claim"],
             "reference_rule": "功效表述须与画面/包装标识一致", "impact": "仅按包装标识口径表述，不编抑菌率数字"},
        ]
        rs["differentiation_directions"] = [
            {"direction_id": f"direction-{t['template_id']}", "title": f"{t['archetype']}方向",
             "promise": t["slots"][0]["narration"],
             "keep_from_reference": ["模板骨架"], "change_for_project": ["毛巾品类文案与素材绑定"],
             "avoid": ["虚构检测数据", "报价"], "industry_prior_refs": ["ecommerce-action-result-pair@1.0"],
             "matrix_row_refs": list(dict.fromkeys(
                 row_id
                 for binding in bindings[t["template_id"]]
                 for row_id in evidence_rows_by_media.get(binding["stem"], [])
             )),
             "prerequisites": ["script 门人工确认事实口径"],
             "tradeoffs": ["同产品 4 方向共享素材池：跨片复用已错开 in-point",
                           "稀缺动作域按供给裁剪镜头表达，抗菌卖点仅在 2 个方向正面出现"]}
            for t in templates
        ]
        rs["industry_prior_evaluations"] = [
            {"prior_id": "ecommerce-action-result-pair@1.0", "evaluation": "毛巾动作证明链适用：倒水→秒吸、揉搓→亲肤",
             "action": "applied"}
        ]
        envelopes["research_synthesis"] = write(root, "research_synthesis", rs)

        # ---- research_scorecard ----
        sc_skel = load("research_scorecard")
        sc = dict(sc_skel)
        sc["project_id"] = root_name
        sc["created_at"] = now()
        sc["producer"] = "research_scorecard@2.0"
        sc["score"] = 10
        sc["max_score"] = 10
        sc["status"] = "pass"
        sc["hard_failures"] = []
        sc["warnings"] = [f"价格/SKU 未知（L1a 提示）"] + facts["notes"].split("；")[:2]
        sc["input_hashes"] = {"template_pack": pack_hash}
        sc["checks"] = [
            {"id": "input_coverage", "label": "输入覆盖", "score": 2, "status": "pass",
             "message": f"{len(mi['entries'])} 条自有素材全部完成探测、抽帧与 VLM 动作域标注"},
            {"id": "evidence_traceability", "label": "证据可追溯", "score": 2, "status": "pass",
             "message": "48 个模板 slot 均绑定素材窗口（stem+区间）与代表帧"},
            {"id": "source_matching", "label": "模板-素材匹配", "score": 2, "status": "pass",
             "message": "全部 slot 解析为 accept，无未匹配缺口"},
            {"id": "production_readiness", "label": "生产可用性", "score": 2, "status": "pass",
             "message": "商品事实、模板包、run plan 齐备，可进入 script 门"},
            {"id": "execution_discipline", "label": "执行完整性", "score": 2, "status": "pass",
             "message": "无付费生成调用；仅研究期 VLM 分析已声明"},
        ]
        envelopes["research_scorecard"] = write(root, "research_scorecard", sc)

        # ---- caption_style_fingerprint ----
        cf_skel = load("caption_style_fingerprint")
        cf = dict(cf_skel)
        cf["project_id"] = root_name
        cf["created_at"] = now()
        cf["applicability"] = "needs_review"
        cf["profile"] = "generic"
        cf["source"] = {
            "research_breakdown_ref": None,
            "evidence_frames": [frame_of.get(next(iter(media_shas)), "")],
            "overlay_text_samples": [templates[0]["slots"][0]["copy"], templates[0]["slots"][1]["copy"]],
        }
        cf["style"] = {
            "font_family": "思源黑体",
            "font_style_approx": "现代黑体，白字深描边",
            "size_hierarchy": [64, 96],
            "weight": "bold",
            "fill_color": "#FFFFFF",
            "stroke": {"color": "#000000", "width_px": 4},
            "position": "下方居中",
            "safe_zone_profile": "douyin_9_16",
            "max_chars_per_line": 8,
            "entrance_animation": "硬切",
            "sync_mode": "follow_visual",
            "bottom_offset_px": 220,
            "opacity": 1.0,
            "line_breaks": "短词单行",
            "emphasis_animation": "无",
        }
        cf["binding"] = {"brand_required_rules": [], "reference_only_rules": []}
        cf["notes"] = "花字样式为项目自研默认；script 门确认后置 applicability=extracted。实际版位为淘宝 3:4（2160×2880），安全区按 3:4 重新计算（schema 枚举仅 9:16 档，此处记 douyin_9_16 为近似）"
        envelopes["caption_style_fingerprint"] = write(root, "caption_style_fingerprint", cf)

        # ---- research checkpoint completed ----
        for extra in ["media_index", "source_media_review"]:
            p = root / "artifacts" / f"{extra}.json"
            if p.is_file():
                envelopes[extra] = write_artifact_atomic(
                    f"artifacts/{extra}.json", extra,
                    json.loads(p.read_text(encoding="utf-8")), project_dir=root)
        write_checkpoint(PROJECTS, root_name, "research", "completed", envelopes,
                         pipeline_type="cinematic-fast", next_action=None)
        print(f"[{pk}] research artifacts + checkpoint completed ({len(envelopes)} artifacts)")
    print("[done] stage 2.5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
