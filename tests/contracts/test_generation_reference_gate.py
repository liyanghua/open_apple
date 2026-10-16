"""Offline provenance and authorization checks bind every transmitted input."""
import hashlib
import json
from datetime import datetime, timezone

import pytest


def ref(path):
    return {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def reference_case(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: SimpleNamespace(returncode=0,
                        stdout=json.dumps({'format': {'duration': '4.125'}}), stderr=''))
    monkeypatch.setattr('shutil.which', lambda _: '/fake/ffprobe')
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'original-generation-bytes')
    source_ref = ref(source)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'task_id': 'task-original', 'provider': 'volcengine_ark',
        'model': 'seedance-2.5', 'account_fingerprint': 'a' * 64,
        'media_sha256': source_ref['sha256']}))
    approval = tmp_path / 'approval.json'
    approval.write_text(json.dumps({'status': 'approved', 'approved_by': 'user',
        'media_sha256': [source_ref['sha256']], 'purposes': ['product-motion'],
        'recipients': ['volcengine_ark']}))
    availability = tmp_path / 'available.json'
    availability.write_text(json.dumps({'url': 'https://example.test/original.mp4',
        'media_sha256': source_ref['sha256'], 'available': True,
        'checked_at': '2026-10-16T01:00:00Z', 'expires_at': '2026-10-17T01:00:00Z'}))
    media = {'reference_id': 'motion', 'media_type': 'video', 'roles': ['motion'],
        'scope': 'hand path only', 'purpose': 'product-motion', 'source': source_ref,
        'generation_receipt_ref': ref(receipt), 'duration_seconds': 4.125,
        'remote': {'url': 'https://example.test/original.mp4',
                   'expires_at': '2026-10-17T01:00:00Z', 'availability_evidence_ref': ref(availability)},
        'authorization_refs': [ref(approval)]}
    inputs = {'reference_video_urls': [media['remote']['url']],
              'reference_video_durations': [4.125], 'reference_media': [media]}
    return tmp_path, inputs


def check(root, inputs, **kwargs):
    from lib import generation_references
    return generation_references.preflight_generation_references(root, inputs,
        now=datetime(2026, 10, 16, 2, tzinfo=timezone.utc), **kwargs)


def test_reference_preflight_is_offline_and_does_not_certify_provider(reference_case, monkeypatch):
    root, inputs = reference_case
    monkeypatch.setattr('requests.get', lambda *a, **kw: pytest.fail('network forbidden'))
    result = check(root, inputs, remote_availability=True)
    assert result['valid'] and result['issues'] == []
    assert result['network_accessed'] is False
    assert result['provider_qualification'] == 'not_verified'
    assert result['references'][0]['measured_duration_seconds'] == 4.125


@pytest.mark.parametrize('mutation,code', [
    ('expired', 'remote_expired'), ('changed', 'source_hash_mismatch'),
    ('unauthorized', 'authorization_missing'), ('receipt', 'receipt_source_mismatch'),
    ('duration', 'duration_mismatch'), ('missing', 'unbound_input'),
    ('roles', 'roles_missing'), ('evidence', 'remote_availability_missing')])
def test_reference_preflight_collects_binding_failures(reference_case, mutation, code):
    root, inputs = reference_case
    media = inputs['reference_media'][0]
    if mutation == 'expired':
        media['remote']['expires_at'] = '2026-10-15T00:00:00Z'
    elif mutation == 'changed':
        (root / 'source.mp4').write_bytes(b'changed')
    elif mutation == 'unauthorized':
        media['authorization_refs'] = []
    elif mutation == 'receipt':
        receipt = root / 'receipt.json'
        doc = json.loads(receipt.read_text())
        doc['media_sha256'] = '0' * 64
        receipt.write_text(json.dumps(doc))
        media['generation_receipt_ref'] = ref(receipt)
    elif mutation == 'duration':
        media['duration_seconds'] = 5
    elif mutation == 'missing':
        inputs['reference_video_urls'].append('https://example.test/extra.mp4')
    elif mutation == 'roles':
        media['roles'] = []
    elif mutation == 'evidence':
        media['remote'].pop('availability_evidence_ref')
    result = check(root, inputs, remote_availability=True)
    assert not result['valid']
    assert code in {issue['code'] for issue in result['issues']}


