"""阶段 2：批量建单——商品事实、模板包、run 项目、template_run_plan、script 草案、批次控制面。

按 batch-002 运营模式（Agent 创作 + canonical 落盘）：
  - 语义路径重建 media_index / source_media_review（同一 analysis_version → 缓存命中，秒级）
  - product_facts → 研究根项目
  - template_pack（4 模板/产品）→ <slug>-batch/artifacts/template_pack.json
  - 16 个 template-run-<tid> 项目（fork_template_run：共享研究 + research completed）
  - 每 run：template_run_plan（全 slot 绑定 owned 素材窗口）+ proposal/ccp/hook_plan/decision_log
    + script.json（draft）
  - 每产品：template_batch.json + candidate_batch.json（批量工作台）
  - checkpoint：proposal completed；script awaiting_human（script 门，待用户批 16 条文案）
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from towel_creative import PRODUCTS, PRODUCT_KEYS, build_templates  # noqa: E402

from lib.artifact_io import write_artifact_atomic  # noqa: E402
from lib.checkpoint import init_project, write_checkpoint  # noqa: E402
from lib.differentiation import build_differentiation_plan  # noqa: E402
from lib.hook_plan import build_hook_plan  # noqa: E402
from lib.media_index import build_media_index  # noqa: E402
from lib.source_media_review import review_source_media  # noqa: E402
from lib.template_batch import create_template_batch  # noqa: E402
from lib.template_fork import fork_template_run, shared_research_refs  # noqa: E402
from lib.template_run_plan import create_template_run, bind_slot  # noqa: E402
from lib.template_mainline import (  # noqa: E402
    build_script as build_canonical_script,
    scene_plan_data as build_canonical_scene_plan_data,
)
from tools.tool_registry import registry  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
ANALYSIS_VERSION = "towel-2026-09-02"


def build_canonical_template_batch(template_pack: dict, *, product_facts_ref: dict,
                                   template_run_plan_refs: dict | None = None,
                                   shared_research_refs: list[dict] | None = None,
                                   max_parallel: int = 2,
                                   max_cost_usd: float = 200.0,
                                   max_retries_per_run: int = 1,
                                   publish_policy: str = "selective",
                                   render_runtime: str | None = None,
                                   batch_id: str | None = None,
                                   differentiation_plan_ref: dict | None = None) -> dict:
    """CLI compatibility seam delegating batch ownership to the canonical builder."""
    return create_template_batch(
        template_pack,
        product_facts_ref=product_facts_ref,
        batch_id=batch_id,
        template_run_plan_refs=template_run_plan_refs,
        shared_research_refs=shared_research_refs,
        max_parallel=max_parallel,
        max_cost_usd=max_cost_usd,
        max_retries_per_run=max_retries_per_run,
        publish_policy=publish_policy,
        render_runtime=render_runtime,
        differentiation_plan_ref=differentiation_plan_ref,
    )


def persist_canonical_differentiation_plan(
    batch_root: Path,
    *,
    batch_id: str,
    candidates: list[dict],
    research_refs: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Persist the sole batch-root differentiation plan and return its ref."""
    plan = build_differentiation_plan(
        batch_id, candidates, research_refs=research_refs or [],
    )
    env = write_artifact_atomic(
        "artifacts/differentiation_plan.json", "differentiation_plan",
        plan, project_dir=batch_root,
    )
    ref = {
        "name": "differentiation_plan",
        "path": "artifacts/differentiation_plan.json",
        "artifact_sha256": env["data"]["artifact_sha256"],
    }
    return env, ref


