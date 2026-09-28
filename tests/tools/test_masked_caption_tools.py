"""Safety gates for the single s01 masked-caption provider trial."""

import json
from pathlib import Path

import pytest

from tools.tool_registry import ToolRegistry


def test_registry_exposes_bounded_tools_outside_video_selector():
    registry = ToolRegistry()
    registry.discover()
    local = registry.get("masked_caption_composite")
    provider = registry.get("vace_caption_candidate")
    assert local.capability == provider.capability == "video_post"
    assert local.provider == "local"
    assert provider.provider == "fal"
    assert "python:fal_client" in provider.dependencies
    assert "env:FAL_KEY" in provider.dependencies


def test_prepare_rejects_unapproved_source_without_output(tmp_path):
    from tools.video.masked_caption_composite import MaskedCaptionComposite
    source = tmp_path / "source.mp4"
    mask = tmp_path / "mask.pgm"
    source.write_bytes(b"wrong source")
    mask.write_bytes(b"wrong mask")
    output = tmp_path / "prepared"
    result = MaskedCaptionComposite().execute({"action": "prepare", "input_path": str(source),
        "mask_path": str(mask), "output_dir": str(output), "single_shot_verified": True})
    assert not result.success
    assert not output.exists()


def test_provider_rejects_before_network_without_approved_checkpoint(tmp_path, monkeypatch):
    from tools.video.vace_caption_candidate import VaceCaptionCandidate
    project = tmp_path / "project"
    project.mkdir()
    (project / "checkpoint_assets.json").write_text(json.dumps({"data": {"decision_log": {"decisions": []}}, "metadata": {}}))
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    output = tmp_path / "attempt"
    monkeypatch.setenv("FAL_KEY", "test-secret")
    result = VaceCaptionCandidate().execute({"action": "submit", "contract_path": str(contract),
        "output_dir": str(output), "project_dir": str(project), "reservation_id": "no-budget",
        "approval_ref": "d030"})
    assert not result.success
    assert not output.exists()
    assert "test-secret" not in (result.error or "")


def test_alias_configuration_and_actual_sdk_lifecycle(monkeypatch):
    from fal_client import StorageSettings
    from fal_client.client import _normalize_upload_lifecycle
    from tools.video.vace_caption_candidate import VaceCaptionCandidate
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setenv("FAL_AI_API_KEY", "alias-secret")
    tool = VaceCaptionCandidate()
    tool.check_dependencies()
    assert tool._headers()["Authorization"] == "Key alias-secret"
    assert _normalize_upload_lifecycle(StorageSettings(expires_in=86400)) == {"expiration_duration_seconds": 86400}


@pytest.fixture(scope="module")
def prepared_pilot(tmp_path_factory):
    """Use the approved immutable local pilot; never call a provider."""
    from tools.video.masked_caption_composite import MaskedCaptionComposite
    root = Path(__file__).resolve().parents[2].parents[1]
    project = root / "projects/table-mat-reuse-first-v1"
    source = project / "inputs/reference/douyin-7670014963255151913.mp4"
    mask = project / "analysis/assets-correction-v3/s01-caption-glyph-mask-v2.pgm"
    if not source.is_file() or not mask.is_file():
        pytest.skip("approved pilot media is not installed in this checkout")
    base = tmp_path_factory.mktemp("masked-caption-pilot")
    result = MaskedCaptionComposite().execute({"action": "prepare", "input_path": str(source),
        "mask_path": str(mask), "output_dir": str(base / "prepared"), "single_shot_verified": True})
    assert result.success, result.error
    assert len(result.data["mask_coverage_evidence"]) == 4
    assert result.data["evidence_frames"] == 38
    return Path(result.data["contract_path"])


