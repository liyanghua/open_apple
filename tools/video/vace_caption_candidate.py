"""One approved fal VACE submission, with durable no-retry ownership."""

from __future__ import annotations

import json
import os
import re
import time
import importlib
import shutil
import socket
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from lib.cache_io import atomic_write_json
from lib.masked_caption_media import MAX_CANDIDATE_BYTES, validate_contract
from tools.base_tool import (BaseTool, DependencyError, Determinism, ExecutionMode, ResourceProfile,
                             ResumeSupport, RetryPolicy, ToolResult, ToolRuntime,
                             ToolStability, ToolTier)
from tools.cost_tracker import CostTracker
from tools.video.temporal_caption_repair import _file_path, _output_path, _source_hash

ENDPOINT = "fal-ai/wan-vace-14b/inpainting"
QUEUE = "https://queue.fal.run/" + ENDPOINT
OPERATION = "s01_wan_vace14b_once"
APPROVAL = "d030"
CLAIM_NAME = ".masked-caption-d030-s01-attempt.json"
PAYLOAD = {
    "match_input_num_frames": True, "num_frames": 81,
    "match_input_frames_per_second": True, "frames_per_second": 30,
    "resolution": "720p", "aspect_ratio": "9:16", "seed": 20260926,
    "num_inference_steps": 30, "guidance_scale": 5, "sampler": "unipc",
    "shift": 5, "acceleration": "none", "video_quality": "maximum",
    "enable_safety_checker": True, "enable_prompt_expansion": False,
    "preprocess": False, "num_interpolated_frames": 0,
    "temporal_downsample_factor": 0, "enable_auto_downsample": False,
    "prompt": "Reconstruct the background under the burned-in caption and its shadow only. Continue the original dark wood table edge, wood grain and warm background. Preserve visible mat geometry, color, motion and lighting. Do not restyle, add new objects or text.",
    "negative_prompt": "ghost text, residual caption, caption shadow, warped table edge, flicker, glass reinterpretation, new objects, restyling",
}


def _queue_url(value: str, request_id: str, *, status: bool) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid provider queue URL")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.hostname != "queue.fal.run" or parsed.port is not None
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not re.fullmatch(r"/fal-ai/wan-vace-14b/(?:inpainting/)?requests/" + re.escape(request_id)
                                + (r"/status" if status else ""), parsed.path)):
        raise ValueError("provider queue URL is outside approved endpoint")
    return value


def _media_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("invalid provider media URL")
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or not (host == "fal.media" or host.endswith(".fal.media"))
            or parsed.port is not None or parsed.username or parsed.password or parsed.fragment):
        raise ValueError("provider media URL is outside fal.media")
    return value


def _project_path(raw) -> Path:
    if not isinstance(raw, (str, os.PathLike)):
        raise ValueError("project_dir must be a directory")
    path = Path(raw).absolute()
    if not path.is_dir() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("project_dir must be a regular directory without symlink ancestors")
    return path


def _approval(project: Path, approval_ref: str) -> None:
    if approval_ref != APPROVAL:
        raise ValueError("approval_ref must be the approved d030 single trial")
    path = _file_path(project / "checkpoint_assets.json", "checkpoint_assets")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    artifact = checkpoint.get("artifacts", {}).get("decision_log", {})
    decisions = artifact.get("data", artifact).get("decisions", [])
    matching = [d for d in decisions if d.get("category") == "provider_selection"
                and d.get("subject") == "Caption reconstruction model"]
    decision = matching[-1] if matching else {}
    metadata = checkpoint.get("metadata", {}).get("caption_reconstruction", {})
    # The canonical checkpoint stores the trial record under this namespace.
    if not metadata:
        for value in checkpoint.get("metadata", {}).values():
            if isinstance(value, dict) and value.get("approval_ref") == APPROVAL:
                metadata = value
                break
    if (decision.get("decision_id") != APPROVAL
            or decision.get("selected") != "wan_vace14b_single_trial"
            or decision.get("user_approved") is not True
            or metadata.get("approval_ref") != APPROVAL
            or metadata.get("model_call_approved") is not True
            or metadata.get("proposed_endpoint") != ENDPOINT
            or metadata.get("proposed_trial_ceiling_usd") != 0.5
            or metadata.get("proposed_upload_scope") != "s01 silent padded frames and glyph mask only"):
        raise ValueError("canonical checkpoint does not approve this exact single trial")


def _write_state(path: Path, state: dict) -> None:
    atomic_write_json(path, state)
    path.chmod(0o600)


