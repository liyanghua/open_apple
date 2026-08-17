from __future__ import annotations

from tools.base_tool import BaseTool, ToolResult


class _CachedTool(BaseTool):
    name = "cached_test"

    def execute(self, inputs):
        return ToolResult(
            success=True,
            data={
                "cache_status": inputs["cache_status"],
                "cache_key": "abc",
                "reused_from": "shared" if inputs["cache_status"] == "hit" else None,
                "saved_seconds": 12.5 if inputs["cache_status"] == "hit" else 0.0,
            },
        )


def test_instrumentation_emits_cache_hit_and_miss_events(tmp_path, monkeypatch) -> None:
    projects = tmp_path / "projects"
    project = projects / "p"
    project.mkdir(parents=True)
    monkeypatch.setattr("lib.events.PROJECTS_DIR", projects)

    tool = _CachedTool()
    tool.execute({"project_dir": str(project), "cache_status": "hit"})
    tool.execute({"project_dir": str(project), "cache_status": "miss"})

    from lib.events import read_events

    cache_events = [e for e in read_events(project) if e.get("event", "").startswith("cache_")]
    assert [e["event"] for e in cache_events] == ["cache_hit", "cache_miss"]
    assert cache_events[0]["cost_usd"] == 0.0
    assert cache_events[0]["saved_seconds"] == 12.5
    expected_fields = {
        "event", "tool", "scene_id", "depth", "cache_key", "reused_from",
        "saved_seconds", "cost_usd", "ts",
    }
    assert expected_fields <= cache_events[0].keys()
    assert expected_fields <= cache_events[1].keys()
    assert cache_events[1]["cost_usd"] is None


def test_long_tool_call_emits_periodic_heartbeats(tmp_path, monkeypatch) -> None:
    """P1-⑤: a long synchronous tool call must not be silent between queued
    and its terminal event — the heartbeat worker emits every 5s."""
    import time as _time

    projects = tmp_path / "projects"
    project = projects / "p"
    project.mkdir(parents=True)
    monkeypatch.setattr("lib.events.PROJECTS_DIR", projects)

    class SlowTool(BaseTool):
        name = "slow_tool"

        def execute(self, inputs):
            _time.sleep(5.8)
            return ToolResult(success=True)

    SlowTool().execute({"project_dir": str(project)})

    from lib.events import read_events

    run_events = [e for e in read_events(project) if e.get("schema_version") == "1.0"]
    statuses = [e["status"] for e in run_events]
    assert statuses[0] == "queued"
    assert statuses[-1] == "succeeded"
    heartbeats = [e for e in run_events if e["status"] == "running"]
    assert heartbeats, "long tool call emitted no periodic heartbeat"
    assert all(e["machine_ms"] is not None for e in heartbeats)
    assert all(e["operation"] == "slow_tool" for e in heartbeats)


def test_tool_managed_progress_reuses_the_base_run_id(tmp_path, monkeypatch) -> None:
    projects = tmp_path / "projects"
    project = projects / "p"
    project.mkdir(parents=True)
    monkeypatch.setattr("lib.events.PROJECTS_DIR", projects)

    class ProgressTool(BaseTool):
        name = "progress_tool"
        internal_run_event_operations = frozenset({"render"})

        def execute(self, inputs):
            from lib.events import emit_run_event

            run_id = self.current_run_id()
            emit_run_event(
                inputs["project_dir"], run_id=run_id, stage="compose",
                operation="render", status="running",
            )
            return ToolResult(success=True)

    ProgressTool().execute({"project_dir": str(project), "operation": "render"})

    from lib.events import read_events

    run_events = [e for e in read_events(project) if e.get("schema_version") == "1.0"]
    assert len({e["run_id"] for e in run_events}) == 1
    assert [e["status"] for e in run_events] == ["queued", "running", "succeeded"]