@pytest.fixture
def provider_case(tmp_path, prepared_pilot, monkeypatch):
    from tools.cost_tracker import CostTracker
    from tools.video import vace_caption_candidate as module
    import fal_client

    project = tmp_path / "project"
    project.mkdir()
    checkpoint = {"artifacts": {"decision_log": {"data": {"decisions": [{
        "decision_id": "d030", "category": "provider_selection", "subject": "Caption reconstruction model",
        "selected": "wan_vace14b_single_trial", "user_approved": True}]}}},
        "metadata": {"capability_work": {"approval_ref": "d030", "model_call_approved": True,
        "proposed_endpoint": module.ENDPOINT, "proposed_trial_ceiling_usd": 0.5,
        "proposed_upload_scope": "s01 silent padded frames and glyph mask only"}}}
    (project / "checkpoint_assets.json").write_text(json.dumps(checkpoint))
    tracker = CostTracker(cost_log_path=project / "cost_log.json")
    tracker.approve_tool("vace_caption_candidate")
    reservation = tracker.estimate("vace_caption_candidate", module.OPERATION, 0.5)
    tracker.reserve(reservation)
    args = {"action": "submit", "contract_path": str(prepared_pilot), "output_dir": str(tmp_path / "attempt"),
            "project_dir": str(project), "reservation_id": reservation, "approval_ref": "d030"}
    calls = {"uploads": [], "posts": [], "gets": []}
    monkeypatch.setenv("FAL_KEY", "test-secret")

    class Client:
        def __init__(self, *, key, default_timeout):
            assert key == "test-secret" and default_timeout == 120

        def upload_file(self, path, *, lifecycle):
            from fal_client import StorageSettings
            assert isinstance(lifecycle, StorageSettings)
            calls["uploads"].append(path)
            return "https://v3.fal.media/files/" + Path(path).name

    class Response:
        status_code = 202
        def json(self):
            return {"request_id": "request-123", "status": "IN_QUEUE",
                "status_url": "https://queue.fal.run/fal-ai/wan-vace-14b/requests/request-123/status",
                "response_url": "https://queue.fal.run/fal-ai/wan-vace-14b/requests/request-123",
                "cancel_url": "https://queue.fal.run/fal-ai/wan-vace-14b/requests/request-123/cancel"}

    def post(url, **kwargs):
        calls["posts"].append((url, kwargs))
        return Response()

    monkeypatch.setattr(fal_client, "SyncClient", Client)
    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: pytest.fail("unexpected network GET"))
    return module, args, calls, tracker


@pytest.fixture(scope="module")
def gray_pilot(tmp_path_factory, prepared_pilot):
    from tools.video.masked_caption_composite import MaskedCaptionComposite
    original = json.loads(prepared_pilot.read_text())
    result = MaskedCaptionComposite().execute({"action": "prepare",
        "input_path": original["source"]["path"], "mask_path": original["mask"]["path"],
        "output_dir": str(tmp_path_factory.mktemp("gray-caption-pilot") / "prepared"),
        "single_shot_verified": True, "input_preprocessing": "vace_gray127"})
    assert result.success, result.error
    return Path(result.data["contract_path"])


def test_gray_preparation_and_contract_verify_actual_pixels(gray_pilot, tmp_path):
    import numpy as np
    from lib.masked_caption_media import validate_contract, stream_rgb, encode_rgb
    from tools.video.temporal_caption_repair import _pgm_mask, _source_hash
    contract = json.loads(gray_pilot.read_text())
    assert contract["version"] == 2
    assert contract["input_preprocessing"] == "vace_gray127"
    mask, _ = _pgm_mask(Path(contract["mask"]["path"]), 720, 1280)
    for frame in stream_rgb(Path(contract["input_video"]["path"]), 720, 1280, expected_frames=81):
        assert np.all(frame[mask] == 127)
    assert validate_contract(gray_pilot)["version"] == 2
    # Even an updated file hash cannot conceal a raw/text-bearing upload.
    import shutil
    bad = tmp_path / "bad"
    shutil.copytree(gray_pilot.parent, bad)
    upload = bad / "input-padded.mp4"
    upload.unlink()
    raw = np.zeros((1280, 720, 3), dtype=np.uint8)
    encode_rgb(upload, (raw for _ in range(81)), 720, 1280, 30, codec="h264rgb")
    contract["input_video"].update(path=str(upload), sha256=_source_hash(upload))
    contract["mask_video"]["path"] = str(bad / "mask-padded.mp4")
    altered = bad / "changed-contract.json"
    altered.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="prepared input frame"):
        validate_contract(altered)