def test_old_images_without_declarations_are_compatible_but_videos_require_authorization(tmp_path):
    assert check(tmp_path, {'reference_image_paths': ['legacy.png']})['valid']
    result = check(tmp_path, {'reference_video_urls': ['https://example.test/video.mp4']})
    assert not result['valid']
    assert 'reference_declarations_missing' in {issue['code'] for issue in result['issues']}


def test_video_remote_url_must_bind_same_original_bytes_even_without_availability_flag(reference_case):
    root, inputs = reference_case
    inputs['reference_media'][0]['remote'].pop('availability_evidence_ref')
    result = check(root, inputs)
    assert not result['valid']
    assert 'remote_availability_missing' in {issue['code'] for issue in result['issues']}


@pytest.mark.parametrize('field,value', [('source', ['bad']), ('remote', ['bad']),
    ('authorization_refs', {'bad': 'shape'})])
def test_malformed_declarations_report_issues_instead_of_crashing(reference_case, field, value):
    root, inputs = reference_case
    inputs['reference_media'][0][field] = value
    assert not check(root, inputs)['valid']


def test_authorization_reuses_hash_purpose_and_recipient_for_new_reference_id(reference_case):
    root, inputs = reference_case
    inputs['reference_media'][0]['reference_id'] = 'new-revision-reference-name'
    assert check(root, inputs)['valid']
    inputs['reference_media'][0]['purpose'] = 'different-purpose'
    assert not check(root, inputs)['valid']


def test_original_generation_toolresult_receipt_can_be_bound_without_rewriting(reference_case):
    root, inputs = reference_case
    path = root / 'receipt.json'
    original = json.loads(path.read_text())
    path.write_text(json.dumps({'success': True, 'data': original}))
    inputs['reference_media'][0]['generation_receipt_ref'] = ref(path)
    assert check(root, inputs)['valid']


def test_declared_images_cannot_silently_leave_extra_input_unbound(reference_case):
    root, inputs = reference_case
    inputs['reference_image_paths'] = [str(root / 'unapproved-product.png')]
    result = check(root, inputs)
    assert 'unbound_input' in {issue['code'] for issue in result['issues']}


@pytest.mark.parametrize('field', ['end_image_url', 'end_image_path'])
def test_provider_end_frame_is_always_included_in_strict_reference_gate(reference_case, field):
    root, inputs = reference_case
    inputs[field] = 'https://example.test/unapproved-end.png' if field.endswith('_url') else str(root / 'unapproved-end.png')
    result = check(root, inputs)
    assert not result['valid']
    assert 'unbound_input' in {issue['code'] for issue in result['issues']}


def test_image_to_video_dry_run_blocks_unapproved_tail_actually_sent_by_provider(tmp_path, monkeypatch):
    from PIL import Image
    from tools.video.seedance_ark import SeedanceArkVideo
    monkeypatch.setattr('requests.post', lambda *a, **kw: pytest.fail('preflight must not POST'))
    first = tmp_path / 'first.png'
    Image.new('RGB', (320, 320), 'blue').save(first)
    authorization = tmp_path / 'authorization.json'
    authorization.write_text(json.dumps({'status': 'approved', 'approved_by': 'user',
        'media_sha256': [ref(first)['sha256']], 'purposes': ['product'], 'recipients': ['volcengine_ark']}))
    inputs = {'operation': 'image_to_video', 'model_variant': '2.5', 'prompt': 'product shot',
        'project_dir': str(tmp_path), 'reference_image_path': str(first),
        'end_image_url': 'https://example.test/unapproved-end.png',
        'reference_media': [{'reference_id': 'first', 'media_type': 'image', 'roles': ['first_frame'],
            'scope': 'product identity', 'purpose': 'product', 'source': ref(first),
            'authorization_refs': [ref(authorization)]}]}
    tool = SeedanceArkVideo()
    assert tool._build_payload(inputs)['content'][-1]['role'] == 'last_frame'
    result = tool.dry_run(inputs)
    assert result['parameter_valid'] and not result['valid']
    assert 'unbound_input' in {issue['code'] for issue in result['reference_preflight']['issues']}