def build_differentiation_candidates(
    *,
    product_id: str,
    templates: list[dict],
    bindings: dict[str, list[dict]],
    matrix: dict,
) -> tuple[list[dict], dict[str, list[str]]]:
    """Derive batch signatures from canonical source-evidence rows only."""
    rows_by_media: dict[str, list[dict]] = defaultdict(list)
    for row in matrix.get("rows") or []:
        if not isinstance(row, dict) or row.get("resolution") != "accept":
            continue
        row_id = str(row.get("matrix_row_id") or "")
        if not row_id.startswith("evidence-"):
            raise ValueError(f"source-led matrix row {row_id!r} is not a canonical evidence id")
        rows_by_media[str(row.get("source_media_id") or "")].append(row)
    signatures: list[dict] = []
    refs_by_template: dict[str, list[str]] = {}
    for template in templates:
        template_id = str(template.get("template_id") or "")
        selected_rows: list[dict] = []
        for binding in bindings.get(template_id) or []:
            media_id = str(binding.get("stem") or binding.get("source_media_id") or "")
            rows = rows_by_media.get(media_id) or []
            if not rows:
                raise ValueError(f"template {template_id} binding {media_id!r} has no accepted canonical evidence row")
            for row in rows:
                if row not in selected_rows:
                    selected_rows.append(row)
        evidence_refs = [str(row["matrix_row_id"]) for row in selected_rows]
        refs_by_template[template_id] = evidence_refs
        actions = list(dict.fromkeys(
            str(action)
            for row in selected_rows
            for action in row.get("action_keys") or []
            if str(action).strip()
        ))
        copy_text = " ".join(
            str((row.get("allowed_wording") or [""])[0])
            for row in selected_rows
            if row.get("allowed_wording")
        ).strip()
        slots = template.get("slots") or []
        signatures.append({
            "candidate_id": f"{product_id}-{template_id.rsplit('-', 1)[-1]}",
            "product_id": product_id,
            "hook_pattern": str(template.get("archetype") or "source-proof"),
            "primary_action_keys": actions[:2] or [str((slots[0] if slots else {}).get("domain") or "product")],
            "action_keys": actions or [str(slot.get("domain") or "product") for slot in slots],
            "copy_text": copy_text or " ".join(str(slot.get("domain") or "product") for slot in slots),
            "beat_durations": [float(slot.get("duration_s") or 0) for slot in slots],
            "beat_order": [str(slot.get("role") or "proof") for slot in slots],
            "scene_context": str(template.get("archetype") or "owned-source"),
            "pacing_curve": "-".join(str(slot.get("role") or "proof") for slot in slots),
            "caption_strategy": f"{template.get('archetype') or 'proof'}-short-copy",
            "audio_strategy": "paid-tts-generated-bgm",
            "forbidden_repeats": ["same media_id + in_point"],
            "matrix_row_refs": evidence_refs,
        })
    return signatures, refs_by_template


def build_canonical_script_for_run(project_dir: Path, template: dict, scene_plan: dict,
                                   ccp: dict, facts: dict, *, title: str,
                                   approved: bool = False) -> dict:
    """Compatibility seam for evidence-constrained mainline script creation."""
    return build_canonical_script(
        project_dir, template, scene_plan, ccp, facts,
        approved=approved, title=title,
    )


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _NoTranscribeRegistry:
    def __init__(self, real):
        self._real = real

    def get(self, name):
        return None if name == "transcriber" else self._real.get(name)

    def __getattr__(self, item):
        return getattr(self._real, item)


# ---------- 素材窗口分配 ----------

def _find_window(stem: str, dur: float, dur_max: float,
                 used: list[tuple[float, float]], tpl_used: set,
                 ev: dict | None = None) -> float | None:
    """三级窗口策略（口播-画面对齐优先）：
    1) 覆盖证据窗：窗口完整包含动作区间（ev ⊆ 窗口 ±0.3s）；
    2) 相交证据窗：窗口与动作区间有重叠（动作至少部分可见）；
    3) 任意窗口：无证据窗或前两级都不可用时回退。
    均不与已用区间重叠，不在本模板重复。"""
    if ev and ev.get("start") is not None and ev.get("end") is not None:
        ev_start = max(0.0, min(float(ev["start"]), max(0.0, dur_max - 0.3)))
        ev_end = min(float(ev["end"]), dur_max)
        # 覆盖级：s ∈ [ev_end - dur - 0.3, ev_start + 0.3]
        lo_c = max(0.0, ev_end - dur - 0.3)
        hi_c = min(max(0.0, dur_max - dur), ev_start + 0.3)
        # 相交级：s ∈ [ev_start - dur + 0.3, ev_end - 0.3]
        lo_i = max(0.0, ev_start - dur + 0.3)
        hi_i = min(max(0.0, dur_max - dur), max(0.0, ev_end - 0.3))
        covering = [ev_start]
        for k in range(1, 17):
            covering.append(ev_start - 0.25 * k)
            covering.append(ev_start + 0.25 * k)
        # 相交级：从动作点附近向两侧扩展（保证动作出现在镜头开头，而非尾部）
        intersecting = [ev_start]
        for k in range(1, 17):
            intersecting.append(ev_start - 0.25 * k)
            intersecting.append(ev_start + 0.25 * k)
        passes = [(covering, lo_c, hi_c), (intersecting, lo_i, hi_i)]
        for candidates, lo, hi in passes:
            for s0 in candidates:
                s = round(s0, 3)
                if s < lo - 1e-6 or s > hi + 1e-6:
                    continue
                key = (stem, s)
                if key in tpl_used:
                    continue
                if not any(s < e2 and e1 < s + dur for e1, e2 in used):
                    if s + dur <= dur_max + 1e-6:
                        return s
    # 任意级（窗口必须完整落在素材内）
    hi = max(0.0, dur_max - dur)
    for k in range(0, 80):
        s = round(0.25 * k, 3)
        if s > hi + 1e-6:
            break
        if s + dur > dur_max + 1e-6:
            continue
        key = (stem, s)
        if key in tpl_used:
            continue
        if not any(s < e2 and e1 < s + dur for e1, e2 in used):
            return s
    return None