def test_gray_trial_needs_new_exact_approval_and_own_claim(provider_case, gray_pilot, monkeypatch):
    module, args, calls, tracker = provider_case
    args.update(contract_path=str(gray_pilot), approval_ref="d032")
    tool = module.VaceCaptionCandidate()
    blocked = tool.execute(args)
    assert not blocked.success and not calls["posts"]
    checkpoint_path = Path(args["project_dir"]) / "checkpoint_assets.json"
    cp = json.loads(checkpoint_path.read_text())
    decision = cp["artifacts"]["decision_log"]["data"]["decisions"][0]
    decision.update(decision_id="d032", selected="wan_vace14b_gray127_single_trial")
    cp["metadata"]["capability_work"].update(approval_ref="d032", input_preprocessing="vace_gray127")
    checkpoint_path.write_text(json.dumps(cp))
    reservation = tracker.estimate(tool.name, "s01_wan_vace14b_gray127_once", 0.5)
    tracker.reserve(reservation)
    args["reservation_id"] = reservation
    # A consumed old approval must remain untouched, and must not block a new one.
    old_claim = Path(args["project_dir"]) / module.CLAIM_NAME
    old_claim.write_text("historical d030 claim")
    result = tool.execute(args)
    assert result.success, result.error
    assert old_claim.read_text() == "historical d030 claim"
    assert len(calls["posts"]) == 1
    assert calls["posts"][0][1]["json"]["preprocess"] is False
    assert not tool.execute(args).success
    assert len(calls["posts"]) == 1
    class Pending:
        status_code = 202
        def json(self):
            return {"status": "IN_QUEUE"}
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: Pending())
    resumed = tool.execute({**args, "action": "resume"})
    assert resumed.success and resumed.data["status"] == "pending"
    assert len(calls["posts"]) == 1


def test_gray_trial_rejects_legacy_contract_before_upload(provider_case):
    module, args, calls, tracker = provider_case
    args["approval_ref"] = "d032"
    cp_path = Path(args["project_dir"]) / "checkpoint_assets.json"
    cp = json.loads(cp_path.read_text())
    cp["artifacts"]["decision_log"]["data"]["decisions"][0].update(
        decision_id="d032", selected="wan_vace14b_gray127_single_trial")
    cp["metadata"]["capability_work"].update(approval_ref="d032", input_preprocessing="vace_gray127")
    cp_path.write_text(json.dumps(cp))
    result = module.VaceCaptionCandidate().execute(args)
    assert not result.success
    assert not calls["uploads"] and not calls["posts"]


def test_fixed_payload_lifecycle_and_permanent_duplicate_block(provider_case):
    module, args, calls, tracker = provider_case
    tool = module.VaceCaptionCandidate()
    result = tool.execute(args)
    assert result.success, result.error
    assert result.data["request_id"] == "request-123"
    assert result.cost_usd is None
    assert len(calls["uploads"]) == 2 and len(calls["posts"]) == 1
    url, options = calls["posts"][0]
    assert url == module.QUEUE
    expected = {"video_url": "https://v3.fal.media/files/input-padded.mp4",
                "mask_video_url": "https://v3.fal.media/files/mask-padded.mp4",
                "match_input_num_frames": True, "num_frames": 81,
                "match_input_frames_per_second": True, "frames_per_second": 30,
                "resolution": "720p", "aspect_ratio": "9:16", "seed": 20260926,
                "num_inference_steps": 30, "guidance_scale": 5, "sampler": "unipc",
                "shift": 5, "acceleration": "none", "video_quality": "maximum",
                "enable_safety_checker": True, "enable_prompt_expansion": False,
                "preprocess": False, "num_interpolated_frames": 0,
                "temporal_downsample_factor": 0, "enable_auto_downsample": False}
    assert {key: options["json"][key] for key in expected} == expected
    assert set(options["json"]) == set(expected) | {"prompt", "negative_prompt"}
    assert "caption and its shadow only" in options["json"]["prompt"]
    assert options["headers"]["X-Fal-Store-IO"] == "0"
    assert json.loads(options["headers"]["X-Fal-Object-Lifecycle-Preference"]) == {"expiration_duration_seconds": 86400}
    assert options["allow_redirects"] is False
    new_reservation = tracker.estimate(tool.name, module.OPERATION, 0.5)
    tracker.reserve(new_reservation)
    duplicate = tool.execute({**args, "reservation_id": new_reservation,
                              "output_dir": str(Path(args["output_dir"]).with_name("new-attempt"))})
    assert not duplicate.success
    assert len(calls["uploads"]) == 2 and len(calls["posts"]) == 1
    state = json.loads((Path(args["output_dir"]) / "attempt_state.json").read_text())
    assert "test-secret" not in json.dumps(state)
    assert "fal.media" not in json.dumps(state)


