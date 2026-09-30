"""Result imports use the real authenticated workbench and strict state schema."""
import json

import pytest

from fastapi.testclient import TestClient

from tests.backlot.test_opening_reviews import preview_project
from tests.lib.test_opening_results import result_payload


def _cards(state):
    return next(stage for stage in state["stages"] if stage["id"] == "compose")["editor"]["data"]["production_reviews"]


def test_state_route_shows_pending_imported_and_stale_history(projects_root, backlot_client):
    from backlot.operator_state import load_operator_state
    project = projects_root / "film"
    preview_project(project)
    initial = backlot_client.get("/api/v2/projects/film/operator-state")
    assert initial.status_code == 200, initial.text
    assert _cards(initial.json())[0]["opening_results"] == []
    payload = result_payload(project)
    saved = backlot_client.post("/api/v2/projects/film/opening-results", json=payload)
    assert saved.status_code == 200, saved.text
    state = load_operator_state(project, permissions=("view", "review"))
    assert _cards(state)[0]["opening_results"][0]["metrics"][0]["value"] == .45
    response = backlot_client.get("/api/v2/projects/film/operator-state")
    assert response.status_code == 200, response.text
    assert _cards(response.json())[0]["opening_results"][0]["conclusion"] == "已导入，尚无结论"
    (project / "final.mp4").write_bytes(b"changed")
    stale = backlot_client.get("/api/v2/projects/film/operator-state")
    assert stale.status_code == 200, stale.text
    assert _cards(stale.json())[0]["opening_results"][0]["binding_status"] == "stale"


def test_result_import_requires_project_access_and_csrf(tmp_path, monkeypatch):
    from backlot import server as server_mod
    from backlot.auth_store import AuthStore
    projects = tmp_path / "projects"; projects.mkdir()
    project = projects / "film"
    preview_project(project)
    payload = result_payload(project)
    auth = AuthStore(tmp_path / "backlot.db"); auth.initialize()
    owner = auth.create_user("owner", "a sufficiently long password", "operator")
    auth.create_user("outsider", "a sufficiently long password", "operator")
    auth.set_project_role("film", owner.user_id, "owner")
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    async def no_watch(): return None
    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app(auth_store=auth)) as client:
        url = "/api/v2/projects/film/opening-results"
        assert client.post(url, json=payload).status_code == 401
        client.post("/api/v2/auth/login", json={"schema_version":"1.0", "username":"outsider", "password":"a sufficiently long password"}, headers={"Origin":"http://testserver"})
        assert client.post(url, json=payload, headers={"Origin":"http://testserver"}).status_code == 403
        csrf = client.get("/api/v2/auth/me").json()["csrf_token"]
        client.post("/api/v2/auth/logout", headers={"Origin":"http://testserver", "X-CSRF-Token":csrf})
        client.post("/api/v2/auth/login", json={"schema_version":"1.0", "username":"owner", "password":"a sufficiently long password"}, headers={"Origin":"http://testserver"})
        assert client.post(url, json=payload, headers={"Origin":"http://testserver"}).status_code == 403
        csrf = client.get("/api/v2/auth/me").json()["csrf_token"]
        good = client.post(url, json=payload, headers={"Origin":"http://testserver", "X-CSRF-Token":csrf})
        assert good.status_code == 200, good.text
        assert good.json()["status"] == "imported"
        assert client.post(url, json=payload, headers={"Origin":"http://testserver", "X-CSRF-Token":csrf}).json()["status"] == "replayed"


def test_import_never_changes_existing_review_history(tmp_path):
    from backlot.operator_reviews import ReviewService
    from backlot.production_review_items import production_review_items
    from tests.backlot.test_final_production_reviews import approve
    _, index = preview_project(tmp_path)
    service = ReviewService(tmp_path)
    review = service.create_production_review(record_path="record.json", submitted_by="pipeline")
    approve(service, review)
    before = production_review_items(tmp_path, index, [])[0]
    from lib.opening_results import import_result
    import_result(tmp_path, result_payload(tmp_path), actor_id="tester")
    after = production_review_items(tmp_path, index, [])[0]
    assert after["review_history"] == before["review_history"]
    assert after["review_status"] == before["review_status"]


