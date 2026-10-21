"""Ark file transfer is authorized, durable and never repeats an uncertain POST."""
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


@pytest.fixture
def ark_case(tmp_path, monkeypatch):
    try:
        from tools.video.ark_reference_upload import ArkReferenceUpload
    except ModuleNotFoundError:
        pytest.fail('registered Ark reference uploader is not implemented')
    payload = b'owned-video-reference'
    (tmp_path / 'hand.mp4').write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    auth = {'status': 'approved', 'approved_by': 'user:yichen', 'media_sha256': [sha],
            'purposes': ['sofa-motion'], 'recipients': ['volcengine_ark']}
    (tmp_path / 'approval.json').write_text(json.dumps(auth))
    monkeypatch.setenv('ARK_API_KEY', 'TEST-ARK-SECRET')
    monkeypatch.delenv('DOUBAO_LITE_API_KEY', raising=False)
    monkeypatch.setattr('shutil.which', lambda _: '/fake/ffprobe')
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: SimpleNamespace(stdout=json.dumps({
        'format': {'duration': '2.0'}, 'streams': [{'codec_type': 'video', 'width': 720, 'height': 960}]})))
    inputs = {'operation': 'upload', 'project_dir': str(tmp_path), 'input_path': 'hand.mp4',
              'purpose': 'sofa-motion', 'authorization_ref': {'path': 'approval.json',
              'sha256': hashlib.sha256((tmp_path / 'approval.json').read_bytes()).hexdigest()}}
    return tmp_path, ArkReferenceUpload(), inputs, sha, payload


class Response:
    def __init__(self, body=None, payload=b'', status=200):
        self.body, self.payload, self.status_code = body or {}, payload, status
    def json(self):
        return self.body
    def iter_content(self, chunk_size):
        yield self.payload
    def close(self):
        pass


def bind_remote(monkeypatch, *, status='processing', url=None, payload=b'owned-video-reference'):
    calls = []
    def post(endpoint, **kwargs):
        calls.append(('POST', endpoint, kwargs))
        return Response({'id': 'file-abc', 'status': 'processing'})
    def get(endpoint, **kwargs):
        calls.append(('GET', endpoint, kwargs))
        if '/api/v3/files/' in endpoint:
            body = {'id': 'file-abc', 'status': status, 'expire_at': 2200000000}
            if url is not None:
                body['download_url'] = url
            return Response(body)
        return Response(payload=payload)
    monkeypatch.setattr('requests.post', post)
    monkeypatch.setattr('requests.get', get)
    return calls


def signed_url():
    signed_at = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return f'https://media.tos-cn-beijing.volces.com/clip.mp4?X-Tos-Date={signed_at}&X-Tos-Expires=3600&X-Tos-Signature={"1" * 64}'


def test_dry_run_never_uploads(ark_case, monkeypatch):
    _, tool, inputs, sha, _ = ark_case
    monkeypatch.setattr('requests.post', lambda *a, **kw: pytest.fail('dry-run posted'))
    result = tool.dry_run(inputs)
    assert result['valid'] and result['media_sha256'] == sha
    assert result['network_accessed'] is False


@pytest.mark.parametrize('case', ['missing_approval', 'wrong_hash', 'wrong_recipient', 'escape', 'bad_expiry'])
def test_invalid_local_inputs_never_post(ark_case, monkeypatch, case):
    root, tool, inputs, _, _ = ark_case
    if case == 'missing_approval':
        inputs.pop('authorization_ref')
    elif case == 'wrong_hash':
        inputs['authorization_ref']['sha256'] = '0' * 64
    elif case == 'wrong_recipient':
        path = root / 'approval.json'
        auth = json.loads(path.read_text()); auth['recipients'] = ['third_party']
        path.write_text(json.dumps(auth)); inputs['authorization_ref']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif case == 'escape':
        inputs['input_path'] = '../secret.mp4'
    else:
        inputs['expires_seconds'] = 60
    monkeypatch.setattr('requests.post', lambda *a, **kw: pytest.fail('invalid input posted'))
    assert tool.dry_run(inputs)['valid'] is False
    assert tool.execute(inputs).success is False


