"""Same-provider reference hosting never bypasses source/transfer approvals."""
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def upload_case(tmp_path, monkeypatch):
    from tools.video.reference_video_upload import ReferenceVideoUpload
    media = tmp_path / 'hand.mp4'
    media.write_bytes(b'owned-shot-bytes')
    sha = hashlib.sha256(media.read_bytes()).hexdigest()
    auth = tmp_path / 'authorization.json'
    auth.write_text(json.dumps({'status': 'approved', 'approved_by': 'user:yichen',
        'media_sha256': [sha], 'purposes': ['sofa-motion'],
        'recipients': ['volcengine_tos']}))
    monkeypatch.setenv('VOLC_ACCESSKEY', 'TEST-AK-NEVER-LOG')
    monkeypatch.setenv('VOLC_SECRETKEY', 'TEST-SK-NEVER-LOG')
    monkeypatch.setitem(sys.modules, 'tos', SimpleNamespace(HttpMethodType=SimpleNamespace(Http_Method_Get='GET')))
    monkeypatch.setattr('shutil.which', lambda _: '/fake/ffprobe')
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: SimpleNamespace(returncode=0,
        stdout=json.dumps({'format': {'duration': '2'}, 'streams': [
            {'codec_type': 'video', 'width': 720, 'height': 960, 'avg_frame_rate': '30/1', 'codec_name': 'h264'}]}), stderr=''))
    class Response:
        status_code = 200
        def iter_content(self, chunk_size):
            yield b'owned-shot-bytes'
        def close(self):
            pass
    monkeypatch.setattr('requests.get', lambda *a, **kw: Response())
    inputs = {'operation': 'upload', 'project_dir': str(tmp_path), 'input_path': 'hand.mp4',
        'bucket': 'owned-media', 'region': 'cn-beijing', 'purpose': 'sofa-motion',
        'authorization_ref': {'path': auth.name, 'sha256': hashlib.sha256(auth.read_bytes()).hexdigest()},
        'expires_seconds': 3600}
    tool = ReferenceVideoUpload()
    return tmp_path, tool, inputs, sha


class FakeClient:
    def __init__(self, sha, *, exists=False, wrong_sha=False):
        self.sha, self.exists, self.wrong_sha = sha, exists, wrong_sha
        self.calls = []

    def list_buckets(self):
        self.calls.append(('list', {}))
        return SimpleNamespace(owner=SimpleNamespace(id='owner-123'), buckets=[
            SimpleNamespace(name='owned-media', location='cn-beijing')])

    def head_object(self, **kwargs):
        self.calls.append(('head', kwargs))
        if not self.exists:
            error = Exception('not-found')
            error.status_code = 404
            raise error
        return SimpleNamespace(content_length=len(b'owned-shot-bytes'),
            meta={'sha256': '0' * 64 if self.wrong_sha else self.sha},
            etag='etag', request_id='head-id')

    def put_object_from_file(self, **kwargs):
        self.calls.append(('put', kwargs))
        self.exists = True
        return SimpleNamespace(request_id='put-id', etag='etag')

    def pre_signed_url(self, **kwargs):
        self.calls.append(('sign', kwargs))
        return SimpleNamespace(signed_url='https://owned-media.tos-cn-beijing.volces.com/clip.mp4?signed=temporary')


def bind_client(monkeypatch, tool, client):
    monkeypatch.setattr(tool, '_client', lambda region: client)


def test_upload_dry_run_is_local_and_does_not_create_client(upload_case, monkeypatch):
    root, tool, inputs, sha = upload_case
    monkeypatch.setattr(tool, '_client', lambda _: pytest.fail('network forbidden'))
    result = tool.dry_run(inputs)
    assert result['valid'] and result['media_sha256'] == sha
    assert result['would_execute'] is False and result['network_accessed'] is False


@pytest.mark.parametrize('change', ['missing_auth', 'wrong_hash', 'wrong_recipient', 'wrong_purpose',
    'missing_bucket', 'external_region', 'path_escape', 'expires_too_long'])
def test_invalid_upload_never_reaches_network(upload_case, monkeypatch, change):
    root, tool, inputs, sha = upload_case
    if change == 'missing_auth': inputs.pop('authorization_ref')
    elif change == 'missing_bucket': inputs.pop('bucket')
    elif change == 'external_region': inputs['region'] = 'https://attacker.test'
    elif change == 'path_escape': inputs['input_path'] = '../outside.mp4'
    elif change == 'expires_too_long': inputs['expires_seconds'] = 999999
    else:
        auth = root / 'authorization.json'
        data = json.loads(auth.read_text())
        if change == 'wrong_hash': data['media_sha256'] = ['0' * 64]
        elif change == 'wrong_recipient': data['recipients'] = ['fal']
        else: data['purposes'] = ['different']
        auth.write_text(json.dumps(data))
        inputs['authorization_ref']['sha256'] = hashlib.sha256(auth.read_bytes()).hexdigest()
    monkeypatch.setattr(tool, '_client', lambda _: pytest.fail('must fail before network'))
    assert tool.dry_run(inputs)['valid'] is False
    assert tool.execute(inputs).success is False


