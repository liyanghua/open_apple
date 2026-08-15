from __future__ import annotations

import asyncio
import json

from backlot import server as server_mod


def _payload(event: str) -> dict:
    assert event.startswith("data: ")
    return json.loads(event.removeprefix("data: ").strip())


def test_operator_state_endpoint_returns_versioned_chinese_projection(
    client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")

    response = client.get("/api/v2/projects/film/operator-state")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["summary"]["current_stage"] == "口播与字幕"
    assert body["legacy"]["read_only"] is True


def test_operator_state_endpoint_reuses_project_containment(
    client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")

    assert client.get("/api/v2/projects/nope/operator-state").status_code == 404
    assert client.get("/api/v2/projects/C:/operator-state").status_code == 400


def test_v2_project_events_emit_business_hello_and_change() -> None:
    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    async def consume() -> tuple[dict, dict]:
        stream = server_mod._project_event_stream(
            "film",
            ConnectedRequest(),
            business_facing=True,
        )
        hello = _payload(await anext(stream))
        server_mod.hub.publish("film")
        change = _payload(await anext(stream))
        await stream.aclose()
        return hello, change

    hello, change = asyncio.run(consume())

    assert hello == {
        "type": "hello",
        "project_id": "film",
        "message": "已连接项目进度",
    }
    assert change == {
        "type": "change",
        "project_id": "film",
        "message": "项目进度已更新",
    }


def test_legacy_project_events_keep_existing_payload() -> None:
    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    async def consume() -> tuple[dict, dict]:
        stream = server_mod._project_event_stream(
            "film",
            ConnectedRequest(),
            business_facing=False,
        )
        hello = _payload(await anext(stream))
        server_mod.hub.publish("film")
        change = _payload(await anext(stream))
        await stream.aclose()
        return hello, change

    hello, change = asyncio.run(consume())

    assert hello == {"type": "hello", "project_id": "film"}
    assert change == {"type": "change", "project_id": "film"}


def test_v2_events_route_exists_and_rejects_unknown_project(
    client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")
    paths = {route.path for route in client.app.routes}

    assert "/api/v2/projects/{project_id}/events" in paths
    assert client.get("/api/v2/projects/nope/events").status_code == 404
    assert client.get("/api/v2/projects/C:/events").status_code == 400


def test_diagnostics_route_preserves_the_engineering_board(
    client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")

    response = client.get("/diagnostics/p/film")

    assert response.status_code == 200
    assert 'src="/ui/board.js' in response.text
    assert response.headers["cache-control"] == "no-cache"

    project_response = client.get("/p/film")
    assert project_response.status_code == 200
    assert 'src="/ui/board.js' in project_response.text
