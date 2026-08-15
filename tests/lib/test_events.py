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

    cache_events = [e for e in read_events(project) if e["event"].startswith("cache_")]
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
