from __future__ import annotations

import pytest

from lib.rerun_plan import create_rerun_plan, create_rerun_run, promote_rerun, transition_rerun


def test_rerun_plan_computes_dependency_closure_and_keeps_old_revision() -> None:
    plan = create_rerun_plan(
        candidate_id="cand-01",
        child_revision="rev-3",
        intent="copy",
        anchor={"type": "time_range", "start_seconds": 0, "end_seconds": 3, "label": "开头钩子"},
        instruction="前 3 秒直接进入产品动作，删掉铺垫",
        vlm_finding_ids=[{"id": "f-1", "stage": "script", "label": "开头钩子"}],
        render_runtime="remotion",
    )
    assert plan["from_stage"] == "script"
    assert plan["stages"] == ["script", "scene_plan", "assets", "sample", "edit", "compose"]
    assert plan["preserved_stages"] == ["research", "proposal"]
    assert plan["base_revision"] == "rev-3"
    assert plan["target_revision"] == "rev-4"


def test_rerun_run_requires_preview_before_full_and_can_discard() -> None:
    plan = create_rerun_plan(
        candidate_id="cand-01", child_revision="rev-3", intent="pacing",
        anchor={"type": "shot", "shot_id": "shot-02"},
        instruction="切得更紧", vlm_finding_ids=[], render_runtime="remotion",
    )
    run = create_rerun_run(plan)
    assert run["status"] == "draft_plan"
    run = transition_rerun(run, "preview_running")
    run = transition_rerun(run, "awaiting_preview_review", preview_ref="renders/preview.mp4")
    with pytest.raises(ValueError, match="preview"):
        transition_rerun(run, "full_running", preview_approved=False)
    run = transition_rerun(run, "full_running", preview_approved=True)
    run = transition_rerun(run, "awaiting_final_review", output_ref="renders/rerun.mp4")
    run = promote_rerun(run)
    assert run["status"] == "promoted"
    assert run["current_revision"] == "rev-4"
