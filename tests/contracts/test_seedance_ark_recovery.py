import json
from pathlib import Path

import pytest
import requests

from tools.video.seedance_ark import SeedanceArkVideo
from tools.cost_tracker import CostTracker
from lib.config_model import BudgetMode


TASK = {'id': 'task-1', 'model': 'doubao-seedance-2-5-260628', 'status': 'succeeded',
        'resolution': '720p', 'usage': {'completion_tokens': 87300},
        'content': {'video_url': 'https://example.test/video.mp4'}}


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv('ARK_API_KEY', 'not-a-real-key')
    monkeypatch.delenv('ARK_CNY_PER_USD', raising=False)
    monkeypatch.setenv('ARK_TASK_JOURNAL_PATH', str(tmp_path / 'tasks.json'))
    tool = SeedanceArkVideo()
    monkeypatch.setattr(tool, '_query_task', lambda *_: (_ for _ in ()).throw(AssertionError('network query must be mocked')))
    monkeypatch.setattr(tool, '_download_video', lambda url, path: path.write_bytes(b'video'))
    monkeypatch.setattr('tools.video._shared.probe_output', lambda _: {'duration_seconds': 4})
    return tool


def paid_inputs(tmp_path):
    path = tmp_path / 'paid-generation.json'
    tracker = CostTracker(cost_log_path=path, budget_total_usd=100, mode=BudgetMode.OBSERVE)
    reservation = tracker.estimate('seedance_ark', 'text_to_video', 2,
        budget_equivalent_cny=20, budget_equivalence_provenance={'approval_ref': 'fixture-approved-bound'})
    tracker.reserve(reservation)
    return {'cost_log_path': str(path), 'reservation_id': reservation}


def test_query_reconciles_usage_without_fabricating_bill(configured, monkeypatch, tmp_path):
    cost = tmp_path / 'cost.json'
    t = CostTracker(cost_log_path=cost, mode=BudgetMode.OBSERVE)
    eid = t.estimate('seedance_ark', 'shot', .84)
    t.reserve(eid)
    monkeypatch.setattr(configured, '_query_task', lambda *_: TASK)
    result = configured.execute({'task_action': 'query', 'task_id': 'task-1',
                                 'cost_log_path': str(cost), 'reservation_id': eid})
    assert result.success
    assert result.cost_usd is None
    assert result.data['catalog_estimate']['amount'] == 6.111
    assert result.data['catalog_estimate']['currency'] == 'CNY'
    assert result.data['catalog_estimate']['price_date'] == '2026-09-24'
    entry = json.loads(cost.read_text())['entries'][0]
    assert entry['actual_usd'] is None
    assert entry['reserved_usd'] == 0
    assert entry['budget_commitment_usd'] == .84
    assert entry['provider_task_id'] == 'task-1'


def test_no_implicit_exchange_rate(configured):
    assert configured.estimate_cost({'model_variant': '2.5'}) is None
    assert configured.estimate_cost_cny({'model_variant': '2.5'}) > 0


def test_confirmed_provider_rejection_keeps_evidence_budget_and_releases_slot(configured, monkeypatch, tmp_path):
    response = requests.Response()
    response.status_code = 400
    response._content = b'{"error":{"code":"InvalidParameter","message":"bad ratio"},"request_id":"req-rejected"}'
    response.headers['X-Request-Id'] = 'req-rejected'
    calls = []
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: calls.append('post') or response)
    inputs = {**paid_inputs(tmp_path), 'prompt': 'A towel', 'model_variant': '2.5',
              'idempotency_key': 'rejected', 'account_concurrency_limit': 1}
    result = configured.execute(inputs)
    assert result.data['status'] == 'provider_rejected'
    assert result.data['provider_error'] == {
        'http_status': 400, 'code': 'InvalidParameter', 'request_id': 'req-rejected',
        'task_id': None, 'task_creation': 'not_created'}
    journal = json.loads((tmp_path / 'tasks.json').read_text())['attempts']
    assert journal[0]['status'] == 'provider_rejected'
    assert journal[0]['provider_error'] == result.data['provider_error']
    assert configured.execute(inputs).data['status'] == 'provider_rejected'
    assert calls == ['post']
    entry = json.loads(Path(inputs['cost_log_path']).read_text())['entries'][0]
    assert entry['actual_usd'] is None
    from lib.generation_attempts import GenerationAttempts
    GenerationAttempts(tmp_path / 'tasks.json').claim('other', 'new-fp', account=journal[0]['account'], account_limit=1)


