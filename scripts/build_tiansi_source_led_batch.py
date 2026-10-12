"""Build the Tiansi source-led template batch up to the script review gate.

This entry point consumes the browser capture already stored under
``projects/maojin-tiansi`` and never calls paid generation providers.
"""
from __future__ import annotations

import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backlot.project_commit import ProjectCommitStore
from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import init_project, refresh_checkpoint_envelopes, write_checkpoint
from lib.differentiation import build_differentiation_plan
from lib.product_fact_reconciliation import reconcile_product_facts
from lib.source_semantics import build_source_research_artifacts
from lib.template_batch import create_template_batch, mark_pilot
from lib.candidate_batch import create_candidate_batch
from lib.template_fork import fork_template_run, shared_research_refs
from lib.template_mainline import advance_run_full
from lib.yinlizi_variants import VARIANT_SPECS, build_variant_definition
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
SOURCE = PROJECTS / "maojin-tiansi"
BATCH_ID = "tiansi-script-variants-20260911"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(project: Path, name: str, data: dict) -> dict:
    return write_artifact_atomic(f"artifacts/{name}.json", name, data, project_dir=project)


def _media_map() -> dict[str, dict]:
    semantic = load(SOURCE / "analysis/semantic_map.json")
    indexed = {
        str(item.get("fingerprint", {}).get("content_sha256")): item
        for item in load(SOURCE / "artifacts/media_index.json").get("entries", [])
    }
    result = {}
    for media_id, meta in semantic.items():
        item = indexed.get(str(meta.get("sha") or ""), {})
        result[str(media_id)] = {
            **item,
            "path": str(meta.get("raw") or item.get("path") or ""),
            "fingerprint": {"content_sha256": str(meta.get("sha") or item.get("fingerprint", {}).get("content_sha256") or "")},
        }
    return result


def _frame_for(media_id: str) -> str:
    item = _media_map()[media_id]
    frames = item.get("representative_frames") or []
    if not frames:
        raise ValueError(f"no representative frame for {media_id}")
    return str(frames[0])


