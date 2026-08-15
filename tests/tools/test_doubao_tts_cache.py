from __future__ import annotations

import pytest
from pathlib import Path

from tools.audio.doubao_tts import DoubaoTTS
from tools.base_tool import BaseTool
from tools.base_tool import CacheArtifactSpec, ToolResult, ToolStatus
from tools.audio.tts_selector import TTSSelector
from tools.cost_tracker import CostTracker
from lib.config_model import BudgetMode


def _inputs() -> dict:
    return {
        "text": "透明桌垫一擦就干净",
        "voice_id": "zh_female_vv_uranus_bigtts",
        "resource_id": "seed-tts-2.0",
        "speech_rate": 0,
        "sample_rate": 24000,
        "format": "mp3",
        "enable_timestamp": True,
        "disable_markdown_filter": False,
        "return_usage": True,
        "user_id": "openmontage",
    }


def test_base_tool_cache_contract_is_opt_in() -> None:
    assert BaseTool.canonical_request(object(), {}) is None
    assert BaseTool.cache_artifact_contract(object(), {}) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text", "changed"), ("voice_id", "another_voice"),
        ("resource_id", "seed-tts-2.0-new"), ("speech_rate", 25),
        ("sample_rate", 48000), ("format", "ogg_opus"),
        ("enable_timestamp", False), ("disable_markdown_filter", True),
        ("return_usage", False), ("user_id", "another-user"),
    ],
)
def test_doubao_key_changes_for_every_provider_request_field(field: str, value) -> None:
    tool = DoubaoTTS()
    assert tool.idempotency_key(_inputs()) != tool.idempotency_key({**_inputs(), field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("output_path", "/tmp/a.mp3"), ("metadata_path", "/tmp/a.json"),
        ("request_id", "request-2"), ("api_key", "secret"),
        ("signed_url", "https://signed.example/audio"),
        ("poll_interval_seconds", 9.0), ("timeout_seconds", 999),
    ],
)
def test_doubao_key_ignores_delivery_paths_secrets_and_polling(field: str, value) -> None:
    tool = DoubaoTTS()
    assert tool.idempotency_key(_inputs()) == tool.idempotency_key({**_inputs(), field: value})


def test_doubao_defaults_are_materialized_and_secret_free(monkeypatch) -> None:
    monkeypatch.setenv("DOUBAO_SPEECH_VOICE_TYPE", "env_voice")
    monkeypatch.setenv("DOUBAO_SPEECH_API_KEY", "never-persist-me")
    request = DoubaoTTS().canonical_request({"text": "hello"})
    assert request["voice_id"] == "env_voice"
    assert request["audio_params"] == {
        "format": "mp3", "sample_rate": 24000,
        "speech_rate": 0, "enable_timestamp": True,
    }
    assert request["additions"] == {"disable_markdown_filter": False}
    assert "never-persist-me" not in repr(request)
    assert "unique_id" not in request


def test_doubao_tool_and_resource_revisions_change_key() -> None:
    tool = DoubaoTTS()
    baseline = tool.idempotency_key(_inputs())
    tool.version = "next"
    assert baseline != tool.idempotency_key(_inputs())
    tool.version = "0.1.0"
    tool.RESOURCE_REVISION = "next-resource"
    assert baseline != tool.idempotency_key(_inputs())


class FakeProvider(BaseTool):
    name = "fake_tts"
    provider = "fake"
    capability = "tts"
    version = "1"

    def __init__(self) -> None:
        self.calls = 0

    def get_status(self):
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs):
        return 0.01

    def canonical_request(self, inputs):
        return {
            "text": inputs["text"], "voice_id": inputs.get("voice_id", "warm"),
            "language": inputs.get("language", "zh-CN"),
            "input_type": inputs.get("input_type", "text"),
            "instructions": inputs.get("instructions", ""),
            "style": inputs.get("style", 0.0),
        }

    def cache_artifact_contract(self, inputs):
        valid = lambda path: path.is_file() and path.stat().st_size > 0
        return [
            CacheArtifactSpec("audio", ".mp3", validator=valid),
            CacheArtifactSpec("metadata", ".json", validator=valid),
        ]

    def execute(self, inputs):
        self.calls += 1
        audio = Path(inputs["output_path"])
        metadata = Path(inputs["metadata_path"])
        audio.parent.mkdir(parents=True, exist_ok=True)
        metadata.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"audio")
        metadata.write_text('{"sentences": []}')
        return ToolResult(
            success=True,
            data={"output": str(audio), "metadata_path": str(metadata)},
            artifacts=[str(audio), str(metadata)],
            cost_usd=0.01,
        )


