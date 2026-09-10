from __future__ import annotations

import json
from pathlib import Path

from backlot import state as state_mod
from backlot.editorial_gallery import build_editorial_gallery


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    batch = root / "towel-batch"
    _write(batch / "project.json", {"project_id": "towel-batch", "pipeline_type": "cinematic-fast"})
    _write(batch / "artifacts/candidate_batch.json", {
        "version": "1.0", "batch_id": "towel-batch", "project_id": "towel-batch",
        "created_at": "2026-09-09T00:00:00+00:00", "shared_research": {"refs": []},
        "concurrency": {"max_candidates": 3, "max_parallel": 2},
        "differentiation_axes": {"hook": True},
        "candidates": [
            {"candidate_id": "remotion", "label": "结果先行", "project_id": "cand-remotion", "direction": {"hook": "先看吸水结果"}, "status": "sampled"},
            {"candidate_id": "hyper", "label": "证据链", "project_id": "cand-hyper", "direction": {"hook": "连续倒水"}, "status": "sampled"},
            {"candidate_id": "ffmpeg", "label": "参数先行", "project_id": "cand-ffmpeg", "direction": {"hook": "材质细节"}, "status": "sampled"},
        ],
        "selection": {"selected_candidate_ids": ["remotion"], "selected_at": None, "reason": ""},
        "diversity_mode": "source_led",
    })
    for candidate_id, runtime in (("cand-remotion", "remotion"), ("cand-hyper", "hyperframes"), ("cand-ffmpeg", "ffmpeg")):
        child = root / candidate_id
        _write(child / "project.json", {"project_id": candidate_id, "pipeline_type": "cinematic-fast"})
        _write(child / "artifacts/production_lock.json", {"locked_values": {"render_runtime": runtime}})
        _write(child / "artifacts/product_facts.json", {"claims": [{"id": "claim-1", "statement": "吸水速干", "evidence": {"source": "商品详情页"}}]})
        _write(child / "artifacts/evaluation_report.sample.json", {"scope": "sample", "status": "pass", "hard_gate": {"checks": [{"name": "alignment", "status": "pass"}]}})
        _write(child / f"checkpoint_sample.json", {"version": "1.0", "project_id": candidate_id, "pipeline_type": "cinematic-fast", "stage": "sample", "status": "completed", "timestamp": "2026-09-09T00:01:00+00:00", "artifacts": {}})
        (child / "renders").mkdir(parents=True, exist_ok=True)
        if candidate_id != "cand-ffmpeg":
            (child / "renders/sample-v2.mp4").write_bytes(b"sample")
        if candidate_id == "cand-remotion":
            (child / "renders/final.mp4").write_bytes(b"final")
            _write(child / "artifacts/editorial_timeline.json", {"version": "1.0"})
            _write(child / "operator/editorial/asset-catalogue.json", {"version": "1.0"})
    state_mod.PROJECTS_DIR = root
    return batch


def test_gallery_projects_media_direction_revision_gates_facts_and_studio_eligibility(tmp_path: Path) -> None:
    gallery = build_editorial_gallery(_fixture(tmp_path))
    candidates = {item["candidate_id"]: item for item in gallery["candidates"]}

    remotion = candidates["remotion"]
    assert remotion["direction"]["hook"] == "先看吸水结果"
    assert remotion["current_revision"]
    assert remotion["gate_statuses"]["sample"] == "completed"
    assert remotion["fact_summary"]["claims"][0]["id"] == "claim-1"
    assert remotion["studio_eligibility"]["eligible"] is True
    assert remotion["studio_eligibility"]["runtime"] == "remotion"
    assert remotion["studio_eligibility"]["reason"] is None
    assert remotion["studio_eligibility"]["can_create_v2_session"] is True
    assert remotion["media"]["sample_url"].endswith("sample-v2.mp4")
    assert remotion["media"]["final_url"].endswith("final.mp4")

    hyper = candidates["hyper"]
    assert hyper["studio_eligibility"]["eligible"] is False
    assert hyper["studio_eligibility"]["reason"] == "unsupported_runtime"
    assert hyper["studio_eligibility"]["runtime"] == "hyperframes"


