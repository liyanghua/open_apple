"""Public typing contract for transaction-aware project writers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from backlot.operator_errors import OperatorError


class ProjectWriteSink(Protocol):
    project_id: str
    generation_id: str

    def stage_json(self, relative_path: str, value: object, *, schema: str) -> None: ...

    def stage_bytes(
        self, relative_path: str, source_path: Path, *, media_type: str
    ) -> None: ...

    def stage_delete(self, relative_path: str) -> None: ...

    def append_event(self, stream: str, event: object) -> None: ...


def require_project_sink(
    project_dir: Path, sink: ProjectWriteSink | None
) -> ProjectWriteSink | None:
    """Enforce the operator-managed boundary and matching project identity."""
    project_dir = Path(project_dir)
    managed = (project_dir / "operator" / "operator-managed").exists()
    if managed and sink is None:
        raise OperatorError(
            "operator_transaction_required",
            "该项目的修改必须通过版本事务提交",
            409,
        )
    if sink is None:
        return None
    try:
        marker = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        marker = {}
    expected = marker.get("project_id", project_dir.name)
    if sink.project_id != expected or not sink.generation_id:
        raise OperatorError("invalid_write_context", "项目写入上下文不匹配", 409)
    return sink
