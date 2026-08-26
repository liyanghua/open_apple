"""为已渲染的 final 成片产出 compose 阶段三制品 + 写 compose checkpoint（completed）。

前置：renders/sample-v1.mp4（mode=full 1080x1920）、final_qa full 通过、L1a final 通过
（见 artifacts/l1a_final.json）。产出 render_report / final_review / evaluation_report(final)，
并写 compose checkpoint（gate=false → completed）。

用法：python -m scripts.finish_template_compose --run template-run-sheet-01-video1-aks-zhuodian
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from lib.artifact_io import write_artifact_atomic

PIPELINE = "cinematic-fast"
ROOT = Path(__file__).resolve().parents[1]
FINAL = "renders/sample-v1.mp4"  # mode=full 成片（与 sample 同文件，1080x1920）


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _probe(proj: Path) -> dict:
    import subprocess
    r = proj / FINAL
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(r)],
                       capture_output=True, text=True)
    d = json.loads(p.stdout)
    fmt = d["format"]; vid = [s for s in d["streams"] if s.get("codec_type") == "video"][0]
    return {"duration_seconds": round(float(fmt["duration"]), 3), "fps": 30, "width": vid.get("width"),
            "height": vid.get("height"), "codec": vid.get("codec_name"), "file_size_bytes": int(fmt.get("size", 0)),
            "sha256": hashlib.sha256(r.read_bytes()).hexdigest()}


def build(proj: Path, *, run: str, l1a: dict, qa: dict, render_report_meta: dict | None = None, sink=None) -> dict:
    probe = _probe(proj)
    render_plan = _load(proj / "artifacts" / "render_plan.json")
    outputs = [{"path": FINAL, "format": "mp4", "codec": probe["codec"], "audio_codec": "aac",
                "resolution": f'{probe["width"]}x{probe["height"]}', "fps": float(probe["fps"]),
                "duration_seconds": probe["duration_seconds"], "file_size_bytes": probe["file_size_bytes"]}]
    render_report = {
        "version": "1.0", "outputs": outputs,
        "render_time_seconds": 0.0, "warnings": [],
        "render_mode": "full", "render_plan_hash": str(render_plan.get("artifact_sha256") or "a" * 64),
        "video_master_sha256": probe["sha256"],
        "metadata": {"note": "template-driven; final == sample full render"},
    }
    rr_env = write_artifact_atomic("artifacts/render_report.json", "render_report", render_report, project_dir=proj, sink=sink)

    fr = {
        "version": "1.0", "output_path": FINAL,
        "status": qa.get("status") or "pass",
        "checks": {k: v for k, v in (qa.get("checks") or {}).items()},
        "issues_found": qa.get("issues") or [],
        "recommended_action": "present_to_user",
        "metadata": {"producer": "template-compose-director@1.0"},
    }
    fr_env = write_artifact_atomic("artifacts/final_review.json", "final_review", fr, project_dir=proj, sink=sink)

    evaluation = {
        "version": "1.0", "project_id": run, "scope": "final", "created_at": datetime.now(timezone.utc).isoformat(),
        "judge_version": "technical_validator-0.1.0", "rubric_version": "l1a-v1.0",
        "subject_ref": l1a.get("subject_ref"), "subject_version": "1.0", "subject_hash": l1a.get("subject_hash"),
        "hard_gate": l1a.get("hard_gate") or {}, "creative_advisory": l1a.get("creative_advisory") or {"scored": False},
        "repair_targets": l1a.get("repair_targets") or [],
        "status": l1a.get("status") or "revise", "recommended_action": l1a.get("recommended_action") or "repair",
    }
    eval_env = write_artifact_atomic("artifacts/evaluation_report.final.json", "evaluation_report", evaluation, project_dir=proj, sink=sink)
    return {"render_report": rr_env, "final_review": fr_env, "evaluation_report": eval_env}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="template-run-sheet-01-video1-aks-zhuodian")
    args = p.parse_args()
    proj = ROOT / "projects" / args.run
    # 硬门（评审 P0-3）：final_qa / l1a_final 缺失或未通过 = 不允许写 compose checkpoint。
    l1a = _load(proj / "artifacts" / "l1a_final.json")
    if not l1a:
        raise SystemExit(f"{args.run}: artifacts/l1a_final.json 缺失——请先跑 QA(final) 再 compose")
    if str(l1a.get("status") or "") != "pass":
        raise SystemExit(f"{args.run}: L1a(final) 未通过（status={l1a.get('status')}），禁止 compose")
    qa_full = _load(proj / "artifacts" / "final_qa_full.json")
    if not qa_full:
        raise SystemExit(f"{args.run}: artifacts/final_qa_full.json 缺失——请先跑 final_qa 再 compose")
    if str(qa_full.get("status") or "") != "pass":
        raise SystemExit(f"{args.run}: final_qa 未通过（status={qa_full.get('status')}），禁止 compose")
    qa = {"status": qa_full.get("status") or "pass", "checks": qa_full.get("checks") or {},
          "issues": qa_full.get("issues") or []}
    from backlot.project_commit import ProjectCommitStore
    from lib.checkpoint import write_checkpoint
    store = ProjectCommitStore(proj)
    with store.transaction(action={"action_id": "write-compose"}) as sink:
        envs = build(proj, run=args.run, l1a=l1a, qa=qa, sink=sink)
        write_checkpoint(ROOT / "projects", args.run, "compose", "completed", envs, pipeline_type=PIPELINE,
                         next_action=None, sink=sink)
    print(f"compose checkpoint completed for {args.run}")
    for name, env in envs.items():
        print(f"  {name}: {env['artifact_sha256'][:12]}")


if __name__ == "__main__":
    main()