def _stem_sub_actions(ev_note: str) -> set[str]:
    """从证据标注文本提取子动作标签。"""
    out = set()
    if not ev_note:
        return out
    if "擦拭" in ev_note or "滚筒" in ev_note:
        out.add("wipe")
    if "水滴" in ev_note:
        out.add("drop")
    if "倒水" in ev_note or "泼" in ev_note:
        out.add("pour")
    if "渗透" in ev_note:
        out.add("permeate")
    if "吸水" in ev_note:
        out.add("absorb")
    return out


def _narration_needs(narration: str) -> str | None:
    """口播要求的子动作（None=通用，任意素材）。"""
    if any(k in narration for k in ("水滴", "沾", "一沾", "接触")):
        return "drop"
    if any(k in narration for k in ("倒水", "泼", "盆", "倒下去", "倒一测")):
        return "pour"
    if any(k in narration for k in ("擦拭", "一擦", "来回一擦", "擦")):
        return "wipe"
    if "渗透" in narration:
        return "permeate"
    return None


def allocate_windows(semantic_map: dict, templates: list[dict],
                     evidence: dict | None = None) -> dict[str, list[dict]]:
    """为每个模板的每个 slot 分配素材窗口（去重：同片不同窗；跨片复用不同 in-point；
    优先绑定在证据时间窗内，保证口播动作 == 画面动作）。"""
    stems_by_domain: dict[str, list[str]] = defaultdict(list)
    for stem, meta in semantic_map.items():
        stems_by_domain[meta["domain"]].append(stem)
    for d in stems_by_domain:
        stems_by_domain[d].sort()
    cursor: dict[str, int] = defaultdict(int)
    last_stem: dict[tuple[str, str], str] = {}
    bindings: dict[str, list[dict]] = {}
    for tpl in templates:
        tid = tpl["template_id"]
        # H4 规则：同片内不重复；跨视频可复用同一动作窗口（各自是独立成片）
        used_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
        tpl_bindings: list[dict] = []
        tpl_used: set[tuple[str, float]] = set()
        for i, slot in enumerate(tpl["slots"], 1):
            domain, dur = slot["domain"], float(slot["duration_s"])
            pool = stems_by_domain.get(domain, stems_by_domain.get("使用场景", []))
            if not pool:
                raise SystemExit(f"{tid} slot {i}: 域 {domain} 无素材")
            # 强制绑定：标签类槽位 pin 到确认有文字的素材
            if slot.get("pin_stem"):
                if slot["pin_stem"] not in pool:
                    continue_flag = False
                else:
                    pool = [slot["pin_stem"]]
                    continue_flag = True
            # 子动作精准匹配：口播要求倒水/水滴/擦拭/渗透时，优先用对应子动作素材
            _need = _narration_needs(slot.get("narration", ""))
            if _need and not slot.get("pin_stem"):
                _match = [s for s in pool
                          if _need in _stem_sub_actions((evidence or {}).get(s, {}).get("note", ""))]
                _rest = [s for s in pool if s not in _match]
                pool = _match + _rest
            if slot.get("pin_stem") and slot["pin_stem"] not in pool:
                raise SystemExit(f"{tid} slot {i}: pin_stem {slot['pin_stem']} 不在域内")
            prev = last_stem.get((tid, domain))
            # 有子动作要求时优先子动作匹配（忽略连续性偏好）；无要求时才做同片连续
            idx0 = 0 if (_need or slot.get("pin_stem")) else (pool.index(prev) if prev in pool else cursor[domain])
            picked = None
            reused = False
            for k in range(len(pool)):
                stem = pool[(idx0 + k) % len(pool)]
                dur_max = float(semantic_map[stem]["duration_seconds"])
                ev = (evidence or {}).get(stem)
                s = _find_window(stem, dur, dur_max, used_intervals[stem], tpl_used, ev)
                if s is not None:
                    picked = (stem, s)
                    break
            if picked is None:
                # 复用兜底：同片同窗口在成片内重复一次（尾帧/CTA 常见剪辑手段），标记 reused；
                # 尾帧/CTA/收尾为通用口播，允许复用本片任意已用画面（花字品牌卡）。
                roles_any = {"tail", "cta", "summary"}
                search_space = (tpl_used if slot["role"] in roles_any
                                else [(st, ss) for (st, ss) in tpl_used if st in pool])
                for (st, ss) in sorted(search_space):
                    if ss + dur <= float(semantic_map[st]["duration_seconds"]) + 1e-6:
                        picked = (st, ss)
                        reused = True
                        break
            if picked is None:
                raise SystemExit(f"{tid} slot {i}: 域 {domain} 窗口耗尽（容量不足）")
            stem, s = picked
            last_stem[(tid, domain)] = stem
            if stem in pool:
                cursor[domain] = (pool.index(stem) + 1) % len(pool)
            if not reused:
                used_intervals[stem].append((s, s + dur))
            tpl_used.add((stem, s))
            tpl_bindings.append({
                "slot_id": f"{tid}-slot-{i:03d}",
                "stem": stem,
                "domain": domain,
                "start": s,
                "end": round(s + dur, 3),
                "reused": reused,
            })
        bindings[tid] = tpl_bindings
    return bindings


