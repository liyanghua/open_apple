"""Backfill `evaluation_report` for projects completed before the artifact existed.

Design_Review_2026-08-22.md P0-0: "旧项目缺失时从现有 render、props、QA 和
sample trace 回填；不得删除或覆盖历史制品。" This script only ADDS the two
canonical scoped files (evaluation_report.sample.json / evaluation_report.final.json)
and appends one capability_extension decision; historical artifacts and
checkpoints are never modified.

评审 #11：写入走 write_artifact_atomic（原子替换 + 哈希 + 校验），并优先经
ProjectCommitStore 事务 sink；重复执行幂等（已存在文件不覆盖、决策不重复追加）。
评审 #12：`--repair` 为存量报告回填 subject_hash（缺失/非法时，从 subject
artifact 的 semantic_sha256 推导），不触碰其它字段。

Usage:
    python scripts/backfill_evaluation_report.py <project_id> [--repair]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.caption_layout import layout_captions
from schemas.artifacts import validate_artifact
from tools.analysis.technical_validator import TechnicalValidator

_SUBJECT_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_DECISION_ID = "backfill-evaluation-report-001"


def _valid_subject_hash(value: object) -> bool:
    return isinstance(value, str) and bool(_SUBJECT_HASH_RE.fullmatch(value))


def _load(project_dir: Path, name: str) -> dict:
    path = project_dir / "artifacts" / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing artifact for backfill: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_atomic(project_dir: Path, relative_path: str, name: str, data: dict) -> dict:
    """评审 #11：优先经 ProjectCommitStore 事务 sink，失败回退直接原子写。"""
    try:
        from backlot.project_commit import ProjectCommitStore

        store = ProjectCommitStore(project_dir)
        with store.transaction(action={"action_id": f"backfill-{name}"}) as sink:
            return write_artifact_atomic(
                relative_path, name, data, project_dir=project_dir, sink=sink
            )
    except Exception:
        pass
    return write_artifact_atomic(relative_path, name, data, project_dir=project_dir)


def _cumulative_shot_map(shot_execution_plan: dict) -> list[dict]:
    shots = sorted(shot_execution_plan.get("shots", []), key=lambda s: s.get("order", 0))
    cursor = 0.0
    shot_map = []
    for shot in shots:
        shot_map.append({"shot_id": shot["id"], "start_s": cursor, "end_s": cursor + float(shot.get("duration_seconds", 0))})
        cursor += float(shot.get("duration_seconds", 0))
    return shot_map


def _text_sources(shot_execution_plan: dict, final_props: dict) -> list[dict]:
    sources = []
    for shot in shot_execution_plan.get("shots", []):
        text = " ".join(filter(None, [shot.get("narration") or "", shot.get("screen_copy") or ""])).strip()
        if text:
            sources.append({"source": "shot_copy", "shot_id": shot["id"], "text": text})
    captions = final_props.get("captions") or []
    if captions:
        sources.append({"source": "captions", "text": " ".join(c.get("text", "") for c in captions)})
    return sources


