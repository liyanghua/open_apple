import json
import hashlib

import pytest

from tools.video.video_compose import VideoCompose
from tools.base_tool import ToolResult


@pytest.mark.parametrize("problem", ["silent", "unbound_hash", "internal", "wrong_hash", "double"])
def test_opening_requires_single_hash_bound_external_mix(mainline, problem):
    inputs, seen = mainline
    inputs["edit_decisions"]["opening"] = {"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5}
    inputs["edit_decisions"].pop("audio")
    inputs["render_plan"]["audio"] = {"path": "voice.wav", "sha256": hashlib.sha256(b"fixture").hexdigest()}
    if problem == "silent": inputs["render_plan"].pop("audio")
    elif problem == "unbound_hash": inputs["render_plan"]["audio"].pop("sha256")
    elif problem == "wrong_hash": inputs["render_plan"]["audio"]["sha256"] = "0" * 64
    elif problem == "internal":
        inputs["render_plan"].pop("audio")
        inputs["edit_decisions"]["audio"] = {"narrationSrc": "voice"}
    else: inputs["edit_decisions"]["audio"] = {"narrationSrc": "voice"}
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert not seen["rendered"]


@pytest.mark.parametrize("via_override", [False, True])
def test_opening_external_mix_is_bound_and_muxed_once(mainline, monkeypatch, via_override):
    inputs, seen = mainline
    inputs["edit_decisions"]["opening"] = {"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5}
    inputs["edit_decisions"].pop("audio")
    mix = {"path": "voice.wav", "sha256": hashlib.sha256(b"fixture").hexdigest()}
    inputs["render_plan"]["audio"] = mix
    if via_override: inputs["audio_path"] = "voice"
    calls = []
    monkeypatch.setattr(VideoCompose, "_mux_external_audio", lambda self, output, audio: calls.append(audio) or ToolResult(success=True))
    result = VideoCompose().execute(inputs)
    assert result.success, result.error
    assert len(calls) == 1
    assert "audio" not in seen["props"]
    assert seen["props"]["finalMix"] == {"path": calls[0], "sha256": mix["sha256"], "mode": "external_mux"}
    assert result.data["final_mix"]["sha256"] == mix["sha256"]


def test_opening_cannot_use_direct_remotion_render_as_silent_delivery(mainline):
    inputs, seen = mainline
    inputs["edit_decisions"]["opening"] = {"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5}
    result = VideoCompose().execute({"operation": "remotion_render", "project_dir": inputs["project_dir"],
        "output_path": inputs["output_path"], "composition_data": inputs["edit_decisions"]})
    assert not result.success
    assert "formal render" in result.error
    assert not seen["rendered"]


def test_opening_mix_drift_during_render_prevents_mux(mainline, monkeypatch):
    from pathlib import Path
    inputs, seen = mainline
    inputs["edit_decisions"].update(opening={"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5})
    inputs["edit_decisions"].pop("audio")
    inputs["render_plan"]["audio"] = {"path": "voice.wav", "sha256": hashlib.sha256(b"fixture").hexdigest()}
    original = VideoCompose._run_remotion_command
    def render(self, cmd, **kwargs):
        original(self, cmd, **kwargs)
        (Path(inputs["project_dir"]) / "voice.wav").write_bytes(b"changed mix")
    monkeypatch.setattr(VideoCompose, "_run_remotion_command", render)
    monkeypatch.setattr(VideoCompose, "_mux_external_audio", lambda *a: pytest.fail("changed mix must not be muxed"))
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert "changed during render" in result.error
    assert seen["rendered"] and not seen["reviewed"]


@pytest.mark.parametrize("declaration", [{}, {"path": "voice", "sha256": "0" * 64, "mode": "external_mux"}])
def test_opening_cannot_silently_replace_conflicting_final_mix_declaration(mainline, monkeypatch, declaration):
    inputs, seen = mainline
    inputs["edit_decisions"].update(opening={"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5}, finalMix=declaration)
    inputs["edit_decisions"].pop("audio")
    inputs["render_plan"]["audio"] = {"path": "voice.wav", "sha256": hashlib.sha256(b"fixture").hexdigest()}
    monkeypatch.setattr(VideoCompose, "_mux_external_audio", lambda *a: ToolResult(success=True))
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert not seen["rendered"]


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


@pytest.mark.parametrize("font_mode", ["legacy_appearance", "strict"])
def test_formal_full_variant_runs_real_preflight_and_blocks_unverified_fonts(tmp_path, monkeypatch, font_mode):
    from PIL import Image
    from lib.production_brand import make_towel_brand_profile
    from lib import render_plan
    from lib import production_brand
    monkeypatch.setattr(production_brand, "probe_motion_source_cadence", lambda *a, **k: {"frame_count": 96}, raising=False)
    profile = make_towel_brand_profile(strict=font_mode == "strict")
    profile["production"]["slogan"] = "PLAYBOY, Better everyday."
    Image.new("RGBA", (240, 120), "black").save(tmp_path / "logo.png")
    (tmp_path / "clip.mp4").write_bytes(b"source bytes")
    (tmp_path / "mix.wav").write_bytes(b"mix bytes")
    monkeypatch.setattr(render_plan, "probe_media", lambda path: {"streams": [{"codec_type": "video", "width": 960,
        "height": 960, "avg_frame_rate": "24/1", "r_frame_rate": "24/1", "duration": "4.000000", "nb_frames": "96"}]})
    framing = {"source": {"width": 960, "height": 960}, "viewport": {"x": 0, "y": 350, "width": 1080, "height": 1080},
        "fit": "contain", "position": {"x": .5, "y": .5}, "actionCoverage": "whole_shot_envelope",
        "actionRegions": [{"x": 0, "y": 0, "width": 960, "height": 960}]}
    base_shot = {"footageKey": "clip", "sourceDurationSeconds": 4, "sourceFps": 24, "playbackRate": 1,
                 "cropScale": 1, "framing": framing}
    text = profile["production"]["slogan"]
    props = {"renderer_family": "production-brand", "render_runtime": "remotion", "profile": profile,
        "opening": {"scope": "full_variant", "endFrameExclusive": 90, "transitionFrames": 5},
        "width": 1080, "height": 1920, "fps": 30, "durationInFrames": 150, "logoSrc": "logo", "footage": {"clip": "clip"},
        "scenes": [dict(base_shot, id="hook", role="hook", fromFrame=0, durationInFrames=90, sourceInSeconds=0),
                   dict(base_shot, id="body", role="body", fromFrame=90, durationInFrames=60, sourceInSeconds=.5)],
        "titles": [{"fromFrame": 0, "text": "Soft"}], "timingSource": "measured_word_timestamps",
        "captions": [{"text": text, "startMs": 3000, "endMs": 4500}],
        "words": [{"text": text, "startMs": 3000, "endMs": 4500}]}
    rendered = []
    output = tmp_path / "final.mp4"
    def render(self, cmd, **kwargs):
        rendered.append(cmd)
        output.write_bytes(b"render")
    monkeypatch.setattr(VideoCompose, "_run_remotion_command", render)
    monkeypatch.setattr(VideoCompose, "_normalize_render_to_profile", lambda *a: False)
    monkeypatch.setattr(VideoCompose, "_mux_external_audio", lambda *a: ToolResult(success=True))
    monkeypatch.setattr(VideoCompose, "_run_final_review", lambda *a, **k: {"status": "pass", "checks": {}, "issues_found": []})
    result = VideoCompose().execute({"operation": "render", "project_dir": str(tmp_path), "edit_decisions": props,
        "output_path": str(output), "render_plan": {"mode": "full", "profile": "social_vertical_1080p30",
            "audio": {"path": "mix", "sha256": hashlib.sha256(b"mix bytes").hexdigest()}},
        "proposal_packet": {"production_plan": {"render_runtime": "remotion"}},
        "asset_manifest": {"assets": [{"id": asset_id, "path": path, "type": kind} for asset_id, path, kind in
            [("clip", "clip.mp4", "video"), ("logo", "logo.png", "image"), ("mix", "mix.wav", "audio")]]}})
    assert not result.success
    assert result.data["brand_preflight"]["status"] == "blocked"
    assert not rendered


@pytest.fixture
def mainline(tmp_path, monkeypatch):
    from lib import production_brand
    monkeypatch.setattr(production_brand, "preflight_production_brand", lambda *a, **k: {"status": "passed", "strict_ready": True, "checks": []})
    monkeypatch.setattr(production_brand, "probe_motion_source_cadence", lambda *a, **k: {"frame_count": 216}, raising=False)
    from lib import render_plan
    monkeypatch.setattr(render_plan, "probe_media", lambda path: {"streams": [{"codec_type": "video", "width": 960, "height": 960,
        "avg_frame_rate": "24/1", "r_frame_rate": "24/1", "duration": "9.000000", "nb_frames": "216"}]})
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
    payload["scenes"][0].update(sourceFps=24, framing={"source": {"width": 960, "height": 960}})
    inputs = {"operation": "render", "project_dir": str(tmp_path), "output_path": str(output), "edit_decisions": payload,
        "render_plan": {"mode": "full", "profile": "social_vertical_1080p30"},
        "proposal_packet": {"production_plan": {"render_runtime": "remotion"}},
        "asset_manifest": {"version": "1.0", "assets": [
            {"id": name, "path": path, "type": kind, "scene_id": "one", "source_tool": "fixture"}
            for name, path, kind in [("footage", "footage.mp4", "video"), ("logo", "logo.png", "image"), ("voice", "voice.wav", "audio")]
        ]}}
    return inputs, seen


def test_formal_opening_checks_decoded_pts_once_per_unique_source(mainline, monkeypatch):
    from lib import production_brand
    inputs, seen = mainline
    props = inputs["edit_decisions"]
    props["opening"] = {"scope": "full_variant", "endFrameExclusive": 90, "transitionFrames": 5}
    props.pop("audio")
    props["scenes"].append(dict(props["scenes"][0], id="same-source-again"))
    inputs["render_plan"]["audio"] = {"path": "voice.wav", "sha256": hashlib.sha256(b"fixture").hexdigest()}
    calls = []
    def check_pts(path, probe):
        calls.append(path)
        return {"frame_count": 216, "min_delta_ticks": 512, "max_delta_ticks": 512}
    monkeypatch.setattr(production_brand, "probe_motion_source_cadence", check_pts, raising=False)
    monkeypatch.setattr(VideoCompose, "_mux_external_audio", lambda *a: ToolResult(success=True))
    result = VideoCompose().execute(inputs)
    assert result.success, result.error
    assert len(calls) == 1
    assert all(row["cadence"]["frame_count"] == 216 for row in result.data["motion_source_probe"])


def test_formal_opening_cadence_failure_stops_renderer(mainline, monkeypatch):
    from lib import production_brand
    inputs, seen = mainline
    props = inputs["edit_decisions"]
    props["opening"] = {"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5}
    props.pop("audio")
    inputs["render_plan"]["audio"] = {"path": "voice.wav", "sha256": hashlib.sha256(b"fixture").hexdigest()}
    monkeypatch.setattr(production_brand, "probe_motion_source_cadence", lambda *a: (_ for _ in ()).throw(ValueError("PTS cadence varies")), raising=False)
    monkeypatch.setattr(VideoCompose, "_mux_external_audio", lambda *a: ToolResult(success=True))
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert "PTS cadence" in result.error
    assert not seen["rendered"]


@pytest.mark.parametrize("field", ["width", "height", "fps", "duration", "rotation", "probe_error"])
def test_opening_rejects_declared_source_metadata_drift_before_render(mainline, monkeypatch, field):
    inputs, seen = mainline
    monkeypatch.setattr(VideoCompose, "_mux_external_audio", lambda *a: ToolResult(success=True))
    inputs["edit_decisions"]["opening"] = {"scope": "preview", "endFrameExclusive": 90, "transitionFrames": 5}
    inputs["edit_decisions"].pop("audio")
    inputs["render_plan"]["audio"] = {"path": "voice.wav", "sha256": hashlib.sha256(b"fixture").hexdigest()}
    shot = inputs["edit_decisions"]["scenes"][0]
    if field in ("width", "height"): shot["framing"]["source"][field] = 1080
    elif field == "fps": shot["sourceFps"] = 30
    elif field == "duration": shot["sourceDurationSeconds"] = 8.99
    else:
        from lib import render_plan
        if field == "probe_error": monkeypatch.setattr(render_plan, "probe_media", lambda path: (_ for _ in ()).throw(RuntimeError("fixture probe failure")))
        else: monkeypatch.setattr(render_plan, "probe_media", lambda path: {"streams": [{"codec_type": "video", "width": 960, "height": 960,
            "avg_frame_rate": "24/1", "duration": "9", "side_data_list": [{"rotation": 90}]}]})
    result = VideoCompose().execute(inputs)
    assert not result.success
    assert "source" in result.error
    assert not seen["rendered"]


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
