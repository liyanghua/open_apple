import json

import pytest

from backlot.operator_errors import OperatorError
from backlot.operator_reviews import ReviewService
from backlot.production_review_items import production_review_items
from tests.backlot.test_final_production_reviews import approve
from tests.lib.test_opening_motion_evidence import fixture, write


def preview_project(root, *, media=None, full_media=None):
    """Synthetic UI fixture: no certification or real production authority."""
    root.mkdir(parents=True, exist_ok=True)
    record, _, _ = fixture(root)
    record.update(content_slot_id="SYNTHETIC-A", campaign_role="pilot")
    record["render"]["seconds"] = 3
    if media:
        # Observation does not match replacement test media: honestly unresolved.
        record["render"] = {**write(root, "synthetic-preview.mp4", media.read_bytes()), "seconds": 3}
    write(root, "project.json", {"project_id": root.name, "title": "Synthetic opening UI test"})
    write(root, "record.json", record)
    index = {"items": [{"id": record["content_slot_id"], "record_path": "record.json", "title": "合成测试预览"}]}
    if full_media:
        from copy import deepcopy
        full = deepcopy(record)
        full["content_slot_id"] = "SYNTHETIC-FULL"
        full["opening"]["scope"] = "full_variant"
        full["render"] = {**write(root, "synthetic-full.mp4", full_media.read_bytes()), "seconds": 6}
        # A real full certification requires B5 evidence for this exact render.
        # The synthetic card exercises playback only and remains blocked.
        write(root, "record-full.json", full)
        index["items"].append({"id":"SYNTHETIC-FULL", "record_path":"record-full.json", "title":"合成测试完整播放（未认证）"})
    (root / "artifacts").mkdir(exist_ok=True)
    write(root, "artifacts/production_review_index.json", index)
    return record, index


def test_preview_feedback_has_no_stage_or_delivery_authority(tmp_path):
    record, index = preview_project(tmp_path)
    service = ReviewService(tmp_path)
    review = service.create_production_review(record_path="record.json", submitted_by="pipeline")
    assert review["kind"] == "opening_preview"
    assert service.pending() is None
    assert not list(tmp_path.glob("checkpoint_*.json"))
    assert approve(service, review)["status"] == "approved"
    assert not (tmp_path / "operator/current-delivery.json").exists()
    item = production_review_items(tmp_path, index, [])[0]
    assert item["review_kind"] == "opening_preview"
    assert item["review_status"] == "预览反馈已通过"
    assert item["final_review"] is None
    assert item["opening_group"]["candidate_id"] == record["opening"]["candidate_id"]
    assert not item["certification_eligible"]


def test_rejection_does_not_resurrect_older_approval(tmp_path):
    _, index = preview_project(tmp_path)
    service = ReviewService(tmp_path)
    review = service.create_production_review(record_path="record.json", submitted_by="pipeline")
    approve(service, review)
    # Explicit newer review for the same bytes supersedes the old decision.
    later = service.create(kind="opening_preview", subject_id=review["subject_id"], subject_version=2,
        subject_hash=review["subject_hash"], submitted_by="pipeline", production_subject=review["production_subject"])
    service.decide(review_id=later["review_id"], decision="rejected", actor_id="user", reason="调整开头",
        expected_version=2, expected_hash=later["subject_hash"], issue_tags=["weak_hook"])
    item = production_review_items(tmp_path, index, [])[0]
    assert item["review_status"] == "预览需调整"
    assert service.create_production_review(record_path="record.json", submitted_by="pipeline")["subject_version"] == 3


