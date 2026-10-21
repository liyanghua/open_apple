"""Transfer approved reference bytes through Ark Files, without TOS credentials.

File activation and download availability do not prove Seedance acceptance.
The journal prevents an uncertain multipart POST from being blindly repeated.
"""
from __future__ import annotations

import fcntl
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from backlot.project_commit import ProjectCommitStore
from lib.production_evidence import file_sha256, project_file
from tools.base_tool import (BaseTool, Determinism, ResourceProfile, ResumeSupport,
                             RetryPolicy, ToolResult, ToolRuntime, ToolStability, ToolStatus)


class ArkUploadValidationError(ValueError):
    """Static messages only: provider exceptions may contain temporary credentials."""


class ArkReferenceUpload(BaseTool):
    name = 'ark_reference_upload'
    version = '0.1.0'
    capability = 'media_upload'
    provider = 'volcengine_ark'
    runtime = ToolRuntime.API
    stability = ToolStability.BETA
    determinism = Determinism.STOCHASTIC
    dependencies = ['cmd:ffprobe']
    install_instructions = 'Configure ARK_API_KEY or DOUBAO_LITE_API_KEY locally'
    agent_skills = ['seedance-2-5']
    capabilities = ['upload', 'query']
    resource_profile = ResourceProfile(ram_mb=512, network_required=True)
    retry_policy = RetryPolicy(max_retries=0)
    resume_support = ResumeSupport.FROM_CHECKPOINT
    idempotency_key_fields = ['input_path', 'authorization_ref']
    side_effects = ['uploads approved video to Ark Files and persists a provider receipt']
    user_visible_verification = ['Inspect source SHA-256, upload journal and verified URL expiry']
    ENDPOINT = 'https://ark.cn-beijing.volces.com/api/v3/files'
    MAX_BYTES = 200 * 1024 * 1024
    input_schema = {'type': 'object', 'required': ['operation', 'project_dir', 'input_path', 'purpose', 'authorization_ref'],
                    'properties': {'operation': {'type': 'string', 'enum': ['upload', 'query']},
                                   'project_dir': {'type': 'string'}, 'input_path': {'type': 'string'},
                                   'purpose': {'type': 'string'}, 'authorization_ref': {'type': 'object'},
                                   'expires_seconds': {'type': 'integer', 'minimum': 86400, 'maximum': 2592000}}}

    @staticmethod
    def _credential() -> str:
        key = os.environ.get('ARK_API_KEY') or os.environ.get('DOUBAO_LITE_API_KEY')
        if not key or not key.strip():
            raise ArkUploadValidationError('Configure ARK_API_KEY or DOUBAO_LITE_API_KEY locally')
        return key.strip()

    def get_status(self) -> ToolStatus:
        try:
            self._credential()
            return ToolStatus.AVAILABLE if shutil.which('ffprobe') else ToolStatus.UNAVAILABLE
        except ArkUploadValidationError:
            return ToolStatus.UNAVAILABLE

    def _prepare(self, inputs: dict[str, Any]) -> dict:
        if inputs.get('operation') not in {'upload', 'query'}:
            raise ArkUploadValidationError('unsupported operation')
        root = Path(inputs['project_dir']).resolve(strict=True)
        media = project_file(root, inputs['input_path'])
        size = media.stat().st_size
        if media.suffix.lower() not in {'.mp4', '.mov'} or not 0 < size <= self.MAX_BYTES:
            raise ArkUploadValidationError('reference must be a nonempty MP4/MOV of at most 200 MiB')
        sha = file_sha256(media)
        ref = inputs.get('authorization_ref')
        if not isinstance(ref, dict):
            raise ArkUploadValidationError('hash-bound transfer authorization is required')
        auth_path = project_file(root, ref.get('path'))
        if file_sha256(auth_path) != ref.get('sha256'):
            raise ArkUploadValidationError('transfer authorization hash mismatch')
        auth = json.loads(auth_path.read_text(encoding='utf-8'))
        if not isinstance(auth, dict):
            raise ArkUploadValidationError('transfer authorization must be an object')
        actor = auth.get('approved_by')
        if auth.get('status') != 'approved' or not isinstance(actor, str) or not actor.startswith('user:') or len(actor) <= 5:
            raise ArkUploadValidationError('explicit human transfer approval is required')
        for field, value in (('media_sha256', sha), ('purposes', inputs.get('purpose')), ('recipients', self.provider)):
            values = auth.get(field)
            if not isinstance(values, list) or not value or value not in values:
                raise ArkUploadValidationError(f'transfer authorization does not cover {field}')
        expiry = inputs.get('expires_seconds', 90000)
        if type(expiry) is not int or not 86400 <= expiry <= 2592000:
            raise ArkUploadValidationError('expires_seconds must be between one and thirty days')
        probe = shutil.which('ffprobe')
        if not probe:
            raise ArkUploadValidationError('ffprobe is required')
        measured = subprocess.run([probe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(media)],
                                  capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(measured.stdout)
        duration = float(data['format']['duration'])
        stream = next(s for s in data['streams'] if s.get('codec_type') == 'video')
        if not math.isfinite(duration) or not 2 <= duration <= 30 or int(stream['width']) <= 0 or int(stream['height']) <= 0:
            raise ArkUploadValidationError('reference requires a valid video stream lasting two to thirty seconds')
        key = self._credential()
        fingerprint = hashlib.sha256(key.encode()).hexdigest()
        relative = f'artifacts/reference_uploads/ark/{sha}-{fingerprint}.json'
        journal = (root / relative).resolve()
        if root not in journal.parents or (root / 'artifacts').resolve() not in journal.parents:
            raise ArkUploadValidationError('receipt path escapes project artifacts')
        return {'root': root, 'media': media, 'sha': sha, 'size': size, 'duration': duration,
                'key': key, 'fingerprint': fingerprint, 'relative': relative, 'journal': journal, 'expiry': expiry,
                'scope': {'purpose': inputs['purpose'], 'recipient': self.provider,
                          'authorization_ref': dict(ref)}}

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, ArkUploadValidationError):
            return str(exc)
        status = getattr(exc, 'status_code', None)
        return f'Ark reference transfer failed ({type(exc).__name__}; status={status if type(status) is int else None})'

    def dry_run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            prepared = self._prepare(inputs)
            return {'valid': True, 'would_execute': False, 'network_accessed': False,
                    'media_sha256': prepared['sha'], 'receipt_path': prepared['relative']}
        except Exception as exc:
            return {'valid': False, 'would_execute': False, 'network_accessed': False, 'error': self._safe_error(exc)}

    @staticmethod
    def _save(prepared: dict, journal: dict) -> None:
        journal['updated_at'] = datetime.now(timezone.utc).isoformat()
        with ProjectCommitStore(prepared['root']).transaction(action={'action_id': f"ark-reference-{prepared['sha']}-{journal['status']}"}) as sink:
            sink.stage_json(prepared['relative'], journal, schema='production_evidence')

    @staticmethod
    def _url_expiry(url: str) -> datetime | None:
        query = parse_qs(urlsplit(url).query)
        lowered = {k.lower(): v for k, v in query.items()}
        if len(lowered) != len(query) or any(len(v) != 1 for v in lowered.values()):
            return None
        try:
            for prefix in ('x-tos', 'x-amz'):
                if all(f'{prefix}-{field}' in lowered for field in ('date', 'expires', 'signature')):
                    start = datetime.strptime(lowered[f'{prefix}-date'][0], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
                    seconds = int(lowered[f'{prefix}-expires'][0])
                    if not 0 < seconds <= 604800:
                        return None
                    return datetime.fromtimestamp(start.timestamp() + seconds, timezone.utc)
            if all(field in lowered for field in ('expires', 'signature', 'awsaccesskeyid')):
                return datetime.fromtimestamp(int(lowered['expires'][0]), timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
        return None

    def _verify_remote(self, url: str, prepared: dict) -> datetime | None:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.tos-cn-beijing\.volces\.com', host)):
            raise ArkUploadValidationError('reference download is not on a verified Ark storage host')
        expiry = self._url_expiry(url)
        if expiry is None:
            return None
        if expiry.timestamp() <= time.time() + 30:
            raise ArkUploadValidationError('reference download URL is expired or expires too soon')
        response = requests.get(url, stream=True, allow_redirects=False, timeout=(10, 30))
        try:
            if response.status_code != 200:
                raise ArkUploadValidationError('reference download did not succeed without redirects')
            digest, total = hashlib.sha256(), 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                total += len(chunk)
                if total > prepared['size']:
                    raise ArkUploadValidationError('reference download exceeds approved source size')
                digest.update(chunk)
            if total != prepared['size'] or digest.hexdigest() != prepared['sha']:
                raise ArkUploadValidationError('reference download bytes differ from approved source')
        finally:
            response.close()
        if expiry.timestamp() <= time.time() + 30:
            raise ArkUploadValidationError('reference download URL expired during verification')
        return expiry

    def _query(self, prepared: dict, journal: dict) -> ToolResult:
        file_id = journal['file_id']
        response = requests.get(f'{self.ENDPOINT}/{file_id}', headers={'Authorization': f"Bearer {prepared['key']}"},
                                allow_redirects=False, timeout=(10, 30))
        try:
            if response.status_code != 200:
                raise ArkUploadValidationError('Ark file query did not succeed')
            body = response.json()
        finally:
            response.close()
        if not isinstance(body, dict) or body.get('id') != file_id:
            raise ArkUploadValidationError('Ark file query identity mismatch')
        provider_status = body.get('status')
        if provider_status not in {'processing', 'active', 'failed'}:
            raise ArkUploadValidationError('Ark file query returned an unsupported state')
        journal['provider_status'] = provider_status
        journal['status'] = provider_status
        journal.pop('remote', None); journal.pop('availability', None)
        result = {'provider': self.provider, 'file_id': file_id, 'media_sha256': prepared['sha'],
                  'status': provider_status, 'receipt_path': prepared['relative'], 'settled_cost_cny': None}
        if provider_status == 'active':
            url = body.get('download_url')
            if not isinstance(url, str) or not url:
                result['status'] = journal['status'] = 'needs_readable_url'
            else:
                expiry = self._verify_remote(url, prepared)
                if expiry is None:
                    result['status'] = journal['status'] = 'expiry_unverified'
                else:
                    remote = {'url': url, 'expires_at': expiry.isoformat()}
                    availability = {**remote, 'available': True, 'media_sha256': prepared['sha'],
                                    'checked_at': datetime.now(timezone.utc).isoformat(),
                                    'method': 'signed_https_get_sha256', 'provider_acceptance': 'not_verified'}
                    journal.update(remote=remote, availability=availability, status='ready')
                    result.update(remote=remote, availability=availability, status='ready')
        self._save(prepared, journal)
        return ToolResult(success=provider_status != 'failed', cost_usd=None, data=result,
                          error='Ark reference file processing failed' if provider_status == 'failed' else None)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            prepared = self._prepare(inputs)
            prepared['journal'].parent.mkdir(parents=True, exist_ok=True)
            with prepared['journal'].with_suffix('.lock').open('a') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                if prepared['journal'].exists():
                    journal = json.loads(prepared['journal'].read_text(encoding='utf-8'))
                    if (journal.get('media_sha256') != prepared['sha']
                            or journal.get('account_fingerprint') != prepared['fingerprint']):
                        raise ArkUploadValidationError('stored upload identity differs from approved source or account')
                    if journal.get('scope') != prepared['scope']:
                        raise ArkUploadValidationError('stored upload scope differs from the current approved purpose or authorization')
                    if not journal.get('file_id'):
                        raise ArkUploadValidationError('previous upload outcome is unknown; automatic repeat POST is forbidden')
                else:
                    if inputs['operation'] == 'query':
                        raise ArkUploadValidationError('no recorded Ark upload is available to query')
                    with prepared['media'].open('rb') as source:
                        frozen = source.read(self.MAX_BYTES + 1)
                    if len(frozen) != prepared['size'] or hashlib.sha256(frozen).hexdigest() != prepared['sha']:
                        raise ArkUploadValidationError('reference media changed before upload snapshot')
                    journal = {'version': '1.0', 'provider': self.provider, 'media_sha256': prepared['sha'],
                               'size_bytes': prepared['size'], 'account_fingerprint': prepared['fingerprint'],
                               'account_fingerprint_source': 'api_key_sha256', 'status': 'uploading',
                               'scope': prepared['scope']}
                    self._save(prepared, journal)
                    try:
                        with io.BytesIO(frozen) as media:
                            response = requests.post(self.ENDPOINT,
                                headers={'Authorization': f"Bearer {prepared['key']}"},
                                files={'file': (prepared['media'].name, media, 'video/mp4' if prepared['media'].suffix.lower() == '.mp4' else 'video/quicktime')},
                                data={'purpose': 'user_data', 'expire_at': str(int(time.time()) + prepared['expiry'])},
                                allow_redirects=False, timeout=(10, 90))
                        try:
                            if response.status_code not in {200, 201}:
                                raise ArkUploadValidationError('Ark multipart upload did not succeed')
                            body = response.json()
                        finally:
                            response.close()
                        file_id = body.get('id') if isinstance(body, dict) else None
                        if not isinstance(file_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', file_id):
                            raise ArkUploadValidationError('Ark multipart upload returned no valid file identity')
                        journal.update(file_id=file_id, status='processing')
                        self._save(prepared, journal)
                    except Exception as exc:
                        journal.update(status='unknown', error=self._safe_error(exc))
                        self._save(prepared, journal)
                        raise
                file_id = journal.get('file_id')
                if not isinstance(file_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', file_id):
                    raise ArkUploadValidationError('stored Ark file identity is invalid')
                return self._query(prepared, journal)
        except Exception as exc:
            return ToolResult(success=False, cost_usd=None, error=self._safe_error(exc))
