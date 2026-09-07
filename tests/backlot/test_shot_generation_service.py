from __future__ import annotations

import json
import hashlib
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

    def get_info(self) -> dict:
        return {
            "name": "seedance_video", "provider": "seedance", "status": "available",
            "input_schema": {"properties": {
                "prompt": {"type": "string"}, "operation": {"type": "string"},
                "image_path": {"type": "string"}, "duration": {"type": "string"},
                "aspect_ratio": {"type": "string", "enum": ["3:4"]},
                "resolution": {"type": "string"}, "model_variant": {"type": "string"},
                "output_path": {"type": "string"}, "generate_audio": {"type": "boolean"},
            }},
        }

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


def _generated_product_project(tmp_path: Path, *, approved: bool) -> tuple[Path, str]:
    from lib.template_assets import image_to_video_approval_subject_hash

    project = tmp_path / "product-i2v"
    (project / "artifacts").mkdir(parents=True)
    reference_path = project / "assets/product_page/derived/ref.png"
    reference_path.parent.mkdir(parents=True)
    reference_bytes = b"clean-product-reference"
    reference_path.write_bytes(reference_bytes)
    (project / "project.json").write_text(json.dumps({
        "project_id": "product-i2v", "pipeline_type": "cinematic-fast",
        "budget_total_usd": 10,
    }), encoding="utf-8")
    reference = {
        "asset_id": "clean-ref-1", "parent_asset_id": "page-main-1",
        "local_path": "assets/product_page/derived/ref.png",
        "sha256": hashlib.sha256(reference_bytes).hexdigest(),
        "sku_scope": ["sku-1"],
    }
    shot = {
        "id": "shot-1", "narration": "商品页标注 10A 级抗菌",
        "screen_copy": "商品页标注 · 10A 级抗菌",
    }
    candidate = {
        "tool": "seedance_video", "provider": "seedance", "model": "fast",
        "estimated_cost_usd": 1.21, "supports_local_reference": True,
        "supports_native_3_4": True,
    }
    proposal = {
        "id": "generate-shot-01", "operation": "image_to_video",
        "prompt": "保持商品身份，只做产品英雄展示", "duration_seconds": 4,
        "aspect_ratio": "3:4", "reference_paths": [reference["local_path"]],
        "reference_asset_id": reference["asset_id"], "reference_hash": reference["sha256"],
        "provider_candidates": [candidate],
        "selected_provider_candidate": candidate,
        "provider_selection_status": "locked" if approved else "awaiting_human",
        "required_actions": ["product_hero_display"],
        "required_results": ["product_identity_remains_visible"],
        "consistency_requirements": ["保持商品身份"],
        "prohibitions": ["不得模拟抗菌实验"], "retry_limit": 2,
        "estimated_fast_cost_usd": 1.21, "estimated_standard_cost_usd": 1.52,
        "evidence_risk": "high", "evidence_role": "visual_expression_only",
    }
    approval_hash = image_to_video_approval_subject_hash(shot, proposal)
    proposal["approval_subject_hash"] = approval_hash
    plan = attach_hashes({
        "version": "1.0", "project_id": "product-i2v", "plan_id": "plan-1",
        "plan_version": 1, "status": "approved", "shots": [{**shot,
            "visual_route": "generated_from_product_image",
            "generation_reference": reference,
            "generation_proposals": [proposal],
        }],
    })
    (project / "artifacts/shot_execution_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (project / "artifacts/asset_plan.json").write_text(json.dumps({
        "paid_generation_approved": approved,
        "approved_paid_subject_hashes": [approval_hash] if approved else [],
        "planned_assets": [{
            "id": "generated-shot-01", "type": "generated_video", "shot_id": "shot-1",
            "approval_subject_hash": approval_hash, "generation_reference": reference,
            "paid": True, "exists": False,
        }],
    }), encoding="utf-8")
    (project / "artifacts/product_asset_ledger.json").write_text(json.dumps({
        "assets": [{
            **reference, "asset_role": "derived_clean_reference",
            "usage_role": "generation_reference", "clean_reference_status": "ready",
            "identity_check": {"status": "pass"}, "ocr_residual_text": [],
            "generation_eligibility": "eligible",
        }],
    }), encoding="utf-8")
    return project, approval_hash


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


