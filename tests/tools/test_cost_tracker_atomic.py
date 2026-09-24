from concurrent.futures import ProcessPoolExecutor
import json

import pytest

from lib.config_model import BudgetMode
from tools.cost_tracker import CostTracker, BudgetExceededError


def tracker(path, **kwargs):
    return CostTracker(cost_log_path=path, budget_total_usd=1, reserve_pct=0,
                       single_action_approval_usd=10, require_approval_for_new_paid_tool=False,
                       mode=BudgetMode.CAP, **kwargs)


def reserve_process(path):
    from pathlib import Path
    t = tracker(Path(path))
    eid = t.estimate('ark', 'generate', .6)
    try:
        t.reserve(eid)
        return True
    except BudgetExceededError:
        return False


def test_stale_instances_do_not_lose_entries_or_overspend(tmp_path):
    path = tmp_path / 'cost.json'
    a, b = tracker(path), tracker(path)
    one = a.estimate('ark', 'one', .6)
    two = b.estimate('ark', 'two', .6)
    a.reserve(one)
    with pytest.raises(BudgetExceededError):
        b.reserve(two)
    assert len(json.loads(path.read_text())['entries']) == 2


def test_multiprocess_reservation_is_atomic(tmp_path):
    path = tmp_path / 'cost.json'
    with ProcessPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(reserve_process, [str(path)] * 8))
    assert outcomes.count(True) == 1
    data = json.loads(path.read_text())
    assert len(data['entries']) == 8
    assert data['budget_reserved_usd'] == .6


def test_usage_estimate_is_not_settlement_and_preserves_budget_commitment(tmp_path):
    t = tracker(tmp_path / 'cost.json')
    eid = t.estimate('ark', 'one', .84)
    t.reserve(eid)
    t.reconcile(eid, actual_usd=None, usage={'completion_tokens': 87300},
                catalog_estimate={'amount': 6.111, 'currency': 'CNY', 'price_date': '2026-09-24'},
                provider_status='succeeded', provider_task_id='task-1',
                settlement_provenance={'source': 'provider_usage', 'billing_status': 'unconfirmed'})
    e = t.entries[0]
    assert e['actual_usd'] is None
    assert e['actual_cost'] is None
    assert e['reserved_usd'] == 0
    assert e['budget_commitment_usd'] == .84
    assert t.budget_remaining_usd == pytest.approx(.16)
    assert t.cost_snapshot()['actual_spend_by_currency']['CNY'] is None
    t.record_creative_outcome(eid, accepted=False)
    assert t.entries[0]['outcome'] == 'provider_success_then_creative_reject'
    assert t.entries[0]['budget_commitment_usd'] == .84
    with pytest.raises(ValueError, match='executed'):
        t.refund(eid)


def test_reconcile_refund_idempotency_and_explicit_zero(tmp_path):
    t = tracker(tmp_path / 'cost.json')
    eid = t.estimate('ark', 'one', .6)
    t.reserve(eid)
    t.reserve(eid)
    t.reconcile(eid, None)
    t.reconcile(eid, None)
    t.reconcile(eid, 0, settlement_provenance={'source': 'billing_statement', 'reference': 'invoice-0'})
    t.reconcile(eid, 0)
    assert t.entries[0]['actual_usd'] == 0
    assert t.budget_remaining_usd == 1
    with pytest.raises(ValueError):
        t.reconcile(eid, .5)
    other = t.estimate('ark', 'preflight', .1)
    t.refund(other)
    t.refund(other)
    assert t.entries[1]['outcome'] == 'preflight_rejected'


def test_cny_bill_does_not_become_usd(tmp_path):
    t = tracker(tmp_path / 'cost.json')
    eid = t.estimate('ark', 'one', .6)
    t.reserve(eid)
    t.reconcile(eid, None, actual_cost={'amount': 4, 'currency': 'CNY'},
                settlement_provenance={'source': 'billing_statement'})
    assert t.entries[0]['actual_usd'] is None
    assert t.budget_remaining_usd == pytest.approx(.4)
    assert t.cost_snapshot()['actual_spend_by_currency']['CNY'] == 4


def test_usage_requery_does_not_overwrite_invoice_provenance(tmp_path):
    t = tracker(tmp_path / 'cost.json')
    eid = t.estimate('ark', 'one', .6)
    t.reserve(eid)
    provenance = {'source': 'billing_statement', 'reference': 'invoice-1'}
    t.reconcile(eid, .4, settlement_provenance=provenance)
    t.reconcile(eid, None, usage={'completion_tokens': 87300},
                settlement_provenance={'source': 'provider_usage', 'billing_status': 'unconfirmed'})
    assert t.entries[0]['settlement_provenance'] == provenance
    assert t.entries[0]['actual_usd'] == .4


def test_cost_schema_accepts_unknown_settlement_and_reuse(tmp_path):
    from pathlib import Path
    import jsonschema
    path = tmp_path / 'cost.json'
    t = tracker(path)
    eid = t.estimate('ark', 'shot', .6)
    t.reserve(eid)
    t.bind_submission(eid, tool='ark', attempt_id='attempt-1', idempotency_key='shot-1', task_id='task-1')
    t.reconcile(eid, None, usage={'completion_tokens': 87300},
                catalog_estimate={'amount': 6.111, 'currency': 'CNY', 'price_date': '2026-09-24'},
                provider_status='succeeded', provider_task_id='task-1',
                settlement_provenance={'source': 'provider_usage', 'billing_status': 'unconfirmed'})
    t.record_creative_outcome(eid, accepted=False)
    t.record_reuse('ark', 'cache', 'original', 5)
    schema = json.loads((Path(__file__).parents[2] / 'schemas/artifacts/cost_log.schema.json').read_text())
    jsonschema.validate(json.loads(path.read_text()), schema)


def test_restarted_tracker_keeps_budget_cap_policy(tmp_path):
    path = tmp_path / 'cost.json'
    original = tracker(path)
    first = original.estimate('ark', 'one', .6)
    original.reserve(first)
    restarted = CostTracker(cost_log_path=path)
    second = restarted.estimate('ark', 'two', .6)
    with pytest.raises(BudgetExceededError):
        restarted.reserve(second)


def test_unknown_cny_charge_makes_cny_total_unknown(tmp_path):
    t = tracker(tmp_path / 'cost.json')
    known = t.estimate('ark', 'known', .4)
    t.reconcile(known, None, actual_cost={'amount': 10, 'currency': 'CNY'})
    unknown = t.estimate('ark', 'unknown', .4)
    t.reconcile(unknown, None, catalog_estimate={'amount': 6.111, 'currency': 'CNY'})
    summary = t.cost_snapshot()
    assert summary['actual_spend_by_currency']['CNY'] is None
    assert summary['known_actual_spend_by_currency']['CNY'] == 10
    assert 'USD' not in summary['actual_spend_by_currency']


def test_provider_task_cannot_reconcile_two_reservations(tmp_path):
    t = tracker(tmp_path / 'cost.json')
    first = t.estimate('ark', 'first', .4)
    second = t.estimate('ark', 'second', .4)
    t.reconcile(first, None, provider_task_id='task-1')
    with pytest.raises(ValueError, match='different'):
        t.reconcile(second, None, provider_task_id='task-1')
