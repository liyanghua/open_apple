"""Pure impact previews and short-lived confirmation tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from backlot.operator_adapters import get_adapter
from backlot.operator_errors import OperatorError
from lib.artifact_hashing import semantic_sha256
from lib.change_evaluation import evaluate_change_impact


_STAGE_LABELS = {
    "research": "参考解析与素材体检",
    "proposal": "创意方案",
    "script": "口播与字幕",
    "scene_plan": "分镜",
    "assets": "制作准备",
    "sample": "样片确认",
    "edit": "修改与精简",
    "delivery_review": "成片审核",
}
_RENDER_LABELS = {
    "no_render": "无需重新生成视频",
    "mux_only": "保留画面，仅更新声音",
    "full_render": "重新生成完整画面",
}


def _encoded(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decoded(value: str) -> dict[str, Any]:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))


def _draft_digest(draft: dict[str, Any]) -> str:
    return semantic_sha256({
        "draft_id": draft.get("draft_id"),
        "project_id": draft.get("project_id"),
        "stage": draft.get("stage"),
        "base_revision": draft.get("base_revision"),
        "base_artifact_hash": draft.get("base_artifact_hash"),
        "changes": draft.get("changes", []),
    })


def _display(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return f"{len(value)}项内容"
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"]
    return "已配置"


def _lookup(snapshot: dict[str, Any], field: str) -> Any:
    cursor: Any = snapshot
    for part in field.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
            continue
        if isinstance(cursor, list):
            found = next(
                (
                    item for item in cursor
                    if isinstance(item, dict)
                    and str(item.get("id", item.get("section_id", item.get("shot_id", item.get("segment_id"))))) == part
                ),
                None,
            )
            cursor = found
            continue
        return None
    return cursor


class ImpactService:
    def __init__(
        self,
        *,
        secret: bytes,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = 900,
    ) -> None:
        if len(secret) < 8:
            raise ValueError("Preview secret is too short")
        self.secret = secret
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.ttl_seconds = ttl_seconds

    def preview(
        self,
        *,
        draft: dict[str, Any],
        actor_id: str,
        base_generation: str,
        before: dict[str, Any],
        after: dict[str, Any],
        previous_lock: dict[str, Any] | None = None,
        current_lock: dict[str, Any] | None = None,
        previous_props: dict[str, Any] | None = None,
        current_props: dict[str, Any] | None = None,
        estimate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter = get_adapter(str(draft["stage"]))
        warnings = adapter.validate(after)
        signals = adapter.change_signals(draft.get("changes", []))
        impact = evaluate_change_impact(
            previous_lock or {}, current_lock or {}, previous_props or {}, current_props or {},
            adapter_signals=signals,
        )
        touched = sorted(adapter.touched_fields(draft.get("changes", [])))
        business_changes = adapter.diff(before, after)
        changed_fields = [
            {
                "field": field,
                "label": adapter.field_labels.get(
                    field.split(".", 1)[0],
                    next((label for label in business_changes if label), "内容已调整"),
                ),
                "before": _display(_lookup(before, field)),
                "after": _display(_lookup(after, field)),
            }
            for field in touched
        ]
        affected = [_STAGE_LABELS[str(draft["stage"])]]
        if impact["render_route"] != "no_render":
            affected.extend(["制作准备", "修改与精剪"])
        if impact["reopen_sample"]:
            affected.append("样片确认")
        affected = list(dict.fromkeys(affected))
        reviews = []
        if impact["reopen_creative"]:
            reviews.append("creative_lock")
        if impact["reopen_sample"]:
            reviews.append("sample")
        expires = self.clock() + timedelta(seconds=self.ttl_seconds)
        token = self._token(
            draft=draft,
            actor_id=actor_id,
            base_generation=base_generation,
            expires_at=expires,
        )
        evidence = estimate or {}
        summary = "；".join(business_changes) or "未检测到内容变化"
        return {
            "schema_version": "1.0",
            "draft_id": draft["draft_id"],
            "valid": True,
            "summary": summary,
            "changed_fields": changed_fields,
            "affected_stages": affected,
            "affected_scene_ids": impact["affected_scene_ids"],
            "render_mode": _RENDER_LABELS[impact["render_route"]],
            "reopen_reviews": reviews,
            "estimated_seconds": evidence.get("estimated_seconds"),
            "estimate_confidence": evidence.get("estimate_confidence"),
            "estimated_cost_usd": evidence.get("estimated_cost_usd"),
            "warnings": [str(item.get("message", item)) for item in warnings],
            "preview_token": token,
            "expires_at": expires.isoformat(),
        }

    def _token(
        self,
        *,
        draft: dict[str, Any],
        actor_id: str,
        base_generation: str,
        expires_at: datetime,
    ) -> str:
        payload = {
            "draft": _draft_digest(draft),
            "project": draft.get("project_id"),
            "actor": actor_id,
            "generation": base_generation,
            "expires": int(expires_at.timestamp()),
        }
        encoded = _encoded(payload)
        signature = hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def verify_token(
        self,
        token: str,
        *,
        draft: dict[str, Any],
        actor_id: str,
        base_generation: str,
    ) -> bool:
        try:
            encoded, supplied = token.rsplit(".", 1)
            expected = hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
            payload = _decoded(encoded)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            raise OperatorError("revision_conflict", "影响预览已失效，请重新预览", 409)
        valid = hmac.compare_digest(supplied, expected) and payload == {
            "draft": _draft_digest(draft),
            "project": draft.get("project_id"),
            "actor": actor_id,
            "generation": base_generation,
            "expires": payload.get("expires"),
        }
        if not valid or int(payload.get("expires", 0)) <= int(self.clock().timestamp()):
            raise OperatorError("revision_conflict", "影响预览已失效，请重新预览", 409)
        return True
