"""Stable, business-safe errors for Backlot operator APIs."""

from __future__ import annotations

import re
from typing import Any


ERROR_CODES = frozenset({
    "auth_required",
    "forbidden",
    "csrf_failed",
    "validation_failed",
    "revision_conflict",
    "review_stale",
    "review_already_decided",
    "job_running",
    "authorization_stale",
    "operator_transaction_required",
    "invalid_write_context",
    "recovery_required",
    "idempotency_conflict",
    # 未知阶段/版本（例如批级 rail 相位被当作可编辑阶段查询）
    "not_found",
    # 批级跨项目动作（契约 B）：批聚合 revision 或候选快照过期 / 协调记录待恢复
    "stale",
    "needs_recovery",
})

_UNSAFE_PUBLIC_TEXT = re.compile(
    r"(?:/Users/|/private/|\\Users\\|\.json\b|traceback|[A-Za-z]+(?:Error|Exception)\b)",
    re.IGNORECASE,
)


def _safe_public_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Public error text must be a non-empty string")
    if _UNSAFE_PUBLIC_TEXT.search(value):
        raise ValueError("Public error text contains diagnostic details")
    return value.strip()


class OperatorError(Exception):
    """An expected operator failure with a fixed public representation."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        field_errors: list[dict[str, str]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"Unknown operator error code: {code}")
        self.code = code
        self.message = _safe_public_text(message)
        self.status_code = int(status_code)
        self.details = details
        self.field_errors = []
        for item in field_errors or []:
            if set(item) != {"field", "message"}:
                raise ValueError("Field errors require only field and message")
            self.field_errors.append({
                "field": _safe_public_text(item["field"]),
                "message": _safe_public_text(item["message"]),
            })
        super().__init__(self.message)

    @classmethod
    def validation_failed(
        cls,
        message: str = "提交内容不符合要求",
        *,
        field_errors: list[dict[str, str]] | None = None,
    ) -> "OperatorError":
        return cls("validation_failed", message, 422, field_errors=field_errors)

    def to_public_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.field_errors:
            error["field_errors"] = list(self.field_errors)
        if self.details:
            for key, value in self.details.items():
                if key not in {"code", "message"}:
                    error[key] = value
        return {"error": error}