def _selector(provider: FakeProvider) -> TTSSelector:
    selector = TTSSelector()
    selector._providers = lambda: [provider]
    selector._select_best_tool = lambda inputs, candidates, context: (provider, None)
    return selector


def _selector_inputs(tmp_path: Path, operation: str) -> dict:
    return {
        "operation": operation,
        "project_dir": str(tmp_path / "project"),
        "preferred_provider": "fake",
        "text": "hello",
        "voice_id": "warm",
        "language": "zh-CN",
        "input_type": "text",
        "instructions": "gentle",
        "style": 0.2,
        "output_path": str(tmp_path / "out" / "voice.mp3"),
        "metadata_path": str(tmp_path / "out" / "voice.json"),
    }


def test_selector_prepare_hashes_provider_complete_request_without_calling_provider(tmp_path: Path) -> None:
    provider = FakeProvider()
    selector = _selector(provider)
    first = selector.execute(_selector_inputs(tmp_path, "prepare"))
    changed = selector.execute({**_selector_inputs(tmp_path, "prepare"), "style": 0.8})
    assert first.success and changed.success
    assert first.data["cache_status"] == "miss"
    assert first.data["cache_key"] != changed.data["cache_key"]
    assert provider.calls == 0


def test_selector_generate_requires_matching_reserved_cost_entry(tmp_path: Path) -> None:
    provider = FakeProvider()
    selector = _selector(provider)
    inputs = _selector_inputs(tmp_path, "generate")
    denied = selector.execute(inputs)
    assert denied.success is False
    assert denied.data["provider_called"] is False
    assert provider.calls == 0

    cost_log = tmp_path / "cost_log.json"
    tracker = CostTracker(
        mode=BudgetMode.OBSERVE, require_approval_for_new_paid_tool=False,
        cost_log_path=cost_log,
    )
    reservation = tracker.estimate(provider.name, "generate", 0.01)
    tracker.reserve(reservation)
    allowed = selector.execute({
        **inputs, "cost_log_path": str(cost_log), "reservation_id": reservation,
    })
    assert allowed.success is True
    assert allowed.data["cache_status"] == "miss"
    assert provider.calls == 1


def test_selector_materializes_hit_without_provider_and_fails_closed_if_corrupt(tmp_path: Path) -> None:
    provider = FakeProvider()
    selector = _selector(provider)
    generate = _selector_inputs(tmp_path, "generate")
    cost_log = tmp_path / "cost_log.json"
    tracker = CostTracker(
        mode=BudgetMode.OBSERVE, require_approval_for_new_paid_tool=False,
        cost_log_path=cost_log,
    )
    reservation = tracker.estimate(provider.name, "generate", 0.01)
    tracker.reserve(reservation)
    generated = selector.execute({
        **generate, "cost_log_path": str(cost_log), "reservation_id": reservation,
    })
    key = generated.data["cache_key"]

    prepare = selector.execute(_selector_inputs(tmp_path, "prepare"))
    assert prepare.data["cache_status"] == "hit"
    materialize_inputs = {
        **_selector_inputs(tmp_path, "materialize"),
        "cache_key": key,
        "output_path": str(tmp_path / "reuse" / "voice.mp3"),
        "metadata_path": str(tmp_path / "reuse" / "voice.json"),
    }
    reused = selector.execute(materialize_inputs)
    assert reused.success and reused.data["provider_called"] is False
    assert Path(reused.data["output"]).read_bytes() == b"audio"
    assert provider.calls == 1

    cache_audio = Path(generate["project_dir"]) / ".cache" / "tts" / key / "audio.mp3"
    cache_audio.write_bytes(b"corrupt")
    failed = selector.execute({
        **materialize_inputs,
        "output_path": str(tmp_path / "failed" / "voice.mp3"),
    })
    assert failed.success is False
    assert failed.data["cache_status"] == "miss"
    assert failed.data["provider_called"] is False
    assert provider.calls == 1