def test_same_candidate_labels_in_other_group_cannot_borrow_baseline(tmp_path):
    from lib.opening_results import import_result
    from backlot.production_review_items import production_review_items
    from tests.lib.test_opening_freeze import scoped_registered_group, publish_group_in_shared_project
    (tmp_path / "project.json").write_text(json.dumps({"project_id":"synthetic-groups"}))
    entries = []
    for group in ("A01", "A03"):
        publish_group_in_shared_project(tmp_path, group, scoped_registered_group(tmp_path, group))
        for name in ("record.json", "H01_record.json"):
            record_path = f"{group}/{name}"
            record = json.loads((tmp_path / record_path).read_text())
            entries.append({"id":record["content_slot_id"], "record_path":record_path, "title":record["content_slot_id"]})
    index = {"items":entries}
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    (tmp_path / "artifacts/production_review_index.json").write_text(json.dumps(index))
    import_result(tmp_path, result_payload(tmp_path, "A01/record.json", import_id="a01-baseline"), actor_id="tester")
    import_result(tmp_path, result_payload(tmp_path, "A01/H01_record.json", import_id="a01-variant"), actor_id="tester")
    import_result(tmp_path, result_payload(tmp_path, "A03/H01_record.json", import_id="a03-variant"), actor_id="tester")
    cards = {card["id"]:card for card in production_review_items(tmp_path, index, [])}
    a01 = cards["A01-H1"]["opening_results"][0]
    a03 = cards["A03-H1"]["opening_results"][0]
    assert "缺少同源基线实测" not in a01["comparison_reasons"]
    assert "缺少同源基线实测" in a03["comparison_reasons"]
    assert a01["conclusion"] == a03["conclusion"] == "已导入，尚无结论"


@pytest.mark.parametrize("changed,group_invalid", [
    ("experiment", True), ("hook", True), ("record", True), ("render", False), ("raw", False),
])
def test_stale_result_history_survives_binding_failure_in_strict_state(
    projects_root, backlot_client, changed, group_invalid
):
    from lib.opening_results import import_result
    from backlot.operator_state import load_operator_state
    project = projects_root / "film"
    preview_project(project)
    import_result(project, result_payload(project), actor_id="tester")
    if changed == "record":
        path = project / "record.json"
        record = json.loads(path.read_text())
        record["opening"]["candidate_id"] = "unregistered"
        path.write_text(json.dumps(record))
    else:
        path = project / {"experiment":"experiment.json", "hook":"hook.json", "render":"final.mp4",
                          "raw":"assets/synthetic-metrics.csv"}[changed]
        path.write_bytes(path.read_bytes() + b"changed")
    state = load_operator_state(project, permissions=("view", "review"))
    card = _cards(state)[0]
    response = backlot_client.get("/api/v2/projects/film/operator-state")
    assert response.status_code == 200, response.text
    http_card = _cards(response.json())[0]
    for row in (card, http_card):
        assert row["opening_results"][0]["binding_status"] == "stale"
        assert row["opening_results"][0]["comparison_status"] == "不可比"
        assert row["opening_results"][0]["metrics"][0]["value"] == .45
        assert row["review"] is None
        assert bool(row["scope_error"]) == group_invalid
        assert (row["opening_group"] is None) == group_invalid


def test_unknown_film_durations_cannot_be_treated_as_equal(tmp_path):
    from lib.opening_results import import_result
    from backlot.production_review_items import production_review_items
    from tests.lib.test_opening_freeze import scoped_registered_group, publish_group_in_shared_project
    (tmp_path / "project.json").write_text(json.dumps({"project_id":"synthetic-unknown-duration"}))
    publish_group_in_shared_project(tmp_path, "A01", scoped_registered_group(tmp_path, "A01"))
    entries = []
    for name in ("record.json", "H01_record.json"):
        record_path = f"A01/{name}"
        path = tmp_path / record_path
        record = json.loads(path.read_text())
        record["render"].pop("seconds", None)
        path.write_text(json.dumps(record))
        entries.append({"id":record["content_slot_id"], "record_path":record_path})
    index = {"items":entries}
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    (tmp_path / "artifacts/production_review_index.json").write_text(json.dumps(index))
    import_result(tmp_path, result_payload(tmp_path, "A01/record.json", import_id="baseline"), actor_id="tester")
    import_result(tmp_path, result_payload(tmp_path, "A01/H01_record.json", import_id="variant"), actor_id="tester")
    cards = {card["id"]:card for card in production_review_items(tmp_path, index, [])}
    result = cards["A01-H1"]["opening_results"][0]
    assert result["comparison_status"] == "不可比"
    assert "成片时长未知" in result["comparison_reasons"]