def source_plan_case(reference_case):
    root, inputs = reference_case
    inputs.update(shot_id='shot-a', parent_budget_id='budget-a', lineage_id='lineage-a',
        project_id='project', model='pinned-model', model_variant='2.5', operation='reference_to_video')
    dependencies = {}
    for name, data in [('fact_snapshot', {}), ('category_profile', {}),
        ('production_lock', {'project_id': 'project', 'tool': 'seedance_ark', 'provider': 'ark',
            'model': 'pinned-model', 'operation': 'reference_to_video',
            'shot_id': 'shot-a', 'parent_budget_id': 'budget-a', 'lineage_id': 'lineage-a'})]:
        path = root / f'{name}.json'
        path.write_text(json.dumps(data))
        dependencies[name] = ref(path)
    inputs['production_lock_ref'] = dependencies['production_lock']
    inputs['shot_source_plan'] = {'version': '1.0', 'project_id': 'project', 'shot_id': 'shot-a',
        'revision': 'v1', 'sku': 'sku', 'parent_budget_id': 'budget-a', 'lineage_id': 'lineage-a',
        'original_purpose_id': 'product-motion', 'dependencies': dependencies, 'global_requirement_ids': ['motion'],
        'requirements': [{'id': 'motion', 'required': True, 'method': 'full_playback', 'description': 'hand moves'}],
        'uses': [{'purpose_id': 'product-motion', 'required_requirement_ids': ['motion']}],
        'references': inputs['reference_media']}
    return root, inputs


@pytest.mark.parametrize('mutation', ['shot', 'parent', 'lineage', 'revision', 'lock', 'lock_model', 'invalid_schema', 'references'])
def test_source_plan_cannot_be_mixed_with_other_request_or_production_lock(reference_case, mutation):
    root, inputs = source_plan_case(reference_case)
    assert check(root, inputs)['valid']
    if mutation in {'shot', 'parent', 'lineage'}:
        inputs[{'shot': 'shot_id', 'parent': 'parent_budget_id', 'lineage': 'lineage_id'}[mutation]] = 'other'
    elif mutation == 'revision':
        inputs['revision_id'] = 'v2'
    elif mutation == 'lock':
        inputs['production_lock_ref'] = inputs['shot_source_plan']['dependencies']['fact_snapshot']
    elif mutation == 'lock_model':
        inputs['model'] = 'other-model'
    elif mutation == 'invalid_schema':
        inputs['shot_source_plan'].pop('requirements')
    elif mutation == 'references':
        inputs['shot_source_plan']['references'] = []
    result = check(root, inputs)
    assert not result['valid']
    assert 'source_plan_binding_invalid' in {issue['code'] for issue in result['issues']}


def test_dry_run_reports_reference_issues_without_network(reference_case, monkeypatch):
    from tools.video.seedance_ark import SeedanceArkVideo
    root, inputs = reference_case
    monkeypatch.setenv('ARK_API_KEY', 'fake-key')
    monkeypatch.setattr('requests.get', lambda *a, **kw: pytest.fail('network forbidden'))
    inputs.update(prompt='A hand moves', model_variant='2.5', operation='reference_to_video', project_dir=str(root))
    inputs['reference_media'][0]['authorization_refs'] = []
    result = SeedanceArkVideo().dry_run(inputs)
    assert result['valid'] is False
    assert result['reference_preflight']['issues'][0]['code'] == 'authorization_missing'


def test_dry_run_collects_parameter_and_reference_problems_together(reference_case):
    from tools.video.seedance_ark import SeedanceArkVideo
    root, inputs = reference_case
    inputs.update(prompt='A hand moves', operation='reference_to_video', model_variant='2.5',
                  resolution='1080p', project_dir=str(root))
    inputs['reference_media'][0]['authorization_refs'] = []
    result = SeedanceArkVideo().dry_run(inputs)
    assert result['valid'] is False
    assert result['parameter_valid'] is False
    assert 'authorization_missing' in {issue['code'] for issue in result['reference_preflight']['issues']}
