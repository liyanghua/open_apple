import json

import pytest

from tools.video.video_compose import VideoCompose
from tools.base_tool import ToolResult


def test_production_brand_uses_real_entry_props_and_stages_named_media(tmp_path, monkeypatch):
    from lib import production_brand
    monkeypatch.setattr(production_brand, "preflight_production_brand", lambda *a, **k: {"status": "passed", "strict_ready": True, "checks": []})
    for name in ("footage.mp4", "logo.png", "voice.wav"):
        (tmp_path / name).write_bytes(b"fixture")
    output = tmp_path / "final.mp4"
    seen = {}
    def render(cmd, **kwargs):
        seen["cmd"] = cmd
        path = next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--props="))
        seen["props"] = json.loads(open(path).read())
        output.write_bytes(b"render")
    monkeypatch.setattr(VideoCompose, "_run_remotion_command", lambda self, cmd, **kwargs: render(cmd, **kwargs))
    result = VideoCompose().execute({"operation": "remotion_render", "project_dir": str(tmp_path), "output_path": str(output),
        "composition_data": {"renderer_family": "production-brand", "profile": {"production": {"font_mode": "strict"}},
            "logoSrc": "logo.png", "footage": {"one": "footage.mp4"}, "audio": {"narrationSrc": "voice.wav"},
            "durationInFrames": 240, "scenes": [{"id": "one"}]}})
    assert result.success, result.error
    assert any(arg.endswith("src/brand/entry.tsx") for arg in seen["cmd"])
    assert "ProductionBrand" in seen["cmd"]
    assert seen["props"]["footage"]["one"] != "footage.mp4"
    assert seen["props"]["logoSrc"] != "logo.png"
    assert result.data["brand_preflight"]["strict_ready"]


def test_brand_preflight_failure_prevents_renderer_start(tmp_path, monkeypatch):
    from lib import production_brand
    monkeypatch.setattr(production_brand, "preflight_production_brand", lambda *a, **k: {"status": "blocked", "checks": [{"check_id": "font_identity", "status": "fail"}]})
    monkeypatch.setattr(VideoCompose, "_run_remotion_command", lambda *a, **k: (_ for _ in ()).throw(AssertionError("renderer must not start")))
    result = VideoCompose().execute({"operation": "remotion_render", "project_dir": str(tmp_path), "output_path": str(tmp_path / "x.mp4"),
        "composition_data": {"renderer_family": "production-brand", "profile": {"production": {}}, "scenes": []}})
    assert not result.success
    assert result.data["brand_preflight"]["status"] == "blocked"


@pytest.fixture
def mainline(tmp_path, monkeypatch):
    from lib import production_brand
    monkeypatch.setattr(production_brand, "preflight_production_brand", lambda *a, **k: {"status": "passed", "strict_ready": True, "checks": []})
    seen = {"rendered": False, "reviewed": False, "normalized": False}
    for name in ("footage.mp4", "logo.png", "voice.wav"):
        (tmp_path / name).write_bytes(b"fixture")
    output = tmp_path / "final.mp4"
    def render(self, cmd, **kwargs):
        seen["rendered"] = True
        seen["cmd"] = cmd
        path = next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--props="))
        seen["props"] = json.loads(open(path).read())
        output.write_bytes(b"render")
    def review(self, path, decisions, proposal, **kwargs):
        seen["reviewed"] = True
        seen["review_decisions"] = decisions
        return {"status": "pass", "checks": {}, "issues_found": []}
    def normalize(self, path, profile):
        seen["normalized"] = True
        return False
    monkeypatch.setattr(VideoCompose, "_run_remotion_command", render)
    monkeypatch.setattr(VideoCompose, "_run_final_review", review)
    monkeypatch.setattr(VideoCompose, "_normalize_render_to_profile", normalize)
    payload = {"renderer_family": "production-brand", "render_runtime": "remotion", "profile": {"production": {"font_mode": "strict"}},
        "width": 1080, "height": 1920, "fps": 30, "durationInFrames": 240,
        "logoSrc": "logo", "footage": {"one": "footage"}, "audio": {"narrationSrc": "voice"},
        "captions": [{"text": "完整口播", "startMs": 0, "endMs": 7000}],
        "scenes": [{"id": "one", "footageKey": "one", "fromFrame": 0, "durationInFrames": 240,
                    "sourceInSeconds": 0, "sourceDurationSeconds": 9, "playbackRate": 1, "cropScale": 1, "role": "body"}]}
    inputs = {"operation": "render", "project_dir": str(tmp_path), "output_path": str(output), "edit_decisions": payload,
        "render_plan": {"mode": "full", "profile": "social_vertical_1080p30"},
        "proposal_packet": {"production_plan": {"render_runtime": "remotion"}},
        "asset_manifest": {"version": "1.0", "assets": [
            {"id": name, "path": path, "type": kind, "scene_id": "one", "source_tool": "fixture"}
            for name, path, kind in [("footage", "footage.mp4", "video"), ("logo", "logo.png", "image"), ("voice", "voice.wav", "audio")]
        ]}}
    return inputs, seen