def test_missing_budget_or_tampered_contract_has_zero_paid_side_effects(provider_case):
    module, args, calls, _ = provider_case
    tool = module.VaceCaptionCandidate()
    assert not tool.execute({**args, "reservation_id": "missing"}).success
    tampered = Path(args["output_dir"]).parent / "tampered.json"
    contract = json.loads(Path(args["contract_path"]).read_text())
    contract["frame_map"][21] = 1
    tampered.write_text(json.dumps(contract))
    assert not tool.execute({**args, "contract_path": str(tampered)}).success
    assert calls["uploads"] == calls["posts"] == []


def test_uncertain_post_never_retries_and_resume_has_no_arbitrary_id(provider_case, monkeypatch):
    module, args, calls, _ = provider_case
    def uncertain(url, **kwargs):
        calls["posts"].append((url, kwargs))
        raise module.requests.Timeout("signed-url-and-secret-must-not-leak")
    monkeypatch.setattr(module.requests, "post", uncertain)
    tool = module.VaceCaptionCandidate()
    result = tool.execute(args)
    assert not result.success and result.data["status"] == "submission_unknown"
    assert "signed-url" not in result.error
    assert not tool.execute(args).success
    resumed = tool.execute({**args, "action": "resume", "request_id": "caller-made-up"})
    assert not resumed.success
    assert len(calls["posts"]) == 1


@pytest.mark.parametrize("http_status,provider_status", [(200, "IN_PROGRESS"), (202, "IN_QUEUE"), (202, "IN_PROGRESS")])
def test_resume_polls_owned_request_once(provider_case, monkeypatch, http_status, provider_status):
    module, args, calls, _ = provider_case
    tool = module.VaceCaptionCandidate()
    assert tool.execute(args).success
    state_path = Path(args["output_dir"]) / "attempt_state.json"
    stale = json.loads(state_path.read_text())
    stale.update(http_status=202, provider_error_code="provider_unreported", provider_error_message="old status query failed")
    module._write_state(state_path, stale)
    class Pending:
        status_code = http_status
        def json(self):
            return {"status": provider_status, "request_id": "request-123", "logs": None}
    def get(url, **kwargs):
        calls["gets"].append((url, kwargs))
        return Pending()
    monkeypatch.setattr(module.requests, "get", get)
    resumed = tool.execute({**args, "action": "resume"})
    assert resumed.success and resumed.data["status"] == "pending"
    assert len(calls["posts"]) == 1 and len(calls["gets"]) == 1
    assert calls["gets"][0][0].endswith("/requests/request-123/status")
    assert calls["gets"][0][1]["allow_redirects"] is False
    assert "http_status" not in resumed.data and "provider_error_message" not in resumed.data
    assert "http_status" not in json.loads(state_path.read_text())


def test_status_202_unknown_body_cannot_complete_candidate(provider_case, monkeypatch):
    module, args, calls, _ = provider_case
    tool = module.VaceCaptionCandidate()
    assert tool.execute(args).success
    class Unknown:
        status_code = 202
        def json(self):
            return {"detail": "processing", "request_id": "request-123"}
    def get(url, **kwargs):
        calls["gets"].append(url)
        return Unknown()
    monkeypatch.setattr(module.requests, "get", get)
    resumed = tool.execute({**args, "action": "resume"})
    assert not resumed.success and resumed.data["status"] == "pending"
    assert "candidate_path" not in resumed.data and len(calls["gets"]) == 1
    assert len(calls["posts"]) == 1