def test_upload_verifies_bytes_and_returns_expiring_reference(upload_case, monkeypatch):
    root, tool, inputs, sha = upload_case
    client = FakeClient(sha)
    bind_client(monkeypatch, tool, client)
    result = tool.execute(inputs)
    assert result.success, result.error
    put = next(v for k, v in client.calls if k == 'put')
    assert put['meta'] == {'sha256': sha}
    assert put['content_sha256'] == sha and put['forbid_overwrite'] is True
    assert put['key'].endswith(sha + '.mp4')
    assert 'public' not in str(put.get('acl', '')).lower()
    assert result.data['media_sha256'] == sha
    assert result.data['availability']['available'] is True
    assert result.data['availability']['media_sha256'] == sha
    assert result.data['remote']['url'] == result.data['availability']['url']
    assert result.data['remote']['expires_at'] == result.data['availability']['expires_at']
    assert result.data['settled_cost_cny'] is None
    text = json.dumps(result.data)
    assert 'TEST-AK-NEVER-LOG' not in text and 'TEST-SK-NEVER-LOG' not in text


def test_existing_hash_object_is_reused_without_upload(upload_case, monkeypatch):
    _, tool, inputs, sha = upload_case
    client = FakeClient(sha, exists=True)
    bind_client(monkeypatch, tool, client)
    result = tool.execute(inputs)
    assert result.success and result.data['reused'] is True
    assert not any(k == 'put' for k, _ in client.calls)


def test_conflicting_remote_object_is_never_overwritten(upload_case, monkeypatch):
    _, tool, inputs, sha = upload_case
    client = FakeClient(sha, exists=True, wrong_sha=True)
    bind_client(monkeypatch, tool, client)
    result = tool.execute(inputs)
    assert not result.success
    assert not any(k in {'put', 'sign'} for k, _ in client.calls)


def test_list_buckets_only_reads_and_does_not_expose_credentials(upload_case, monkeypatch):
    _, tool, _, sha = upload_case
    client = FakeClient(sha)
    bind_client(monkeypatch, tool, client)
    result = tool.execute({'operation': 'list_buckets', 'region': 'cn-beijing'})
    assert result.success
    assert result.data['buckets'] == [{'name': 'owned-media', 'region': 'cn-beijing'}]
    assert len(result.data['account_fingerprint']) == 64
    assert [k for k, _ in client.calls] == ['list']


def test_remote_error_redacts_secrets_and_signed_urls(upload_case, monkeypatch):
    _, tool, inputs, _ = upload_case
    def failure(region):
        raise RuntimeError('TEST-SK-NEVER-LOG https://example.test/?X-Tos-Signature=secret')
    monkeypatch.setattr(tool, '_client', failure)
    result = tool.execute(inputs)
    assert not result.success
    assert 'TEST-SK' not in result.error and 'Signature' not in result.error


def test_signed_url_must_actually_return_the_same_bytes(upload_case, monkeypatch):
    _, tool, inputs, sha = upload_case
    client = FakeClient(sha)
    bind_client(monkeypatch, tool, client)
    response = SimpleNamespace(status_code=200, iter_content=lambda chunk_size: [b'wrong bytes'], close=lambda: None)
    monkeypatch.setattr('requests.get', lambda *a, **kw: response)
    result = tool.execute(inputs)
    assert not result.success and 'availability' not in result.data


def test_access_denied_head_does_not_trigger_upload(upload_case, monkeypatch):
    _, tool, inputs, sha = upload_case
    client = FakeClient(sha)
    def denied(**kwargs):
        error = Exception('private details')
        error.status_code = 403
        raise error
    monkeypatch.setattr(client, 'head_object', denied)
    bind_client(monkeypatch, tool, client)
    assert not tool.execute(inputs).success
    assert not any(k == 'put' for k, _ in client.calls)


def test_missing_credentials_have_actionable_redacted_error(upload_case, monkeypatch):
    _, tool, _, _ = upload_case
    monkeypatch.delenv('VOLC_ACCESSKEY')
    monkeypatch.delenv('VOLC_SECRETKEY')
    result = tool.execute({'operation': 'list_buckets', 'region': 'cn-beijing'})
    assert not result.success
    assert 'VOLC_ACCESSKEY' in result.error and 'VOLC_SECRETKEY' in result.error
    assert 'TEST-' not in result.error


def test_registered_tool_has_lifecycle_instrumentation():
    from tools.tool_registry import ToolRegistry
    from tools.video import reference_video_upload
    registry = ToolRegistry()
    assert registry.register_module(reference_video_upload) == ['reference_video_upload']
    assert registry.get('reference_video_upload').execute._backlot_instrumented is True
