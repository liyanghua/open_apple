"""Public typing contract for transaction-aware project writers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ProjectWriteSink(Protocol):
    project_id: str
    generation_id: str

    def stage_json(self, relative_path: str, value: object, *, schema: str) -> None: ...

    def stage_bytes(
        self, relative_path: str, source_path: Path, *, media_type: str
    ) -> None: ...

    def stage_delete(self, relative_path: str) -> None: ...

    def append_event(self, stream: str, event: object) -> None: ...