# ---------- 共享规则（CCP sections） ----------

def ccp_sections(pk: str) -> dict:
    pname = PRODUCTS[pk]["name"]
    facts = PRODUCTS[pk]["facts"]
    claims_txt = "；".join(c["claim"] for c in facts["claims"])
    return {
        "content_direction": {
            "title": "内容方向",
            "summary": f"{pname} 淘宝详情页主图竖版 30s 混剪：4 个方向（测评证明/痛点反转/卖点罗列/场景种草）各 1 条，全部使用自有实拍素材。",
            "rules": ["每个方向 12 镜", "口播每镜一句", "CTA 不报价"],
            "evidence_refs": [f"product_facts:claims（{claims_txt[:60]}…）"],
        },
        "story_pacing": {
            "title": "节奏",
            "summary": "钩子 2-2.5s → 证明链 2-3s/镜 → CTA 2.5s → 尾闪帧 1s；口播每镜一句（8-16 字）。",
            "rules": ["前三秒必须给出钩子", "证明链每镜一个动作域"],
            "evidence_refs": ["template_pack:slots.duration_s"],
        },
        "visual_rules": {
            "title": "视觉规则",
            "summary": "3:4 竖版 2160×2880：源片竖拍 9:16 上下裁切、宽度零损失；花字白字深描边置于主体空白处；同片去重、跨片复用错开 in-point。",
            "rules": ["2160×2880@30fps 3:4", "同片去重", "花字不遮主体动作"],
            "evidence_refs": ["source_media_review", "scene_plan:source_mappings"],
        },
        "fact_continuity": {
            "title": "事实和连续性",
            "summary": f"每句口播必须能被该镜素材画面证明：{claims_txt}。价格/SKU 未知，成片不报价格。",
            "rules": ["口播动作域 == 画面动作域", "不出现价格数字", "抗菌表述只按包装标识口径"],
            "evidence_refs": ["product_facts:claims", "research_synthesis"],
        },
        "originality_boundary": {
            "title": "原创边界",
            "summary": "无参考视频；模板台词与花字为本项目原创，允许进入成片；素材全部自有实拍；不出现第三方品牌 logo 特写（画面内吊牌文字按事实卡口径）。",
            "rules": ["无参考视频，无版权边界问题", "台词/花字为项目原创"],
            "evidence_refs": ["template_pack:source_document"],
        },
    }


