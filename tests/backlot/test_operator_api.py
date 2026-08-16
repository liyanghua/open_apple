from __future__ import annotations

import asyncio
import json

from backlot import server as server_mod


def _payload(event: str) -> dict:
    assert event.startswith("data: ")
    return json.loads(event.removeprefix("data: ").strip())


async def _consume_http_sse(app, path: str, project_id: str) -> list[dict]:
    events: list[dict] = []
    response_status: int | None = None
    disconnected = asyncio.Event()
    request_sent = False

    async def receive() -> dict:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        nonlocal response_status
        if message["type"] == "http.response.start":
            response_status = message["status"]
            return
        if message["type"] != "http.response.body" or not message.get("body"):
            return
        for raw_event in message["body"].decode().split("\n\n"):
            if not raw_event:
                continue
            events.append(_payload(f"{raw_event}\n\n"))
            if len(events) == 1:
                server_mod.hub.publish(project_id)
            elif len(events) == 2:
                disconnected.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=2)
    assert response_status == 200
    assert len(events) == 2
    return events


def test_operator_state_endpoint_returns_versioned_chinese_projection(
    backlot_client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")

    response = backlot_client.get("/api/v2/projects/film/operator-state")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["summary"]["current_stage"] == "口播与字幕"
    assert body["legacy"]["read_only"] is True


def test_operator_state_endpoint_reuses_project_containment(
    backlot_client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")

    assert backlot_client.get("/api/v2/projects/nope/operator-state").status_code == 404
    assert backlot_client.get("/api/v2/projects/C:/operator-state").status_code == 400


def test_v2_project_events_emit_business_hello_and_change(
    backlot_client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")

    hello, change = asyncio.run(
        _consume_http_sse(
            backlot_client.app,
            "/api/v2/projects/film/events",
            "film",
        )
    )

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


def test_legacy_project_events_keep_existing_payload(
    backlot_client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")

    hello, change = asyncio.run(
        _consume_http_sse(
            backlot_client.app,
            "/api/project/film/events",
            "film",
        )
    )

    assert hello == {"type": "hello", "project_id": "film"}
    assert change == {"type": "change", "project_id": "film"}


def test_v2_events_route_exists_and_rejects_unknown_project(
    backlot_client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")
    paths = {route.path for route in backlot_client.app.routes}

    assert "/api/v2/projects/{project_id}/events" in paths
    assert backlot_client.get("/api/v2/projects/nope/events").status_code == 404
    assert backlot_client.get("/api/v2/projects/C:/events").status_code == 400


def test_diagnostics_route_preserves_the_engineering_board(
    backlot_client, projects_root, make_project
) -> None:
    make_project(projects_root, "film")

    response = backlot_client.get("/diagnostics/p/film")

    assert response.status_code == 200
    assert 'src="/ui/board.js' in response.text
    assert response.headers["cache-control"] == "no-cache"

    project_response = backlot_client.get("/p/film")
    assert project_response.status_code == 200
    assert 'lang="zh-CN"' in project_response.text
    assert 'src="/ui/operator/app.js' in project_response.text

    paths = {route.path for route in backlot_client.app.routes}
    assert "/diagnostics/p/{project_path:path}" not in paths