@pytest.mark.parametrize("path", ["asset.mp4", "facts.json", "record.json"])
def test_nested_dependency_changes_invalidate_preview_approval(tmp_path, path):
    _, index = preview_project(tmp_path)
    service = ReviewService(tmp_path)
    review = service.create_production_review(record_path="record.json", submitted_by="pipeline")
    approve(service, review)
    (tmp_path / path).write_bytes(b"changed")
    with pytest.raises(OperatorError) as exc:
        approve(service, review)
    assert exc.value.code == "review_stale"
    if path != "record.json":
        item = production_review_items(tmp_path, index, [])[0]
        assert item["review"] is None
        assert item["review_history"][0]["status"] == "approved"
        assert item["binding_status"] == "changed"


@pytest.mark.parametrize("scope", ["bogus", "full_variant"])
def test_preview_scope_change_never_inherits_approval(tmp_path, scope):
    record, index = preview_project(tmp_path)
    service = ReviewService(tmp_path)
    review = service.create_production_review(record_path="record.json", submitted_by="pipeline")
    approve(service, review)
    record["opening"]["scope"] = scope
    write(tmp_path, "record.json", record)
    with pytest.raises(OperatorError):
        service.create_production_review(record_path="record.json", submitted_by="pipeline")
    assert production_review_items(tmp_path, index, [])[0]["review"] is None


def test_more_than_300_candidates_are_not_silently_hidden(tmp_path):
    from tests.backlot.test_final_production_reviews import make_record
    name = make_record(tmp_path)
    index = {"items": [{"id": "A01", "record_path": name}] * 301}
    assert len(production_review_items(tmp_path, index, [])) == 301


def test_synthetic_full_playback_card_is_visibly_uncertified(tmp_path):
    preview = tmp_path / "input-preview.mp4"; preview.write_bytes(b"synthetic preview")
    full = tmp_path / "input-full.mp4"; full.write_bytes(b"synthetic full")
    _, index = preview_project(tmp_path / "film", media=preview, full_media=full)
    items = production_review_items(tmp_path / "film", index, [])
    assert len(items) == 2
    assert items[0]["review_kind"] == "opening_preview"
    assert items[1]["review_kind"] == "final_review"
    assert items[1]["video_url"].endswith("synthetic-full.mp4")
    assert not items[1]["certification_eligible"]
    with pytest.raises(OperatorError):
        ReviewService(tmp_path / "film").create_production_review(record_path="record-full.json", submitted_by="pipeline")


def test_group_identity_isolates_registered_local_candidate_ids(tmp_path):
    from tests.lib.test_opening_freeze import scoped_registered_group, publish_group_in_shared_project
    index = {"items": []}
    for group in ("A01", "A03"):
        publish_group_in_shared_project(tmp_path, group, scoped_registered_group(tmp_path, group))
        for name in ("record.json", "H01_record.json"):
            record = json.loads((tmp_path / group / name).read_text())
            index["items"].append({"id": record["content_slot_id"], "record_path": group + "/" + name})
    items = production_review_items(tmp_path, index, [])
    assert len({i["opening_group"]["id"] for i in items if i["opening_group"]}) == 2
    assert len({i["id"] for i in items}) == 4


def test_unchanged_legacy_binding_retains_history_without_claiming_file_mutation(tmp_path):
    from tests.backlot.test_final_production_reviews import make_record
    name = make_record(tmp_path)
    service = ReviewService(tmp_path)
    review = service.create_final_review(record_path=name, submitted_by="pipeline")
    approve(service, review)
    path = service.review_dir / (review["review_id"] + ".json")
    historical = json.loads(path.read_text())
    historical["production_subject"]["dependencies"].pop("file:A01-props.json")
    path.write_text(json.dumps(historical))
    item = production_review_items(tmp_path, {"items": [{"id": "A01", "record_path": name}]}, [])[0]
    assert item["binding_status"] == "insufficient_history"
    assert item["review_history"][0]["status"] == "approved"
    assert "文件已变化" not in item["review_status"]


