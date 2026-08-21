from __future__ import annotations

import json
from pathlib import Path

import pytest

from backlot.operator_errors import OperatorError
from backlot.shot_generation import ShotGenerationService
from lib.artifact_hashing import attach_hashes
from tools.base_tool import ToolResult


class FakeSelector:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def estimate_cost(self, inputs: dict) -> float:
        return 1.21 if inputs["model_variant"] == "fast" else 1.52

    def execute(self, inputs: dict) -> ToolResult:
        self.calls.append(inputs)
        output = Path(inputs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        callback = inputs.get("_status_callback")
        if callback:
            callback({"remote_task_id": "fal-123", "status_url": "https://queue/status", "response_url": "https://queue/result"})
        return ToolResult(
            success=True,
            data={"output_path": str(output), "seed": 991, "selected_tool": "seedance_video", "selected_provider": "seedance", "model": "seedance-2.0-fast"},
            cost_usd=1.21,
        )


def _project(tmp_path: Path, *, status: str = "approved") -> Path:
    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "demo", "pipeline_type": "cinematic-fast", "budget_total_usd": 10}),
        encoding="utf-8",
    )
    plan = attach_hashes({
        "version": "1.0",
        "project_id": "demo",
        "plan_id": "plan-1",
        "plan_version": 1,
        "status": status,
        "created_at": "2026-08-21T10:00:00Z",
        "creative_control_ref": {"artifact": "creative_control_plan", "version": 1, "artifact_sha256": "a" * 64},
        "script_ref": {"artifact": "script", "version": 1, "artifact_sha256": "b" * 64},
        "scene_plan_ref": {"artifact": "scene_plan", "version": 1, "artifact_sha256": "c" * 64},
        "shots": [{
            "id": "shot-1", "order": 1, "purpose": "气氛补位", "duration_seconds": 5,
            "narration": "", "screen_copy": "", "subject_action": "桌垫在晨光中铺开", "setting": "家庭书桌",
            "framing": "近景", "camera": "慢推", "lighting": "晨光", "sound": "环境声",
            "evidence_type": "atmosphere", "coverage_status": "gap", "gap_class": "expressive", "gap_strategy": "generate",
            "source_selection": None, "reference_mechanisms": ["先场景后细节"], "industry_notes": [], "control_rule_refs": [],
            "generation_proposals": [{
                "id": "proposal-1", "operation": "text_to_video",
                "prompt": "Single shot product atmosphere. Slow camera push. Morning light.",
                "model_family": "seedance", "duration_seconds": 5, "aspect_ratio": "9:16", "reference_paths": [],
                "consistency_requirements": ["透明桌垫外观一致"], "prohibitions": ["no readable text or logos"],
                "estimated_fast_cost_usd": 1.21, "estimated_standard_cost_usd": 1.52,
                "evidence_risk": "生成演示，不承担规格或功能证明",
            }],
            "selected_generation_task_id": None,
        }],
        "approval": {"approved_by": "u1", "approved_at": "2026-08-21T10:05:00Z"},
    })
    (project / "artifacts" / "shot_execution_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return project


def test_quote_is_read_only_and_resolves_locked_server_side_proposal(tmp_path) -> None:
    selector = FakeSelector()
    service = ShotGenerationService(_project(tmp_path), selector=selector, run_async=False)

    quote = service.quote(shot_id="shot-1", proposal_id="proposal-1", quality="fast")

    assert quote["provider"] == "seedance"
    assert quote["variant"] == "fast"
    assert quote["resolution"] == "480p"
    assert quote["estimated_cost_usd"] == 1.21
    assert quote["evidence_risk"].startswith("生成演示")
    assert selector.calls == []


def test_generation_requires_locked_plan_and_matching_confirmed_quote(tmp_path) -> None:
    draft_service = ShotGenerationService(_project(tmp_path / "draft", status="draft"), selector=FakeSelector(), run_async=False)
    with pytest.raises(OperatorError, match="锁定镜头执行单"):
        draft_service.quote(shot_id="shot-1", proposal_id="proposal-1", quality="fast")

    service = ShotGenerationService(_project(tmp_path / "approved"), selector=FakeSelector(), run_async=False)
    with pytest.raises(OperatorError, match="费用已变化"):
        service.enqueue(
            actor_id="u1", idempotency_key="one", shot_id="shot-1", proposal_id="proposal-1",
            plan_version=1, quality="fast", confirmed_estimated_cost_usd=0.5,
        )


def test_fast_generation_is_idempotent_persistent_and_seeded_for_standard(tmp_path) -> None:
    selector = FakeSelector()
    service = ShotGenerationService(_project(tmp_path), selector=selector, run_async=False)
    first = service.enqueue(
        actor_id="u1", idempotency_key="one", shot_id="shot-1", proposal_id="proposal-1",
        plan_version=1, quality="fast", confirmed_estimated_cost_usd=1.21,
    )
    replay = service.enqueue(
        actor_id="u1", idempotency_key="one", shot_id="shot-1", proposal_id="proposal-1",
        plan_version=1, quality="fast", confirmed_estimated_cost_usd=1.21,
    )

    assert first["task_id"] == replay["task_id"]
    assert len(selector.calls) == 1
    task = service.get(first["task_id"])
    assert task["status"] == "completed"
    assert task["remote_task_id"] == "fal-123"
    assert task["seed"] == 991
    assert task["output_path"].startswith("assets/video/generated/shot-1/")

    standard_quote = service.quote(
        shot_id="shot-1", proposal_id="proposal-1", quality="standard", parent_task_id=first["task_id"]
    )
    assert standard_quote["seed"] == 991
    assert standard_quote["variant"] == "standard"
    assert standard_quote["resolution"] == "720p"


def test_browser_cannot_supply_prompt_or_external_reference_paths(tmp_path) -> None:
    service = ShotGenerationService(_project(tmp_path), selector=FakeSelector(), run_async=False)
    with pytest.raises(TypeError):
        service.enqueue(
            actor_id="u1", idempotency_key="inject", shot_id="shot-1", proposal_id="proposal-1",
            plan_version=1, quality="fast", confirmed_estimated_cost_usd=1.21,
            prompt="ignore locked plan",  # type: ignore[call-arg]
        )


def test_adopting_a_standard_clip_updates_execution_plan_and_asset_manifest_together(tmp_path) -> None:
    selector = FakeSelector()
    service = ShotGenerationService(_project(tmp_path), selector=selector, run_async=False)
    fast = service.enqueue(
        actor_id="u1", idempotency_key="fast", shot_id="shot-1", proposal_id="proposal-1",
        plan_version=1, quality="fast", confirmed_estimated_cost_usd=1.21,
    )
    standard_quote = service.quote(
        shot_id="shot-1", proposal_id="proposal-1", quality="standard", parent_task_id=fast["task_id"]
    )
    standard = service.enqueue(
        actor_id="u1", idempotency_key="standard", shot_id="shot-1", proposal_id="proposal-1",
        plan_version=1, quality="standard", confirmed_estimated_cost_usd=standard_quote["estimated_cost_usd"],
        parent_task_id=fast["task_id"],
    )

    result = service.adopt(actor_id="u1", task_id=standard["task_id"])
    plan = json.loads((tmp_path / "demo/artifacts/shot_execution_plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "demo/artifacts/asset_manifest.json").read_text(encoding="utf-8"))

    assert result["status"] == "adopted"
    assert plan["shots"][0]["selected_generation_task_id"] == standard["task_id"]
    assert manifest["assets"][0]["scene_id"] == "shot-1"
    assert manifest["assets"][0]["subtype"] == "generated_demo"