def test_gallery_missing_media_is_honest_and_runtime_blocks_v2_session(tmp_path: Path) -> None:
    gallery = build_editorial_gallery(_fixture(tmp_path))
    ffmpeg = next(item for item in gallery["candidates"] if item["candidate_id"] == "ffmpeg")
    assert ffmpeg["media"]["sample_url"] is None
    assert ffmpeg["media"]["final_url"] is None
    assert ffmpeg["media"]["poster_url"] is None
    assert ffmpeg["studio_eligibility"]["eligible"] is False
    assert ffmpeg["studio_eligibility"]["reason"] == "unsupported_runtime"
    assert ffmpeg["studio_eligibility"]["can_create_v2_session"] is False


def test_gallery_requires_materialized_v2_artifacts_before_showing_studio_entry(tmp_path: Path) -> None:
    batch = _fixture(tmp_path)
    candidate = batch.parent / "cand-remotion"
    (candidate / "artifacts/editorial_timeline.json").unlink()
    gallery = build_editorial_gallery(batch)
    remotion = next(item for item in gallery["candidates"] if item["candidate_id"] == "remotion")
    assert remotion["studio_eligibility"] == {
        "eligible": False,
        "runtime": "remotion",
        "reason": "timeline_unavailable",
        "can_create_v2_session": False,
    }


def test_gallery_projects_legacy_template_batch_for_a_materialized_candidate(tmp_path: Path) -> None:
    batch = _fixture(tmp_path)
    (batch / "artifacts/candidate_batch.json").unlink()
    _write(batch / "artifacts/template_batch.json", {
        "version": "1.0", "batch_id": "towel-batch", "runs": [{
            "project_id": "cand-remotion", "template_id": "source-led-a", "status": "completed",
        }],
    })

    gallery = build_editorial_gallery(batch)

    assert gallery["candidates"][0]["candidate_id"] == "cand-remotion"
    assert gallery["candidates"][0]["studio_eligibility"]["eligible"] is True


def test_editorial_gallery_api_and_studio_entrypoint_are_available(backlot_client, projects_root, monkeypatch) -> None:
    batch = _fixture(projects_root.parent)
    response = backlot_client.get(f"/api/v2/projects/{batch.name}/editorial-gallery")
    assert response.status_code == 200
    assert response.json()["batch_id"] == batch.name
    page = backlot_client.get(f"/studio/{batch.name}")
    assert page.status_code == 200

    editor = backlot_client.get(f"/studio/{batch.name}/edit/remotion")
    assert editor.status_code == 200
    assert "editorial-editor/shell.js" in editor.text
    assert "editorial-editor-shell.js" not in editor.text
    # shell.js writes these state nodes during boot.  Keep this contract here
    # so a markup-only refactor cannot prevent the OpenReel iframe from mounting.
    for element_id in ("pendingCount", "unsupportedCount", "qaStatus", "progressState"):
        assert f'id="{element_id}"' in editor.text


def test_editorial_session_api_rejects_non_remotion_candidate(backlot_client, projects_root) -> None:
    batch = _fixture(projects_root.parent)
    response = backlot_client.post(
        f"/api/v2/projects/{batch.name}/editorial-gallery/candidates/hyper/edit-session",
        json={"idempotency_key": "open-hyper"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_runtime"


def test_legacy_template_batch_resolves_candidate_for_studio_session_routes(backlot_client, projects_root) -> None:
    batch = _fixture(projects_root.parent)
    (batch / "artifacts/candidate_batch.json").unlink()
    _write(batch / "artifacts/template_batch.json", {
        "version": "1.0", "batch_id": batch.name, "runs": [{
            "project_id": "cand-remotion", "template_id": "source-led-a", "status": "completed",
        }],
    })

    response = backlot_client.post(
        f"/api/v2/projects/{batch.name}/editorial-gallery/edit-session",
        json={"candidate_id": "cand-remotion", "idempotency_key": "open-legacy"},
    )
    # The fixture's intentionally minimal timeline is invalid, but the route
    # must resolve the legacy batch and reach the V2 session validator.
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "recovery_required"


def test_editorial_routes_are_hidden_when_v2_feature_flag_is_off(backlot_client, projects_root, monkeypatch) -> None:
    batch = _fixture(projects_root.parent)
    monkeypatch.setenv("OPENMONTAGE_EDITORIAL_TIMELINE_V2", "0")
    assert backlot_client.get(f"/studio/{batch.name}").status_code == 404
    response = backlot_client.get(f"/api/v2/projects/{batch.name}/editorial-gallery")
    assert response.status_code == 404
    assert backlot_client.get(f"/p/{batch.name}").status_code == 200