def test_preview_count_and_group_model():
    from tests.backlot.test_operator_artifact_model import _node
    model = _node("""
const compose = buildApprovalStages({stages:[{id:'compose',status:'awaiting_human',editor:{data:{production_reviews:[
  {id:'p',review_kind:'opening_preview',review_status:'预览反馈已通过',opening_group:{id:'g',candidate_id:'H01',scope:'preview'}},
  {id:'f',review_kind:'final_review',review_status:'已通过',opening_group:{id:'g',candidate_id:'B0',scope:'full_variant'}}
]}}}]}).find(s=>s.stageId==='compose');
console.log(JSON.stringify(compose));
""")
    assert model["status"] == "成片已验收"
    assert "1/1 条成片" in model["summary"]
    assert "1 条开头预览" in model["summary"]


def test_preview_component_labels_playback_and_scope():
    import subprocess
    from pathlib import Path
    script = r'''
const elements=[];
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.listeners={};this.textContent=''; elements.push(this);}
  append(...children){this.children.push(...children);}
  setAttribute(key,value){this[key]=value;}
  addEventListener(key,fn){this.listeners[key]=fn;}
  pause(){this.paused=true;}
  scrollIntoView(){this.scrolled=true;}
}
global.document={createElement:tag=>new Element(tag),querySelectorAll:()=>elements.filter(e=>e.tag==='video')};
global.window={location:{search:'?content=p'}};
const {renderProductionReviews}=await import('./backlot/ui/operator/approval.js');
const container=new Element('main');
renderProductionReviews(container,{items:[{id:'p',title:'Test',video_url:'/preview.mp4',review_kind:'opening_preview',
 opening_group:{id:'g',experiment_id:'exp',sku:'s',candidate_id:'H01',scope:'preview',role:'variant',shots:[]},
 checks:{opening_motion:{machine_status:'not_run',effective_status:'manual_verified',observations:[{shot_id:'s1',method:'human_review',motion:{verb:'opens',visible_result:'contents visible'},actual_action:{source_interval_seconds:[0.5,2],output_interval_seconds:[0.5,2]}}]}}}]},{canReview:true,projectId:'test'});
const allText=elements.map(e=>e.textContent).join('|');
const video=elements.find(e=>e.tag==='video');
video.currentTime=3.1;video.listeners.timeupdate();
console.log(JSON.stringify({allText,time:video.currentTime,full:elements.filter(e=>e.textContent==='观看完整成片').length}));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=Path(__file__).resolve().parents[2], check=True, capture_output=True, text=True)
    actual = json.loads(result.stdout)
    assert "确认开头预览反馈" in actual["allText"]
    assert "仅开头预览" in actual["allText"]
    assert "自动 not_run" in actual["allText"]
    assert "人工 manual_verified" in actual["allText"]
    assert "contents visible" in actual["allText"]
    assert actual["full"] == 0
    assert actual["time"] == 0


def test_canonical_batch_context_is_verified_and_ignores_request_claims(tmp_path):
    from tests.lib.test_opening_freeze import scoped_registered_group, publish_group_in_shared_project, write as write_ref
    from lib.opening_batch_context import resolve_opening_context
    context = publish_group_in_shared_project(tmp_path, "A01", scoped_registered_group(tmp_path, "A01"))
    (tmp_path / "artifacts").mkdir()
    write_ref(tmp_path, "artifacts/opening_batch_context.json", {"version": "1.0", **{k:v for k,v in context.items() if k != "root"}})
    assert resolve_opening_context(tmp_path, "H01")["experiment_ref"] == context["experiment_ref"]
    (tmp_path / "A01/H01_render.mp4").write_bytes(b"changed")
    assert resolve_opening_context(tmp_path, "H01") is None


def test_campaign_role_pilot_and_preview_never_subtract_original_target():
    from tests.lib.test_campaign_panorama import record, proof
    from lib.campaign_panorama import build_campaign_panorama
    row = record(slot="s")
    plan = {"campaign_id":"test", "slots":[{"content_slot_id":"s", "sku":"S01", "production_route":"ai_assisted", "week":1}], "target_count":1}
    for extra in ({"campaign_role": "pilot"}, {"opening": {"scope":"preview"}}):
        candidate = {**row, **extra}
        result = build_campaign_panorama(plan, [candidate], verification_reports={candidate["run_id"]: proof(candidate)})
        assert result["summary"]["approved_unique"] == 0


def test_actual_batch_callers_propagate_verified_opening_context(tmp_path):
    from tests.lib.test_opening_freeze import scoped_registered_group, publish_group_in_shared_project, write as write_ref
    from tests.backlot.test_batch_actions import _child_with_review, _write
    from lib.candidate_diversity import build_variant_plan
    from backlot.batch_actions import selection_quality_failures
    from lib.batch_reporting import build_batch_quality_report
    from backlot.batch_state import build_batch_review_data
    batch_root = tmp_path / "batch"
    batch_root.mkdir()
    context = publish_group_in_shared_project(batch_root, "A01", scoped_registered_group(batch_root, "A01"))
    (batch_root / "artifacts").mkdir()
    write_ref(batch_root, "artifacts/opening_batch_context.json", {"version":"1.0", **{k:v for k,v in context.items() if k != "root"}})
    candidates=[]
    for name in ("B0", "H01"):
        child = _child_with_review(tmp_path, name)
        plan = build_variant_plan(batch_id="batch", candidate_id=name, variant_revision=1,
            baseline_ref={"path":"A01/record.json"}, dimensions={}, shot_differences=[], opening_only_change=True,
            provenance={"preregistered_variable":"opening_package", "registration_ref":context["experiment_ref"]["path"]})
        _write(child / "artifacts/candidate_variant_plan.json", plan)
        candidates.append({"candidate_id":name, "project_id":name, "status":"evaluated"})
    batch={"batch_id":"batch", "candidates":candidates, "diversity_mode":"hard_gate"}
    _write(batch_root / "artifacts/candidate_batch.json", batch)
    for c in candidates:
        failures = selection_quality_failures(batch, c, tmp_path / c["project_id"], batch_dir=batch_root)
        assert not any("差异" in f for f in failures), failures
    report = build_batch_quality_report(batch_root)
    assert report["pairwise_diversity"][0]["passes"]
    state = build_batch_review_data({"_project_dir":batch_root}, batch)
    assert state["diversity"]["pairwise"][0]["passes"]


def test_prepare_route_requires_project_role_and_csrf(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backlot import server
    from backlot.auth_store import AuthStore
    from tests.backlot.test_operator_mutation_api import _login
    projects = tmp_path / "projects"
    project = projects / "film"
    preview_project(project)
    auth = AuthStore(tmp_path / "auth.db"); auth.initialize()
    owner = auth.create_user("owner", "a sufficiently long password", "operator")
    auth.create_user("outsider", "a sufficiently long password", "operator")
    auth.set_project_role("film", owner.user_id, "owner")
    monkeypatch.setattr(server, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server, "_watch_projects", lambda: _never())
    url = "/api/v2/projects/film/production-reviews/SYNTHETIC-A/prepare"
    with TestClient(server.create_app(auth_store=auth)) as client:
        assert client.post(url).status_code == 401
        _login(client, "outsider")
        assert client.post(url, headers={"Origin":"http://testserver", "X-CSRF-Token":client.get("/api/v2/auth/me").json()["csrf_token"]}).status_code == 403
        client.post("/api/v2/auth/logout", headers={"Origin":"http://testserver", "X-CSRF-Token":client.get("/api/v2/auth/me").json()["csrf_token"]})
        csrf = _login(client)
        assert client.post(url, headers={"Origin":"http://testserver"}).status_code == 403
        prepared = client.post(url, headers={"Origin":"http://testserver", "X-CSRF-Token":csrf})
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["kind"] == "opening_preview"


async def _never():
    import asyncio
    while True:
        await asyncio.sleep(3600)