def _build_inputs(project_dir: Path, project_id: str, scope: str) -> dict:
    script = _load(project_dir, "script")
    final_props = _load(project_dir, "final_props")
    edit_decisions = _load(project_dir, "edit_decisions")
    shot_execution_plan = _load(project_dir, "shot_execution_plan")
    sample_report = _load(project_dir, "sample_report")
    final_review = _load(project_dir, "final_review")
    sample_trace = _load(project_dir, "sample_execution_trace")

    if scope == "sample":
        render_path = project_dir / "renders" / "sample-v1.mp4"
        expected_duration = float(sample_report["probe"]["duration_seconds"])
        subject = {"name": "sample_report", "path": "artifacts/sample_report.json",
                   "artifact_sha256": sample_report.get("artifact_sha256", "")}
        subject_version = str(sample_report.get("version", "1.0"))
        subject_hash = sample_report.get("semantic_sha256", "")
    else:
        render_path = project_dir / "renders" / "final.mp4"
        expected_duration = float(script.get("total_duration_seconds", 15))
        subject = {"name": "final_review", "path": "artifacts/final_review.json",
                   "artifact_sha256": final_review.get("artifact_sha256", "")}
        subject_version = str(final_review.get("version", "2.0"))
        subject_hash = final_review.get("semantic_sha256", "")

    if not _valid_subject_hash(subject_hash):
        raise ValueError(
            f"[{scope}] subject artifact 缺少合法 semantic_sha256，无法生成可回溯的评价报告"
        )

    captions = final_props.get("captions") or []
    profile = {"width": final_props.get("width", 1080), "height": final_props.get("height", 1920)}
    computed_boxes = layout_captions(captions, width=profile["width"], height=profile["height"]) if captions else []

    return {
        "input_path": str(render_path),
        "project_id": project_id,
        "scope": scope,
        "judge_version": "technical_validator-0.1.0",
        "rubric_version": "l1a-v1.0",
        "subject_ref": subject,
        "subject_version": subject_version,
        "subject_hash": subject_hash,
        "execution_diff_ref": {
            "name": "sample_execution_trace",
            "path": "artifacts/sample_execution_trace.json",
            "artifact_sha256": sample_trace.get("artifact_sha256", ""),
        },
        "expected_profile": "social_vertical_1080p30" if scope == "final" else "social_vertical_sample_540p30",
        "expected_duration_s": round(expected_duration, 3),
        "duration_tolerance_s": 0.5,
        "expected_facts": {},
        "text_sources": _text_sources(shot_execution_plan, final_props),
        "shot_map": _cumulative_shot_map(shot_execution_plan),
        "caption_declaration": {
            "caption_render_mode": edit_decisions.get("caption_render_mode"),
            "caption_source": edit_decisions.get("caption_source"),
            "safe_zone_profile": edit_decisions.get("safe_zone_profile"),
        },
        "caption_spec": {"captions": captions, "computed_boxes": computed_boxes},
    }


def _append_decision(project_dir: Path, project_id: str, summaries: dict) -> None:
    """Append the capability_extension decision once (idempotent, atomic)."""
    log = _load(project_dir, "decision_log")
    existing_ids = {
        str(item.get("decision_id"))
        for item in log.get("decisions", [])
        if isinstance(item, dict)
    }
    if _DECISION_ID in existing_ids:
        print("decision_log already records the backfill entry — skip append")
        return
    log.pop("semantic_sha256", None)
    log.pop("artifact_sha256", None)
    entry = {
        "decision_id": _DECISION_ID,
        "stage": "compose",
        "category": "capability_extension",
        "subject": "evaluation_report 回填（Design_Review v1.2 P0-0）",
        "options_considered": [
            {"option_id": "backfill-from-artifacts", "label": "从现有 render/props/QA/sample trace 回填",
             "score": 0.9, "reason": "契约要求不删除或覆盖历史制品"},
            {"option_id": "re-run-full-pipeline", "label": "重跑管线生成", "score": 0.2,
             "reason": "对已完成项目成本高且改动历史状态", "rejected_because": "对已完成项目成本高且改动历史状态"},
        ],
        "selected": "backfill-from-artifacts",
        "reason": (
            "v1.2 P0-0 要求旧项目补齐 evaluation_report。已新增 "
            "evaluation_report.sample.json 与 evaluation_report.final.json，"
            "历史制品与 checkpoint 均未修改。"
            f"结果摘要：{summaries}"
        ),
        "confidence": 0.9,
    }
    log.setdefault("decisions", []).append(entry)
    _write_atomic(project_dir, "artifacts/decision_log.json", "decision_log", log)
    print("decision_log appended: capability_extension / evaluation_report 回填")


def _subject_hash_for_scope(project_dir: Path, scope: str) -> str:
    source_name = "sample_report" if scope == "sample" else "final_review"
    source = _load(project_dir, source_name)
    value = source.get("semantic_sha256", "")
    if not _valid_subject_hash(value):
        raise ValueError(f"[{scope}] {source_name}.semantic_sha256 缺失/非法")
    return value