def test_product_image_generation_requires_current_approved_subject_hash(tmp_path) -> None:
    from lib.product_image_asset_execution import ProductImageAssetExecutor

    selector = FakeSelector()
    project, approval_hash = _generated_product_project(tmp_path, approved=False)
    executor = ProductImageAssetExecutor(project, tool_resolver=lambda _name: selector)
    service = ShotGenerationService(
        project, selector=selector, product_executor=executor, run_async=False
    )

    with pytest.raises(OperatorError, match="当前商品图生成方案"):
        service.enqueue(
            actor_id="u1", idempotency_key="blocked", shot_id="shot-1",
            proposal_id="generate-shot-01", plan_version=1, quality="fast",
            confirmed_estimated_cost_usd=1.21,
        )
    assert selector.calls == []

    asset_plan_path = project / "artifacts/asset_plan.json"
    asset_plan = json.loads(asset_plan_path.read_text(encoding="utf-8"))
    asset_plan["paid_generation_approved"] = True
    asset_plan["approved_paid_subject_hashes"] = [approval_hash]
    asset_plan_path.write_text(json.dumps(asset_plan), encoding="utf-8")
    plan_path = project / "artifacts/shot_execution_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["shots"][0]["generation_proposals"][0]["provider_selection_status"] = "locked"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    task = service.enqueue(
        actor_id="u1", idempotency_key="approved", shot_id="shot-1",
        proposal_id="generate-shot-01", plan_version=1, quality="fast",
        confirmed_estimated_cost_usd=1.21,
    )
    assert task["status"] == "completed"
    assert len(selector.calls) == 1


def test_product_image_generation_rejects_stale_prompt_after_approval(tmp_path) -> None:
    from lib.product_image_asset_execution import ProductImageAssetExecutor

    selector = FakeSelector()
    project, _approval_hash = _generated_product_project(tmp_path, approved=True)
    plan_path = project / "artifacts/shot_execution_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["shots"][0]["generation_proposals"][0]["prompt"] = "已被修改的新提示词"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    executor = ProductImageAssetExecutor(project, tool_resolver=lambda _name: selector)
    service = ShotGenerationService(
        project, selector=selector, product_executor=executor, run_async=False
    )
    with pytest.raises(OperatorError, match="方案已变化"):
        service.enqueue(
            actor_id="u1", idempotency_key="stale", shot_id="shot-1",
            proposal_id="generate-shot-01", plan_version=1, quality="fast",
            confirmed_estimated_cost_usd=1.21,
        )
    assert selector.calls == []


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


def test_source_led_template_shot_generation_rejects_missing_authoritative_batch(tmp_path) -> None:
    project = _project(tmp_path)
    marker = json.loads((project / "project.json").read_text(encoding="utf-8"))
    marker.update({"input_mode": "source_led_template", "template_run": {"batch_project_id": "missing-batch"}})
    (project / "project.json").write_text(json.dumps(marker), encoding="utf-8")
    run_plan = {"status": "approved", "template_id": "", "differentiation_plan_ref": {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": "e" * 64}, "slot_bindings": [{"slot_id": "s", "source": "owned", "source_media_id": "m", "reason": "r"}]}
    (project / "artifacts" / "template_run_plan.json").write_text(json.dumps(run_plan), encoding="utf-8")
    with pytest.raises(OperatorError, match="differentiation"):
        ShotGenerationService(project, selector=FakeSelector(), run_async=False).quote(shot_id="shot-1", proposal_id="proposal-1", quality="fast")


def test_source_led_template_shot_generation_rejects_mismatched_batch_ref(tmp_path, monkeypatch) -> None:
    import lib.template_batch as template_batch
    project = _project(tmp_path)
    marker = json.loads((project / "project.json").read_text(encoding="utf-8"))
    marker["input_mode"] = "source_led_template"
    (project / "project.json").write_text(json.dumps(marker), encoding="utf-8")
    run_plan = {"status": "approved", "template_id": "", "differentiation_plan_ref": {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": "e" * 64}, "slot_bindings": [{"slot_id": "s", "source": "owned", "source_media_id": "m", "reason": "r"}]}
    (project / "artifacts" / "template_run_plan.json").write_text(json.dumps(run_plan), encoding="utf-8")
    monkeypatch.setattr(template_batch, "resolve_run_batch_differentiation_ref", lambda *_: ("source_led_template", {"name": "differentiation_plan", "path": "artifacts/differentiation_plan.json", "artifact_sha256": "d" * 64}))
    with pytest.raises(OperatorError, match="does not match"):
        ShotGenerationService(project, selector=FakeSelector(), run_async=False).quote(shot_id="shot-1", proposal_id="proposal-1", quality="fast")


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
