"""Build four silver-ion towel script candidates through the cinematic-fast mainline.

The command stops at the script human gate.  It reuses the approved research
and product-facts card, while each candidate gets its own template/run plan,
evidence order, timing profile, proposal, creative-control plan and draft
script.  No TTS, music or render provider is called here.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import init_project, refresh_checkpoint_envelopes
from lib.differentiation import build_differentiation_plan
from lib.template_batch import create_template_batch, mark_pilot
from lib.template_fork import fork_template_run, shared_research_refs
from lib.template_mainline import advance_run_full
from lib.yinlizi_variants import VARIANT_SPECS, build_variant_definition
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
SOURCE_RUN = "template-run-yinlizi-aligned-A"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(project: Path, filename: str, artifact_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return write_artifact_atomic(
        f"artifacts/{filename}", artifact_name, data, project_dir=project
    )


def _signature(definition: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    rows = {
        str(row.get("matrix_row_id")): row
        for row in matrix.get("rows", [])
        if isinstance(row, dict)
    }
    refs = [f"evidence-coverage-{row:03d}" for row in definition["row_order"]]
    action_keys = [
        key
        for ref in refs
        for key in rows.get(ref, {}).get("action_keys", [])
    ]
    copy_text = " ".join(
        str(word)
        for ref in refs
        for word in rows.get(ref, {}).get("allowed_wording", [])
    )
    return {
        "candidate_id": f"yinlizi-{definition['variant_id']}",
        "product_id": "1060430166297",
        "hook_pattern": definition["variant_id"],
        "primary_action_keys": tuple(action_keys[:2]),
        "action_keys": tuple(action_keys),
        "copy_text": copy_text,
        "beat_durations": tuple(
            float(slot["duration_s"]) for slot in definition["template"]["slots"]
        ),
        "beat_order": tuple(refs),
        "scene_context": definition["label"],
        "pacing_curve": definition["variant_id"],
        "caption_strategy": "taobao_3_4_two_layer",
        "audio_strategy": "doubao_tts_suno_bgm_reuse",
        "forbidden_repeats": ["水滴一沾上", "5秒吸干", "滚筒一滚就干"],
        "matrix_row_refs": tuple(refs),
    }


def _run_id(batch_id: str, variant_id: str) -> str:
    return f"{batch_id}-{variant_id}"


def _bind_batch_run_ids(batch: dict[str, Any], batch_id: str) -> dict[str, Any]:
    bound = deepcopy(batch)
    run_ids_by_template: dict[str, str] = {}
    for run in bound.get("runs", []):
        template_id = str(run.get("template_id") or "")
        variant_id = template_id.removeprefix("yinlizi-")
        project_id = _run_id(batch_id, variant_id)
        run["project_id"] = project_id
        run_ids_by_template[template_id] = project_id
    bound["pilot_run_ids"] = [
        run_ids_by_template.get(str(value), str(value))
        for value in bound.get("pilot_run_ids", [])
    ]
    return bound


def build_batch(batch_id: str = "yinlizi-variants-batch") -> dict[str, Any]:
    source = PROJECTS / SOURCE_RUN
    batch = init_project(
        batch_id,
        title="银离子毛巾四方向脚本候选",
        pipeline_type="cinematic-fast",
        pipeline_dir=PROJECTS,
        input_mode="source_led_template",
        template_prior={
            "present": True,
            "usage": "structural_only",
            "template_pack_ref": f"projects/{batch_id}/artifacts/template_pack.json",
        },
        product_input=_load(source / "project.json").get("product_input"),
        owned_source_root="inputs/source",
    )
    base_pack = _load(source / "artifacts/template_pack.json")
    base_template = deepcopy(base_pack["templates"][0])
    base_run_plan = _load(source / "artifacts/template_run_plan.json")
    facts = _load(source / "artifacts/product_facts.json")
    matrix = _load(source / "artifacts/reference_source_matrix.json")
    definitions = [
        build_variant_definition(base_template, base_run_plan, spec)
        for spec in VARIANT_SPECS
    ]

    variant_pack = deepcopy(base_pack)
    variant_pack["project_id"] = batch_id
    variant_pack["templates"] = [item["template"] for item in definitions]
    variant_pack.pop("semantic_sha256", None)
    variant_pack.pop("artifact_sha256", None)
    variant_pack = attach_hashes(variant_pack)
    validate_artifact("template_pack", variant_pack)
    pack_env = _write(batch, "template_pack.json", "template_pack", variant_pack)
    facts_env = _write(batch, "product_facts.json", "product_facts", facts)

    research_refs = shared_research_refs(source)
    diff_plan = build_differentiation_plan(
        batch_id,
        [_signature(item, matrix) for item in definitions],
        research_refs=research_refs,
    )
    diff_env = _write(batch, "differentiation_plan.json", "differentiation_plan", diff_plan)
    diff_ref = {
        "name": "differentiation_plan",
        "path": "artifacts/differentiation_plan.json",
        "artifact_sha256": diff_env["data"]["artifact_sha256"],
    }

    run_plan_refs: dict[str, dict[str, str]] = {}
    for definition in definitions:
        variant_id = definition["variant_id"]
        run_id = _run_id(batch_id, variant_id)
        run_dir = fork_template_run(
            run_id,
            source_project_dir=source,
            pipeline_dir=PROJECTS,
            product_facts_path=source / "artifacts/product_facts.json",
            input_mode="source_led_template",
            template_prior={
                "present": True,
                "usage": "structural_only",
                "template_pack_ref": f"projects/{batch_id}/artifacts/template_pack.json",
            },
            template_pack_path=batch / "artifacts/template_pack.json",
            batch_project_id=batch_id,
        )
        run_plan = deepcopy(definition["run_plan"])
        run_plan["run_id"] = run_id
        run_plan["template_pack_ref"] = {
            "artifact_sha256": pack_env["data"]["artifact_sha256"],
            "version": str(variant_pack.get("version") or "1.0"),
        }
        run_plan["product_facts_ref"] = {
            "artifact_sha256": facts_env["data"]["artifact_sha256"]
        }
        run_plan["differentiation_plan_ref"] = diff_ref
        run_plan = attach_hashes(run_plan)
        validate_artifact("template_run_plan", run_plan)
        _write(run_dir, "template_run_plan.json", "template_run_plan", run_plan)
        refresh_checkpoint_envelopes(
            PROJECTS, run_id, pipeline_type="cinematic-fast"
        )
        run_plan_refs[str(definition["template"]["template_id"])] = {
            "artifact_sha256": run_plan["artifact_sha256"]
        }

        marker_path = run_dir / "project.json"
        marker = _load(marker_path)
        marker["variant"] = {
            "id": variant_id,
            "label": definition["label"],
            "hook": definition["hook"],
            "row_order": definition["row_order"],
            "baseline_project": SOURCE_RUN,
            "status": "script_review_pending",
        }
        marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
        advance_run_full(run_id, pipeline_dir=PROJECTS, approve_control_plan=True)

    template_batch = create_template_batch(
        variant_pack,
        product_facts_ref={"artifact_sha256": facts_env["data"]["artifact_sha256"]},
        batch_id=batch_id,
        template_run_plan_refs=run_plan_refs,
        shared_research_refs=research_refs,
        max_parallel=2,
        max_cost_usd=4.0,
        publish_policy="selective",
        render_runtime="remotion",
        differentiation_plan_ref=diff_ref,
    )
    template_batch = mark_pilot(
        template_batch,
        [str(item["template"]["template_id"]) for item in definitions],
    )
    template_batch = _bind_batch_run_ids(template_batch, batch_id)
    template_batch = attach_hashes(template_batch)
    validate_artifact("template_batch", template_batch)
    _write(batch, "template_batch.json", "template_batch", template_batch)
    return {
        "batch_id": batch_id,
        "batch_dir": str(batch),
        "run_ids": [_run_id(batch_id, item["variant_id"]) for item in definitions],
        "template_batch": template_batch,
        "differentiation_plan": diff_plan,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", default="yinlizi-variants-batch")
    args = parser.parse_args()
    result = build_batch(args.batch)
    print(json.dumps({
        "batch_id": result["batch_id"],
        "batch_dir": result["batch_dir"],
        "run_ids": result["run_ids"],
        "status": result["template_batch"]["status"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
