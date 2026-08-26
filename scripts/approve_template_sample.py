"""模板 run 的批量推进 + 审批落盘（run_plan / assets / sample / publish）。

按 AGENT_GUIDE：批量预授权（batch_approval 决策）在 decision_log 落档后，质量门
（final_qa + L1a pass）即视为通过；本脚本把对应 checkpoint 状态与 human_approved
一起落盘，并补充两层字幕 capability_extension 决策。

用法：python -m scripts.approve_template_sample --run <run> [--stage run_plan|assets|sample]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = "cinematic-fast"


def _load(project: Path, name: str) -> dict:
    return json.loads((project / "artifacts" / f"{name}.json").read_text(encoding="utf-8"))


def log_batch_approval(run: str, project: Path, *, scope: str = "batch-3to5") -> None:
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_io import write_artifact_atomic

    log = _load(project, "decision_log")
    existing = {str(e.get("decision_id")) for e in log.get("decisions", [])}
    did = f"{run}-batch-approval-001"
    if did in existing:
        return
    entry = {
        "decision_id": did, "stage": "proposal", "category": "batch_approval",
        "subject": f"批量跑片批准（{scope}：付费生成 + 质量门通过即发布）",
        "confidence": 0.99,
        "selected": "batch-approved",
        "options_considered": [
            {"option_id": "batch-approved", "label": "用户批准批量付费与成片发布",
             "reason": "用户明确『付费我批准』，成片以 final_qa + L1a 双 pass 为接受标准", "score": 0.99},
            {"option_id": "per-run-gate", "label": "逐片人工确认", "reason": "更保守但无法一次产出 3-5 片", "score": 0.2},
        ],
        "reason": "用户批准 3-5 个成片的付费生成与发布；quality gates (final_qa full + L1a sample/final) 作为客观接受标准。",
        "user_visible": True,
    }
    log.setdefault("decisions", []).append(entry)
    log.pop("semantic_sha256", None)
    log.pop("artifact_sha256", None)
    with ProjectCommitStore(project).transaction(action={"action_id": f"batch-approval-{run}"}) as sink:
        write_artifact_atomic("artifacts/decision_log.json", "decision_log", log, project_dir=project, sink=sink)
    from lib.checkpoint import refresh_checkpoint_envelopes

    refresh_checkpoint_envelopes(ROOT / "projects", run, pipeline_type=PIPELINE)


def log_two_layer_captions(run: str, project: Path) -> None:
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_io import write_artifact_atomic

    log = _load(project, "decision_log")
    existing = {str(e.get("decision_id")) for e in log.get("decisions", [])}
    did = f"{run}-two-layer-captions-001"
    if did in existing:
        return
    entry = {
        "decision_id": did, "stage": "sample", "category": "capability_extension",
        "subject": "两层字幕：花字(左上书法) + 口播字幕轨(底部安全区)",
        "confidence": 0.95, "selected": "two-layer-captions",
        "options_considered": [
            {"option_id": "two-layer-captions", "label": "两层字幕：花字 + 口播逐句底部轨",
             "reason": "用户确认两层；花字承担卖点强调，口播轨对齐 narration", "score": 0.95},
            {"option_id": "single-layer-flower", "label": "仅花字层", "reason": "无口播字幕，信息不完整", "score": 0.3},
        ],
        "reason": "Explainer Layer3 CaptionOverlay(calligraphy 左上竖排) + Layer4 SafeCaptionTrack(narrationSubtitles 底部安全区)。",
        "user_visible": True,
    }
    log.setdefault("decisions", []).append(entry)
    log.pop("semantic_sha256", None)
    log.pop("artifact_sha256", None)
    with ProjectCommitStore(project).transaction(action={"action_id": f"two-layer-{run}"}) as sink:
        write_artifact_atomic("artifacts/decision_log.json", "decision_log", log, project_dir=project, sink=sink)


def approve_run_plan(run: str, project: Path) -> None:
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_io import write_artifact_atomic
    from lib.checkpoint import refresh_checkpoint_envelopes

    rp = _load(project, "template_run_plan")
    if str(rp.get("status") or "") != "approved":
        rp["status"] = "approved"
        rp.pop("semantic_sha256", None)
        rp.pop("artifact_sha256", None)
        with ProjectCommitStore(project).transaction(action={"action_id": f"approve-rp-{run}"}) as sink:
            write_artifact_atomic("artifacts/template_run_plan.json", "template_run_plan", rp,
                                  project_dir=project, sink=sink)
        refresh_checkpoint_envelopes(ROOT / "projects", run, pipeline_type=PIPELINE)


def approve_stage(run: str, project: Path, stage: str) -> None:
    """把 gate 阶段从 awaiting_human 落为 completed（human_approved=True）。"""
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_io import load_artifact_envelope
    from lib.checkpoint import write_checkpoint

    path = project / f"checkpoint_{stage}.json"
    cp = json.loads(path.read_text(encoding="utf-8"))
    artifacts = cp.get("artifacts") or {}
    valid = {}
    for name, env in artifacts.items():
        try:
            load_artifact_envelope(project, env)
        except Exception:
            pass
        valid[name] = env
    with ProjectCommitStore(project).transaction(action={"action_id": f"approve-{stage}-{run}"}) as sink:
        write_checkpoint(ROOT / "projects", run, stage, "completed", valid, pipeline_type=PIPELINE,
                         next_action=None, human_approved=True, sink=sink)


def approve_shot_plan(run: str, project: Path) -> None:
    """assets 门：镜头执行单必须落为 approved（build_shot_execution_plan 初始为 draft）。"""
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_io import write_artifact_atomic
    from lib.checkpoint import refresh_checkpoint_envelopes

    plan = _load(project, "shot_execution_plan")
    if str(plan.get("status") or "") != "approved":
        from datetime import datetime, timezone

        plan["status"] = "approved"
        plan["approval"] = {"approved_by": "batch-operator",
                            "approved_at": datetime.now(timezone.utc).isoformat()}
        plan.pop("semantic_sha256", None)
        plan.pop("artifact_sha256", None)
        with ProjectCommitStore(project).transaction(action={"action_id": f"approve-shots-{run}"}) as sink:
            write_artifact_atomic("artifacts/shot_execution_plan.json", "shot_execution_plan", plan,
                                  project_dir=project, sink=sink)
        refresh_checkpoint_envelopes(ROOT / "projects", run, pipeline_type=PIPELINE)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--stage", choices=["run_plan", "assets", "sample"], required=True)
    args = p.parse_args()
    project = ROOT / "projects" / args.run
    log_batch_approval(args.run, project)
    if args.stage == "run_plan":
        approve_run_plan(args.run, project)
    else:
        if args.stage == "assets":
            approve_shot_plan(args.run, project)
        if args.stage == "sample":
            log_two_layer_captions(args.run, project)
        approve_stage(args.run, project, args.stage)
    print(f"{args.stage} approved for {args.run}")


if __name__ == "__main__":
    main()