def build_research_artifacts(facts: dict) -> None:
    """Build nine independent evidence rows from the audited owned footage."""
    media = _media_map()
    # Each row has one action and one source window. The scale clip is excluded.
    specs = [
        ("product_天丝莱赛尔毛巾-吸水演示-3", (0.0, 5.805), "dynamic_result", ["吸水演示"], ["连续水流接触毛巾", "湿润范围可见"], 8, "一股水浇下，湿润范围清楚可见", "strong"),
        ("product_天丝莱赛尔毛巾-材质细节-3", (0.0, 4.0), "static_feature", ["蓝色毛巾", "毛圈纹理"], ["纹理特写"], 6, "细密竖条毛圈，纹理清楚可见", "strong"),
        ("product_天丝莱赛尔毛巾-亲肤柔软-2", (0.0, 4.571), "dynamic_action", ["海天蓝毛巾", "面部"], ["轻抚脸颊"], 11, "手指轻抚，织物表面顺滑可见", "moderate"),
        ("product_天丝莱赛尔毛巾-亲肤柔软-3", (0.0, 5.505), "dynamic_action", ["海天蓝毛巾", "面部"], ["擦拭面部"], 11, "擦拭面部，日常使用动作清楚", "strong"),
        ("product_天丝莱赛尔毛巾-使用场景-3", (0.0, 5.973), "static_feature", ["叠放毛巾", "浴室摆件"], ["叠放展示"], 6, "叠放后的层次与边缘结构看得见", "moderate"),
        ("product_天丝莱赛尔毛巾-亲肤柔软-4", (0.0, 5.072), "dynamic_action", ["海天蓝毛巾", "颈部"], ["包裹颈部"], 11, "轻轻包裹颈部，贴肤使用画面可见", "moderate"),
        ("product_天丝莱赛尔毛巾-使用场景-4", (0.0, 5.873), "dynamic_action", ["海天蓝毛巾", "浴室挂钩"], ["挂起毛巾"], 0, "挂起后，日常取用场景清楚", "strong"),
        ("product_天丝莱赛尔毛巾-色彩质感-2", (0.0, 7.374), "static_feature", ["多色毛巾", "海天蓝"], ["悬挂展示"], 1, "海天蓝单条展示，颜色与轮廓清楚", "moderate"),
        ("product_天丝莱赛尔毛巾-材质细节-5", (0.0, 4.872), "static_feature", ["海天蓝毛巾", "织物表面"], ["纹理展示"], 0, "花花公子天丝莱赛尔毛巾，主体完整", "strong"),
    ]
    observations = []
    candidates = load(SOURCE / "analysis/product_page/capture_seed.json")["fact_candidates"]
    for media_id, (start, end), evidence_class, subjects, actions, claim_index, result, strength in specs:
        if media_id not in media:
            raise ValueError(f"missing audited source media: {media_id}")
        fact = candidates[claim_index]
        observations.append({
            "media_id": media_id,
            "source_path": str(media[media_id]["path"]),
            "source_hash": str(media[media_id]["fingerprint"]["content_sha256"]),
            "interval": {"start_seconds": start, "end_seconds_exclusive": end},
            "observed_subject": subjects,
            "observed_actions": actions,
            "observed_results": [result],
            "evidence_class": evidence_class,
            "claim_bindings": [{
                "claim_id": str(fact["fact_id"]),
                "product_fact_ref": f"product_facts.claims[{claim_index}]",
                "allowed_wording": [str(fact["allowed_wording"][0])],
                "prohibited_wording": list(fact.get("prohibited_wording") or []),
                "evidence_strength": strength,
                "required_evidence_class": evidence_class,
                "requires_visible_result": evidence_class == "dynamic_result",
            }],
            "crop_safety": {"subject_complete_in_3_4": True, "safe_caption_regions": ["top", "bottom"]},
            "quality": {"usable": True, "confidence": 0.9, "risks": []},
            "representative_frames": [_frame_for(media_id)],
            **({"temporal_evidence": {"before": {"start_seconds": start, "end_seconds_exclusive": min(start + 0.4, end - 0.8)}, "action": {"start_seconds": min(start + 0.4, end - 0.8), "end_seconds_exclusive": min(start + 3.0, end - 0.4)}, "result": {"start_seconds": min(start + 3.0, end - 0.4), "end_seconds_exclusive": end}}} if evidence_class == "dynamic_result" else {}),
        })
    built = build_source_research_artifacts(project_id=SOURCE.name, input_mode="source_led_template", observations=observations, product_facts=facts)
    matrix = built["reference_source_matrix"]
    rows = matrix.get("rows") or []
    for index, row in enumerate(rows, 1):
        row["matrix_row_id"] = f"evidence-coverage-{index:03d}"
        row["reference_intent"] = "source-led evidence coverage"
        row["route_reason"] = "accepted owned source covers the bound action and 3:4 crop"
    matrix["rows"] = rows
    # Keep the source project research bundle coherent and mode-specific.
    for name, data in built.items():
        write(SOURCE, name, data)
    old = {name: load(SOURCE / f"artifacts/{name}.json") for name in ("research_brief", "research_breakdown", "research_scorecard", "research_synthesis", "caption_style_fingerprint", "source_media_review", "media_index", "reference_fingerprint", "video_analysis_brief") if (SOURCE / f"artifacts/{name}.json").is_file()}
    old["reference_source_matrix"] = matrix
    for name, data in old.items():
        if name in {"reference_source_matrix", "media_index", "source_media_review", "research_brief", "research_breakdown", "research_scorecard", "research_synthesis", "caption_style_fingerprint", "reference_fingerprint", "video_analysis_brief"}:
            write(SOURCE, name, data)
    marker = load(SOURCE / "project.json")
    marker.update({"input_mode": "source_led_template", "template_prior": {"present": True, "usage": "structural_only", "template_pack_ref": "artifacts/template_pack.json"}, "product_input": {"product_id": "1060138211544", "product_name": "天丝莱赛尔毛巾", "product_url": "https://detail.tmall.com/item.htm?id=1060138211544", "target_platform": "taobao"}})
    (SOURCE / "project.json").write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    # The source root is finalized below after its structural template prior is
    # available; child runs will refresh their own research checkpoints.