def _provider_error(response) -> dict:
    try:
        body = response.json()
    except (ValueError, requests.RequestException):
        body = {}
    if not isinstance(body, dict):
        body = {}
    detail = body.get("error") if isinstance(body.get("error"), dict) else body
    code = str(detail.get("code", "provider_unreported"))
    code = re.sub(r"[^A-Za-z0-9_-]", "", code)[:100]
    message = detail.get("message", body.get("detail", body.get("error", "provider returned HTTP error")))
    if not isinstance(message, str):
        message = json.dumps(message, ensure_ascii=False)
    for variable in ("FAL_KEY", "FAL_AI_API_KEY"):
        if os.environ.get(variable):
            message = message.replace(os.environ[variable], "[credential redacted]")
    message = re.sub(r"https?://[^\s\"']+", "[url redacted]", message)
    message = re.sub(r"(?i)(authorization|api[_ -]?key|token)\s*[:=]\s*[^\s,]+", r"\1=[redacted]", message)
    return {"http_status": response.status_code, "provider_error_code": code,
            "provider_error_message": message[:500]}


class VaceCaptionCandidate(BaseTool):
    name = "vace_caption_candidate"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "fal"
    stability = ToolStability.EXPERIMENTAL
    runtime = ToolRuntime.API
    execution_mode = ExecutionMode.ASYNC
    determinism = Determinism.SEEDED
    resume_support = ResumeSupport.FROM_CHECKPOINT
    retry_policy = RetryPolicy(max_retries=0)
    dependencies = ["python:requests", "python:fal_client", "env:FAL_KEY", "cmd:ffmpeg", "cmd:ffprobe", "python:numpy"]
    install_instructions = "Install requests and fal-client 1.0.3, configure FAL_KEY or FAL_AI_API_KEY, and install FFmpeg/NumPy."
    capabilities = ["approved_s01_masked_caption_candidate"]
    best_for = ["One d030-approved s01 Wan VACE14B candidate"]
    not_good_for = ["Automatic retries", "unapproved clips", "production acceptance", "general video generation"]
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, disk_mb=200, network_required=True)
    side_effects = ["Uploads only prepared pilot video/mask; permanently claims one project attempt; submits at most once"]
    user_visible_verification = ["Configuration does not prove provider semantics or visual quality; review the local composite"]
    input_schema = {"type": "object", "required": ["action", "contract_path", "output_dir", "project_dir", "reservation_id", "approval_ref"],
                    "properties": {"action": {"enum": ["submit", "resume"]},
                                   **{key: {"type": "string"} for key in ("contract_path", "output_dir", "project_dir", "reservation_id")},
                                   "approval_ref": {"const": APPROVAL}}}

    def get_info(self) -> dict:
        info = super().get_info()
        info["provider_semantics_verified"] = False
        info["visual_quality_verified"] = False
        info["endpoint"] = ENDPOINT
        return info

    def estimate_cost(self, inputs: dict) -> float:
        return 0.405

    @staticmethod
    def _key() -> str:
        key = os.environ.get("FAL_KEY") or os.environ.get("FAL_AI_API_KEY")
        if not key:
            raise DependencyError("FAL_KEY or FAL_AI_API_KEY must be configured")
        return key

    def check_dependencies(self) -> None:
        self._key()
        for dependency in self.dependencies:
            if dependency.startswith("python:"):
                try:
                    importlib.import_module(dependency[7:])
                except ImportError as exc:
                    raise DependencyError("Missing " + dependency) from exc
            elif dependency.startswith("cmd:") and shutil.which(dependency[4:]) is None:
                raise DependencyError("Missing " + dependency)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.monotonic()
        state_path = None
        state = None
        try:
            if not isinstance(inputs, dict) or inputs.get("action") not in {"submit", "resume"}:
                raise ValueError("action must be submit or resume")
            project = _project_path(inputs.get("project_dir"))
            _approval(project, inputs.get("approval_ref"))
            contract_path = _file_path(inputs.get("contract_path"), "contract_path")
            contract = validate_contract(contract_path)
            claim_path = project / CLAIM_NAME
            if inputs["action"] == "resume":
                return self._resume(inputs, project, contract_path, claim_path, started)
            self.check_dependencies()
            tracker = CostTracker(cost_log_path=project / "cost_log.json")
            reservation = inputs.get("reservation_id")
            tracker.assert_reserved(reservation, self.name, OPERATION, 0.5)
            output = _output_path(inputs.get("output_dir"), Path(contract["source"]["path"]), Path(contract["mask"]["path"]))
            claim = {"approval_ref": APPROVAL, "operation": OPERATION, "endpoint": ENDPOINT,
                     "reservation_id": reservation, "output_dir": str(output),
                     "contract_path": str(contract_path), "contract_sha256": _source_hash(contract_path)}
            # O_EXCL makes different output directories and different reservations
            # compete for the same permanent project-level authorization.
            descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(claim, handle)
                handle.flush()
                os.fsync(handle.fileno())
            output.mkdir(exist_ok=False)
            state_path = output / "attempt_state.json"
            state = {**claim, "status": "preparing_upload", "billing_status": "unknown", "generation_settings": PAYLOAD}
            _write_state(state_path, state)
            from fal_client import StorageSettings, SyncClient
            client = SyncClient(key=self._key(), default_timeout=120)
            lifecycle = StorageSettings(expires_in=86400)
            video_url = client.upload_file(contract["input_video"]["path"], lifecycle=lifecycle)
            mask_url = client.upload_file(contract["mask_video"]["path"], lifecycle=lifecycle)
            # Only the SDK upload response supplies payload URLs. Never log them.
            _media_url(video_url)
            _media_url(mask_url)
            tracker.bind_submission(reservation, tool=self.name, attempt_id=APPROVAL + ":s01:" + ENDPOINT,
                                    idempotency_key=APPROVAL + ":s01:" + ENDPOINT,
                                    operation=OPERATION, minimum_usd=0.5)
            state["status"] = "submission_intent"
            _write_state(state_path, state)
            payload = {**PAYLOAD, "video_url": video_url, "mask_video_url": mask_url}
            state["status"] = "submission_unknown"
            _write_state(state_path, state)
            response = requests.post(QUEUE, json=payload, headers=self._headers(),
                                     timeout=(10, 120), allow_redirects=False)
            if response.status_code not in {200, 201, 202}:
                state["status"] = "submission_rejected"
                state.update(_provider_error(response))
                _write_state(state_path, state)
                return self._result(state, started, success=False, error="provider rejected the one submission")
            body = response.json()
            request_id = body.get("request_id")
            if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
                raise ValueError("provider returned invalid request ID")
            status_url = _queue_url(body.get("status_url"), request_id, status=True)
            response_url = _queue_url(body.get("response_url"), request_id, status=False)
            claim.update(request_id=request_id, status_url=status_url, response_url=response_url)
            _write_state(claim_path, claim)
            state.update(claim, status="submitted")
            _write_state(state_path, state)
            tracker.bind_submission(reservation, tool=self.name, attempt_id=claim["approval_ref"] + ":s01:" + ENDPOINT,
                                    idempotency_key=APPROVAL + ":s01:" + ENDPOINT, task_id=request_id,
                                    operation=OPERATION, minimum_usd=0.5)
            return self._result(state, started)
        except Exception as exc:
            if state_path is not None and state is not None:
                if state["status"] not in {"submission_unknown", "submitted", "submission_rejected"}:
                    state["status"] = "pre_submit_failed"
                state["error_type"] = type(exc).__name__
                _write_state(state_path, state)
            # External exceptions may contain signed URLs or authorization.
            return ToolResult(success=False, error=f"trial operation blocked or failed ({type(exc).__name__})",
                              data={"status": state["status"] if state else "blocked"}, cost_usd=None,
                              duration_seconds=round(time.monotonic() - started, 3))

    @staticmethod
    def _headers() -> dict:
        return {"Authorization": "Key " + VaceCaptionCandidate._key(), "Content-Type": "application/json",
                "X-Fal-Store-IO": "0",
                "X-Fal-Object-Lifecycle-Preference": json.dumps({"expiration_duration_seconds": 86400})}

    def _resume(self, inputs, project, contract_path, claim_path, started):
        self.check_dependencies()
        claim = json.loads(_file_path(claim_path, "attempt claim").read_text())
        output = Path(inputs.get("output_dir", "")).absolute()
        if (str(output) != claim.get("output_dir") or str(contract_path) != claim.get("contract_path")
                or _source_hash(contract_path) != claim.get("contract_sha256")
                or inputs.get("reservation_id") != claim.get("reservation_id")
                or claim.get("approval_ref") != APPROVAL or claim.get("endpoint") != ENDPOINT):
            raise ValueError("resume must reference the owned attempt and original contract")
        if any(p.is_symlink() for p in (output, *output.parents)):
            raise ValueError("attempt output must not have symlink ancestors")
        state_path = _file_path(output / "attempt_state.json", "attempt state")
        state = json.loads(state_path.read_text())
        if any(state.get(key) != claim.get(key) for key in claim):
            raise ValueError("attempt state ownership differs from permanent claim")
        if state.get("status") == "completed":
            candidate = _file_path(output / "candidate.mp4", "candidate")
            if _source_hash(candidate) != state.get("candidate_sha256"):
                raise ValueError("downloaded candidate hash changed")
            return self._result(state, started)
        request_id = state.get("request_id")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
            return self._result(state, started, success=False, error="attempt has no recoverable request ID; resubmission forbidden")
        status_url = _queue_url(state.get("status_url"), request_id, status=True)
        response = requests.get(status_url, headers=self._headers(), timeout=(10, 120), allow_redirects=False)
        if response.status_code != 200:
            state.update(_provider_error(response))
            _write_state(state_path, state)
            return self._result(state, started, success=False, error="status query failed; request retained")
        body = response.json()
        provider_status = body.get("status")
        if provider_status in {"IN_QUEUE", "IN_PROGRESS"}:
            state.update(status="pending", provider_status=provider_status)
            _write_state(state_path, state)
            return self._result(state, started)
        if provider_status != "COMPLETED":
            state.update(status="provider_failed", provider_status=str(provider_status)[:64])
            _write_state(state_path, state)
            return self._result(state, started, success=False, error="provider failed or rejected this candidate")
        result = requests.get(_queue_url(state.get("response_url"), request_id, status=False), headers=self._headers(),
                              timeout=(10, 120), allow_redirects=False)
        if result.status_code != 200:
            state.update(_provider_error(result))
            _write_state(state_path, state)
            return self._result(state, started, success=False, error="result query failed; request retained")
        media = result.json().get("video", {})
        url = _media_url(media.get("url"))
        candidate = output / "candidate.mp4"
        self._download(url, candidate)
        state.update(status="completed", candidate_path=str(candidate), candidate_sha256=_source_hash(candidate),
                     model_version="provider_unreported", accepted_for_production=False)
        _write_state(state_path, state)
        return self._result(state, started)

    @staticmethod
    def _download(url: str, destination: Path):
        _media_url(url)
        started = time.monotonic()
        if destination.exists() or destination.is_symlink():
            raise ValueError("candidate destination already exists")
        holder = []
        timed_out = threading.Event()

        def expire():
            timed_out.set()
            if holder:
                response = holder[0]
                connection = getattr(getattr(response, "raw", None), "_connection", None)
                sock = getattr(connection, "sock", None)
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                try:
                    response.close()
                except AttributeError:
                    pass

        watchdog = threading.Timer(120, expire)
        watchdog.daemon = True
        watchdog.start()
        try:
            with requests.get(url, stream=True, timeout=(10, 110), allow_redirects=False) as response:
                holder.append(response)
                if response.status_code != 200:
                    raise ValueError("candidate download failed")
                declared = response.headers.get("Content-Length")
                if declared is not None and (int(declared) < 0 or int(declared) > MAX_CANDIDATE_BYTES):
                    raise ValueError("candidate download exceeds 100 MiB")
                if timed_out.is_set() or time.monotonic() - started > 120:
                    raise ValueError("candidate download exceeds 120 seconds")
                descriptor, temporary_name = tempfile.mkstemp(prefix=".candidate-download-", suffix=".part", dir=destination.parent)
                temporary = Path(temporary_name)
                size = 0
                with os.fdopen(descriptor, "wb") as handle:
                    for part in response.iter_content(65536):
                        if timed_out.is_set() or time.monotonic() - started > 120:
                            raise ValueError("candidate download exceeds 120 seconds")
                        size += len(part)
                        if size > MAX_CANDIDATE_BYTES:
                            raise ValueError("candidate download exceeds 100 MiB")
                        handle.write(part)
                    handle.flush()
                    os.fsync(handle.fileno())
                if size == 0 or (declared is not None and size != int(declared)):
                    raise ValueError("candidate download is empty or truncated")
                if timed_out.is_set() or time.monotonic() - started > 120:
                    raise ValueError("candidate download exceeds 120 seconds")
                # Atomic publication without replacing another caller's file.
                os.link(temporary, destination)
                temporary.unlink()
        finally:
            watchdog.cancel()

    @staticmethod
    def _result(state, started, *, success=True, error=None):
        data = {key: state[key] for key in ("status", "request_id", "candidate_path", "candidate_sha256", "provider_status",
                                         "http_status", "provider_error_code", "provider_error_message") if key in state}
        data.update(accepted_for_production=False, billing_status="unknown")
        return ToolResult(success=success, data=data, error=error, cost_usd=None,
                          duration_seconds=round(time.monotonic() - started, 3), model=ENDPOINT, seed=20260926)
