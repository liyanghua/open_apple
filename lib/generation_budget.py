"""Native money persistence behind CostTracker; no production orchestration.

The project identity and canonical path are not child-request parameters. Every
read/check/write uses the same process lock, including retries after a restart.
Decimal strings preserve catalog and invoice precision without inventing FX.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import uuid

from lib.cache_io import atomic_write_json
from lib.cost_persistence import ledger_lock


class NativeBudgetExceeded(ValueError):
    pass


def amount(value, *, positive=False):
    if isinstance(value, bool) or value is None:
        raise ValueError("native money requires a finite amount")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("native money requires a finite amount") from None
    if (not result.is_finite() or result < 0 or (positive and result == 0)
            or len(result.as_tuple().digits) > 80 or abs(result.as_tuple().exponent) > 80):
        raise ValueError("native money requires a finite nonnegative amount and known positive price")
    return result


def money_text(value):
    text = format(amount(value), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def currency(value):
    # Supported native currencies; unsupported prices fail closed, never imply FX.
    if value not in {"USD", "CNY", "EUR", "GBP", "JPY", "CAD", "AUD", "HKD", "SGD", "CHF", "INR", "KRW", "TWD"}:
        raise ValueError("unknown or unsupported native currency")
    return value


def text_identity(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} requires a nonempty identity")
    return value


class GenerationBudgetLedger:
    def __init__(self, project_dir, *, declared_path=None):
        self.project_dir = Path(project_dir).resolve()
        self.path = self.project_dir / "artifacts/budgets/generation.json"
        if declared_path is not None and Path(declared_path).resolve() != self.path:
            raise ValueError("native budget requires the canonical project ledger")
        # Reject a symlink that redirects even the canonical spelling elsewhere.
        if self.path.resolve() != self.path:
            raise ValueError("native budget requires the canonical project ledger")

    @contextmanager
    def transaction(self):
        with ledger_lock(self.path), localcontext() as context:
            context.prec = 256
            if self.path.exists():
                try:
                    data = json.loads(self.path.read_text())
                    self.validate(data)
                except (TypeError, KeyError, AttributeError, ValueError) as error:
                    raise ValueError(f"invalid native generation ledger: {error}") from error
            else:
                data = {"version": "2.0", "ledger_kind": "native_generation",
                        "project_dir": str(self.project_dir), "parent_budgets": [], "entries": []}
            yield data
            self.validate(data)
            atomic_write_json(self.path, data)

    def validate(self, data):
        if not isinstance(data, dict):
            raise ValueError("invalid native generation ledger object")
        if data.get("version") != "2.0" or data.get("ledger_kind") != "native_generation":
            raise ValueError("invalid native generation ledger kind/version")
        if data.get("project_dir") != str(self.project_dir):
            raise ValueError("native generation ledger project mismatch")
        if not isinstance(data.get("parent_budgets"), list) or not isinstance(data.get("entries"), list):
            raise ValueError("invalid native generation ledger collections")
        parents, lineages, requests, tasks = {}, set(), set(), set()
        for parent in data["parent_budgets"]:
            identity = self.parent_identity(parent)
            pid = identity["parent_budget_id"]
            lineage = (identity["shot_id"], identity["lineage_id"])
            if pid in parents or lineage in lineages:
                raise ValueError("duplicate parent or lineage in native ledger")
            parents[pid] = parent
            lineages.add(lineage)
        for entry in data["entries"]:
            parent = parents.get(entry["parent_budget_id"])
            if parent is None or any(entry[key] != parent[key] for key in ("currency", "shot_id", "lineage_id")):
                raise ValueError("native ledger parent identity mismatch")
            for key in ("id", "request_id", "tool", "operation", "timestamp"):
                text_identity(entry[key], key)
            if entry["id"] != self.entry_id(entry["request_id"]) or entry["request_id"] in requests:
                raise ValueError("native ledger request identity mismatch")
            requests.add(entry["request_id"])
            if entry["status"] not in {"estimated", "reserved", "completed", "failed", "refunded"}:
                raise ValueError("invalid native ledger entry status")
            amount(entry["estimated_amount"], positive=True)
            for key in ("reservation_amount", "reserved_amount", "commitment_amount"):
                amount(entry[key])
            if not isinstance(entry["paid_call_counted"], bool):
                raise ValueError("invalid native ledger paid call count")
            for key in ("actual_cost", "catalog_estimate"):
                if entry.get(key) is not None:
                    self.native_money(entry[key], entry["currency"])
            estimate = amount(entry["estimated_amount"])
            reservation = amount(entry["reservation_amount"])
            reserved = amount(entry["reserved_amount"])
            commitment = amount(entry["commitment_amount"])
            counted = entry["paid_call_counted"]
            state, actual = entry["status"], entry["actual_cost"]
            valid = isinstance(entry.get("revision_id"), str)
            if state == "estimated":
                valid &= not counted and reservation == reserved == commitment == 0 and actual is None
            elif state == "reserved":
                valid &= counted and reservation == reserved == estimate and commitment == 0 and actual is None
            elif state in {"completed", "failed"}:
                valid &= counted and reservation == estimate and reserved == 0
                valid &= commitment == (reservation if actual is None else 0)
            else:
                valid &= reserved == commitment == 0 and actual is not None and amount(actual["amount"]) == 0
                valid &= (counted and reservation == estimate) or (not counted and reservation == 0)
            if not valid:
                raise ValueError("native ledger reservation/call accounting is inconsistent")
            task = entry.get("provider_task_id")
            if task:
                if task in tasks:
                    raise ValueError("provider task belongs to another native reservation")
                tasks.add(task)
        for parent in parents.values():
            if sum(e["paid_call_counted"] for e in data["entries"]
                   if e["parent_budget_id"] == parent["parent_budget_id"]) > parent["max_paid_calls"]:
                raise ValueError("native ledger exceeds authorized cumulative call limit")

    @staticmethod
    def parent_identity(fields):
        result = {key: text_identity(fields[key], key) for key in
                  ("parent_budget_id", "authorization_ref", "shot_id", "lineage_id")}
        result.update(currency=currency(fields["currency"]), amount=money_text(amount(fields["amount"], positive=True)))
        calls = fields["max_paid_calls"]
        if isinstance(calls, bool) or not isinstance(calls, int) or calls <= 0:
            raise ValueError("parent budget requires a positive cumulative call limit")
        result["max_paid_calls"] = calls
        return result

    def entry_id(self, request_id):
        return "native_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{self.project_dir}:{request_id}").hex

    @staticmethod
    def find(data, entry_id):
        for entry in data["entries"]:
            if entry["id"] == entry_id:
                return entry
        raise KeyError(f"native cost entry {entry_id!r} not found")

    @staticmethod
    def parent(data, parent_budget_id):
        for parent in data["parent_budgets"]:
            if parent["parent_budget_id"] == parent_budget_id:
                return parent
        raise ValueError("native parent budget is not authorized")

    def create_parent(self, fields):
        identity = self.parent_identity(fields)
        with self.transaction() as data:
            for old in data["parent_budgets"]:
                if old["parent_budget_id"] == identity["parent_budget_id"]:
                    if self.parent_identity(old) != identity:
                        raise ValueError("parent budget identity cannot be changed")
                    return deepcopy(old)
                if (old["shot_id"], old["lineage_id"]) == (identity["shot_id"], identity["lineage_id"]):
                    raise ValueError("lineage already belongs to another parent budget")
            data["parent_budgets"].append(identity)
            return deepcopy(identity)

    def estimate(self, fields):
        identity = {key: text_identity(fields[key], key) for key in
                    ("tool", "operation", "parent_budget_id", "shot_id", "lineage_id", "request_id")}
        identity.update(currency=currency(fields["currency"]),
                        estimated_amount=money_text(amount(fields["estimated_amount"], positive=True)),
                        revision_id=fields.get("revision_id", ""))
        with self.transaction() as data:
            parent = self.parent(data, identity["parent_budget_id"])
            for key in ("currency", "shot_id", "lineage_id"):
                if identity[key] != parent[key]:
                    raise ValueError(f"native estimate {key} mismatches parent budget identity")
            eid = self.entry_id(identity["request_id"])
            for old in data["entries"]:
                if old["id"] == eid:
                    if any(old.get(key) != value for key, value in identity.items()):
                        raise ValueError("idempotent request identity cannot change")
                    return eid
            data["entries"].append({**identity, "id": eid, "status": "estimated", "reservation_amount": "0",
                                    "reserved_amount": "0", "commitment_amount": "0", "actual_cost": None,
                                    "catalog_estimate": None, "paid_call_counted": False,
                                    "provider_billing_status": "not_submitted", "timestamp": self.now()})
            return eid

    @staticmethod
    def summary(data, parent):
        entries = [e for e in data["entries"] if e["parent_budget_id"] == parent["parent_budget_id"]]
        reserved = sum((amount(e["reserved_amount"]) for e in entries), Decimal(0))
        commitment = sum((amount(e["commitment_amount"]) for e in entries), Decimal(0))
        known = sum((amount(e["actual_cost"]["amount"]) for e in entries if e["actual_cost"] is not None), Decimal(0))
        unknown = sum(e["status"] in {"completed", "failed"} and e["actual_cost"] is None for e in entries)
        remaining = amount(parent["amount"]) - reserved - commitment - known
        return {**deepcopy(parent), "reserved_amount": money_text(reserved), "commitment_amount": money_text(commitment),
                "known_actual_amount": money_text(known), "actual_amount": None if unknown else money_text(known),
                "remaining_amount": format(remaining, "f").rstrip("0").rstrip(".") if remaining != remaining.to_integral() else str(remaining.to_integral()),
                "unknown_settlement_count": unknown, "paid_calls": sum(e["paid_call_counted"] for e in entries)}

    def snapshot(self, parent_budget_id):
        with self.transaction() as data:
            return self.summary(data, self.parent(data, parent_budget_id))

    def reserve(self, entry_id):
        with self.transaction() as data:
            entry = self.find(data, entry_id)
            if entry["status"] == "reserved":
                return
            if entry["status"] != "estimated":
                raise ValueError("only an estimated native entry may be reserved")
            parent = self.parent(data, entry["parent_budget_id"])
            summary = self.summary(data, parent)
            if amount(entry["estimated_amount"]) > Decimal(summary["remaining_amount"]):
                raise NativeBudgetExceeded("native reservation exceeds parent budget amount")
            if summary["paid_calls"] >= parent["max_paid_calls"]:
                raise NativeBudgetExceeded("native reservation exceeds parent cumulative paid call limit")
            entry.update(status="reserved", reservation_amount=entry["estimated_amount"],
                         reserved_amount=entry["estimated_amount"], paid_call_counted=True, timestamp=self.now())

    def assert_reserved(self, entry_id, tool, operation, *, estimated_amount=None, currency=None, **identity):
        with self.transaction() as data:
            entry = self.find(data, entry_id)
            if entry["status"] != "reserved":
                raise ValueError("native cost reservation is not active")
            expected = {"tool": tool, "operation": operation, **{k: v for k, v in identity.items() if v is not None}}
            if currency is not None:
                expected["currency"] = currency
            if estimated_amount is not None:
                expected["estimated_amount"] = money_text(estimated_amount)
            if any(entry.get(key) != value for key, value in expected.items()):
                raise ValueError("native cost reservation identity, currency or amount mismatch")

    def bind(self, entry_id, *, tool, attempt_id, idempotency_key, task_id=None, operation=None,
             minimum_usd=None, minimum_cny=None):
        with self.transaction() as data:
            entry = self.find(data, entry_id)
            if entry["status"] != "reserved" or entry["tool"] != tool or (operation and entry["operation"] != operation):
                raise ValueError("submission requires an active matching native reservation")
            for code, minimum in (("USD", minimum_usd), ("CNY", minimum_cny)):
                if minimum is not None and (entry["currency"] != code or amount(minimum) > amount(entry["reserved_amount"])):
                    raise ValueError("native reservation currency/amount does not cover generation price")
            if entry.get("attempt_id") not in {None, attempt_id} or entry.get("idempotency_key") not in {None, idempotency_key}:
                raise ValueError("native reservation already bound to another submission identity")
            self.check_task(data, entry, task_id)
            entry.update(attempt_id=attempt_id, idempotency_key=idempotency_key,
                         submission_status="submitted" if task_id else "submitting", provider_billing_status="unconfirmed")
            if task_id:
                entry["provider_task_id"] = task_id
            entry["timestamp"] = self.now()

    @staticmethod
    def native_money(value, expected_currency):
        if value.get("currency") != expected_currency:
            raise ValueError("native settlement/estimate currency mismatch; no implicit FX")
        return {**deepcopy(value), "amount": money_text(value["amount"])}

    @staticmethod
    def check_task(data, entry, task_id):
        if task_id and (entry.get("provider_task_id") not in {None, task_id} or any(
                e["id"] != entry["id"] and e.get("provider_task_id") == task_id for e in data["entries"])):
            raise ValueError("provider task or reservation belongs to another native entry")

    def reconcile(self, entry_id, *, actual_usd=None, actual_cost=None, success=True, catalog_estimate=None,
                  usage=None, provider_status=None, provider_task_id=None, settlement_provenance=None):
        with self.transaction() as data:
            entry = self.find(data, entry_id)
            if entry["status"] not in {"reserved", "completed", "failed"}:
                raise ValueError("native reconciliation requires a reserved or executed request")
            if actual_usd is not None:
                usd = {"currency": "USD", "amount": money_text(actual_usd)}
                if actual_cost is not None and self.native_money(actual_cost, "USD") != usd:
                    raise ValueError("conflicting native settlement currencies")
                actual_cost = usd
            if actual_cost is not None:
                actual_cost = self.native_money(actual_cost, entry["currency"])
                if entry["actual_cost"] is not None and entry["actual_cost"] != actual_cost:
                    raise ValueError("native settlement already recorded with a different amount")
            if catalog_estimate is not None:
                catalog_estimate = self.native_money(catalog_estimate, entry["currency"])
            self.check_task(data, entry, provider_task_id)
            old_actual = entry["actual_cost"]
            entry.update(status="completed" if success else "failed", reserved_amount="0", timestamp=self.now())
            if actual_cost is not None:
                entry["actual_cost"] = actual_cost
            entry["commitment_amount"] = "0" if entry["actual_cost"] is not None else entry["reservation_amount"]
            entry["provider_billing_status"] = "settled" if entry["actual_cost"] is not None else "unconfirmed"
            for key, value in (("catalog_estimate", catalog_estimate), ("usage", usage), ("provider_status", provider_status),
                               ("provider_task_id", provider_task_id), ("settlement_provenance", settlement_provenance)):
                if value is not None and not (key == "settlement_provenance" and old_actual is not None and actual_cost is None):
                    entry[key] = value

    def creative_outcome(self, entry_id, accepted):
        with self.transaction() as data:
            entry = self.find(data, entry_id)
            if entry["status"] != "completed":
                raise ValueError("creative outcome requires provider success")
            entry["outcome"] = "creative_accepted" if accepted else "provider_success_then_creative_reject"

    def refund(self, entry_id):
        with self.transaction() as data:
            entry = self.find(data, entry_id)
            if entry["status"] == "refunded":
                return
            if entry["status"] in {"completed", "failed"} or entry.get("submission_status") or entry.get("provider_task_id"):
                raise ValueError("cannot refund an executed native task without billing evidence")
            entry.update(status="refunded", reserved_amount="0", commitment_amount="0",
                         actual_cost={"amount": "0", "currency": entry["currency"]},
                         outcome="preflight_rejected", provider_billing_status="not_submitted")

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()
