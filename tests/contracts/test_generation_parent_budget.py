"""Native generation authorization is one project ledger across revisions/tools."""
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal
import json
from pathlib import Path

import pytest

from tools.cost_tracker import BudgetExceededError, CostTracker


def tracker(project):
    return CostTracker(project_dir=Path(project))


def parent(t, amount="8", calls=3, **kwargs):
    return t.create_parent_budget("approved", currency="CNY", amount=amount,
                                 max_paid_calls=calls, authorization_ref="approval-1",
                                 shot_id="shot-1", lineage_id="lineage-1", **kwargs)


def estimate(t, request, amount="8", **kwargs):
    fields = dict(currency="CNY", parent_budget_id="approved", shot_id="shot-1",
                  lineage_id="lineage-1", request_id=request, revision_id="r1")
    fields.update(kwargs)
    return t.estimate_native(fields.pop("tool", "seedance_ark"), "generate", amount, **fields)


def reserve_process(args):
    project, request, amount = args
    t = tracker(project)
    eid = estimate(t, request, amount, tool=f"tool-{request}", revision_id=request)
    try:
        t.reserve(eid)
        return True
    except BudgetExceededError:
        return False


@pytest.mark.parametrize("amount,calls,request_amount", [("8", 3, "5"), ("100", 1, "1")])
def test_processes_share_last_amount_and_call_across_revisions(tmp_path, amount, calls, request_amount):
    parent(tracker(tmp_path), amount, calls)
    with ProcessPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve_process, [(str(tmp_path), str(i), request_amount) for i in range(2)]))
    assert outcomes.count(True) == 1
    snapshot = tracker(tmp_path).snapshot_parent_budget("approved")
    assert snapshot["paid_calls"] == 1
    assert Decimal(snapshot["reserved_amount"]) == Decimal(request_amount)


def test_restart_is_idempotent_and_changed_request_identity_rejected(tmp_path):
    t = tracker(tmp_path)
    parent(t)
    eid = estimate(t, "request-1")
    t.reserve(eid)
    restarted = tracker(tmp_path)
    assert estimate(restarted, "request-1") == eid
    restarted.reserve(eid)
    assert restarted.snapshot_parent_budget("approved")["paid_calls"] == 1
    with pytest.raises(ValueError, match="identity"):
        estimate(restarted, "request-1", revision_id="r2")
    restarted.assert_reserved(eid, "seedance_ark", "generate", estimated_amount="8", currency="CNY",
                              parent_budget_id="approved", shot_id="shot-1", lineage_id="lineage-1")
    with pytest.raises(ValueError):
        restarted.assert_reserved(eid, "seedance_ark", "generate", estimated_amount="8", currency="USD")


def test_unknown_actual_retains_original_commitment_after_creative_rejection(tmp_path):
    t = tracker(tmp_path)
    parent(t)
    eid = estimate(t, "request-1")
    t.reserve(eid)
    t.bind_submission(eid, tool="seedance_ark", attempt_id="attempt-1", idempotency_key="request-1",
                      task_id="task-1", operation="generate", minimum_cny=7)
    t.reconcile(eid, actual_cost=None, catalog_estimate={"currency": "CNY", "amount": "7.2954"},
                provider_status="succeeded", provider_task_id="task-1")
    t.record_creative_outcome(eid, accepted=False)
    snapshot = tracker(tmp_path).snapshot_parent_budget("approved")
    assert snapshot["reserved_amount"] == "0"
    assert snapshot["commitment_amount"] == "8"
    assert snapshot["known_actual_amount"] == "0"
    assert snapshot["actual_amount"] is None
    assert snapshot["unknown_settlement_count"] == 1
    assert snapshot["paid_calls"] == 1
    with pytest.raises(ValueError, match="executed"):
        t.refund(eid)
    other = estimate(t, "request-2", "0.01")
    with pytest.raises(BudgetExceededError):
        t.reserve(other)
    t.reconcile(eid, actual_cost={"amount": "7.2954", "currency": "CNY"},
                settlement_provenance={"source": "billing_statement", "reference": "bill-1"})
    t.reserve(other)
    assert tracker(tmp_path).snapshot_parent_budget("approved")["remaining_amount"] == "0.6946"


def test_decimal_boundary_and_currency_mismatch_never_use_fx(tmp_path):
    t = tracker(tmp_path)
    parent(t, "0.3", 3)
    for request, amount in [("a", "0.1"), ("b", "0.2")]:
        t.reserve(estimate(t, request, amount))
    assert t.snapshot_parent_budget("approved")["remaining_amount"] == "0"
    with pytest.raises(ValueError, match="currency"):
        estimate(t, "usd", "0.001", currency="USD")
    eid = estimate(t, "tiny", "0.00000000000000000000000000001")
    with pytest.raises(BudgetExceededError):
        t.reserve(eid)
    with pytest.raises(ValueError, match="currency"):
        t.reconcile(estimate(t, "a", "0.1"), actual_cost={"amount": "0.1", "currency": "USD"})