def build_pack(pk: str, templates: list[dict]) -> dict:
    source = (Path(__file__).resolve().parent / "towel_creative.py").read_bytes()
    import hashlib
    return {
        "version": "1.0",
        "project_id": f"{pk}-batch",
        "created_at": now(),
        "taxonomy_version": "template-pack@1",
        "source_document": {
            "path": "scripts/towel_batch_2026_09_02/towel_creative.py",
            "sha256": hashlib.sha256(source).hexdigest(),
            "parser_version": "towel-creative@1",
        },
        "templates": [
            {
                "template_id": t["template_id"],
                "sheet_name": f"{PRODUCTS[pk]['name']} {t['archetype']}",
                "archetype": t["archetype"],
                "slots": [
                    {
                        "slot_id": f"{t['template_id']}-slot-{i:03d}",
                        "ordinal": i,
                        "duration_s": s["duration_s"],
                        "shot_language": {"shot_size": None, "camera_movement": None, "camera_angle": None},
                        "visual_content": s["domain"],
                        "overlay_text": s["copy"],
                        "caption_treatment": "subtitle",
                        "effect_treatment": "字幕",
                        "audio_layers": ["人声+背景音乐"],
                        "music_profile": "轻快种草 BGM",
                        "scene": "浴室/居家",
                        "dialogue": s["narration"],
                    }
                    for i, s in enumerate(t["slots"], 1)
                ],
            }
            for t in templates
        ],
        "normalization_warnings": [],
    }


