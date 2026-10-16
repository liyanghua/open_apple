"""Host approved reference bytes in an existing Volcengine TOS bucket.

This tool does not create buckets, alter ACLs, claim generation provenance,
or submit a generation task. Signed URLs are sensitive, expiring receipts.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from lib.production_evidence import file_sha256, project_file
from tools.base_tool import (
    BaseTool, Determinism, ExecutionMode, ResourceProfile, RetryPolicy,
    ResumeSupport, ToolResult, ToolRuntime, ToolStability, ToolStatus, ToolTier,
)


class ReferenceUploadValidationError(ValueError):
    """Only static, locally authored messages may be exposed to the operator."""


class ReferenceVideoUpload(BaseTool):
    name = "reference_video_upload"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "media_upload"
    provider = "volcengine_tos"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API
    dependencies = ["python:tos", "cmd:ffprobe"]
    install_instructions = "pip install -r requirements-media-upload.txt; configure VOLC_ACCESSKEY and VOLC_SECRETKEY"
    agent_skills = ["seedance-2-5"]
    capabilities = ["list_buckets", "upload"]
    resource_profile = ResourceProfile(ram_mb=256, network_required=True)
    retry_policy = RetryPolicy(max_retries=0)
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["bucket", "region", "input_path", "authorization_ref"]
    side_effects = ["writes content-addressed video object in an existing approved TOS bucket"]
    user_visible_verification = ["Verify remote video SHA-256, expiry, source and transfer authorization"]
    MAX_BYTES = 200 * 1024 * 1024
    input_schema = {
        "type": "object", "required": ["operation", "region"],
        "properties": {
            "operation": {"type": "string", "enum": ["list_buckets", "upload"]},
            "region": {"type": "string"}, "bucket": {"type": "string"},
            "project_dir": {"type": "string"}, "input_path": {"type": "string"},
            "purpose": {"type": "string"}, "authorization_ref": {"type": "object"},
            "expires_seconds": {"type": "integer", "minimum": 300, "maximum": 86400},
        },
    }

    def get_status(self) -> ToolStatus:
        if (importlib.util.find_spec("tos") and shutil.which("ffprobe")
                and os.environ.get("VOLC_ACCESSKEY") and os.environ.get("VOLC_SECRETKEY")):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    @staticmethod
    def _region(inputs: dict) -> str:
        region = inputs.get("region")
        if not isinstance(region, str) or not re.fullmatch(r"[a-z]{2}-[a-z]+(?:-[a-z]+)?", region):
            raise ReferenceUploadValidationError("region must be a Volcengine region identifier")
        return region

    def _prepare(self, inputs: dict) -> dict:
        region = self._region(inputs)
        operation = inputs.get("operation")
        if operation == "list_buckets":
            return {"operation": operation, "region": region}
        if operation != "upload":
            raise ReferenceUploadValidationError("unsupported operation")
        bucket = inputs.get("bucket")
        if not isinstance(bucket, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
            raise ReferenceUploadValidationError("an existing bucket name is required")
        expiry = inputs.get("expires_seconds", 3600)
        if type(expiry) is not int or not 300 <= expiry <= 86400:
            raise ReferenceUploadValidationError("expires_seconds must be an integer between 300 and 86400")
        root = Path(inputs["project_dir"]).resolve(strict=True)
        media = project_file(root, inputs["input_path"])
        size = media.stat().st_size
        if media.suffix.lower() not in {".mp4", ".mov"} or not 0 < size <= self.MAX_BYTES:
            raise ReferenceUploadValidationError("reference must be a nonempty MP4/MOV of at most 200 MiB")
        sha = file_sha256(media)
        ref = inputs.get("authorization_ref")
        if not isinstance(ref, dict):
            raise ReferenceUploadValidationError("hash-bound transfer authorization is required")
        auth_path = project_file(root, ref["path"])
        if file_sha256(auth_path) != ref["sha256"]:
            raise ReferenceUploadValidationError("transfer authorization hash mismatch")
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        if not isinstance(auth, dict):
            raise ReferenceUploadValidationError("transfer authorization must be an object")
        actor = auth.get("approved_by")
        if auth.get("status") != "approved" or not isinstance(actor, str) or not actor.startswith("user:") or len(actor) <= 5:
            raise ReferenceUploadValidationError("explicit human transfer approval is required")
        for field, value in (("media_sha256", sha), ("recipients", "volcengine_tos"), ("purposes", inputs.get("purpose"))):
            values = auth.get(field)
            if not isinstance(values, list) or not value or value not in values:
                raise ReferenceUploadValidationError(f"transfer approval does not cover {field}")
        probe = shutil.which("ffprobe")
        if not probe:
            raise ReferenceUploadValidationError("ffprobe is required")
        measured = subprocess.run([probe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(media)],
                                  capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(measured.stdout)
        duration = float(data["format"]["duration"])
        stream = next(s for s in data["streams"] if s.get("codec_type") == "video")
        if not math.isfinite(duration) or not 2 <= duration <= 30 or int(stream["width"]) <= 0 or int(stream["height"]) <= 0:
            raise ReferenceUploadValidationError("reference must have a valid video stream lasting 2–30 seconds")
        return {"operation": operation, "region": region, "bucket": bucket, "media": media,
                "sha": sha, "size": size, "duration": duration, "expiry": expiry,
                "key": f"openmontage/reference-media/{sha}{media.suffix.lower()}"}

    def dry_run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            prepared = self._prepare(inputs)
            return {"valid": True, "would_execute": False, "network_accessed": False,
                    "operation": prepared["operation"], "media_sha256": prepared.get("sha")}
        except Exception as exc:
            return {"valid": False, "would_execute": False, "network_accessed": False,
                    "error": self._safe_error(exc)}

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        # SDK exceptions can embed credentials, authorization headers and URLs.
        if isinstance(exc, ReferenceUploadValidationError):
            return str(exc)
        status = getattr(exc, "status_code", None)
        code = getattr(exc, "code", None)
        safe_code = code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_]{1,80}", code) else None
        return f"reference upload rejected ({type(exc).__name__}; status={status if type(status) is int else None}; code={safe_code})"

    @staticmethod
    def _client(region: str):
        import tos
        ak, sk = os.environ.get("VOLC_ACCESSKEY"), os.environ.get("VOLC_SECRETKEY")
        if not ak or not sk:
            raise ReferenceUploadValidationError("Configure VOLC_ACCESSKEY and VOLC_SECRETKEY locally; credentials are currently missing")
        return tos.TosClientV2(ak, sk, endpoint=f"https://tos-{region}.volces.com", region=region,
                               max_retry_count=0, connection_time=10, socket_timeout=30,
                               enable_verify_ssl=True, enable_crc=True)

    @staticmethod
    def _matches(head, prepared: dict) -> bool:
        return (head.content_length == prepared["size"]
                and (getattr(head, "meta", None) or {}).get("sha256") == prepared["sha"])

    def _verify_remote(self, url: str, prepared: dict) -> None:
        parsed = urlsplit(url)
        expected_host = f"{prepared['bucket']}.tos-{prepared['region']}.volces.com"
        if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.username or parsed.password or parsed.port:
            raise ReferenceUploadValidationError("signed reference is not on the selected TOS endpoint")
        response = requests.get(url, stream=True, allow_redirects=False, timeout=(10, 30))
        try:
            if response.status_code != 200:
                raise ReferenceUploadValidationError("signed reference GET did not succeed")
            digest, total = hashlib.sha256(), 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                total += len(chunk)
                if total > prepared["size"]:
                    raise ReferenceUploadValidationError("remote reference exceeds source size")
                digest.update(chunk)
            if total != prepared["size"] or digest.hexdigest() != prepared["sha"]:
                raise ReferenceUploadValidationError("remote reference bytes differ from approved source")
        finally:
            response.close()

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            prepared = self._prepare(inputs)
            client = self._client(prepared["region"])
            if prepared["operation"] == "list_buckets":
                result = client.list_buckets()
                owner = str(result.owner.id)
                return ToolResult(success=True, cost_usd=None, data={
                    "buckets": [{"name": b.name, "region": b.location} for b in result.buckets],
                    "account_fingerprint": hashlib.sha256(owner.encode()).hexdigest(),
                    "settled_cost_cny": None})
            args = {"bucket": prepared["bucket"], "key": prepared["key"]}
            try:
                head = client.head_object(**args)
                reused = True
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
                # Rehash before transferring; never overwrite after an uncertain response.
                if file_sha256(prepared["media"]) != prepared["sha"]:
                    raise ReferenceUploadValidationError("local media changed after authorization check")
                client.put_object_from_file(**args, file_path=str(prepared["media"]),
                    content_type="video/mp4" if prepared["media"].suffix.lower() == ".mp4" else "video/quicktime",
                    content_sha256=prepared["sha"], meta={"sha256": prepared["sha"]}, forbid_overwrite=True)
                head = client.head_object(**args)
                reused = False
            if not self._matches(head, prepared):
                raise ReferenceUploadValidationError("remote object identity differs; overwrite is forbidden")
            import tos
            signed_at = datetime.now(timezone.utc)
            url = client.pre_signed_url(**args, http_method=tos.HttpMethodType.Http_Method_Get,
                                        expires=prepared["expiry"]).signed_url
            self._verify_remote(url, prepared)
            expires_at = (signed_at + timedelta(seconds=prepared["expiry"])).isoformat()
            return ToolResult(success=True, cost_usd=None, data={
                "provider": self.provider, "media_sha256": prepared["sha"], "size_bytes": prepared["size"],
                "bucket": prepared["bucket"], "region": prepared["region"], "object_key": prepared["key"],
                "reused": reused, "settled_cost_cny": None,
                "remote": {"url": url, "expires_at": expires_at},
                "availability": {"available": True, "url": url, "expires_at": expires_at,
                    "media_sha256": prepared["sha"], "checked_at": datetime.now(timezone.utc).isoformat(),
                    "method": "signed_https_get_sha256", "provider_acceptance": "not_verified"},
            })
        except Exception as exc:
            return ToolResult(success=False, cost_usd=None, error=self._safe_error(exc))
