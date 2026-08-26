"""主链路驱动（瘦包装）：模板 run 的 proposal → script → scene_plan 全部委托 lib.template_mainline。

历史背景（评审 P1-9）：本脚本曾是**第二套**硬编码 narration/scene_plan 逻辑（8 镜索引错配的
来源），与新主链路并存会重新引入错误。现改为唯一入口 lib.template_mainline.{build_proposal,
build_hook_plan, build_decision_log, scene_plan_data, build_script, build_scene_plan} 的薄 CLI，
不再含有任何逐镜文案或素材映射代码。

用法：python -m scripts.run_template_mainchain --run template-run-sheet-01-video1-aks-zhuodian
      [--advance]  # 推进到下一个 gated 点（script awaiting_human）后停止
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
PIPELINE = "cinematic-fast"


def _load(p: Path) -> dict:
    import json

    return json.loads(p.read_text(encoding="utf-8"))


def _template(project: Path) -> dict:
    pack = _load(ROOT / "projects/template-pack-library/artifacts/template_pack.json")
    template_id = str(_load(project / "artifacts/template_run_plan.json").get("template_id") or "")
    template = next((t for t in pack.get("templates", []) if t.get("template_id") == template_id), None)
    if template is None:
        raise SystemExit(f"template {template_id} not in pack")
    return template


def advance(run: str, *, stop_at_gate: bool = True) -> list[str]:
    """委托主链路库函数逐段推进（唯一入口；不再含任何逐镜文案/映射逻辑）。"""
    from lib.checkpoint import get_completed_stages, get_next_stage, write_checkpoint
    from lib.template_mainline import (
        build_decision_log, build_hook_plan, build_proposal, build_scene_plan, build_script,
        scene_plan_data,
    )

    project = PROJECTS / run
    template = _template(project)
    facts = _load(project / "artifacts/product_facts.json") or {}
    done: list[str] = []
    while True:
        stage = get_next_stage(PROJECTS, run, PIPELINE)
        if stage is None:
            print("all stages complete")
            break
        if stage not in {"proposal", "script", "scene_plan"}:
            print(f"  stopping: stage {stage} not in template mainchain scope")
            break
        if stage in get_completed_stages(PROJECTS, run, PIPELINE):
            continue
        print(f"== {stage} ==")
        if stage == "proposal":
            from backlot.project_commit import ProjectCommitStore

            with ProjectCommitStore(project).transaction(action={"action_id": f"advance-{stage}-{run}"}) as sink:
                envs = build_proposal(project, template, facts, sink=sink)
                envs["hook_plan"] = build_hook_plan(project, template, facts, sink=sink)
                envs["decision_log"] = build_decision_log(project, template, facts, sink=sink)
                write_checkpoint(PROJECTS, run, "proposal", "completed", envs,
                                 pipeline_type=PIPELINE, next_action=None,
                                 review={"findings": [], "verdict": "pass"}, sink=sink)
            done.append("proposal")
        elif stage == "script":
            from backlot.project_commit import ProjectCommitStore

            ccp = _load(project / "artifacts/creative_control_plan.json")
            rp = _load(project / "artifacts/template_run_plan.json")
            sp_data = scene_plan_data(project, template, rp, ccp, facts)
            with ProjectCommitStore(project).transaction(action={"action_id": f"advance-{stage}-{run}"}) as sink:
                sc_env = build_script(project, template, sp_data, ccp, facts, sink=sink)
                write_checkpoint(PROJECTS, run, "script", "awaiting_human",
                                 {"script": sc_env}, pipeline_type=PIPELINE,
                                 next_action={"summary": f"script 已 produced，等待人工锁定 script（{run}）",
                                              "verb": "await_user",
                                              "context_refs": ["artifacts/script.json"]}, sink=sink)
            done.append("script")
            if stop_at_gate:
                break
        elif stage == "scene_plan":
            from backlot.project_commit import ProjectCommitStore

            with ProjectCommitStore(project).transaction(action={"action_id": f"advance-{stage}-{run}"}) as sink:
                sp_env = build_scene_plan(project, template, rp, ccp, facts, sink=sink)
                write_checkpoint(PROJECTS, run, "scene_plan", "completed",
                                 {"scene_plan": sp_env}, pipeline_type=PIPELINE, next_action=None, sink=sink)
            done.append("scene_plan")
    return done


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="template-run-sheet-01-video1-aks-zhuodian")
    p.add_argument("--advance", action="store_true", help="推进到下一个 gated 点后停止")
    args = p.parse_args()
    done = advance(args.run, stop_at_gate=args.advance)
    print("advanced:", done)


if __name__ == "__main__":
    main()