def test_parent_identity_and_canonical_path_are_immutable(tmp_path):
    t = tracker(tmp_path)
    parent(t)
    parent(t)
    with pytest.raises(ValueError, match="identity"):
        parent(t, "9")
    with pytest.raises(ValueError, match="identity"):
        t.create_parent_budget("approved", currency="CNY", amount="8", max_paid_calls=3,
                               authorization_ref="other-approval", shot_id="shot-1", lineage_id="lineage-1")
    with pytest.raises(ValueError, match="canonical"):
        CostTracker(project_dir=tmp_path, cost_log_path=tmp_path / "alternate.json").create_parent_budget(
            "other", currency="CNY", amount="8", max_paid_calls=3, authorization_ref="other",
            shot_id="shot-1", lineage_id="lineage-1")
    with pytest.raises(ValueError, match="lineage"):
        t.create_parent_budget("other", currency="CNY", amount="8", max_paid_calls=3,
                               authorization_ref="other", shot_id="shot-1", lineage_id="lineage-1")


def test_native_schema_and_separate_estimate_reservation_actual_evidence(tmp_path):
    import jsonschema
    t = tracker(tmp_path)
    parent(t)
    eid = estimate(t, "a")
    t.reserve(eid)
    t.reconcile(eid, actual_cost={"amount": "6.2", "currency": "CNY"},
                catalog_estimate={"amount": "7.2954", "currency": "CNY", "price_date": "2026-09-24"},
                settlement_provenance={"source": "billing_statement", "reference": "bill-1"})
    data = json.loads((tmp_path / "artifacts/budgets/generation.json").read_text())
    entry = data["entries"][0]
    assert entry["estimated_amount"] == "8"
    assert entry["reservation_amount"] == "8"
    assert entry["catalog_estimate"]["amount"] == "7.2954"
    assert entry["actual_cost"]["amount"] == "6.2"
    schema = json.loads((Path(__file__).parents[2] / "schemas/artifacts/cost_log.schema.json").read_text())
    jsonschema.validate(data, schema)


def test_malformed_or_wrong_project_ledger_fails_closed(tmp_path):
    path = tmp_path / "artifacts/budgets/generation.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"version":"1.1","entries":[]}')
    with pytest.raises(ValueError, match="ledger"):
        parent(tracker(tmp_path))
    path.unlink()
    parent(tracker(tmp_path))
    data = json.loads(path.read_text())
    data["project_dir"] = str(tmp_path / "another")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="project"):
        tracker(tmp_path).snapshot_parent_budget("approved")


@pytest.mark.parametrize("amount", [None, "NaN", "Infinity", "-1", True, "0"])
def test_unknown_or_invalid_price_never_reserves(tmp_path, amount):
    t = tracker(tmp_path)
    parent(t)
    with pytest.raises(ValueError):
        estimate(t, "a", amount)


def test_canonical_path_constructor_recovers_unknown_submission_without_new_call(tmp_path):
    t = tracker(tmp_path)
    parent(t)
    eid = estimate(t, "a")
    t.reserve(eid)
    t.bind_submission(eid, tool="seedance_ark", attempt_id="attempt-a", idempotency_key="a", minimum_cny="8")
    recovered = CostTracker(cost_log_path=tmp_path / "artifacts/budgets/generation.json")
    recovered.reserve(eid)
    assert recovered.get_native_entry(eid)["submission_status"] == "submitting"
    assert recovered.snapshot_parent_budget("approved")["paid_calls"] == 1
    with pytest.raises(ValueError, match="executed"):
        recovered.refund(eid)


def test_refund_does_not_reset_cumulative_count_and_explicit_zero_settles(tmp_path):
    t = tracker(tmp_path)
    parent(t, "8", 2)
    unsubmitted = estimate(t, "unsubmitted")
    t.reserve(unsubmitted)
    t.refund(unsubmitted)
    eid = estimate(t, "submitted")
    t.reserve(eid)
    t.reconcile(eid, actual_cost={"amount": "0", "currency": "CNY"},
                settlement_provenance={"source": "billing_statement", "reference": "no-charge"})
    snapshot = t.snapshot_parent_budget("approved")
    assert snapshot["actual_amount"] == "0"
    assert snapshot["unknown_settlement_count"] == 0
    assert snapshot["remaining_amount"] == "8"
    assert snapshot["paid_calls"] == 2
    with pytest.raises(BudgetExceededError, match="call"):
        t.reserve(estimate(t, "third", "0.1"))


def test_corrupt_reserved_amount_or_call_count_is_not_trusted(tmp_path):
    t = tracker(tmp_path)
    parent(t)
    eid = estimate(t, "a")
    t.reserve(eid)
    path = tmp_path / "artifacts/budgets/generation.json"
    data = json.loads(path.read_text())
    data["entries"][0]["reserved_amount"] = "0"
    data["entries"][0]["paid_call_counted"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="ledger"):
        t.reserve(estimate(t, "b", "8"))


def test_settlement_requery_is_idempotent_and_keeps_invoice_evidence(tmp_path):
    t = tracker(tmp_path)
    parent(t)
    eid = estimate(t, "a")
    t.reserve(eid)
    bill = {"source": "billing_statement", "reference": "bill-a"}
    t.reconcile(eid, actual_cost={"amount": "7", "currency": "CNY"}, settlement_provenance=bill)
    t.reconcile(eid, usage={"completion_tokens": 123},
                settlement_provenance={"source": "usage_requery"})
    assert t.get_native_entry(eid)["settlement_provenance"] == bill
    assert t.snapshot_parent_budget("approved")["known_actual_amount"] == "7"
    with pytest.raises(ValueError, match="different amount"):
        t.reconcile(eid, actual_cost={"amount": "6", "currency": "CNY"})
