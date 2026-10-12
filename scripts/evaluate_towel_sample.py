"""Evaluate an existing towel sample through the upgraded campaign gates.

This script intentionally does not call a provider. It reuses an already
rendered local sample, runs the deterministic media and L1a checks, and marks
the additional source-led alignment gate explicitly when its canonical
execution artifacts are not present.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from lib.artifact_io import write_artifact_atomic
from lib.campaign_contracts import validate_sample_shot_plan_semantics
from scripts.validate_towel_campaign import validate as validate_campaign
from tools.analysis.technical_validator import TechnicalValidator
from tools.video.final_qa import FinalQA


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(project_dir: Path, sample_path: Path, *, sample_id: str, product_project: Path,
             expected_duration_s: float, narration: str) -> dict:
    project_dir = Path(project_dir).resolve()
    sample_path = Path(sample_path).resolve()
    product_project = Path(product_project).resolve()
    subject_hash = _hash(sample_path)
    campaign_gate = validate_campaign(project_dir)
    shot_plan_path = project_dir / "artifacts" / "sample_shot_plan_c1.json"
    shot_plan = json.loads(shot_plan_path.read_text(encoding="utf-8")) if shot_plan_path.is_file() else {}
    shot_plan_error = None
    try:
        validate_sample_shot_plan_semantics(shot_plan)
    except ValueError as exc:
        shot_plan_error = str(exc)
    final_qa = FinalQA().execute({
        "mode": "full",
        "input_path": str(sample_path),
        "expected_profile": "social_vertical_1080p30",
    })
    l1a = TechnicalValidator().execute({
        "input_path": str(sample_path),
        "project_id": project_dir.name,
        "project_dir": str(product_project),
        "scope": "sample",
        "subject_hash": subject_hash,
        "expected_profile": "social_vertical_1080p30",
        "expected_duration_s": expected_duration_s,
        "duration_tolerance_s": 0.25,
        "text_sources": [{"source": "approved_narration", "text": narration}],
    })
    qa_data = final_qa.data if final_qa.success else {}
    l1a_data = l1a.data if l1a.success else {}
    alignment_check = {
        "id": "campaign_alignment",
        "name": "campaign内容配方与执行卡对齐",
        "status": "fail",
        "severity": "warning",
        "message": "样片已有campaign/recipe、3–5秒镜头执行记录和成片，但尚未绑定script、scene_plan、shot_execution_plan、final_props四层canonical输入",
        "evidence": {"campaign_gate": campaign_gate, "sample_id": sample_id},
        "affected_shots": [sample_id],
        "fixable": True,
        "fix_suggestion": "先补齐单条样片的script、scene_plan、shot_execution_plan和final_props，再运行alignment和video_judge",
    }
    shot_duration_check = {
        "id": "shot_duration_contract",
        "name": "单镜头 3–5 秒约束",
        "status": "fail" if shot_plan_error else "pass",
        "severity": "fatal" if shot_plan_error else "info",
        "message": shot_plan_error or "动作镜头均为 3–5 秒；编辑节拍未超过 5 秒",
        "evidence": {"path": "artifacts/sample_shot_plan_c1.json"},
        "affected_shots": [sample_id] if shot_plan_error else [],
        "fixable": bool(shot_plan_error),
    }
    if shot_plan_error:
        shot_duration_check["fix_suggestion"] = "拆分超过 5 秒的连续动作，按 3–5 秒重新生成或裁切"
    hard_gate = dict(l1a_data.get("hard_gate") or {
        "pass": False,
        "checks": [],
        "coverage": {"executed": 0, "total": 0, "minimum": 9, "sufficient": False},
    })
    hard_gate["checks"] = list(hard_gate.get("checks") or []) + [shot_duration_check, alignment_check]
    hard_gate["pass"] = bool(hard_gate.get("pass")) and not any(
        item["status"] == "fail" for item in (shot_duration_check, alignment_check)
    )
    report = {
        "version": "1.0",
        "project_id": project_dir.name,
        "scope": "sample",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "judge_version": "technical_validator-0.1.0 + campaign-gate-1.0",
        "rubric_version": "l1a-v1.0",
        "subject_ref": {"name": sample_id, "path": str(sample_path)},
        "subject_version": "1.0",
        "subject_hash": subject_hash,
        "execution_diff_ref": {
            "name": "sample_execution_trace",
            "path": "artifacts/sample_execution_trace.json",
        },
        "hard_gate": hard_gate,
        "creative_advisory": {
            "scored": False,
            "summary": "未运行video_judge；当前只完成确定性媒体/L1a评估",
            "dimensions": [],
        },
        "repair_targets": [],
        "status": "revise",
        "recommended_action": "repair",
    }
    write_artifact_atomic(
        "artifacts/evaluation_report.sample.json",
        "evaluation_report",
        report,
        project_dir=project_dir,
    )
    return {
        "sample_id": sample_id,
        "sample_path": str(sample_path),
        "campaign_gate": campaign_gate,
        "final_qa": {"success": final_qa.success, "status": qa_data.get("status"), "issues": qa_data.get("issues_found", [])},
        "l1a": {"success": l1a.success, "status": l1a_data.get("status"), "coverage": (l1a_data.get("hard_gate") or {}).get("coverage")},
        "upgraded_status": report["status"],
        "evaluation_report": "artifacts/evaluation_report.sample.json",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("sample_path", type=Path)
    parser.add_argument("--product-project", type=Path, required=True)
    parser.add_argument("--sample-id", default="P2-S01-upgraded-review")
    parser.add_argument("--expected-duration", type=float, default=12.05)
    parser.add_argument("--narration", default="素色毛巾，看清织纹。长绒棉材质，棉含量百分之百。PLAYBOY，让日常更有质感。")
    args = parser.parse_args()
    print(json.dumps(evaluate(
        args.project_dir,
        args.sample_path,
        sample_id=args.sample_id,
        product_project=args.product_project,
        expected_duration_s=args.expected_duration,
        narration=args.narration,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