def test_result_202_retains_pending_owned_request(provider_case, monkeypatch):
    module, args, calls, _ = provider_case
    tool = module.VaceCaptionCandidate()
    assert tool.execute(args).success
    class CompleteStatus:
        status_code = 202
        def json(self):
            return {"status": "COMPLETED", "request_id": "request-123", "logs": None}
    class PendingResult:
        status_code = 202
        def json(self):
            return {"detail": "result still processing"}
    def get(url, **kwargs):
        calls["gets"].append(url)
        return CompleteStatus() if url.endswith("/status") else PendingResult()
    monkeypatch.setattr(module.requests, "get", get)
    resumed = tool.execute({**args, "action": "resume"})
    assert resumed.success and resumed.data["status"] == "pending"
    assert resumed.data["request_id"] == "request-123"
    assert "http_status" not in resumed.data and "candidate_path" not in resumed.data
    assert len(calls["gets"]) == 2 and len(calls["posts"]) == 1


def test_provider_rejection_keeps_bounded_sanitized_diagnostic(provider_case, monkeypatch):
    module, args, calls, _ = provider_case
    class Rejection:
        status_code = 422
        def json(self):
            return {"error": {"code": "policy_violation", "message": "Rejected test-secret https://v3.fal.media/file?signature=secret " + "x" * 2000}}
    monkeypatch.setattr(module.requests, "post", lambda *a, **k: Rejection())
    result = module.VaceCaptionCandidate().execute(args)
    assert not result.success and result.data["http_status"] == 422
    assert result.data["provider_error_code"] == "policy_violation"
    assert len(result.data["provider_error_message"]) <= 500
    assert "test-secret" not in json.dumps(result.data)
    assert "https://" not in json.dumps(result.data)


@pytest.mark.parametrize("url", ["http://fal.media/x", "https://fal.media.evil.test/x",
    "https://evil.test/x", "https://user:secret@fal.media/x", "https://fal.media:443/x"])
def test_media_urls_reject_arbitrary_hosts_and_credentials(url):
    from tools.video.vace_caption_candidate import _media_url
    with pytest.raises(ValueError):
        _media_url(url)


def test_queue_url_requires_owned_request_id():
    from tools.video.vace_caption_candidate import _queue_url
    with pytest.raises(ValueError):
        _queue_url("https://queue.fal.run/fal-ai/wan-vace-14b/requests/other/status", "request-123", status=True)


def test_concurrent_callers_share_one_permanent_claim(provider_case):
    from concurrent.futures import ThreadPoolExecutor
    module, args, calls, tracker = provider_case
    second = tracker.estimate("vace_caption_candidate", module.OPERATION, 0.5)
    tracker.reserve(second)
    other = {**args, "reservation_id": second, "output_dir": str(Path(args["output_dir"]).with_name("concurrent"))}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(module.VaceCaptionCandidate().execute, [args, other]))
    assert sum(result.success for result in results) == 1
    assert len(calls["posts"]) == 1 and len(calls["uploads"]) == 2


def test_download_limits_and_no_auth_or_redirects(tmp_path, monkeypatch):
    from tools.video import vace_caption_candidate as module
    observed = []
    class Response:
        status_code = 200
        headers = {"Content-Length": str(module.MAX_CANDIDATE_BYTES + 1)}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_content(self, size):
            yield b"candidate"
    def get(url, **kwargs):
        observed.append(kwargs)
        return Response()
    monkeypatch.setattr(module.requests, "get", get)
    with pytest.raises(ValueError, match="100 MiB"):
        module.VaceCaptionCandidate._download("https://v3.fal.media/x", tmp_path / "large.mp4")
    assert not (tmp_path / "large.mp4").exists()
    assert "headers" not in observed[0]
    assert observed[0]["allow_redirects"] is False
    Response.headers = {}
    clock = iter([0, 121])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    with pytest.raises(ValueError, match="120 seconds"):
        module.VaceCaptionCandidate._download("https://v3.fal.media/x", tmp_path / "slow.mp4")


