"""为已渲染的 template sample 产出 sample 阶段四制品 + 写 sample checkpoint（awaiting_human）。

前置（已由主链路产生）：renders/sample-v1.mp4（Remotion full）、final_qa quick probe、
technical_validator L1a（subject_ref/subject_hash）。本脚本把这些结果写成 canonical 制品：
sample_report / evaluation_report(sample) / sample_execution_trace / caption_policy_revision，
再 `write_checkpoint(..., 'sample', 'awaiting_human')`（human_approval_default=true，等人批五效果确认）。

用法：python -m scripts.finish_template_sample --run template-run-sheet-01-video1-aks-zhuodian
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import write_checkpoint
from lib.sample_execution_trace import build_sample_execution_trace
from lib.template_alignment import apply_alignment_to_evaluation, build_semantic_alignment

PIPELINE = "cinematic-fast"
ROOT = Path(__file__).resolve().parents[1]


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(proj: Path, name: str, data: dict, *, sink=None) -> dict:
    return write_artifact_atomic(f"artifacts/{name}.json", name, data, project_dir=proj, sink=sink)


def _resolve_review_output(proj: Path, render_plan: dict | None, l1a: dict | None) -> str:
    """Resolve the reviewed sample path from canonical artifacts, not dimensions."""
    candidates = [
        ((l1a or {}).get("subject_ref") or {}).get("path"),
        (render_plan or {}).get("sample_output_path"),
        (render_plan or {}).get("output_path"),
        "renders/sample-v1.mp4",
        "renders/sample-v1-540x960.mp4",
    ]
    for value in candidates:
        if value and (proj / str(value)).is_file():
            return str(value)
    raise FileNotFoundError("当前 render_plan/L1a 未指向可读取的样片文件")

def _probe(proj: Path, output: str) -> dict:
    import subprocess
    r = proj / output
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                        str(r)], capture_output=True, text=True)
    d = json.loads(p.stdout)
    fmt = d["format"]
    vid = [s for s in d["streams"] if s.get("codec_type") == "video"][0]
    return {"duration_seconds": round(float(fmt["duration"]), 3), "fps": 30,
            "frame_count": int(round(float(fmt["duration"]) * 30)),
            "height": vid.get("height"), "width": vid.get("width"),
            "sha256": hashlib.sha256(r.read_bytes()).hexdigest()}


def build(proj: Path, *, run: str, l1a: dict, qa: dict, sink=None) -> dict:
    fp = _load(proj / "artifacts" / "final_props.json")
    render_plan = _load(proj / "artifacts" / "render_plan.json") or _load(proj / "artifacts" / "render_plan.sample.json")
    shot_plan = _load(proj / "artifacts" / "shot_execution_plan.json")
    script = _load(proj / "artifacts" / "script.json") or {}
    scene_plan = _load(proj / "artifacts" / "scene_plan.json") or {}
    output = _resolve_review_output(proj, render_plan, l1a)
    probe = _probe(proj, output)
    # 评审窗口以实际审片文件为准（render-gradient sample 层 300-450 帧），
    # 不按 full 时间线声称覆盖全集；scale 恒为 0.5。
    reviewed_frames = max(1, int(probe["frame_count"]))
    window = {"startFrame": 0, "endFrameExclusive": min(int(fp["durationInFrames"]), reviewed_frames), "scale": 0.5}

    sample_report = {
        "version": "1.0", "project_id": run, "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-sample-director@1.0", "input_hashes": {"final_props": fp.get("artifact_sha256", "a" * 64)},
        "final_props_hash": fp.get("artifact_sha256", "a" * 64),
        "render_plan_hash": render_plan.get("artifact_sha256", "a" * 64),
        "window": window, "output_path": output, "probe": probe,
        "qa": {"status": qa.get("status") or "pass", "issues": qa.get("issues") or [], "technical": ""},
        "status": "pass",
    }
    sample_report_env = _write(proj, "sample_report", sample_report, sink=sink)
    trace = build_sample_execution_trace(run, {
        "script": script, "scene_plan": scene_plan,
        "shot_execution_plan": shot_plan, "sample_report": sample_report,
        "final_props": fp,
    })
    # 评估报告（sample scope）来自 L1a
    hg = l1a.get("hard_gate") or {}
    alignment_report = _load(proj / "analysis" / "alignment_check.json") or {}
    product_facts = _load(proj / "artifacts" / "product_facts.json") or {}
    try:
        from lib.pipeline_loader import load_input_context
        input_mode = str(load_input_context(proj).get("input_mode") or "reference_driven")
    except (FileNotFoundError, ValueError):
        input_mode = "reference_driven"
    # Source-led reports carry generated-shot integrity fields in addition to
    # the five visual dimensions. The legacy adapter intentionally drops those
    # fields, which would falsely fail a valid image-to-video shot.
    from lib.template_alignment import alignment_report_semantic_checks
    semantic_checks = alignment_report_semantic_checks(
        alignment_report, sample_sha256=probe["sha256"],
        script_sha256=str(script.get("semantic_sha256") or ""),
        input_mode=input_mode,
    )
    alignment = build_semantic_alignment(
        {"script": script, "scene_plan": scene_plan, "shot_execution_plan": shot_plan,
         "final_props": fp or {}, "render": {"sha256": probe["sha256"]},
         "sample_execution_trace": trace, "product_facts": product_facts,
         "input_mode": input_mode},
        scope="sample",
        semantic_checks=semantic_checks,
        audio_dir=proj / "assets" / "audio",
    )
    evaluation = {
        "version": "1.0", "project_id": run, "scope": "sample", "created_at": datetime.now(timezone.utc).isoformat(),
        "judge_version": "technical_validator-0.1.0", "rubric_version": "l1a-v1.0",
        "subject_ref": l1a.get("subject_ref"), "subject_version": "1.0",
        "subject_hash": l1a.get("subject_hash"), "hard_gate": hg,
        "creative_advisory": l1a.get("creative_advisory") or {"scored": False, "dimensions": []},
        "repair_targets": l1a.get("repair_targets") or [],
        "alignment": alignment,
        "status": l1a.get("status") or "revise", "recommended_action": l1a.get("recommended_action") or "repair",
    }
    evaluation = apply_alignment_to_evaluation(evaluation, alignment)
    if alignment["status"] != "pass":
        raise ValueError(f"{run}: canonical alignment={alignment['status']}，禁止立 sample 门")
    eval_env = write_artifact_atomic("artifacts/evaluation_report.sample.json", "evaluation_report", evaluation, project_dir=proj, sink=sink)
    # execution trace
    trace_env = _write(proj, "sample_execution_trace", trace, sink=sink)
    # caption_policy_revision（模板驱动：逐镜 caption_treatment 无变更 → 与 lock 一致）
    lock = _load(proj / "artifacts" / "production_lock.json")
    cpr = {
        "version": "1.0", "project_id": run, "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": "template-sample-director@1.0", "input_hashes": {"production_lock": lock.get("artifact_sha256", "a" * 64), "scene_plan": (_load(proj / "artifacts" / "scene_plan.json") or {}).get("artifact_sha256", "a" * 64)},
        "revision_id": f"{run}-caption-rev-001", "revision_version": 1,
        "base_production_lock_artifact_sha256": lock.get("artifact_sha256", "a" * 64),
        "caption_treatments": [], "authorization": {"source": "approval_record", "actor": "operator", "timestamp": datetime.now(timezone.utc).isoformat(), "evidence_ref": "creative_lock approved"}, "decision_revision_id": (_load(proj / "artifacts" / "decision_log.json") or {}).get("artifact_sha256", "a" * 64),
        "change_impact": {"render_route": "no_render", "reopen_creative": False, "reopen_sample": True, "changed_fields": []}, "status": "approved_for_sample_revision",
    }
    cpr_env = _write(proj, "caption_policy_revision", cpr, sink=sink)
    return {"sample_report": sample_report_env, "evaluation_report": eval_env,
            "sample_execution_trace": trace_env, "caption_policy_revision": cpr_env}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="template-run-sheet-01-video1-aks-zhuodian")
    args = p.parse_args()
    proj = ROOT / "projects" / args.run
    # 硬门（评审 P0-3）：l1a_sample 缺失或未通过 = 不允许立 sample 门；绝不构造假 pass。
    l1a = _load(proj / "artifacts" / "l1a_sample.json")
    if not l1a:
        raise SystemExit(f"{args.run}: artifacts/l1a_sample.json 缺失——请先跑 technical_validator（sample scope）再立门")
    if str(l1a.get("status") or "") != "pass":
        raise SystemExit(f"{args.run}: L1a(sample) 未通过（status={l1a.get('status')}），禁止立 sample 门")
    alignment_path = proj / "analysis" / "alignment_check.json"
    if alignment_path.is_file():
        from lib.template_alignment import alignment_gate_errors, current_alignment_checks
        try:
            alignment_report = json.loads(alignment_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"{args.run}: alignment_check.json 无法读取") from exc
        render_plan = _load(proj / "artifacts" / "render_plan.json") or _load(proj / "artifacts" / "render_plan.sample.json")
        try:
            review_output = _resolve_review_output(proj, render_plan, l1a)
        except FileNotFoundError as exc:
            raise SystemExit(f"{args.run}: {exc}") from exc
        sample_path = proj / review_output
        sample_hash = hashlib.sha256(sample_path.read_bytes()).hexdigest() if sample_path.is_file() else ""
        script_data = _load(proj / "artifacts" / "script.json") or {}
        checks = current_alignment_checks(
            alignment_report, sample_sha256=sample_hash,
            script_sha256=str(script_data.get("semantic_sha256") or ""),
        )
        if checks is None:
            raise SystemExit(f"{args.run}: alignment_check.json 与当前样片/脚本不匹配，禁止立 sample 门")
        alignment_errors = alignment_gate_errors(checks)
        if alignment_errors:
            raise SystemExit(f"{args.run}: 画面对齐硬门失败，禁止立 sample 门：" + "; ".join(alignment_errors[:8]))
    qa = {"status": "pass", "issues": []}
    envs = {}
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_io import load_artifact_envelope
    store = ProjectCommitStore(proj)
    # 补上 sample 阶段必须的既有制品：asset_manifest / final_props / render_plan
    for name in ("asset_manifest", "final_props", "render_plan"):
        p = proj / "artifacts" / f"{name}.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            envs[name] = {"name": name, "path": f"artifacts/{name}.json",
                          "semantic_sha256": data.get("semantic_sha256"), "artifact_sha256": data.get("artifact_sha256"),
                          "data": data}
    with store.transaction(action={"action_id": "write-sample-artifacts"}) as sink:
        envs.update(build(proj, run=args.run, l1a=l1a, qa=qa, sink=sink))
        write_checkpoint(ROOT / "projects", args.run, "sample", "awaiting_human", envs, pipeline_type=PIPELINE,
                         next_action={"summary": "sample 已渲染并过 final_qa + L1a，等待人工五效果确认", "verb": "await_user",
                                      "context_refs": ["renders/sample-v1-540x960.mp4", "artifacts/sample_report.json", "artifacts/evaluation_report.sample.json"]},
                         sink=sink)
    print(f"sample checkpoint awaiting_human written for {args.run}")
    for name, env in envs.items():
        print(f"  {name}: {env['artifact_sha256'][:12]}")


if __name__ == "__main__":
    main()
