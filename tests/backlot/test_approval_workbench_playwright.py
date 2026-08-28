"""Browser acceptance for the connected batch and single-review workbench.

These tests intentionally fail during fixture setup when Playwright or its
Chromium binary is unavailable.  A skipped browser suite must not be treated
as approval of the operator entry point.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from copy import deepcopy
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _project_state(*, batch: bool = True, permissions: tuple[str, ...] = ("view", "review"),
                   data: dict | None = None) -> dict:
    stages = [{
        "id": "sample",
        "label": "查看样片",
        "status": "等待确认" if batch else "已完成",
        "version": 1,
        "editor": {"type": "batch_review", "data": data or {}} if batch else {
            "type": "sample_review",
            "data": {"qa_status": "检查通过", "duration_seconds": 10, "review_summary": "样片已准备好"},
        },
    }]
    return {
        "project_id": "batch-demo" if batch else "candidate-a",
        "title": "桌面防护片批次" if batch else "结果先行",
        "permissions": list(permissions),
        "summary": {
            "progress_percent": 70 if batch else 100,
            "current_task": "样片确认" if batch else "查看样片",
            "estimated_seconds": 120,
            "next_action": "确认样片" if batch else "返回批量总览",
            "performance": {"promise": "预计 2 分钟"},
        },
        "pending_review": None if batch else {
            "review_id": "review-sample-a",
            "subject_hash": "a" * 64,
            "subject_version": 1,
            "label": "样片效果确认",
            "summary": "请确认五项效果",
        },
        "legacy": None,
        "stages": stages,
        "workspace": {
            "stage_id": "sample",
            "view_mode": "approval",
            "editor": stages[0]["editor"],
        },
        "drafts": {},
        "previews": {},
    }


def _batch_data(*, eligible: bool = True, degraded: bool = False, media_url: str | None = None) -> dict:
    candidates = [
        {
            "candidate_id": "candidate-a",
            "project_id": "candidate-a",
            "label": "结果先行",
            "status": "evaluated",
            "candidate_phase": "evaluated",
            "current_step": "查看样片",
            "current_artifact": "样片预览",
            "review_status": "approved",
            "selection_eligible": eligible,
            "selection_block_reason": None if eligible else "评价报告不完整",
            "direction": {"title": "结果先行"},
            "links": {"project_page": "/p/candidate-a?from=batch&batch_id=batch-demo"},
            "media": {"sample_url": media_url, "audio_tracks": []},
            "score": {"evaluation": {"status": "pass" if eligible else "partial"}},
            "stage_states": [{"stage_id": "sample", "status": "approved"}],
            "pending_reviews": [],
            "cost": {"cost_usd": 0.12, "attempts": 1},
            "failure": {"failure": None, "technical": False},
        },
        {
            "candidate_id": "candidate-b",
            "project_id": "candidate-b",
            "label": "痛点先行",
            "status": "awaiting_review",
            "candidate_phase": "awaiting_review",
            "current_step": "查看样片",
            "current_artifact": "样片预览",
            "review_status": "awaiting_review",
            "selection_eligible": False,
            "selection_block_reason": "还没有完成样片确认",
            "direction": {"title": "痛点先行"},
            "links": {"project_page": "/p/candidate-b?from=batch&batch_id=batch-demo"},
            "media": {"sample_url": None, "audio_tracks": []},
            "score": {},
            "stage_states": [{"stage_id": "sample", "status": "awaiting_human"}],
            "pending_reviews": [{"kind": "sample", "review_id": "review-sample-b", "subject_hash": "b" * 64, "subject_version": 1}],
            "cost": {"cost_usd": 0.10, "attempts": 1},
            "failure": {"failure": None, "technical": False},
        },
        {
            "candidate_id": "candidate-failed",
            "project_id": "candidate-failed",
            "label": "高密度快剪",
            "status": "failed",
            "candidate_phase": "failed",
            "current_step": "查看样片",
            "current_artifact": "样片预览",
            "review_status": "not_ready",
            "selection_eligible": False,
            "selection_block_reason": "样片没有生成",
            "direction": {"title": "高密度快剪"},
            "links": {"project_page": "/p/candidate-failed?from=batch&batch_id=batch-demo"},
            "media": {"sample_url": None, "audio_tracks": []},
            "score": {},
            "stage_states": [{"stage_id": "sample", "status": "failed"}],
            "pending_reviews": [],
            "cost": {"cost_usd": 0.03, "attempts": 2},
            "failure": {"failure": "样片生成失败，请检查素材后重试", "technical": True},
        },
    ]
    if not eligible:
        for candidate in candidates:
            candidate["selection_eligible"] = False
            candidate["selection_block_reason"] = candidate["selection_block_reason"] or "本批没有可用视频"
    return {
        "schema_version": "1.1",
        "kind": "batch_review",
        "batch_id": "batch-demo",
        "aggregate_revision": "agg-1",
        "phase": "waiting_review" if eligible else "completed",
        "phase_reason": "等待样片确认" if eligible else "本批没有可用视频",
        "consistency": "stable",
        "rail": [],
        "candidates": candidates,
        "pending_gates": [{"gate": "sample", "label": "样片效果确认", "stage": "sample", "candidates": [
            {"candidate_id": "candidate-b", "project_id": "candidate-b"},
        ]}] if eligible else [],
        "selection": {"selected_candidate_ids": [], "eligible_candidate_ids": ["candidate-a"] if eligible else [], "reason": ""},
        "warnings": [] if eligible else [{"candidate_id": "candidate-failed", "description": "样片没有生成", "suggested_action": "查看问题汇总"}],
        "budget": {"spent_usd": 0.25, "max_cost_usd": 2.0, "remaining_usd": 1.75, "over_budget": False},
        "concurrency": {"active_count": 0, "max_parallel": 3},
        "reports": {"status": "degraded" if degraded else "complete", "disabled_actions": ["select"] if degraded else [], "recovery_action": "重新拉取最新结果" if degraded else ""},
        "diversity": {},
    }


@pytest.fixture(scope="module")
def backlot_url(tmp_path_factory):
    projects = tmp_path_factory.mktemp("browser-projects")
    port = 4917
    script = (
        "import uvicorn; from backlot.server import create_app; "
        f"uvicorn.run(create_app(auth_mode='test'), host='127.0.0.1', port={port}, log_level='error')"
    )
    env = dict(os.environ)
    env["OPENMONTAGE_PROJECTS_DIR"] = str(projects)
    server = subprocess.Popen([sys.executable, "-c", script], cwd=REPO_ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1):
                break
        except Exception:
            time.sleep(0.2)
    else:
        server.terminate()
        raise RuntimeError("Backlot server did not become healthy")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


@pytest.fixture(scope="module")
def chromium():
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as exc:  # pragma: no cover - environment guard
        pytest.fail(
            "Phase 4 浏览器验收需要 Playwright。请安装 requirements-dev.txt 后运行 "
            "`playwright install chromium`，不能把缺依赖当作通过。",
            pytrace=False,
        )
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Error as exc:  # pragma: no cover - environment guard
            pytest.fail(
                "Phase 4 浏览器验收需要 Chromium。请运行 `playwright install chromium`。\n"
                f"原始错误：{exc}",
                pytrace=False,
            )
        try:
            yield browser
        finally:
            browser.close()


def _open(page, base_url: str, path: str, states: dict[str, dict]) -> None:
    def route_state(route):
        project_id = route.request.url.split("/projects/", 1)[1].split("/", 1)[0]
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(states[project_id], ensure_ascii=False))

    page.route("**/api/v2/projects/*/operator-state", route_state)
    page.goto(base_url + path, wait_until="domcontentloaded")
    page.wait_for_timeout(250)


def test_batch_first_view_links_to_single_and_returns_with_context(chromium, backlot_url):
    batch = _batch_data()
    states = {"batch-demo": _project_state(data=batch), "candidate-a": _project_state(batch=False)}
    context = chromium.new_context(viewport={"width": 1180, "height": 900})
    page = context.new_page()
    try:
        _open(page, backlot_url, "/p/batch-demo", states)
        assert page.get_by_test_id("batch-workbench").is_visible()
        assert page.get_by_test_id("candidate-card-candidate-a").is_visible()
        single_link = page.get_by_test_id("open-single-candidate-a")
        assert "from=batch" in (single_link.get_attribute("href") or "")
        assert "batch_id=batch-demo" in (single_link.get_attribute("href") or "")

        page.get_by_test_id("quick-view-candidate-a").click()
        drawer = page.get_by_test_id("candidate-quick-view")
        assert drawer.is_visible()
        assert drawer.get_by_role("button", name="通过").count() == 0
        assert drawer.get_by_role("button", name="退回").count() == 0
        page.get_by_test_id("close-quick-view").click()

        single_link.click()
        page.wait_for_timeout(250)
        assert "from=batch" in page.url and "batch_id=batch-demo" in page.url
        assert page.get_by_test_id("return-to-batch").is_visible()
        page.get_by_test_id("return-to-batch").click()
        page.wait_for_timeout(250)
        assert page.url.rstrip("/").endswith("/p/batch-demo")
        assert page.get_by_test_id("batch-workbench").is_visible()
    finally:
        context.close()


def test_mixed_failure_and_degraded_report_use_business_recovery_states(chromium, backlot_url):
    batch = _batch_data(eligible=False, degraded=True)
    state = _project_state(data=batch)
    context = chromium.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        _open(page, backlot_url, "/p/batch-demo", {"batch-demo": state})
        assert page.get_by_test_id("batch-workbench").is_visible()
        assert page.get_by_test_id("candidate-card-candidate-failed").get_by_text("样片没有生成").is_visible()
        assert page.get_by_test_id("batch-selection").get_by_role("button", name="重新拉取最新结果").is_visible()
        assert page.get_by_test_id("batch-selection").get_by_role("button").is_disabled()
        assert "本批没有可用视频" in page.get_by_test_id("batch-issue-summary").inner_text()
        assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    finally:
        context.close()


def test_batch_candidate_mismatch_shows_chinese_recovery_entry(chromium, backlot_url):
    context = chromium.new_context(viewport={"width": 1180, "height": 900})
    page = context.new_page()
    try:
        def mismatch(route):
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({"error": {"code": "stale", "message": "批次与候选不匹配，请返回批量总览"}}, ensure_ascii=False),
            )

        page.route("**/api/v2/projects/candidate-a/operator-state", mismatch)
        page.goto(backlot_url + "/p/candidate-a?from=batch&batch_id=other-batch", wait_until="domcontentloaded")
        page.wait_for_timeout(250)
        message = page.get_by_test_id("workbench-message")
        assert message.is_visible()
        assert "返回批量总览" in message.inner_text()
    finally:
        context.close()


def test_media_failure_and_permission_revoke_disable_actions(chromium, backlot_url):
    batch = _batch_data(media_url="/media/candidate-a/missing.mp4")
    state = _project_state(data=batch, permissions=("view", "review"))
    context = chromium.new_context(viewport={"width": 1180, "height": 900})
    page = context.new_page()
    try:
        _open(page, backlot_url, "/p/batch-demo", {"batch-demo": state})
        video = page.get_by_test_id("candidate-card-candidate-a").locator("video")
        if video.count():
            video.dispatch_event("error")
        assert page.get_by_test_id("media-error-candidate-a").is_visible()
        assert page.get_by_test_id("batch-primary-action").is_disabled()
    finally:
        context.close()