def test_upload_journals_identity_before_post_and_processing_recovery_only_gets(ark_case, monkeypatch):
    root, tool, inputs, sha, _ = ark_case
    calls = bind_remote(monkeypatch)
    original_post = __import__('requests').post
    def verify_before_post(*a, **kw):
        journals = list((root / 'artifacts/reference_uploads/ark').glob('*.json'))
        assert len(journals) == 1
        journal = json.loads(journals[0].read_text())
        assert journal['media_sha256'] == sha and journal['status'] == 'uploading'
        assert len(journal['account_fingerprint']) == 64
        assert kw['data']['purpose'] == 'user_data' and 'tos' not in kw['data']
        assert kw['allow_redirects'] is False
        return original_post(*a, **kw)
    monkeypatch.setattr('requests.post', verify_before_post)
    first = tool.execute(inputs)
    assert first.success and first.data['status'] == 'processing'
    assert first.data['file_id'] == 'file-abc' and 'remote' not in first.data
    inputs['operation'] = 'query'
    second = tool.execute(inputs)
    assert second.success and second.data['file_id'] == 'file-abc'
    assert [c[0] for c in calls].count('POST') == 1


def test_unknown_post_outcome_blocks_repeat_and_redacts_secrets(ark_case, monkeypatch):
    root, tool, inputs, _, _ = ark_case
    attempts = []
    def post(*a, **kw):
        attempts.append(1)
        raise RuntimeError('TEST-ARK-SECRET https://evil.test/signed?secret=hidden')
    monkeypatch.setattr('requests.post', post)
    first, second = tool.execute(inputs), tool.execute(inputs)
    assert not first.success and not second.success and len(attempts) == 1
    assert 'unknown' in second.error.lower()
    exposed = json.dumps([first.data, second.data, first.error, second.error])
    assert 'TEST-ARK-SECRET' not in exposed and 'evil.test' not in exposed
    receipt = list((root / 'artifacts/reference_uploads/ark').glob('*.json'))[0].read_text()
    assert 'TEST-ARK-SECRET' not in receipt and 'evil.test' not in receipt


def test_active_without_download_url_is_honest_block(ark_case, monkeypatch):
    _, tool, inputs, _, _ = ark_case
    bind_remote(monkeypatch, status='active')
    result = tool.execute(inputs)
    assert result.success and result.data['status'] == 'needs_readable_url'
    assert result.data['file_id'] == 'file-abc' and 'remote' not in result.data


def test_verified_download_returns_byte_bound_availability(ark_case, monkeypatch):
    _, tool, inputs, sha, payload = ark_case
    calls = bind_remote(monkeypatch, status='active', url=signed_url(), payload=payload)
    result = tool.execute(inputs)
    assert result.success and result.data['availability']['media_sha256'] == sha
    assert result.data['availability']['provider_acceptance'] == 'not_verified'
    assert result.data['remote']['expires_at']
    download = calls[-1]
    assert download[2]['allow_redirects'] is False and 'headers' not in download[2]


@pytest.mark.parametrize('case', ['foreign_host', 'wrong_bytes', 'redirect'])
def test_remote_identity_failures_never_report_availability(ark_case, monkeypatch, case):
    _, tool, inputs, _, payload = ark_case
    url = signed_url().replace('media.tos-cn-beijing.volces.com', 'evil.test') if case == 'foreign_host' else signed_url()
    bind_remote(monkeypatch, status='active', url=url, payload=b'bad' if case == 'wrong_bytes' else payload)
    if case == 'redirect':
        original = __import__('requests').get
        monkeypatch.setattr('requests.get', lambda u, **kw: Response(status=302) if '/api/v3/files/' not in u else original(u, **kw))
    result = tool.execute(inputs)
    assert not result.success and 'availability' not in result.data