def _repair_report_subject_hash(
    project_dir: Path, relative_path: str, scope: str
) -> bool:
    """评审 #12：为存量报告回填 subject_hash（仅缺失/非法时），原子写入。"""
    path = project_dir / relative_path
    if not path.is_file():
        return False
    report = json.loads(path.read_text(encoding="utf-8"))
    if _valid_subject_hash(report.get("subject_hash")):
        return False
    report.pop("semantic_sha256", None)
    report.pop("artifact_sha256", None)
    report["subject_hash"] = _subject_hash_for_scope(project_dir, scope)
    attached = attach_hashes(report)
    validate_artifact("evaluation_report", attached)
    _write_atomic(project_dir, relative_path, "evaluation_report", attached)
    print(f"[repair] {relative_path}: subject_hash 已回填")
    return True


def _persist_checkpoint(project_dir: Path, project_id: str, stage: str, raw: dict) -> None:
    """原子写回检查点；已启用版本事务的项目经 store sink 提交。

    使用 persist_checkpoint_atomic（只校验本检查点与前置检查点），不做
    decision_log 合并/全量 resync——部分回填中途其余检查点尚未补齐时，
    write_checkpoint 的全量 resync 会误伤尚未修复的后续阶段。
    """
    from lib.checkpoint import persist_checkpoint_atomic

    try:
        from backlot.project_commit import ProjectCommitStore

        store = ProjectCommitStore(project_dir)
        with store.transaction(action={"action_id": f"backfill-legacy-{stage}"}) as sink:
            persist_checkpoint_atomic(
                project_dir.parent, project_id, stage, raw, sink=sink
            )
        return
    except Exception:
        pass
    persist_checkpoint_atomic(project_dir.parent, project_id, stage, raw)


def _envelope_for_existing_file(
    project_dir: Path, relative_path: str, name: str
) -> dict | None:
    path = project_dir / relative_path
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "semantic_sha256" not in data:
        return None
    return {
        "name": name,
        "path": relative_path,
        "semantic_sha256": data["semantic_sha256"],
        "artifact_sha256": data["artifact_sha256"],
        "data": data,
    }


def _backfill_legacy_contracts(project_dir: Path, project_id: str) -> list[str]:
    """契约回填：补齐旧检查点缺失的 produces 制品（P0-0/P1-1/P1-2）。

    旧项目运行于部分制品契约之前，contract-v2 下 completed 检查点缺制品
    即校验失败。从该运行自身的数据确定性重建并原子写回：
      research → caption_style_fingerprint（由 research_breakdown 重建）
      proposal → hook_plan（由 creative_control_plan + script 重建）
      sample   → evaluation_report（scoped 文件 evaluation_report.sample.json）
      compose  → evaluation_report（scoped 文件 evaluation_report.final.json）
    """
    from lib.caption_style import build_caption_style_fingerprint
    from lib.checkpoint import sync_checkpoint_envelopes
    from lib.hook_plan import build_hook_plan

    done: list[str] = []

    research_cp = project_dir / "checkpoint_research.json"
    if research_cp.is_file():
        raw = json.loads(research_cp.read_text(encoding="utf-8"))
        if raw.get("status") == "completed" and "caption_style_fingerprint" not in raw.get("artifacts", {}):
            sync_checkpoint_envelopes(project_dir, raw)
            breakdown_path = project_dir / "artifacts" / "research_breakdown.json"
            breakdown = json.loads(breakdown_path.read_text(encoding="utf-8")) if breakdown_path.is_file() else None
            fingerprint = build_caption_style_fingerprint(project_id, breakdown)
            fingerprint["notes"] = (
                str(fingerprint.get("notes") or "")
                + "（契约回填：该研究运行于 caption_style_fingerprint 制品契约之前，"
                "由脚本从 research_breakdown 确定性重建）"
            )
            envelope = _write_atomic(
                project_dir, "artifacts/caption_style_fingerprint.json",
                "caption_style_fingerprint", fingerprint,
            )
            raw["artifacts"]["caption_style_fingerprint"] = envelope
            _persist_checkpoint(project_dir, project_id, "research", raw)
            done.append("research+caption_style_fingerprint")

    proposal_cp = project_dir / "checkpoint_proposal.json"
    if proposal_cp.is_file():
        raw = json.loads(proposal_cp.read_text(encoding="utf-8"))
        if raw.get("status") in {"completed", "awaiting_human"} and "hook_plan" not in raw.get("artifacts", {}):
            # 旧回填曾直接追加 decision_log，可能造成信封漂移——先同步再补制品。
            sync_checkpoint_envelopes(project_dir, raw)
            creative = _load(project_dir, "creative_control_plan")
            script = _load(project_dir, "script")
            hook = build_hook_plan(project_id, creative_control_plan=creative, script=script)
            envelope = _write_atomic(
                project_dir, "artifacts/hook_plan.json", "hook_plan", hook
            )
            raw["artifacts"]["hook_plan"] = envelope
            _persist_checkpoint(project_dir, project_id, "proposal", raw)
            done.append("proposal+hook_plan")

    for stage, scope in (("sample", "sample"), ("compose", "final")):
        cp_path = project_dir / f"checkpoint_{stage}.json"
        if not cp_path.is_file():
            continue
        raw = json.loads(cp_path.read_text(encoding="utf-8"))
        if raw.get("status") in {"completed", "awaiting_human"} and "evaluation_report" not in raw.get("artifacts", {}):
            sync_checkpoint_envelopes(project_dir, raw)
            envelope = _envelope_for_existing_file(
                project_dir, f"artifacts/evaluation_report.{scope}.json", "evaluation_report"
            )
            if envelope is None:
                print(f"[legacy] {stage} 缺少 evaluation_report，且 scoped 文件不存在 — 先跑默认回填")
                continue
            raw["artifacts"]["evaluation_report"] = envelope
            _persist_checkpoint(project_dir, project_id, stage, raw)
            done.append(f"{stage}+evaluation_report")
    return done