def test_render_operation_routes_brand_payload_through_media_preflight_and_final_review(mainline):
    inputs, seen = mainline
    result = VideoCompose().execute(inputs)
    assert result.success, result.error
    assert "ProductionBrand" in seen["cmd"]
    assert seen["reviewed"] and seen["normalized"]
    assert seen["props"]["logoSrc"] != "logo"
    assert seen["props"]["footage"]["one"] != "footage"
    assert seen["review_decisions"]["cuts"][0]["source"].endswith("footage.mp4")
    assert result.data["brand_preflight"]["strict_ready"]
    assert result.data["final_review_status"] == "pass"
    assert inputs["edit_decisions"]["logoSrc"] == "logo", "canonical input must not be mutated"


@pytest.mark.parametrize("mode", ["still", "window", "sample", "range", "mux_only", "unknown"])
def test_brand_mainline_rejects_unsupported_modes_before_generic_routing(mainline, mode):
    inputs, seen = mainline
    inputs["render_plan"]["mode"] = mode
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert "production-brand" in result.error and "full" in result.error
    assert not seen["rendered"]


@pytest.mark.parametrize("runtime", ["ffmpeg", "hyperframes", ""])
def test_brand_mainline_cannot_swap_the_locked_runtime(mainline, runtime):
    inputs, seen = mainline
    inputs["edit_decisions"]["render_runtime"] = runtime
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert "runtime" in result.error.lower()
    assert not seen["rendered"]


@pytest.mark.parametrize("missing", ["manifest", "unlisted", "file", "plan"])
def test_brand_mainline_requires_manifest_and_resolvable_approved_media(mainline, missing):
    inputs, seen = mainline
    if missing == "manifest":
        inputs.pop("asset_manifest")
    elif missing == "unlisted":
        inputs["asset_manifest"]["assets"].pop()
    elif missing == "file":
        from pathlib import Path
        (Path(inputs["project_dir"]) / "voice.wav").unlink()
    else:
        inputs.pop("render_plan")
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert not seen["rendered"]


def test_brand_mainline_preserves_precompose_gate(mainline, monkeypatch):
    inputs, seen = mainline
    monkeypatch.setattr(VideoCompose, "_pre_compose_validation", lambda *a, **k: ToolResult(success=False, error="fixture delivery promise failed"))
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert "delivery promise" in result.error
    assert not seen["rendered"]


def test_brand_mainline_preserves_failed_final_review(mainline, monkeypatch):
    inputs, seen = mainline
    monkeypatch.setattr(VideoCompose, "_run_final_review", lambda *a, **k: {"status": "fail", "checks": {}, "issues_found": ["fixture QA failed"]})
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert result.data["final_review_status"] == "fail"
    assert seen["rendered"]


