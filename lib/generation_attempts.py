"""Persist submission identity and limits; no creative decisions or stage runner.

A submission with unknown outcome remains active until its remote task is found.
The local idempotency key prevents another POST; it is not a provider guarantee.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.cache_io import atomic_write_json
from lib.cost_persistence import ledger_lock


class ConcurrencyLimitError(ValueError):
    pass


class AttemptLimitError(ValueError):
    pass


class GenerationAttempts:
    TERMINAL = {'succeeded', 'failed', 'cancelled', 'expired', 'preflight_rejected'}

    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _transaction(self):
        with ledger_lock(self.path):
            data = json.loads(self.path.read_text()) if self.path.exists() else {'version': '1.0', 'attempts': []}
            yield data['attempts']
            atomic_write_json(self.path, data)

    @staticmethod
    def fingerprint(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def claim(self, key: str, request_fingerprint: str, *, account: str,
              account_limit: int = 2, concurrency_limit: int = 2,
              attempt_kind: str = 'initial', parent_attempt_id: str | None = None,
              metadata: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
        if not key or not request_fingerprint or not account:
            raise ValueError('key, fingerprint and account are required')
        if account_limit < 1 or concurrency_limit < 1:
            raise ValueError('concurrency limits must be positive')
        if attempt_kind not in {'initial', 'creative_retry', 'judge_format_repair'}:
            raise ValueError('unknown attempt_kind')
        with self._transaction() as attempts:
            for existing in attempts:
                if existing['idempotency_key'] == key and existing['account'] == account:
                    if existing['request_fingerprint'] != request_fingerprint:
                        raise ValueError('idempotency key fingerprint differs from the original submission')
                    if (existing['status'] == 'preflight_rejected'
                            and existing.get('post_started') is False
                            and not existing.get('task_id') and not existing.get('provider_task_id')):
                        if (existing['attempt_kind'] != attempt_kind
                                or existing.get('parent_attempt_id') != parent_attempt_id):
                            raise ValueError('preflight recovery cannot change attempt lineage')
                        active = sum(a['account'] == account and a['status'] not in self.TERMINAL for a in attempts)
                        if active >= min(account_limit, concurrency_limit):
                            raise ConcurrencyLimitError('account generation concurrency limit reached')
                        existing.setdefault('preflight_recovery_history', []).append({
                            'metadata': dict(existing.get('metadata') or {}),
                            'rejected_at': existing['updated_at'],
                        })
                        existing.update(status='submitting', metadata=dict(metadata or {}),
                                        updated_at=datetime.now(timezone.utc).isoformat())
                        return dict(existing), True
                    return dict(existing), False
            root_id = None
            if attempt_kind != 'initial':
                parent = self._find(attempts, parent_attempt_id)
                if parent['account'] != account or parent['status'] not in self.TERMINAL:
                    raise ValueError('retry parent must be a terminal attempt on this account')
                root_id = parent.get('root_attempt_id') or parent['attempt_id']
                limit = 2 if attempt_kind == 'creative_retry' else 1
                used = sum(a['attempt_kind'] == attempt_kind and a.get('root_attempt_id') == root_id for a in attempts)
                if used >= limit:
                    raise AttemptLimitError(f'{attempt_kind} limit reached; human review required')
            elif parent_attempt_id:
                raise ValueError('a parent requires an explicit retry attempt_kind')
            active = sum(a['account'] == account and a['status'] not in self.TERMINAL for a in attempts)
            if active >= min(account_limit, concurrency_limit):
                raise ConcurrencyLimitError('account generation concurrency limit reached')
            record = {'attempt_id': uuid.uuid4().hex, 'idempotency_key': key,
                      'request_fingerprint': request_fingerprint, 'account': account,
                      'attempt_kind': attempt_kind, 'parent_attempt_id': parent_attempt_id,
                      'root_attempt_id': root_id, 'task_id': None, 'status': 'submitting', 'post_started': False,
                      'updated_at': datetime.now(timezone.utc).isoformat(),
                      'metadata': metadata or {}}
            attempts.append(record)
            return dict(record), True

    def mark_submission_started(self, attempt_id: str):
        """Persist the uncertainty boundary before any paid POST can begin."""
        with self._transaction() as attempts:
            record = self._find(attempts, attempt_id)
            if record['status'] != 'submitting' or record.get('post_started') is not False or record.get('task_id'):
                raise ValueError('attempt is not an unsubmitted submission owner')
            record['post_started'] = True
            record['updated_at'] = datetime.now(timezone.utc).isoformat()

    def mark_submitted(self, attempt_id: str, task_id: str):
        with self._transaction() as attempts:
            record = self._find(attempts, attempt_id)
            if record['task_id'] not in {None, task_id}:
                raise ValueError('attempt already bound to a different task')
            record['task_id'] = task_id
            record['post_started'] = True
            if record['status'] not in self.TERMINAL:
                record['status'] = 'submitted'
            record['updated_at'] = datetime.now(timezone.utc).isoformat()

    def mark_result(self, attempt_id: str, status: str):
        with self._transaction() as attempts:
            record = self._find(attempts, attempt_id)
            if record['status'] in self.TERMINAL and record['status'] != status:
                return  # A stale query must not reopen a completed task.
            if status == 'preflight_rejected' and (record.get('post_started') is not False or record.get('task_id')):
                status = 'submitted_result_unknown' if record.get('task_id') else 'submission_result_unknown'
            record['status'] = status
            record['updated_at'] = datetime.now(timezone.utc).isoformat()

    def find_task(self, task_id: str, *, account: str) -> dict[str, Any] | None:
        with self._transaction() as attempts:
            return next((dict(a) for a in attempts if a['task_id'] == task_id and a['account'] == account), None)

    @staticmethod
    def _find(attempts, attempt_id):
        for record in attempts:
            if record['attempt_id'] == attempt_id:
                return record
        raise ValueError('parent/attempt ID does not exist')