def main() -> int:
    registry.discover()
    templates_all = build_templates()
    for pk in PRODUCT_KEYS:
        pname = PRODUCTS[pk]["name"]
        slug = PRODUCTS[pk]["slug"]
        research = PROJECTS / f"maojin-{slug}" if pk in ("yinlizi", "tiansi") else (
            PROJECTS / f"maojin-{slug}" if pk == "chenxu" else PROJECTS / f"yujin-{slug}")
        research = {"yinlizi": PROJECTS / "maojin-yinlizi", "tiansi": PROJECTS / "maojin-tiansi",
                    "chenxu": PROJECTS / "maojin-chenxu", "yujin": PROJECTS / "yujin-chenxu"}[pk]
        batch_root = init_project(
            f"{slug}-batch", title=f"{pname} 批量混剪批次", pipeline_type="cinematic-fast",
            input_mode="source_led_template",
            template_prior={"present": True, "usage": "structural_only"},
            owned_source_root="inputs/source",
        )

        # 1) 语义路径重建 media_index / source_media_review
        product_dir = research / "inputs" / "source" / "video" / "product"
        semantic_paths = sorted(product_dir.glob("*.MP4"))
        mi = build_media_index(semantic_paths, project_dir=research, registry=registry,
                               analysis_version=ANALYSIS_VERSION)
        smr = review_source_media(semantic_paths,
                                  context={"pipeline_type": "cinematic-fast", "project_dir": str(research)},
                                  tool_registry=_NoTranscribeRegistry(registry), media_index=mi)
        for f in smr.get("files", []):
            _stem = Path(f["path"]).stem
            f["media_id"] = _stem
            f["path"] = f"inputs/source/video/product/{_stem}.MP4"
        write_artifact_atomic("artifacts/source_media_review.json", "source_media_review", smr, project_dir=research)
        print(f"[{pk}] semantic media_index: {len(mi.get('entries', []))} entries")

        # 2) product_facts
        raw_facts = PRODUCTS[pk]["facts"]
        facts = {
            "version": "1.0",
            "product_name": raw_facts["product_name"],
            "sku": raw_facts.get("sku") or "unknown",
            "price": raw_facts.get("price") or "unknown",
            "params": [f"{k}: {v if v else '未知'}" for k, v in raw_facts["params"].items()],
            "provenance": {
                **{f"claim-{i}": c.get("evidence_ref", "") for i, c in enumerate(raw_facts["claims"])},
                "notes": raw_facts.get("notes", ""),
            },
            "visual_identity": {
                "must_preserve": ["产品本体形态", "包装标识文字口径"],
                "allowed_variation": ["角度", "景别", "光照"],
            },
            "claims": [{"claim": c["claim"], "status": "needs_evidence"} for c in raw_facts["claims"]],
            "filled_by": "agent-draft",
            "filled_at": now(),
        }
        write_artifact_atomic("artifacts/product_facts.json", "product_facts", facts, project_dir=research)

        # 3) 窗口分配 + 模板包
        semantic_map = json.loads((research / "analysis" / "semantic_map.json").read_text(encoding="utf-8"))
        templates = templates_all[pk]
        _ev_path = research / "analysis" / "evidence_windows.json"
        _evidence = json.loads(_ev_path.read_text(encoding="utf-8")) if _ev_path.is_file() else None
        bindings = allocate_windows(semantic_map, templates, _evidence)
        pack = build_pack(pk, templates)
        pack_env = write_artifact_atomic("artifacts/template_pack.json", "template_pack", pack, project_dir=batch_root)
        pack_data = pack_env["data"]

        matrix = json.loads((research / "artifacts" / "reference_source_matrix.json").read_text(encoding="utf-8"))
        differentiation_candidates, evidence_refs_by_template = build_differentiation_candidates(
            product_id=slug, templates=templates, bindings=bindings, matrix=matrix,
        )
        research_refs = shared_research_refs(research)
        _, differentiation_ref = persist_canonical_differentiation_plan(
            batch_root,
            batch_id=batch_root.name,
            candidates=differentiation_candidates,
            research_refs=research_refs,
        )

        # 4) run 项目 + run plan + script + proposal/ccp/hook/decision_log + checkpoints
        run_plan_refs: dict[str, dict] = {}
        candidates: list[dict] = []
        for tpl in templates:
            tid = tpl["template_id"]
            run_dir = fork_template_run(f"template-run-{tid}", source_project_dir=research,
                                        pipeline_dir=PROJECTS,
                                        product_facts_path=research / "artifacts" / "product_facts.json",
                                        input_mode="source_led_template",
                                        template_prior={"present": True, "usage": "structural_only",
                                                        "template_pack_ref": "artifacts/template_pack.json"},
                                        template_pack_path=batch_root / "artifacts/template_pack.json",
                                        batch_project_id=batch_root.name)
            run_plan = create_template_run(
                {"template_id": tid, "slots": pack_data["templates"][
                    next(i for i, t in enumerate(pack_data["templates"]) if t["template_id"] == tid)]["slots"]},
                template_pack_ref={"artifact_sha256": pack_data["artifact_sha256"],
                                   "version": pack_data["version"]},
                product_facts_ref={"artifact_sha256": json.loads(
                    (research / "artifacts" / "product_facts.json").read_text(encoding="utf-8")
                ).get("artifact_sha256", "")},
                differentiation_plan_ref=differentiation_ref,
            )
            for b in bindings[tid]:
                run_plan = bind_slot(run_plan, b["slot_id"], source="owned",
                                     source_media_id=b["stem"],
                                     asset_type="video_proxy",
                                     reason=f"{b['domain']} 窗口 {b['start']}-{b['end']}s（素材画面可证）")
            rp_env = write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan",
                                           run_plan, project_dir=run_dir)
            run_plan_refs[tid] = {"artifact_sha256": rp_env["data"]["artifact_sha256"]}

            canonical_template = next(item for item in pack_data["templates"] if item["template_id"] == tid)
            ccp = {
                "version": "1.0", "project_id": run_dir.name, "created_at": now(), "producer": "agent",
                "input_hashes": {"template_pack": pack_data["artifact_sha256"],
                                 "differentiation_plan": differentiation_ref["artifact_sha256"]},
                "differentiation_plan_ref": differentiation_ref,
                "plan_id": tid, "plan_version": 1, "status": "approved",
                "selected_direction_id": f"{tid}-concept",
                "section_reviews": {"content_direction": "approved", "story_pacing": "approved",
                                    "visual_rules": "approved", "fact_continuity": "approved",
                                    "originality_boundary": "approved"},
                "sections": ccp_sections(pk),
            }
            ccp_env = write_artifact_atomic("artifacts/creative_control_plan.json", "creative_control_plan",
                                            ccp, project_dir=run_dir)
            scene_preview = build_canonical_scene_plan_data(
                run_dir, canonical_template, rp_env["data"], ccp_env["data"], facts,
            )
            # script draft（script 门评审对象）；文案只从 canonical evidence matrix 派生。
            _existing_script = run_dir / "artifacts" / "script.json"
            approved_script = False
            if _existing_script.is_file():
                _old = json.loads(_existing_script.read_text(encoding="utf-8"))
                if _old.get("status") == "approved":
                    approved_script = True
            sc_env = build_canonical_script_for_run(
                run_dir, canonical_template, scene_preview, ccp_env["data"], facts,
                title=f"{pname} · {tpl['archetype']} · 30s 混剪", approved=approved_script,
            )
            script = sc_env["data"]

            # proposal + ccp + hook_plan + decision_log
            _NARR = {"测评证明型": "data_narrative", "痛点反转型": "problem_solution",
                     "卖点罗列型": "tutorial", "场景种草型": "story"}
            concept_options = [
                {"id": f"{t['template_id']}-concept",
                 "title": f"{pname} · {t['archetype']}",
                 "hook": t["slots"][0]["narration"],
                 "narrative_structure": _NARR[t["archetype"]],
                 "visual_approach": "竖拍实拍素材 3:4 裁切 + 白字深描边花字 + 硬切",
                 "target_duration_seconds": 30,
                 "why_this_works": "动作-口播一一对应，每句文案都有画面证据",
                 "research_direction_refs": [f"direction-{t['template_id']}"],
                 "fingerprint_rule_refs": ["hook", "proof", "scene_cta"],
                 "matrix_row_refs": evidence_refs_by_template[t["template_id"]]}
                for t in templates
            ]
            proposal = {
                "version": "1.0",
                "differentiation_plan_ref": differentiation_ref,
                "concept_options": concept_options,
                "selected_concept": {"concept_id": f"{tid}-concept",
                                     "rationale": f"{pname} 第 {templates.index(tpl) + 1} 方向：{tpl['archetype']}"},
                "production_plan": {
                    "pipeline": "cinematic-fast",
                    "stages": [
                        {"stage": s, "tools": [], "approach": "canonical 阶段机推进"}
                        for s in ["research", "proposal", "script", "scene_plan", "assets", "sample", "edit", "compose", "publish"]
                    ],
                    "render_runtime": "remotion",
                    "composition_mode": "templated",
                },
                "cost_estimate": {
                    "total_estimated_usd": 0.10,
                    "line_items": [
                        {"tool": "doubao_tts", "operation": "seed-tts-2.0 口播合成", "estimated_usd": 0.05},
                        {"tool": "suno_music", "operation": "轻快种草 BGM 生成", "estimated_usd": 0.05},
                    ],
                    "budget_verdict": "within_budget",
                },
                "approval": {"status": "pending"},
            }
            proposal_env = write_artifact_atomic("artifacts/proposal_packet.json", "proposal_packet", proposal, project_dir=run_dir)

            hook = build_hook_plan(
                run_dir.name,
                creative_control_plan=ccp_env["data"],
                script=sc_env["data"],
                overrides={"hook_pattern": "problem_first" if tpl["archetype"] in ("痛点反转型", "测评证明型") else "other",
                           "first_audio": script["sections"][0]["narration"],
                           "first_frame_visual": script["sections"][0]["visual_intent"],
                           "promise": f"{pname} 实测：吸水快、{PRODUCTS[pk]['facts']['claims'][0]['claim'][:20]}"},
            )
            hook_env = write_artifact_atomic("artifacts/hook_plan.json", "hook_plan", hook, project_dir=run_dir)

            dlog = {
                "version": "1.0", "project_id": run_dir.name,
                "decisions": [
                    {"decision_id": f"{tid}-d1", "stage": "proposal", "category": "pipeline_selection",
                     "subject": "无参考模板主链路",
                     "options_considered": [
                         {"option_id": "reference-driven", "label": "reference 驱动", "score": 0.2, "reason": "无参考视频"},
                         {"option_id": "template-driven", "label": "template_pack + template_run_plan", "score": 1.0, "reason": "batch-002 已验证"}],
                     "selected": "template-driven",
                     "reason": "无参考视频；模板模式为既有验证路径"},
                    {"decision_id": f"{tid}-d2", "stage": "proposal", "category": "render_runtime_selection",
                     "subject": "合成运行时",
                     "options_considered": [
                         {"option_id": "remotion", "label": "Remotion", "score": 1.0, "reason": "历史批次验证路径"},
                         {"option_id": "hyperframes", "label": "HyperFrames", "score": 0.0, "reason": "本机不可用"},
                         {"option_id": "ffmpeg", "label": "FFmpeg", "score": 0.6, "reason": "可用但花字动画弱"}],
                     "selected": "remotion",
                     "reason": "HyperFrames 本机不可用；Remotion 为历史批次验证路径"},
                    {"decision_id": f"{tid}-d3", "stage": "proposal", "category": "composition_mode",
                     "subject": "成片规格",
                     "options_considered": [
                         {"option_id": "douyin-1080", "label": "1080×1920 抖音竖版", "score": 0.0, "reason": "版位不符"},
                         {"option_id": "taobao-3-4", "label": "3:4 2160×2880", "score": 1.0, "reason": "用户指定淘宝详情页主图 3:4"}],
                     "selected": "taobao-3-4",
                     "reason": "用户指定淘宝详情页主图 3:4 版位"},
                    {"decision_id": f"{tid}-d4", "stage": "proposal", "category": "capability_extension",
                     "subject": "品类动作域/文案表",
                     "options_considered": [
                         {"option_id": "patch-lib", "label": "改 lib 硬编码表", "score": 0.2, "reason": "生产期基建改造风险"},
                         {"option_id": "creative-data", "label": "创作数据外置", "score": 1.0, "reason": "关键路径纪律：生产期不做基建改造"}],
                     "selected": "creative-data",
                     "reason": "关键路径纪律：生产期不做基建改造"},
                ],
            }
            dlog_env = write_artifact_atomic("artifacts/decision_log.json", "decision_log", dlog, project_dir=run_dir)

            # checkpoints: proposal completed → script awaiting_human；已批的 script 不回退
            _sc_cp = run_dir / "checkpoint_script.json"
            _script_done = _sc_cp.is_file() and json.loads(_sc_cp.read_text(encoding="utf-8")).get("status") == "completed"
            write_checkpoint(PROJECTS, run_dir.name, "proposal", "completed",
                             {"proposal_packet": proposal_env, "creative_control_plan": ccp_env,
                              "hook_plan": hook_env, "decision_log": dlog_env},
                             pipeline_type="cinematic-fast", next_action=None)
            if _script_done:
                write_checkpoint(PROJECTS, run_dir.name, "script", "completed", {"script": sc_env},
                                 pipeline_type="cinematic-fast", human_approval_required=True,
                                 human_approved=True, next_action=None)
            else:
                write_checkpoint(PROJECTS, run_dir.name, "script", "awaiting_human",
                                 {"script": sc_env},
                                 pipeline_type="cinematic-fast", human_approval_required=True,
                                 human_approved=False,
                                 next_action={"verb": "await_user", "summary": "script 门：人工确认 16 条逐镜文案与商品事实口径",
                                              "context_refs": [f"projects/{run_dir.name}/artifacts/script.json"]})
            candidates.append({
                "candidate_id": f"{slug}-{tpl['template_id'].split('-')[1]}",
                "label": tpl["archetype"], "project_id": run_dir.name, "status": "in_progress",
                "direction": {"hook": tpl["archetype"], "pacing": "steady-reveal", "packaging": "hero-product-macro",
                              "audience": "proof_after_claim", "duration": "30s"},
                "cost_usd": 0.0, "attempts": 0, "failure": None, "notes": "", "iteration": None,
                "parent_candidate_id": None, "mutation": None, "mutation_fingerprint": None,
                "changed_dimensions": [], "failure_dimensions": [], "dimension_scores": {},
            })
            print(f"[{pk}] run {tid}: {len(script['sections'])} sections, "
                  f"{script['total_duration_seconds']}s, script=awaiting_human")

        # 5) template_batch + candidate_batch
        facts_sha = json.loads((research / "artifacts" / "product_facts.json").read_text(encoding="utf-8")).get("artifact_sha256", "")
        tb = build_canonical_template_batch(
            pack_data,
            product_facts_ref={"artifact_sha256": facts_sha},
            batch_id=batch_root.name,
            template_run_plan_refs=run_plan_refs,
            shared_research_refs=research_refs,
            max_parallel=2, max_cost_usd=20.0, publish_policy="selective", render_runtime="remotion",
            differentiation_plan_ref=differentiation_ref,
        )
        write_artifact_atomic("artifacts/template_batch.json", "template_batch", tb, project_dir=batch_root)
        cb = {
            "version": "1.0", "batch_id": f"{slug}-batch", "project_id": f"{slug}-batch",
            "created_at": now(),
            "shared_research": {"refs": shared_research_refs(research)},
            "source_media_refs": [str(p.relative_to(PROJECTS)) for p in semantic_paths],
            "concurrency": {"max_candidates": 4, "max_parallel": 2},
            "budget": {"max_cost_usd": 20.0, "max_latency_minutes": 300.0, "max_retries_per_candidate": 2},
            "differentiation_axes": {"hook": True, "pacing": True, "packaging": True, "audience": True, "duration": True},
            "diversity_mode": "warning",
            "differentiation_plan_ref": differentiation_ref,
            "candidates": candidates,
            "selection": {"selected_candidate_ids": [], "selected_at": None, "reason": ""},
        }
        write_artifact_atomic("artifacts/candidate_batch.json", "candidate_batch", cb, project_dir=batch_root)
        print(f"[{pk}] batch root {batch_root.name}: template_batch + candidate_batch (4 runs)")
    print("[done] stage 2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