@pytest.mark.parametrize("override", ["sample_frames", "remotion_width", "editorial_timeline"])
def test_brand_mainline_rejects_unsupported_overrides(mainline, override):
    inputs, seen = mainline
    inputs[override] = "0-30" if override == "sample_frames" else 540 if override == "remotion_width" else {"tracks": []}
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert "production-brand" in result.error
    assert not seen["rendered"]


def test_brand_mainline_preserves_structured_brand_preflight_failure(mainline, monkeypatch):
    from lib import production_brand
    inputs, seen = mainline
    monkeypatch.setattr(production_brand, "preflight_production_brand", lambda *a, **k: {"status": "blocked", "checks": [{"check_id": "font_files", "status": "fail"}]})
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert result.data["brand_preflight"]["checks"][0]["check_id"] == "font_files"
    assert not seen["rendered"]


def test_brand_mainline_rejects_proposal_runtime_swap_before_render(mainline):
    inputs, seen = mainline
    inputs["proposal_packet"]["production_plan"]["render_runtime"] = "hyperframes"
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert "runtime" in result.error
    assert not seen["rendered"]


def test_brand_mainline_checks_proxy_source_hash_against_source_not_proxy(mainline):
    import hashlib
    from pathlib import Path
    inputs, _ = mainline
    (Path(inputs["project_dir"]) / "original.mp4").write_bytes(b"original source")
    inputs["asset_manifest"]["assets"][0].update(source_path="original.mp4", source_content_sha256=hashlib.sha256(b"original source").hexdigest())
    result = VideoCompose().execute(inputs)
    assert result.success, result.error


def test_brand_mainline_cannot_override_the_approved_renderer_family(mainline):
    inputs, seen = mainline
    inputs["proposal_packet"]["production_plan"]["renderer_family"] = "product-reveal"
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert "renderer_family" in result.error
    assert not seen["rendered"]


def test_brand_mainline_muxes_the_hash_bound_plan_audio_and_reviews_afterwards(mainline, monkeypatch):
    import hashlib
    inputs, seen = mainline
    inputs["edit_decisions"].pop("audio")
    inputs["render_plan"]["audio"] = {"path": "voice.wav", "sha256": hashlib.sha256(b"fixture").hexdigest()}
    def mux(self, output, audio):
        assert not seen["reviewed"]
        seen["mux_audio"] = audio
        return ToolResult(success=True)
    monkeypatch.setattr(VideoCompose, "_mux_external_audio", mux)
    result = VideoCompose().execute(inputs)
    assert result.success, result.error
    assert seen["mux_audio"].endswith("voice.wav")
    assert result.data["has_mixed_audio"]
    assert seen["reviewed"]


@pytest.mark.parametrize("mismatch", ["audio_hash", "dimensions", "manifest_hash", "double_audio"])
def test_brand_mainline_rejects_approved_dependency_conflicts(mainline, mismatch):
    inputs, seen = mainline
    if mismatch in ("audio_hash", "double_audio"):
        inputs["render_plan"]["audio"] = {"path": "voice.wav", "sha256": "0" * 64}
        if mismatch == "audio_hash":
            inputs["edit_decisions"].pop("audio")
    elif mismatch == "dimensions":
        inputs["edit_decisions"]["width"] = 540
    else:
        inputs["asset_manifest"]["assets"][0]["source_content_sha256"] = "0" * 64
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert not seen["rendered"]


@pytest.mark.parametrize("artifact,path", [
    ("edit_decisions", ["properties", "renderer_family"]),
    ("proposal_packet", ["properties", "production_plan", "properties", "renderer_family"]),
])
def test_canonical_artifacts_accept_the_production_brand_renderer(artifact, path):
    from pathlib import Path
    import jsonschema
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "artifacts" / f"{artifact}.schema.json").read_text())
    for key in path:
        schema = schema[key]
    jsonschema.validate("production-brand", schema)
