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
