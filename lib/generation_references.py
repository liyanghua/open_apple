"""Local, read-only provenance checks; never upload, fetch, or grant permission.

Declarations bind transmitted media to saved bytes, receipt and authorization.
The provider's acceptance of those media is a separate, unverified question.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from lib.production_evidence import file_sha256, project_file


def _timestamp(value: Any) -> datetime:
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp requires timezone')
    return result.astimezone(timezone.utc)


def _bound(root: Path, ref: Mapping[str, Any], *, json_object: bool = False):
    if not isinstance(ref, Mapping):
        raise ValueError('evidence reference must be an object')
    path = project_file(root, ref['path'])
    if file_sha256(path) != ref['sha256']:
        raise ValueError('file hash differs from bound evidence')
    if not json_object:
        return path
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('evidence must be a JSON object')
    return data


def _local_duration(path: Path) -> float:
    probe = shutil.which('ffprobe')
    if not probe:
        raise ValueError('ffprobe is required to verify video duration')
    result = subprocess.run([probe, '-v', 'error', '-show_entries', 'format=duration',
                             '-of', 'json', str(path)], capture_output=True,
                            text=True, check=True, timeout=30)
    duration = float(json.loads(result.stdout)['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('video duration is not finite and positive')
    return duration


def _contains_generation_identity(value: Any) -> bool:
    if isinstance(value, Mapping):
        keys = {'task_id', 'generation_task_id', 'model', 'model_variant',
                'account_fingerprint', 'generation_receipt_ref'}
        return bool(keys.intersection(value)) or any(
            _contains_generation_identity(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_generation_identity(item) for item in value)
    return False


def _owned_clip_interval(root: Path, media: Mapping[str, Any], provenance: Mapping[str, Any],
                         original_path: Path, measured: float) -> None:
    parent = media['parent_media_ref']
    if (_bound(root, parent) != original_path
            or parent['sha256'] != provenance['source_original_ref']['sha256']):
        raise ValueError('derived parent differs from the owned original')
    interval = provenance['source_interval_seconds']
    if not isinstance(interval, list) or len(interval) != 2:
        raise ValueError('derived clip requires a two-value source interval')
    if any(isinstance(value, bool) for value in interval):
        raise ValueError('source interval seconds cannot be boolean')
    try:
        start, end = map(float, interval)
    except OverflowError as exc:
        raise ValueError('source interval seconds exceed finite numeric range') from exc
    original_duration = _local_duration(original_path)
    if not (math.isfinite(start) and math.isfinite(end)
            and 0 <= start < end <= original_duration):
        raise ValueError('source interval is outside the measured original')
    if abs(end - start - measured) > .001:
        raise ValueError('owned clip duration differs from its unretimed source interval')
    transform = provenance.get('transform_description')
    if not isinstance(transform, str) or not transform.strip():
        raise ValueError('derived clip requires a transform description')


def _owned_live_action(root: Path, media: Mapping[str, Any], source_path: Path | None,
                       measured: float | None) -> dict[str, Any]:
    provenance = _bound(root, media['source_provenance_ref'], json_object=True)
    if media.get('generation_receipt_ref') or _contains_generation_identity(provenance):
        raise ValueError('owned live action cannot inherit generated-media identifiers')
    owner = provenance.get('owner_id')
    if (provenance.get('kind') != 'owned_live_action'
            or not isinstance(owner, str) or not owner.startswith('user:')
            or not owner.removeprefix('user:').strip()
            or provenance.get('media_sha256') != media['source']['sha256']):
        raise ValueError('owned provenance does not bind current bytes and user owner')
    original_ref = provenance['source_original_ref']
    original_path = _bound(root, original_ref)
    approval = _bound(root, provenance['ownership_authorization_ref'], json_object=True)
    owned_hashes = approval.get('owned_source_sha256')
    if (approval.get('status') != 'approved' or approval.get('owner_id') != owner
            or approval.get('approved_by') != owner
            or not isinstance(owned_hashes, list) or original_ref['sha256'] not in owned_hashes):
        raise ValueError('separate user ownership approval does not bind the original')
    if source_path is None or measured is None:
        raise ValueError('owned media bytes and duration must be verified')
    if media.get('origin') == 'derived':
        _owned_clip_interval(root, media, provenance, original_path, measured)
    elif original_path != source_path or original_ref['sha256'] != media['source']['sha256']:
        raise ValueError('unmodified owned media must be its bound original')
    return {'owner_id': owner, 'owned_source_sha256': original_ref['sha256']}


def _input_media(inputs: Mapping[str, Any]) -> list[tuple[str, str]]:
    result = []
    for kind in ('image', 'video', 'audio'):
        names = [f'reference_{kind}_{suffix}' for suffix in ('url', 'path', 'urls', 'paths')]
        if kind == 'image':
            names += ['image_url', 'image_path', 'end_image_url', 'end_image_path',
                      'last_frame_url', 'last_frame_path']
        for name in names:
            value = inputs.get(name)
            values = value if isinstance(value, list) else ([value] if value else [])
            result.extend((kind, str(item)) for item in values)
    return result


def preflight_generation_references(
    root: Path, inputs: Mapping[str, Any], *, reference_media: list[dict] | None = None,
    authorizations: list[dict] | None = None, recipient: str = 'volcengine_ark',
    purpose: str | None = None, now: datetime | None = None,
    remote_availability: bool = False, tool: str | None = None, provider: str | None = None,
) -> dict[str, Any]:
    """Collect issues without mutating evidence or accessing any remote URL.

    Legacy image-only inputs without declarations remain compatible. A declared
    source plan enables strict binding of every input. Videos always require
    declarations. ``remote_availability`` requires saved availability evidence,
    never a HEAD/GET request and never proof of provider-side eligibility.
    """
    root = Path(root).resolve()
    now = now or datetime.now(timezone.utc)
    issues, verified = [], []

    def issue(code: str, message: str, reference_id: str | None = None):
        issues.append(dict(code=code, message=message, reference_id=reference_id))

    actual = _input_media(inputs)
    declared = reference_media if reference_media is not None else inputs.get('reference_media')
    plan = inputs.get('shot_source_plan')
    if plan is not None:
        try:
            from lib.shot_source_contracts import validate_source_plan
            validate_source_plan(root, plan)
            for key in ('shot_id', 'parent_budget_id', 'lineage_id', 'project_id'):
                if key in plan and plan[key] != inputs.get(key):
                    raise ValueError(f'{key} differs from the actual generation request')
            if inputs.get('revision_id') and plan['revision'] != inputs['revision_id']:
                raise ValueError('revision differs from the actual generation request')
            lock_ref = plan['dependencies']['production_lock']
            if inputs.get('production_lock_ref') != lock_ref:
                raise ValueError('production_lock_ref differs from the source plan')
            lock = _bound(root, lock_ref, json_object=True)
            if lock.get('project_id') != plan['project_id']:
                raise ValueError('production lock project differs from the source plan')
            for name, actual_name in (('shot_id', 'shot_id'), ('parent_budget_id', 'parent_budget_id'),
                ('lineage_id', 'lineage_id'), ('model', 'model'), ('model_variant', 'model_variant'),
                ('operation', 'operation'), ('source_duration_seconds', 'duration'),
                ('source_resolution', 'resolution'), ('source_ratio', 'aspect_ratio'),
                ('generate_audio', 'generate_audio')):
                if name in lock and lock[name] != inputs.get(actual_name):
                    raise ValueError(f'production lock {name} differs from the actual request')
            if ((tool is not None and lock.get('tool', tool) != tool)
                    or (provider is not None and lock.get('provider', provider) != provider)):
                raise ValueError('production lock tool/provider differs from the actual request')
            if declared is not None and declared != plan['references']:
                raise ValueError('reference_media differs from the source plan references')
        except (KeyError, ValueError, TypeError, OSError) as exc:
            issue('source_plan_binding_invalid', f'Cannot bind source plan: {exc}')
    if declared is None and isinstance(plan, Mapping):
        declared = plan.get('reference_media', plan.get('references', []))
    strict = declared is not None or plan is not None or any(kind == 'video' for kind, _ in actual)
    if strict and not declared and actual:
        issue('reference_declarations_missing', 'Every reference input requires a bound declaration')
    if declared is not None and not isinstance(declared, list):
        issue('reference_declarations_invalid', 'reference_media must be a list')
        declared = []
    bound_inputs: set[tuple[str, str]] = set()
    ids = set()
    for media in declared or []:
        if not isinstance(media, Mapping):
            issue('reference_declarations_invalid', 'Reference declaration must be an object')
            continue
        rid = str(media.get('reference_id') or '')
        if not rid or rid in ids:
            issue('reference_identity_invalid', 'Reference IDs must be present and unique', rid)
        ids.add(rid)
        kind = media.get('media_type')
        if not isinstance(kind, str) or kind not in {'image', 'video', 'audio'}:
            issue('media_type_invalid', 'Reference media_type must be image, video or audio', rid)
            kind = 'unknown'
        roles = media.get('roles')
        if not isinstance(roles, list) or not roles or not all(isinstance(role, str) and role for role in roles) or not media.get('scope'):
            issue('roles_missing', 'Reference needs roles and their observable scope', rid)
        intended = media.get('purpose') or purpose
        if not intended:
            issue('purpose_missing', 'Reference purpose is required', rid)
        source = media.get('source') or {}
        if not isinstance(source, Mapping):
            source = {}
        sha = source.get('sha256')
        source_path = None
        try:
            source_path = _bound(root, source)
            bound_inputs.add((kind, str(source_path)))
            bound_inputs.add((kind, str(source['path'])))
        except (KeyError, ValueError, TypeError, OSError) as exc:
            issue('source_hash_mismatch', f'Cannot bind original bytes: {exc}', rid)
        if media.get('origin') == 'derived':
            try:
                _bound(root, media['parent_media_ref'])
            except (KeyError, ValueError, TypeError, OSError) as exc:
                issue('parent_media_missing', f'Derived reference needs bound parent media: {exc}', rid)
        remote = media.get('remote') or {}
        if not isinstance(remote, Mapping):
            issue('remote_reference_invalid', 'remote reference must be an object', rid)
            remote = {}
        url = remote.get('url')
        if url:
            bound_inputs.add((kind, str(url)))
            try:
                if _timestamp(remote['expires_at']) <= now:
                    issue('remote_expired', 'Reference URL has expired', rid)
            except (KeyError, ValueError, TypeError):
                issue('remote_expiry_missing', 'Reference URL needs a timezone-aware expiry', rid)
            if remote_availability or kind == 'video' or remote.get('availability_evidence_ref'):
                try:
                    evidence = _bound(root, remote['availability_evidence_ref'], json_object=True)
                    if (evidence.get('url') != url or evidence.get('media_sha256') != sha
                            or evidence.get('available') is not True
                            or _timestamp(evidence['checked_at']) > now
                            or _timestamp(evidence['expires_at']) <= now):
                        raise ValueError('saved availability does not bind URL, bytes or current validity')
                except (KeyError, ValueError, TypeError, OSError) as exc:
                    issue('remote_availability_missing', f'Cannot establish saved remote availability: {exc}', rid)
        authorized = False
        approval_refs = media.get('authorization_refs') or []
        if not isinstance(approval_refs, list):
            issue('authorization_invalid', 'authorization_refs must be a list', rid)
            approval_refs = []
        for approval_ref in [*(authorizations or []), *approval_refs]:
            try:
                approval = _bound(root, approval_ref, json_object=True)
                authorized |= (approval.get('status') == 'approved' and bool(approval.get('approved_by'))
                    and sha in (approval.get('media_sha256') or [])
                    and intended in (approval.get('purposes') or [])
                    and recipient in (approval.get('recipients') or []))
            except (KeyError, ValueError, TypeError, OSError):
                continue
        if not authorized:
            issue('authorization_missing', 'No saved authorization binds these bytes, purpose and recipient', rid)
        row = dict(reference_id=rid, media_type=kind, source_sha256=sha, roles=roles,
                   authorization_status='approved' if authorized else 'missing')
        if kind == 'video':
            if not url:
                issue('remote_reference_missing', 'Video reference requires bound remote URL', rid)
            provenance_kind = media.get('provenance_kind', 'generated')
            row['provenance_kind'] = provenance_kind
            if not isinstance(provenance_kind, str) or provenance_kind not in {'generated', 'owned_live_action'}:
                issue('provenance_kind_invalid', 'Unknown video provenance kind', rid)
            elif provenance_kind == 'generated':
                try:
                    receipt = _bound(root, media['generation_receipt_ref'], json_object=True)
                    if receipt.get('success') is False:
                        raise ValueError('generation receipt reports failure')
                    receipt = receipt.get('data', receipt)
                    if not isinstance(receipt, Mapping):
                        raise ValueError('generation receipt data is not an object')
                    if (receipt.get('media_sha256') != sha or not receipt.get('task_id')
                            or not receipt.get('provider') or not receipt.get('model')
                            or not re.fullmatch('[a-f0-9]{64}', str(receipt.get('account_fingerprint') or ''))):
                        raise ValueError('receipt does not bind original bytes, task, model and account fingerprint')
                    row['generation_task_id'] = receipt['task_id']
                except (KeyError, ValueError, TypeError, OSError) as exc:
                    issue('receipt_source_mismatch', f'Cannot bind generation receipt: {exc}', rid)
            if source_path:
                try:
                    measured = _local_duration(source_path)
                    row['measured_duration_seconds'] = measured
                    supplied = float(media['duration_seconds'])
                    if not math.isfinite(supplied) or abs(measured - supplied) > .001:
                        issue('duration_mismatch', 'Declared duration differs from original video bytes', rid)
                    urls = list(inputs.get('reference_video_urls') or [])
                    if inputs.get('reference_video_url'):
                        urls.append(inputs['reference_video_url'])
                    durations = inputs.get('reference_video_durations') or []
                    for index, actual_url in enumerate(urls):
                        if actual_url == url and (index >= len(durations) or abs(float(durations[index]) - measured) > .001):
                            issue('duration_mismatch', 'Tool duration does not bind measured reference duration', rid)
                except (KeyError, ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
                    issue('duration_unverified', f'Cannot measure original video duration: {exc}', rid)
            if provenance_kind == 'owned_live_action':
                try:
                    row.update(_owned_live_action(root, media, source_path,
                        row.get('measured_duration_seconds')))
                except (KeyError, ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
                    issue('owned_provenance_invalid', f'Cannot bind owned live action: {exc}', rid)
        verified.append(row)
    if strict:
        for kind, location in actual:
            normalized = str(Path(location).resolve()) if not location.startswith(('http:', 'https:', 'data:', 'asset:')) else location
            if (kind, location) not in bound_inputs and (kind, normalized) not in bound_inputs:
                issue('unbound_input', f'Unbound {kind} input')
        if not actual and declared:
            issue('unused_references', 'Declared references are absent from generation inputs')
    return dict(valid=not issues, issues=issues, references=verified,
                provider_qualification='not_verified', network_accessed=False)