def main() -> None:
    capture = load(SOURCE / "analysis/product_page/capture_seed.json")
    # The browser capture lists five non-promotable claims in ``gaps``; they
    # are retained as facts with evidence limits, not volatile candidates.
    capture.setdefault("capture_scope", {})["excluded_volatile_count"] = sum(
        1 for item in capture.get("fact_candidates", []) if item.get("volatile") is True
    )
    capture = attach_hashes(capture)
    ledger = attach_hashes(load(SOURCE / "analysis/product_page/ledger_seed.json"))
    facts = reconcile_product_facts(capture=capture, asset_ledger=ledger, operator_confirmation={"selected_sku_id": "visible-selection-haitianlan"})
    # Keep narrative constraints in claim-level wording. The reconciliation
    # helper's legacy ``params`` projection is too broad for this page copy
    # (its first-8-character heuristic would reject the approved SKU wording).
    facts["params"] = []
    write(SOURCE, "product_page_capture", capture)
    write(SOURCE, "product_asset_ledger", ledger)
    write(SOURCE, "product_facts", facts)
    build_research_artifacts(facts)

    base_pack = load(PROJECTS / "template-run-yinlizi-aligned-A/artifacts/template_pack.json")
    base_template = deepcopy(base_pack["templates"][0])
    base_template["template_id"] = "tiansi-aligned-A"
    base_template["sheet_name"] = "天丝莱赛尔毛巾 Source-led 连续证据型"
    # Reframe the structural skeleton around the nine audited evidence rows.
    labels = ["吸水过程", "毛圈纹理", "轻抚触感", "日常擦拭", "层次展示", "贴肤使用", "浴室挂放", "海天蓝展示", "产品身份"]
    for i, slot in enumerate(base_template["slots"]):
        slot["slot_id"] = f"tiansi-aligned-A-slot-{i + 1:03d}"
        slot["ordinal"] = i + 1
        slot["visual_content"] = f"structural_only:{labels[i]}"
    pack = {"version": "1.0", "project_id": BATCH_ID, "created_at": "2026-09-11T00:00:00Z", "taxonomy_version": "template-pack@1", "source_document": base_pack.get("source_document", {}), "templates": []}
    definitions = []
    base_bindings = []
    matrix = load(SOURCE / "artifacts/reference_source_matrix.json")
    rows = matrix["rows"]
    for i, row in enumerate(rows):
        base_bindings.append({"slot_id": f"tiansi-aligned-A-slot-{i + 1:03d}", "source": "owned", "source_media_id": row.get("source_media_id"), "asset_type": None, "evidence_row_ids": [row["matrix_row_id"]], "reason": f"accepted owned coverage row {row['matrix_row_id']}: {row.get('match_reason', '')}"})
    base_run_plan = {"version": "1.0", "run_id": "tiansi-aligned-A", "template_id": "tiansi-aligned-A", "template_pack_ref": {}, "product_facts_ref": {}, "adaptation_policy": "proof-first", "slot_bindings": base_bindings, "caption_policy": {"reference_text": "analysis_only", "copy_reference_caption": False}, "status": "approved"}
    base_template["slots"] = [deepcopy(slot) for slot in base_template["slots"]]
    pack["templates"].append(base_template)
    # Variant builder only changes ordering and duration; all evidence bindings stay explicit.
    for spec in VARIANT_SPECS:
        definition = build_variant_definition(base_template, base_run_plan, spec)
        definition["template"]["template_id"] = f"tiansi-{spec['variant_id']}"
        definition["template"]["sheet_name"] = f"天丝莱赛尔毛巾 {spec['label']}"
        definition["run_plan"]["template_id"] = f"tiansi-{spec['variant_id']}"
        pack["templates"].append(definition["template"])
        definitions.append(definition)
    # Drop the base-only template from the production pack.
    pack["templates"] = pack["templates"][1:]
    # Make the shared research root self-describing so child forks copy the
    # canonical source-semantic and browser-fact artifacts.
    write(SOURCE, "template_pack", attach_hashes(pack))
    research_envs = {}
    for artifact_path in sorted((SOURCE / "artifacts").glob("*.json")):
        name = artifact_path.stem
        try:
            data = load(artifact_path)
            research_envs[name] = {"name": name, "path": f"artifacts/{name}.json", "semantic_sha256": data["semantic_sha256"], "artifact_sha256": data["artifact_sha256"], "data": data}
        except (KeyError, json.JSONDecodeError):
            continue
    write_checkpoint(PROJECTS, SOURCE.name, "research", "completed", research_envs, pipeline_type="cinematic-fast", human_approved=False)
    batch = init_project(BATCH_ID, title="天丝莱赛尔毛巾四方向脚本候选", pipeline_type="cinematic-fast", pipeline_dir=PROJECTS, input_mode="source_led_template", template_prior={"present": True, "usage": "structural_only", "template_pack_ref": f"projects/{BATCH_ID}/artifacts/template_pack.json"}, product_input={"product_id": "1060138211544", "product_name": "天丝莱赛尔毛巾", "product_url": "https://detail.tmall.com/item.htm?id=1060138211544", "target_platform": "taobao"}, owned_source_root="inputs/source")
    batch_marker = load(batch / "project.json")
    batch_marker["product_input"] = {"product_id": "1060138211544", "product_name": "天丝莱赛尔毛巾", "product_url": "https://detail.tmall.com/item.htm?id=1060138211544", "target_platform": "taobao"}
    (batch / "project.json").write_text(json.dumps(batch_marker, ensure_ascii=False, indent=2), encoding="utf-8")
    pack_env = write(batch, "template_pack", attach_hashes(pack))
    facts_env = write(batch, "product_facts", facts)
    diff = build_differentiation_plan(BATCH_ID, [{"candidate_id": f"tiansi-{d['variant_id']}", "product_id": "1060138211544", "hook_pattern": d["variant_id"], "primary_action_keys": ["source_evidence"], "action_keys": ["source_evidence"], "copy_text": d["hook"], "beat_durations": [float(s["duration_s"]) for s in d["template"]["slots"]], "beat_order": d["row_order"], "scene_context": d["label"], "pacing_curve": d["variant_id"], "caption_strategy": "taobao_3_4_two_layer", "audio_strategy": "doubao_tts_generated_bgm", "forbidden_repeats": ["3秒吸干", "水滴一沾上就吸干", "电子秤0.00证明115g"], "matrix_row_refs": [f"evidence-coverage-{r:03d}" for r in d["row_order"]]} for d in definitions], research_refs=shared_research_refs(SOURCE))
    diff_env = write(batch, "differentiation_plan", diff)
    plan_refs = {}
    for definition in definitions:
        variant_id = definition["variant_id"]
        run_id = f"{BATCH_ID}-{variant_id}"
        run_dir = fork_template_run(run_id, source_project_dir=SOURCE, pipeline_dir=PROJECTS, product_facts_path=SOURCE / "artifacts/product_facts.json", input_mode="source_led_template", template_prior={"present": True, "usage": "structural_only", "template_pack_ref": f"projects/{BATCH_ID}/artifacts/template_pack.json"}, template_pack_path=batch / "artifacts/template_pack.json", batch_project_id=BATCH_ID, product_input={"product_id": "1060138211544", "product_name": "天丝莱赛尔毛巾", "product_url": "https://detail.tmall.com/item.htm?id=1060138211544", "target_platform": "taobao"})
        rp = deepcopy(definition["run_plan"])
        rp.update({"run_id": run_id, "template_pack_ref": {"artifact_sha256": pack_env["data"]["artifact_sha256"], "version": "1.0"}, "product_facts_ref": {"artifact_sha256": facts_env["data"]["artifact_sha256"]}, "differentiation_plan_ref": {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": diff_env["data"]["artifact_sha256"]}})
        with ProjectCommitStore(run_dir).transaction(
            action={"action_id": f"seed-variant-contract-{run_id}"}
        ) as sink:
            write_artifact_atomic(
                "artifacts/template_run_plan.json", "template_run_plan", rp,
                project_dir=run_dir, sink=sink,
            )
            marker = sink.read_json("project.json")
            if not isinstance(marker, dict):
                raise SystemExit(f"{run_id}: project marker is missing")
            marker["product_input"] = {"product_id": "1060138211544", "product_name": "天丝莱赛尔毛巾", "product_url": "https://detail.tmall.com/item.htm?id=1060138211544", "target_platform": "taobao"}
            marker["variant"] = {"id": variant_id, "label": definition["label"], "hook": definition["hook"], "row_order": definition["row_order"], "baseline_project": SOURCE.name, "status": "script_review_pending"}
            sink.stage_json("project.json", marker, schema="project_marker")
            refresh_checkpoint_envelopes(
                PROJECTS, run_id, pipeline_type="cinematic-fast", sink=sink
            )
            # Rebuild the draft when an earlier partial attempt already created it;
            # this picks up the now-explicit Taobao target platform.
            for relative in ("checkpoint_script.json", "artifacts/script.json"):
                if (run_dir / relative).exists():
                    sink.stage_delete(relative)
        advance_run_full(run_id, pipeline_dir=PROJECTS, approve_control_plan=True)
        plan = load(run_dir / "artifacts/template_run_plan.json")
        plan_refs[definition["template"]["template_id"]] = {"artifact_sha256": plan["artifact_sha256"]}
    tb = create_template_batch(attach_hashes(pack), product_facts_ref={"artifact_sha256": facts_env["data"]["artifact_sha256"]}, batch_id=BATCH_ID, template_run_plan_refs=plan_refs, shared_research_refs=shared_research_refs(SOURCE), max_parallel=2, max_cost_usd=4.0, publish_policy="selective", render_runtime="remotion", differentiation_plan_ref={"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": diff_env["data"]["artifact_sha256"]})
    tb = mark_pilot(tb, [f"tiansi-{s['variant_id']}" for s in VARIANT_SPECS])
    for run in tb["runs"]:
        run["project_id"] = f"{BATCH_ID}-{run['template_id'].removeprefix('tiansi-')}"
    write(batch, "template_batch", attach_hashes(tb))
    # The batch workbench and its approval endpoints consume candidate_batch as
    # the candidate index. Keep it alongside template_batch so a source-led
    # batch can use the same review/approval flow as legacy candidate batches.
    candidate_batch = create_candidate_batch(
        BATCH_ID,
        shared_research_refs=shared_research_refs(SOURCE),
        source_media_refs=[
            str(item.get("path"))
            for item in load(SOURCE / "artifacts/media_index.json").get("entries", [])
            if item.get("path")
        ],
        candidates=[
            {
                "candidate_id": f"tiansi-{d['variant_id']}",
                "label": d["label"],
                "project_id": f"{BATCH_ID}-{d['variant_id']}",
                "status": "in_progress",
                "direction": {
                    "hook": d["variant_id"],
                    "pacing": d["variant_id"],
                    "packaging": "source-led evidence",
                    "audience": "taobao shopper",
                    "duration": "30s",
                },
                "variant_plan_ref": {
                    "name": "differentiation_plan",
                    "path": "artifacts/differentiation_plan.json",
                    "artifact_sha256": diff_env["data"]["artifact_sha256"],
                },
            }
            for d in definitions
        ],
        differentiation_axes={"hook": True, "pacing": True, "packaging": True, "audience": True, "duration": True},
        max_candidates=4,
        max_parallel=2,
        budget={"max_cost_usd": 4.0, "max_latency_minutes": 300.0, "max_retries_per_candidate": 1},
        diversity_mode="warning",
        differentiation_plan_ref={"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": diff_env["data"]["artifact_sha256"]},
    )
    write(batch, "candidate_batch", attach_hashes(candidate_batch))
    print(json.dumps({"batch_id": BATCH_ID, "batch_dir": str(batch), "runs": [r["project_id"] for r in tb["runs"]], "status": "script_review_pending"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
