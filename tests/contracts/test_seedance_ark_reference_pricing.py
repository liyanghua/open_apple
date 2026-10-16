"""Seedance 2.5 reference-video prices must be known before a paid POST."""

import pytest
import requests

from tools.video.seedance_ark import SeedanceArkVideo


@pytest.fixture
def offline_tool(monkeypatch):
    calls = []

    def reject_network(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Pricing checks must not access the network")

    monkeypatch.setattr(requests.sessions.Session, "request", reject_network)
    monkeypatch.setenv("ARK_API_KEY", "pricing-test-key")
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    monkeypatch.delenv("ARK_CNY_PER_USD", raising=False)
    return SeedanceArkVideo(), calls


def reference_inputs(**overrides):
    return {
        "task_action": "generate",
        "model": "doubao-seedance-2-5-260628",
        "model_variant": "2.5",
        "operation": "reference_to_video",
        "prompt": "A new continuous product shot based on the reference.",
        "reference_video_urls": ["https://example.test/original.mp4"],
        "reference_video_durations": [4.041667],
        "duration": 4,
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "generate_audio": False,
        **overrides,
    }


@pytest.mark.parametrize("singular_reference", [False, True])
def test_seedance25_reference_preflight_prices_input_and_output_offline(offline_tool, singular_reference):
    tool, network_calls = offline_tool
    inputs = reference_inputs()
    if singular_reference:
        inputs["reference_video_url"] = inputs.pop("reference_video_urls")[0]

    result = tool.dry_run(inputs)

    # Pricing remains available without pretending a bare URL authorizes upload.
    assert result["parameter_valid"] is True
    assert result["valid"] is False
    assert result["reference_preflight"]["issues"][0]["code"] == "reference_declarations_missing"
    assert result["status"] == "available"
    assert result["estimated_tokens"] == 173700
    assert result["estimated_cost_cny"] == pytest.approx(7.2954)
    assert result["estimated_cost_usd"] is None
    assert result["would_execute"] is False
    assert result["paid_submission"] is False
    assert network_calls == []


@pytest.mark.parametrize("video_evidence", [
    {"reference_video_url": "https://example.test/original.mp4"},
    {"input_includes_video": True},
])
def test_seedance25_reference_usage_uses_same_catalog_rate(offline_tool, video_evidence):
    tool, network_calls = offline_tool
    task = {"model": "doubao-seedance-2-5-260628", "resolution": "720p",
            "usage": {"completion_tokens": 173700}}

    assert tool._cost_from_task_cny(task, video_evidence) == pytest.approx(7.2954)
    assert tool._cost_from_task(task, video_evidence) is None
    assert network_calls == []


def test_seedance25_without_video_price_is_unchanged(offline_tool):
    tool, network_calls = offline_tool
    inputs = reference_inputs(operation="text_to_video")
    inputs.pop("reference_video_urls")
    inputs.pop("reference_video_durations")

    result = tool.dry_run(inputs)

    assert result["valid"] is True
    assert result["estimated_tokens"] == 86400
    assert result["estimated_cost_cny"] == pytest.approx(6.048)
    task = {"model": inputs["model"], "resolution": "720p",
            "usage": {"completion_tokens": 87300}}
    assert tool._cost_from_task_cny(task, inputs) == pytest.approx(6.111)
    assert network_calls == []


def test_seedance25_unknown_reference_price_remains_blocked(offline_tool):
    tool, network_calls = offline_tool
    inputs = reference_inputs(resolution="480p")

    with pytest.raises(ValueError, match="pricing is unknown"):
        tool.estimate_cost_cny(inputs)
    result = tool.dry_run(inputs)
    assert result["valid"] is False
    assert "pricing is unknown" in result["error"]
    assert result["paid_submission"] is False
    task = {"model": inputs["model"], "resolution": "480p",
            "usage": {"completion_tokens": 173700}}
    assert tool._cost_from_task_cny(task, inputs) is None
    assert network_calls == []


def test_seedance25_reference_1080p_is_still_unsupported(offline_tool):
    tool, network_calls = offline_tool
    result = tool.dry_run(reference_inputs(resolution="1080p"))

    assert result["valid"] is False
    assert "2.5 supports only 480p or 720p" in result["error"]
    assert result["paid_submission"] is False
    assert network_calls == []