def test_interrupted_download_keeps_final_path_free_for_same_request_resume(tmp_path, monkeypatch):
    from tools.video import vace_caption_candidate as module
    class Response:
        status_code = 200
        headers = {}
        broken = True
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_content(self, size):
            yield b"first"
            if self.broken:
                raise module.requests.ConnectionError("interrupted")
            yield b"second"
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: Response())
    destination = tmp_path / "candidate.mp4"
    with pytest.raises(module.requests.ConnectionError):
        module.VaceCaptionCandidate._download("https://v3.fal.media/x", destination)
    assert not destination.exists()
    Response.broken = False
    module.VaceCaptionCandidate._download("https://v3.fal.media/x", destination)
    assert destination.read_bytes() == b"firstsecond"


def test_completed_download_has_no_media_auth_and_local_composite_stays_unapproved(provider_case, monkeypatch):
    from tools.video.masked_caption_composite import MaskedCaptionComposite
    from lib.masked_caption_media import verify_video
    module, args, calls, _ = provider_case
    tool = module.VaceCaptionCandidate()
    assert tool.execute(args).success
    prepared = json.loads(Path(args["contract_path"]).read_text())
    candidate_bytes = Path(prepared["input_video"]["path"]).read_bytes()
    class Response:
        status_code = 200
        headers = {"Content-Length": str(len(candidate_bytes))}
        def __init__(self, body):
            self.body = body
        def json(self):
            return self.body
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_content(self, size):
            for start in range(0, len(candidate_bytes), size):
                yield candidate_bytes[start:start + size]
    def get(url, **kwargs):
        calls["gets"].append((url, kwargs))
        if url.endswith("/status"):
            return Response({"status": "COMPLETED", "request_id": "request-123", "logs": None})
        if url.startswith("https://queue.fal.run/"):
            return Response({"video": {"url": "https://v3.fal.media/candidate.mp4", "content_type": "video/mp4", "file_name": "candidate.mp4", "file_size": len(candidate_bytes)}})
        assert "headers" not in kwargs and kwargs["allow_redirects"] is False
        return Response({})
    monkeypatch.setattr(module.requests, "get", get)
    result = tool.execute({**args, "action": "resume"})
    assert result.success and result.data["status"] == "completed"
    candidate = Path(result.data["candidate_path"])
    assert verify_video(candidate, 720, 1280, 30, 81) == 81
    composite_dir = Path(args["output_dir"]).with_name("composite")
    composite = MaskedCaptionComposite().execute({"action": "composite", "contract_path": args["contract_path"],
        "candidate_path": str(candidate), "output_dir": str(composite_dir)})
    assert composite.success, composite.error
    report = composite.data["report"]
    assert report["outside_mask_exact"] is True and report["frames_verified"] == 38
    assert report["alignment_status"] == "unverified" and report["visual_review_status"] == "pending"
    assert report["accepted_for_production"] is False
    assert report["endpoint"] == module.ENDPOINT and report["request_id"] == "request-123"
    assert report["generation_settings"]["seed"] == 20260926
    assert report["code_commit"] and report["timestamp"]
    assert verify_video(composite_dir / "master.mkv", 720, 1280, 30, 38) == 38
    assert len(list(composite_dir.glob("contact-sheet-*.png"))) == 4
    again = tool.execute({**args, "action": "resume"})
    assert again.success and len(calls["gets"]) == 3 and len(calls["posts"]) == 1