def test_unstructured_server_error_preserves_unknown_creation(configured, monkeypatch, tmp_path):
    response = requests.Response()
    response.status_code = 500
    response._content = b'{"error":{"code":"InternalError","message":"failure"},"request_id":"req-unknown"}'
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: response)
    result = configured.execute({**paid_inputs(tmp_path), 'prompt': 'A towel', 'model_variant': '2.5'})
    assert result.data['status'] == 'submission_result_unknown'
    assert result.data['provider_error']['task_creation'] == 'unknown'
    assert result.data['provider_error']['http_status'] == 500


@pytest.mark.parametrize('status,content', [(200, b'not-json'), (200, b'{}'), (400, b'<html>gateway failure</html>')])
def test_malformed_response_does_not_claim_task_was_rejected(configured, monkeypatch, tmp_path, status, content):
    response = requests.Response()
    response.status_code = status
    response._content = content
    response.headers['X-Request-Id'] = 'req-malformed'
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: response)
    result = configured.execute({**paid_inputs(tmp_path), 'prompt': 'A towel', 'model_variant': '2.5'})
    assert result.data['status'] == 'submission_result_unknown'
    assert result.data['provider_error']['task_creation'] == 'unknown'
    assert result.data['provider_error']['http_status'] == status
    assert result.data['provider_error']['request_id'] == 'req-malformed'