def test_unverifiable_url_expiry_cannot_be_reported_as_file_expiry(ark_case, monkeypatch):
    _, tool, inputs, _, _ = ark_case
    calls = bind_remote(monkeypatch, status='active', url='https://media.tos-cn-beijing.volces.com/clip.mp4?temporary=1')
    result = tool.execute(inputs)
    assert result.success and result.data['status'] == 'expiry_unverified'
    assert 'remote' not in result.data and len(calls) == 2


def test_existing_journal_is_bound_to_approved_scope(ark_case, monkeypatch):
    _, tool, inputs, _, _ = ark_case
    calls = bind_remote(monkeypatch)
    assert tool.execute(inputs).success
    root = __import__('pathlib').Path(inputs['project_dir'])
    path = root / 'approval.json'
    approval = json.loads(path.read_text())
    approval['purposes'].append('other-purpose')
    path.write_text(json.dumps(approval))
    inputs['purpose'] = 'other-purpose'
    inputs['authorization_ref']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = tool.execute(inputs)
    assert not result.success and 'scope' in result.error
    assert len(calls) == 2


def test_upload_mutex_rejects_concurrent_operation(ark_case, monkeypatch):
    import fcntl
    root, tool, inputs, _, _ = ark_case
    prepared = tool._prepare(inputs)
    lock_path = prepared['journal'].with_suffix('.lock')
    lock_path.parent.mkdir(parents=True)
    with lock_path.open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr('requests.post', lambda *a, **kw: pytest.fail('locked operation posted'))
        assert tool.execute(inputs).success is False


def test_compatible_credential_name_and_untrusted_base_url_are_ignored(ark_case, monkeypatch):
    _, tool, inputs, _, _ = ark_case
    monkeypatch.delenv('ARK_API_KEY')
    monkeypatch.setenv('DOUBAO_LITE_API_KEY', 'FALLBACK-ARK-SECRET')
    monkeypatch.setenv('ARK_BASE_URL', 'https://evil.test/')
    calls = bind_remote(monkeypatch)
    assert tool.execute(inputs).success
    assert calls[0][1] == 'https://ark.cn-beijing.volces.com/api/v3/files'
    assert calls[0][2]['headers']['Authorization'] == 'Bearer FALLBACK-ARK-SECRET'


@pytest.mark.parametrize('query', [
    'Expires=2200000000',
    'X-Tos-Date=20261020T000000Z&X-Tos-Expires=60&x-tos-expires=604800&X-Tos-Signature=abc',
])
def test_ambiguous_or_unsigned_expiry_is_not_evidence(ark_case, query):
    _, tool, _, _, _ = ark_case
    assert tool._url_expiry('https://media.tos-cn-beijing.volces.com/v.mp4?' + query) is None


def test_post_transmits_frozen_approved_bytes(ark_case, monkeypatch):
    root, tool, inputs, _, payload = ark_case
    bind_remote(monkeypatch)
    post = __import__('requests').post
    def replace_source_before_read(endpoint, **kwargs):
        (root / 'hand.mp4').write_bytes(b'changed after validation')
        assert kwargs['files']['file'][1].read() == payload
        return post(endpoint, **kwargs)
    monkeypatch.setattr('requests.post', replace_source_before_read)
    assert tool.execute(inputs).success


def test_link_expiry_is_rechecked_after_download(ark_case, monkeypatch):
    _, tool, inputs, _, payload = ark_case
    from tools.video import ark_reference_upload as module
    monkeypatch.setattr(module.time, 'time', lambda: 1800000000)
    url = 'https://media.tos-cn-beijing.volces.com/v.mp4?Expires=1800000100&Signature=signed&AWSAccessKeyId=temporary'
    original = bind_remote(monkeypatch, status='active', url=url, payload=payload)
    get = __import__('requests').get
    def expires_while_reading(endpoint, **kwargs):
        result = get(endpoint, **kwargs)
        if '/api/v3/files/' not in endpoint:
            monkeypatch.setattr(module.time, 'time', lambda: 1800000200)
        return result
    monkeypatch.setattr('requests.get', expires_while_reading)
    result = tool.execute(inputs)
    assert not result.success and 'availability' not in result.data