def test_resume_recovers_claim_written_before_attempt_state_without_accepting_foreign_owner(provider_case, monkeypatch):
    module, args, calls, _ = provider_case
    original_write = module._write_state
    state_path = Path(args["output_dir"]) / "attempt_state.json"
    class Crash(BaseException):
        pass
    def crash_after_claim(path, state):
        if path == state_path and state.get("status") == "submitted":
            raise Crash()
        original_write(path, state)
    monkeypatch.setattr(module, "_write_state", crash_after_claim)
    with pytest.raises(Crash):
        module.VaceCaptionCandidate().execute(args)
    assert len(calls["posts"]) == 1
    persisted = json.loads(state_path.read_text())
    assert "request_id" not in persisted
    monkeypatch.setattr(module, "_write_state", original_write)
    class Pending:
        status_code = 200
        def json(self):
            return {"status": "IN_PROGRESS", "request_id": "request-123", "logs": None}
    def get(url, **kwargs):
        calls["gets"].append(url)
        return Pending()
    monkeypatch.setattr(module.requests, "get", get)
    result = module.VaceCaptionCandidate().execute({**args, "action": "resume"})
    assert result.success and result.data["request_id"] == "request-123"
    assert len(calls["posts"]) == 1 and len(calls["gets"]) == 1
    assert json.loads(state_path.read_text())["response_url"].endswith("/requests/request-123")
    owned = json.loads(state_path.read_text())
    foreign = dict(owned)
    foreign["reservation_id"] = "foreign-owner"
    original_write(state_path, foreign)
    assert not module.VaceCaptionCandidate().execute({**args, "action": "resume"}).success
    assert len(calls["posts"]) == 1 and len(calls["gets"]) == 1
    original_write(state_path, {**owned, "request_id": "foreign-request"})
    assert not module.VaceCaptionCandidate().execute({**args, "action": "resume"}).success
    assert len(calls["posts"]) == 1 and len(calls["gets"]) == 1


def test_resume_recovers_published_candidate_before_completed_state_without_foreign_file_acceptance(provider_case, monkeypatch):
    module, args, calls, _ = provider_case
    tool = module.VaceCaptionCandidate()
    assert tool.execute(args).success
    contract = json.loads(Path(args["contract_path"]).read_text())
    candidate_bytes = Path(contract["input_video"]["path"]).read_bytes()
    class Response:
        status_code = 200
        headers = {"Content-Length": str(len(candidate_bytes))}
        def __init__(self, body):
            self.body = body
        def json(self):
            return self.body
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_content(self, size):
            for start in range(0, len(candidate_bytes), size):
                yield candidate_bytes[start:start + size]
    def get(url, **kwargs):
        calls["gets"].append(url)
        if url.endswith("/status"):
            return Response({"status": "COMPLETED", "request_id": "request-123", "logs": None})
        if url.startswith("https://queue.fal.run/"):
            return Response({"video": {"url": "https://v3.fal.media/candidate.mp4", "content_type": "video/mp4", "file_name": "candidate.mp4", "file_size": len(candidate_bytes)}})
        assert "headers" not in kwargs
        return Response({})
    monkeypatch.setattr(module.requests, "get", get)
    state_path = Path(args["output_dir"]) / "attempt_state.json"
    crashed_state = json.loads(state_path.read_text())
    original_write = module._write_state
    class Crash(BaseException):
        pass
    def crash_after_publication(path, state):
        if path == state_path and state.get("status") == "completed":
            raise Crash()
        original_write(path, state)
    monkeypatch.setattr(module, "_write_state", crash_after_publication)
    with pytest.raises(Crash):
        tool.execute({**args, "action": "resume"})
    candidate = Path(args["output_dir"]) / "candidate.mp4"
    assert candidate.read_bytes() == candidate_bytes
    assert json.loads(state_path.read_text())["status"] == "submitted"
    monkeypatch.setattr(module, "_write_state", original_write)
    recovered = tool.execute({**args, "action": "resume"})
    assert recovered.success and recovered.data["status"] == "completed"
    assert recovered.data["request_id"] == "request-123" and len(calls["posts"]) == 1
    candidate.write_bytes(b"foreign candidate")
    original_write(state_path, crashed_state)
    rejected = tool.execute({**args, "action": "resume"})
    assert not rejected.success
    assert candidate.read_bytes() == b"foreign candidate" and len(calls["posts"]) == 1