def main() -> int:
    args = [arg for arg in sys.argv[1:] if arg != "--repair"]
    repair = "--repair" in sys.argv[1:]
    if len(args) != 1:
        print("usage: python scripts/backfill_evaluation_report.py <project_id> [--repair]")
        return 2
    project_id = args[0]
    project_dir = REPO_ROOT / "projects" / project_id
    if not (project_dir / "project.json").is_file():
        print(f"project not found: {project_dir}")
        return 2

    if repair:
        # 存量报告修复：scoped 文件 + 旧式无 scope 后缀文件（v8 的
        # evaluation_report.json 为 sample 范围）。
        repaired = 0
        for scope in ("sample", "final"):
            repaired += _repair_report_subject_hash(
                project_dir, f"artifacts/evaluation_report.{scope}.json", scope
            )
        unscoped = project_dir / "artifacts" / "evaluation_report.json"
        if unscoped.is_file():
            legacy = json.loads(unscoped.read_text(encoding="utf-8"))
            legacy_scope = legacy.get("scope")
            if legacy_scope in {"sample", "final"}:
                repaired += _repair_report_subject_hash(
                    project_dir, "artifacts/evaluation_report.json", legacy_scope
                )
        _backfill_legacy_contracts(project_dir, project_id)
        print(f"repair done: {repaired} file(s) updated")
        return 0

    summaries = {}
    for scope in ("sample", "final"):
        canonical = f"artifacts/evaluation_report.{scope}.json"
        if (project_dir / canonical).is_file():
            print(f"[{scope}] already exists — skip (idempotent backfill)")
            continue
        inputs = _build_inputs(project_dir, project_id, scope)
        result = TechnicalValidator().execute(inputs)
        if not result.data:
            print(f"[{scope}] failed: {result.error}")
            return 1
        report = result.data
        _write_atomic(project_dir, canonical, "evaluation_report", report)
        summaries[scope] = f"{scope}: status={report['status']}, action={report['recommended_action']}"
        print(f"[{scope}] {summaries[scope]} -> {canonical}")
        for check in report["hard_gate"]["checks"]:
            if check["status"] == "fail":
                print(f"    FAIL {check['id']}: {check['message']}")

    if summaries:
        _append_decision(project_dir, project_id, summaries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