def test_error_response_with_task_identity_is_recovered_by_get(configured, monkeypatch, tmp_path):
    response = requests.Response()
    response.status_code = 500
    response._content = b'{"id":"task-1","error":{"code":"InternalError"}}'
    calls = []
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: calls.append('post') or response)
    inputs = {**paid_inputs(tmp_path), 'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'has-task'}
    first = configured.execute(inputs)
    assert first.data['task_id'] == 'task-1'
    assert first.data['provider_error']['task_creation'] == 'created'
    monkeypatch.setattr(configured, '_query_task', lambda *_: calls.append('get') or TASK)
    assert configured.execute({**inputs, 'output_path': str(tmp_path / 'out.mp4')}).success
    assert calls == ['post', 'get']


def native_inputs(tmp_path, estimate='6.048'):
    tracker = CostTracker(project_dir=tmp_path)
    tracker.create_parent_budget('parent', currency='CNY', amount='30', max_paid_calls=3,
        authorization_ref='approval:local', shot_id='shot', lineage_id='lineage')
    reservation = tracker.estimate_native('seedance_ark', 'text_to_video', estimate, currency='CNY',
        parent_budget_id='parent', shot_id='shot', lineage_id='lineage', request_id='request-one')
    tracker.reserve(reservation)
    return {'project_dir': str(tmp_path), 'parent_budget_id': 'parent', 'shot_id': 'shot',
        'lineage_id': 'lineage', 'reservation_id': reservation, 'model_variant': '2.5',
        'duration': 4, 'generate_audio': False, 'prompt': 'A towel', 'idempotency_key': 'native-key',
        'output_path': str(tmp_path / 'native.mp4')}


def test_native_parent_budget_is_bound_without_usd_proxy(configured, monkeypatch, tmp_path):
    inputs = native_inputs(tmp_path)
    monkeypatch.setattr(configured, '_create_task', lambda *_: 'task-native')
    task = {**TASK, 'id': 'task-native'}
    monkeypatch.setattr(configured, '_poll_task', lambda *_: task)
    result = configured.execute(inputs)
    assert result.success
    entry = CostTracker(project_dir=tmp_path).get_native_entry(inputs['reservation_id'])
    assert entry['provider_task_id'] == 'task-native'
    assert entry['actual_cost'] is None
    assert entry['catalog_estimate']['currency'] == 'CNY'
    assert result.cost_usd is None


def test_native_cny_budget_does_not_use_optional_usd_exchange_rate(configured, monkeypatch, tmp_path):
    inputs = native_inputs(tmp_path)
    monkeypatch.setenv('ARK_CNY_PER_USD', '7')
    monkeypatch.setattr(configured, '_create_task', lambda *_: 'task-native-fx')
    monkeypatch.setattr(configured, '_poll_task', lambda *_: {**TASK, 'id': 'task-native-fx'})
    assert configured.execute(inputs).success


def test_native_reservation_can_cover_price_with_approved_headroom(configured, monkeypatch, tmp_path):
    inputs = native_inputs(tmp_path, estimate='8')
    monkeypatch.setattr(configured, '_create_task', lambda *_: 'task-native-headroom')
    monkeypatch.setattr(configured, '_poll_task', lambda *_: {**TASK, 'id': 'task-native-headroom'})
    assert configured.execute(inputs).success


def test_generated_receipt_binds_downloaded_bytes_and_account(configured, monkeypatch, tmp_path):
    from lib.production_evidence import file_sha256
    inputs = {**paid_inputs(tmp_path), 'prompt': 'A towel', 'model_variant': '2.5',
              'output_path': str(tmp_path / 'receipt-video.mp4')}
    monkeypatch.setattr(configured, '_create_task', lambda *_: 'task-1')
    monkeypatch.setattr(configured, '_poll_task', lambda *_: TASK)
    result = configured.execute(inputs)
    assert result.success
    assert result.data['media_sha256'] == file_sha256(tmp_path / 'receipt-video.mp4')
    journal = json.loads((tmp_path / 'tasks.json').read_text())['attempts'][0]
    assert result.data['account_fingerprint'] == journal['account']


def test_native_read_only_query_cannot_adopt_unbound_reservation(configured, monkeypatch, tmp_path):
    inputs = native_inputs(tmp_path)
    inputs.update(task_action='query', task_id='task-1')
    monkeypatch.setattr(configured, '_query_task', lambda *_: TASK)
    result = configured.execute(inputs)
    assert not result.success
    assert 'binding' in result.error
    entry = CostTracker(project_dir=tmp_path).get_native_entry(inputs['reservation_id'])
    assert entry.get('provider_task_id') is None
    assert entry['status'] == 'reserved'


@pytest.mark.parametrize('recovery_action', ['generate', 'query'])
def test_native_recovery_repairs_crash_between_journal_task_and_ledger_binding(configured, monkeypatch, tmp_path, recovery_action):
    inputs = native_inputs(tmp_path)
    calls = []
    original_bind = configured._bind_reservation
    def interrupted_bind(inputs, attempt, *, task_id=None):
        if task_id:
            raise RuntimeError('crash after journal task binding')
        return original_bind(inputs, attempt)
    monkeypatch.setattr(configured, '_bind_reservation', interrupted_bind)
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-1')
    assert not configured.execute(inputs).success
    entry = CostTracker(project_dir=tmp_path).get_native_entry(inputs['reservation_id'])
    assert entry['attempt_id'] and entry.get('provider_task_id') is None
    monkeypatch.setattr(configured, '_bind_reservation', original_bind)
    monkeypatch.setattr(configured, '_query_task', lambda *_: calls.append('get') or TASK)
    recovery_inputs = inputs if recovery_action == 'generate' else {
        'task_action': 'query', 'task_id': 'task-1', **{key: inputs[key] for key in
            ('project_dir', 'parent_budget_id', 'shot_id', 'lineage_id', 'reservation_id')}}
    recovered = configured.execute(recovery_inputs)
    assert recovered.success
    assert calls == ['post', 'get']
    entry = CostTracker(project_dir=tmp_path).get_native_entry(inputs['reservation_id'])
    assert entry['provider_task_id'] == 'task-1'


def test_native_recovery_does_not_adopt_reservation_without_original_attempt_binding(configured, monkeypatch, tmp_path):
    from lib.generation_attempts import GenerationAttempts
    inputs = native_inputs(tmp_path)
    journal = GenerationAttempts(tmp_path / 'tasks.json')
    account = journal.fingerprint({'base_url': configured._get_base_url(), 'api_key': 'not-a-real-key'})
    attempt, _ = journal.claim(inputs['idempotency_key'], journal.fingerprint(configured._build_payload(inputs)),
        account=account, metadata={key: inputs[key] for key in ('project_dir', 'parent_budget_id', 'shot_id',
                                  'lineage_id', 'reservation_id')})
    journal.mark_submitted(attempt['attempt_id'], 'task-1')
    monkeypatch.setattr(configured, '_query_task', lambda *_: pytest.fail('unbound reservation must stop before GET'))
    result = configured.execute(inputs)
    assert not result.success
    assert 'binding' in result.error


def test_native_receipt_identity_is_real_and_stable_across_create_query_recovery(configured, monkeypatch, tmp_path):
    from lib.generation_attempts import GenerationAttempts
    inputs = native_inputs(tmp_path)
    inputs.update(task_action='create', project_id='project', revision_id='v1')
    source_fp = GenerationAttempts.fingerprint(inputs)
    request_fp = GenerationAttempts.fingerprint(configured._build_payload(inputs))
    monkeypatch.setattr(configured, '_create_task', lambda *_: 'task-1')
    created = configured.execute(inputs)
    assert created.success
    monkeypatch.setattr(configured, '_query_task', lambda *_: TASK)
    queried = configured.execute({'task_action': 'query', 'task_id': 'task-1'})
    assert queried.success
    for result in (created, queried):
        assert result.data['task_id'] == 'task-1'
        assert result.data['model'] == TASK['model']
        assert result.data['provider'] == 'ark'
        assert len(result.data['account_fingerprint']) == 64
        assert result.data['project_id'] == 'project'
        assert result.data['revision'] == 'v1'
        assert result.data['shot_id'] == 'shot'
        assert result.data['lineage_id'] == 'lineage'
        assert result.data['parent_budget_id'] == 'parent'
        assert result.data['request_id'] == 'request-one'
        assert result.data['source_inputs_fingerprint'] == source_fp
        assert result.data['request_fingerprint'] == request_fp
        assert result.data['idempotency_key'] == inputs['idempotency_key']
    recovered = configured.execute({**inputs, 'task_action': 'generate'})
    assert recovered.success
    assert recovered.data['source_inputs_fingerprint'] == source_fp
    assert recovered.data['request_id'] == 'request-one'
    assert recovered.data['task_id'] == 'task-1'


def test_legacy_journal_without_new_receipt_metadata_still_recovers(configured, monkeypatch, tmp_path):
    inputs = {**paid_inputs(tmp_path), 'prompt': 'A towel', 'model': TASK['model'],
              'operation': 'text_to_video', 'resolution': '720p',
              'idempotency_key': 'legacy-journal', 'output_path': str(tmp_path / 'legacy.mp4')}
    monkeypatch.setattr(configured, '_create_task', lambda *_: 'task-1')
    monkeypatch.setattr(configured, '_poll_task', lambda *_: (_ for _ in ()).throw(requests.ReadTimeout()))
    assert not configured.execute(inputs).success
    journal_path = tmp_path / 'tasks.json'
    journal = json.loads(journal_path.read_text())
    journal['attempts'][0]['metadata'] = {key: inputs[key] for key in ('cost_log_path', 'reservation_id')}
    journal_path.write_text(json.dumps(journal))
    monkeypatch.setattr(configured, '_query_task', lambda *_: TASK)
    result = configured.execute(inputs)
    assert result.success
    assert result.data['model'] == TASK['model']
    assert result.data['source_inputs_fingerprint'] is None


def test_receipt_identity_does_not_overwrite_observed_provider_model(configured, monkeypatch, tmp_path):
    inputs = {**paid_inputs(tmp_path), 'prompt': 'A towel', 'model_variant': '2.5',
              'output_path': str(tmp_path / 'observed-model.mp4')}
    monkeypatch.setattr(configured, '_create_task', lambda *_: 'task-1')
    monkeypatch.setattr(configured, '_poll_task', lambda *_: {**TASK, 'model': 'observed-other-model'})
    result = configured.execute(inputs)
    assert result.success
    assert result.data['model'] == 'observed-other-model'


@pytest.mark.parametrize('mutation', ['parent', 'lineage', 'ledger'])
def test_native_parent_identity_cannot_be_replaced_before_post(configured, monkeypatch, tmp_path, mutation):
    inputs = native_inputs(tmp_path)
    if mutation == 'parent':
        inputs['parent_budget_id'] = 'other-parent'
    elif mutation == 'lineage':
        inputs['lineage_id'] = 'other-lineage'
    else:
        inputs['cost_log_path'] = str(tmp_path / 'other-ledger.json')
    monkeypatch.setattr(configured, '_create_task', lambda *_: pytest.fail('invalid binding reached paid POST'))
    result = configured.execute(inputs)
    assert not result.success
    assert result.data['status'] == 'preflight_rejected'


def test_timeout_recovery_queries_existing_task_without_post(configured, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-1')
    monkeypatch.setattr(configured, '_poll_task', lambda *_: (_ for _ in ()).throw(requests.ReadTimeout('timeout')))
    inputs = {**paid_inputs(tmp_path), 'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'shot-a',
              'output_path': str(tmp_path / 'out.mp4')}
    first = configured.execute(inputs)
    assert not first.success
    assert first.data['task_id'] == 'task-1'
    monkeypatch.setattr(configured, '_query_task', lambda *_: calls.append('get') or TASK)
    second = configured.execute(inputs)
    assert second.success
    assert calls == ['post', 'get']
    assert second.data['task_id'] == 'task-1'


def test_submit_timeout_without_task_id_never_blindly_reposts(configured, monkeypatch, tmp_path):
    calls = []
    def fail(*_):
        calls.append('post')
        raise requests.ReadTimeout('unknown remote outcome')
    monkeypatch.setattr(configured, '_create_task', fail)
    inputs = {**paid_inputs(tmp_path), 'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'shot-b'}
    first = configured.execute(inputs)
    second = configured.execute(inputs)
    assert not first.success and not second.success
    assert calls == ['post']
    assert second.data['recovery_action'] == 'resolve_remote_task_id'


def test_preflight_rejection_is_not_provider_failure(configured):
    result = configured.execute({'prompt': '', 'model_variant': '2.5', 'idempotency_key': 'invalid'})
    assert not result.success
    assert result.data['status'] == 'preflight_rejected'


def test_atomic_account_limit_and_attempt_limits(tmp_path):
    from lib.generation_attempts import GenerationAttempts, ConcurrencyLimitError, AttemptLimitError
    a, b = GenerationAttempts(tmp_path / 'tasks.json'), GenerationAttempts(tmp_path / 'tasks.json')
    first, new = a.claim('one', 'fp1', account='account', account_limit=1)
    assert new
    same, new = b.claim('one', 'fp1', account='account', account_limit=1)
    assert not new and same['attempt_id'] == first['attempt_id']
    with pytest.raises(ConcurrencyLimitError):
        b.claim('two', 'fp2', account='account', account_limit=1)
    a.mark_submitted(first['attempt_id'], 'task-1')
    a.mark_result(first['attempt_id'], 'succeeded')
    for i in range(2):
        child, _ = b.claim(f'retry-{i}', str(i), account='account', attempt_kind='creative_retry',
                           parent_attempt_id=first['attempt_id'])
        b.mark_submitted(child['attempt_id'], f'retry-task-{i}')
        b.mark_result(child['attempt_id'], 'succeeded')
    with pytest.raises(AttemptLimitError):
        a.claim('retry-3', '3', account='account', attempt_kind='creative_retry', parent_attempt_id=first['attempt_id'])
    with pytest.raises(ValueError, match='fingerprint'):
        a.claim('one', 'changed', account='account')


def test_recovery_query_uses_persisted_cost_reservation(configured, monkeypatch, tmp_path):
    cost = tmp_path / 'cost.json'
    t = CostTracker(cost_log_path=cost, mode=BudgetMode.OBSERVE)
    eid = t.estimate('seedance_ark', 'text_to_video', .84, budget_equivalent_cny=10, budget_equivalence_provenance={'approval_ref': 'fixture-approval'})
    t.reserve(eid)
    monkeypatch.setattr(configured, '_create_task', lambda *_: 'task-1')
    base = {'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'persisted-cost'}
    first = configured.execute({**base, 'task_action': 'create', 'cost_log_path': str(cost), 'reservation_id': eid})
    assert first.success
    entry = json.loads(cost.read_text())['entries'][0]
    assert entry['provider_task_id'] == 'task-1'
    with pytest.raises(ValueError, match='executed'):
        CostTracker(cost_log_path=cost).refund(eid)
    monkeypatch.setattr(configured, '_query_task', lambda *_: TASK)
    second = configured.execute({'task_action': 'query', 'task_id': 'task-1'})
    assert second.success
    assert json.loads(cost.read_text())['entries'][0]['reserved_usd'] == 0


def test_invalid_cost_reservation_stops_before_post(configured, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-1')
    result = configured.execute({'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'bad-budget',
                                 'cost_log_path': str(tmp_path / 'missing-cost.json'), 'reservation_id': 'missing'})
    assert not result.success
    assert calls == []


def test_unknown_submission_keeps_budget_reserved(configured, monkeypatch, tmp_path):
    cost = tmp_path / 'cost.json'
    t = CostTracker(cost_log_path=cost, mode=BudgetMode.OBSERVE)
    eid = t.estimate('seedance_ark', 'text_to_video', .84, budget_equivalent_cny=10, budget_equivalence_provenance={'approval_ref': 'fixture-approval'})
    t.reserve(eid)
    monkeypatch.setattr(configured, '_create_task', lambda *_: (_ for _ in ()).throw(requests.ReadTimeout('unknown')))
    configured.execute({'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'unknown-budget',
                        'cost_log_path': str(cost), 'reservation_id': eid})
    with pytest.raises(ValueError, match='executed'):
        CostTracker(cost_log_path=cost).refund(eid)
    assert json.loads(cost.read_text())['entries'][0]['reserved_usd'] == .84


def test_concurrent_same_key_has_only_one_submission_owner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from lib.generation_attempts import GenerationAttempts
    def claim(_):
        return GenerationAttempts(tmp_path / 'tasks.json').claim('same', 'fp', account='account')[1]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(claim, range(16))).count(True) == 1


def test_judge_format_repair_has_one_extra_attempt(tmp_path):
    from lib.generation_attempts import GenerationAttempts, AttemptLimitError
    journal = GenerationAttempts(tmp_path / 'tasks.json')
    first, _ = journal.claim('one', 'fp1', account='account')
    journal.mark_result(first['attempt_id'], 'succeeded')
    repair, _ = journal.claim('repair', 'fp2', account='account', attempt_kind='judge_format_repair', parent_attempt_id=first['attempt_id'])
    journal.mark_result(repair['attempt_id'], 'succeeded')
    with pytest.raises(AttemptLimitError):
        journal.claim('repair-again', 'fp3', account='account', attempt_kind='judge_format_repair', parent_attempt_id=repair['attempt_id'])


def test_failed_provider_job_recovery_does_not_resubmit(configured, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-1')
    failed_task = {**TASK, 'status': 'failed', 'error': {'message': 'generation rejected'}}
    monkeypatch.setattr(configured, '_poll_task', lambda *_: failed_task)
    inputs = {**paid_inputs(tmp_path), 'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'failed-provider'}
    first = configured.execute(inputs)
    monkeypatch.setattr(configured, '_query_task', lambda *_: calls.append('get') or failed_task)
    second = configured.execute(inputs)
    assert not first.success
    assert not second.success and second.data['status'] == 'failed'
    assert calls == ['post', 'get']


def test_generation_account_limit_blocks_third_post(configured, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or f'task-{len(calls)}')
    for index in range(2):
        assert configured.execute({**paid_inputs(tmp_path), 'task_action': 'create', 'prompt': f'Towel {index}', 'model_variant': '2.5', 'idempotency_key': str(index)}).success
    result = configured.execute({**paid_inputs(tmp_path), 'task_action': 'create', 'prompt': 'Third towel', 'model_variant': '2.5', 'idempotency_key': 'third'})
    assert not result.success
    assert 'concurrency limit' in result.error
    assert len(calls) == 2


def test_paid_submit_rejects_zero_or_wrong_operation_reservation(configured, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-1')
    for i, (operation, amount) in enumerate([('unrelated', 0), ('text_to_video', 0), ('unrelated', 10)]):
        path = tmp_path / f'bad-cost-{i}.json'
        tracker = CostTracker(cost_log_path=path, budget_total_usd=20, mode=BudgetMode.OBSERVE)
        entry = tracker.estimate('seedance_ark', operation, amount)
        tracker.reserve(entry)
        result = configured.execute({'task_action': 'create', 'prompt': 'A towel', 'model_variant': '2.5',
                                     'cost_log_path': str(path), 'reservation_id': entry, 'idempotency_key': f'bad-op-{i}'})
        assert not result.success
    assert calls == []


def test_known_usd_estimate_must_fit_reservation(configured, monkeypatch, tmp_path):
    monkeypatch.setenv('ARK_CNY_PER_USD', '7')
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-1')
    path = tmp_path / 'insufficient.json'
    t = CostTracker(cost_log_path=path, mode=BudgetMode.OBSERVE)
    eid = t.estimate('seedance_ark', 'text_to_video', .01)
    t.reserve(eid)
    result = configured.execute({'task_action': 'create', 'prompt': 'A towel', 'model_variant': '2.5',
                                 'cost_log_path': str(path), 'reservation_id': eid})
    assert not result.success
    assert calls == []


def test_missing_fx_requires_explicit_cny_budget_bound(configured, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-1')
    path = tmp_path / 'unknown-fx.json'
    t = CostTracker(cost_log_path=path, mode=BudgetMode.OBSERVE)
    eid = t.estimate('seedance_ark', 'text_to_video', .84)
    t.reserve(eid)
    result = configured.execute({'task_action': 'create', 'prompt': 'A towel', 'model_variant': '2.5',
                                 'cost_log_path': str(path), 'reservation_id': eid})
    assert not result.success
    assert calls == []


def test_bound_query_cannot_replace_reservation(configured, monkeypatch, tmp_path):
    monkeypatch.setenv('ARK_CNY_PER_USD', '7')
    path = tmp_path / 'bound-query.json'
    t = CostTracker(cost_log_path=path, budget_total_usd=30, mode=BudgetMode.OBSERVE)
    one = t.estimate('seedance_ark', 'text_to_video', 10)
    two = t.estimate('seedance_ark', 'text_to_video', 10)
    t.reserve(one)
    t.reserve(two)
    monkeypatch.setattr(configured, '_create_task', lambda *_: 'task-1')
    created = configured.execute({'task_action': 'create', 'prompt': 'A towel', 'model_variant': '2.5',
                                  'cost_log_path': str(path), 'reservation_id': one})
    assert created.success
    monkeypatch.setattr(configured, '_query_task', lambda *_: TASK)
    queried = configured.execute({'task_action': 'query', 'task_id': 'task-1',
                                  'cost_log_path': str(path), 'reservation_id': two})
    assert not queried.success
    entries = json.loads(path.read_text())['entries']
    assert entries[1]['status'] == 'reserved'
    assert entries[1].get('provider_task_id') is None


def test_paid_submit_without_reservation_is_rejected(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-1')
    result = configured.execute({'task_action': 'create', 'prompt': 'A towel', 'model_variant': '2.5'})
    assert not result.success
    assert calls == []


def test_generate_recovery_restores_local_artifact_contract(configured, monkeypatch, tmp_path):
    monkeypatch.setenv('ARK_CNY_PER_USD', '7')
    path = tmp_path / 'download-cost.json'
    t = CostTracker(cost_log_path=path, mode=BudgetMode.OBSERVE)
    eid = t.estimate('seedance_ark', 'text_to_video', 10)
    t.reserve(eid)
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-1')
    monkeypatch.setattr(configured, '_poll_task', lambda *_: (_ for _ in ()).throw(requests.ReadTimeout('timeout')))
    output = tmp_path / 'restored.mp4'
    inputs = {'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'download-recovery',
              'cost_log_path': str(path), 'reservation_id': eid, 'output_path': str(output)}
    assert not configured.execute(inputs).success
    monkeypatch.setattr(configured, '_query_task', lambda *_: calls.append('get') or TASK)
    monkeypatch.setattr(configured, '_download_video', lambda url, output_path: output_path.write_bytes(b'video'))
    monkeypatch.setattr('tools.video._shared.probe_output', lambda _: {'duration_seconds': 4})
    result = configured.execute(inputs)
    assert result.success
    assert result.data['output_path'] == str(output)
    assert result.artifacts == [str(output)]
    assert output.read_bytes() == b'video'
    assert calls == ['post', 'get']


def test_confirmed_preflight_rejection_can_reclaim_same_key_with_repaired_budget(configured, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(configured, '_create_task', lambda *_: calls.append('post') or 'task-repaired')
    base = {'task_action': 'create', 'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'repair-preflight'}
    first = configured.execute(base)
    assert first.data['status'] == 'preflight_rejected'
    repaired = configured.execute({**base, **paid_inputs(tmp_path)})
    assert repaired.success
    assert repaired.data['attempt_id'] == first.data['attempt_id']
    assert calls == ['post']
    ledger = json.loads((tmp_path / 'paid-generation.json').read_text())['entries'][0]
    assert ledger['attempt_id'] == first.data['attempt_id']
    assert ledger['provider_task_id'] == 'task-repaired'
    assert ledger['status'] == 'reserved'


def test_preflight_reclaim_has_one_owner_and_respects_account_limit(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from lib.generation_attempts import GenerationAttempts, ConcurrencyLimitError
    journal = GenerationAttempts(tmp_path / 'attempts.json')
    first, _ = journal.claim('repair', 'fp', account='a')
    journal.mark_result(first['attempt_id'], 'preflight_rejected')
    active, _ = journal.claim('active', 'active-fp', account='a')
    with pytest.raises(ConcurrencyLimitError):
        journal.claim('repair', 'fp', account='a', account_limit=1)
    journal.mark_result(active['attempt_id'], 'succeeded')
    def reclaim(_):
        return GenerationAttempts(tmp_path / 'attempts.json').claim('repair', 'fp', account='a')[1]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(reclaim, range(16))).count(True) == 1


@pytest.mark.parametrize('status,task_id,post_started', [
    ('submission_result_unknown', None, False),
    ('preflight_rejected', 'remote-task', False),
    ('preflight_rejected', None, True),
    ('preflight_rejected', None, None),
])
def test_only_explicit_unsubmitted_preflight_records_are_reclaimable(tmp_path, status, task_id, post_started):
    from lib.generation_attempts import GenerationAttempts
    path = tmp_path / 'attempts.json'
    journal = GenerationAttempts(path)
    first, _ = journal.claim('unsafe', 'fp', account='a')
    raw = json.loads(path.read_text())
    raw['attempts'][0].update(status=status, task_id=task_id, post_started=post_started)
    path.write_text(json.dumps(raw))
    recovered, is_new = journal.claim('unsafe', 'fp', account='a')
    assert not is_new
    assert recovered['attempt_id'] == first['attempt_id']


def test_unknown_post_does_not_reclaim_or_release_original_reservation(configured, monkeypatch, tmp_path):
    calls = []
    def fail(*_):
        calls.append('post')
        raise requests.ReadTimeout('outcome unknown')
    monkeypatch.setattr(configured, '_create_task', fail)
    paid = paid_inputs(tmp_path)
    base = {'task_action': 'create', 'prompt': 'A towel', 'model_variant': '2.5', 'idempotency_key': 'unknown-no-reclaim', **paid}
    first = configured.execute(base)
    second = configured.execute(base)
    assert not first.success and not second.success
    assert calls == ['post']
    attempt = json.loads((tmp_path / 'tasks.json').read_text())['attempts'][0]
    assert attempt['post_started'] is True
    tracker = CostTracker(cost_log_path=Path(paid['cost_log_path']))
    with pytest.raises(ValueError, match='executed'):
        tracker.refund(paid['reservation_id'])
