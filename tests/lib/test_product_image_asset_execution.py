from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.base_tool import ToolResult


class FakeI2VTool:
    def __init__(self, *, returned_provider: str = "mock") -> None:
        self.calls: list[dict] = []
        self.returned_provider = returned_provider

    def get_info(self) -> dict:
        return {
            "name": "mock_i2v", "provider": "mock", "status": "available",
            "input_schema": {"properties": {
                "prompt": {"type": "string"},
                "operation": {"type": "string"},
                "image_path": {"type": "string"},
                "duration": {"type": "integer"},
                "aspect_ratio": {"type": "string", "enum": ["3:4"]},
                "resolution": {"type": "string"},
                "model": {"type": "string", "default": "mock-v1"},
                "output_path": {"type": "string"},
            }},
        }

    def estimate_cost(self, inputs: dict) -> float:
        return 0.2

    def execute(self, inputs: dict) -> ToolResult:
        self.calls.append(inputs)
        output = Path(inputs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"generated-video")
        return ToolResult(
            success=True,
            data={
                "output_path": str(output), "selected_tool": "mock_i2v",
                "selected_provider": self.returned_provider, "model": "mock-v1",
            },
            cost_usd=0.2,
        )


def _request(project: Path) -> tuple[dict, dict, Path]:
    reference = project / "assets/product_page/derived/clean.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"clean-reference")
    reference_hash = hashlib.sha256(reference.read_bytes()).hexdigest()
    shot = {"id": "shot-05", "narration": "商品页标注 10A 级抗菌", "screen_copy": "商品页标注"}
    proposal = {
        "id": "generate-shot-05", "operation": "image_to_video",
        "prompt": "保持粉色毛巾身份，只做产品英雄展示",
        "duration_seconds": 4, "aspect_ratio": "3:4",
        "reference_paths": ["assets/product_page/derived/clean.png"],
        "reference_hash": reference_hash,
        "provider_candidates": [{
            "tool": "mock_i2v", "provider": "mock", "model": "mock-v1",
            "estimated_cost_usd": 0.2, "supports_local_reference": True,
            "supports_native_3_4": True,
        }],
        "selected_provider_candidate": {
            "tool": "mock_i2v", "provider": "mock", "model": "mock-v1",
            "estimated_cost_usd": 0.2, "supports_local_reference": True,
            "supports_native_3_4": True,
        },
        "provider_selection_status": "locked",
    }
    return shot, proposal, reference


def test_executor_uses_only_locked_registry_tool_and_records_lineage(tmp_path: Path) -> None:
    from lib.product_image_asset_execution import ProductImageAssetExecutor

    project = tmp_path / "demo"; project.mkdir()
    shot, proposal, reference = _request(project)
    tool = FakeI2VTool()
    executor = ProductImageAssetExecutor(project, tool_resolver=lambda name: tool if name == "mock_i2v" else None)

    receipt = executor.execute(
        shot=shot, proposal=proposal, quality="standard", idempotency_key="run-1",
        output_path="assets/video/shot-05-generated.mp4",
    )

    assert len(tool.calls) == 1
    inputs = tool.calls[0]
    assert inputs["image_path"] == str(reference.resolve())
    assert inputs["aspect_ratio"] == "3:4"
    assert inputs["model"] == "mock-v1"
    assert inputs["duration"] == 4
    assert receipt["provider"] == "mock"
    assert receipt["model"] == "mock-v1"
    assert receipt["reference_hash"] == proposal["reference_hash"]
    assert receipt["output_sha256"] == hashlib.sha256(b"generated-video").hexdigest()
    assert receipt["actual_cost_usd"] == 0.2

    replay = executor.execute(
        shot=shot, proposal=proposal, quality="standard", idempotency_key="run-1",
        output_path="assets/video/shot-05-generated.mp4",
    )
    assert replay == receipt
    assert len(tool.calls) == 1


def test_executor_rejects_unlocked_or_silently_substituted_provider(tmp_path: Path) -> None:
    from lib.product_image_asset_execution import ProductImageAssetExecutor

    project = tmp_path / "demo"; project.mkdir()
    shot, proposal, _reference = _request(project)
    tool = FakeI2VTool(returned_provider="different-provider")
    executor = ProductImageAssetExecutor(project, tool_resolver=lambda _name: tool)

    proposal["provider_selection_status"] = "awaiting_human"
    with pytest.raises(ValueError, match="not locked"):
        executor.execute(
            shot=shot, proposal=proposal, quality="standard", idempotency_key="unlocked",
            output_path="assets/video/unlocked.mp4",
        )

    proposal["provider_selection_status"] = "locked"
    with pytest.raises(ValueError, match="provider substitution"):
        executor.execute(
            shot=shot, proposal=proposal, quality="standard", idempotency_key="mismatch",
            output_path="assets/video/mismatch.mp4",
        )


def test_executor_rejects_idempotency_key_reuse_for_changed_prompt(tmp_path: Path) -> None:
    from lib.product_image_asset_execution import ProductImageAssetExecutor

    project = tmp_path / "demo"; project.mkdir()
    shot, proposal, _reference = _request(project)
    tool = FakeI2VTool()
    executor = ProductImageAssetExecutor(project, tool_resolver=lambda _name: tool)
    executor.execute(
        shot=shot, proposal=proposal, quality="standard", idempotency_key="same",
        output_path="assets/video/original.mp4",
    )
    changed = dict(proposal, prompt="different prompt")
    with pytest.raises(ValueError, match="idempotency"):
        executor.execute(
            shot=shot, proposal=changed, quality="standard", idempotency_key="same",
            output_path="assets/video/original.mp4",
        )
