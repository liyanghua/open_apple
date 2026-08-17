# Backlot Page Auth Gate Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redirect unauthenticated browser page requests to `/login` while preserving the existing API authentication contract and project creation flow.

**Architecture:** Add one small production-mode page guard in `backlot/server.py` that validates the existing session cookie and returns a 303 redirect. Apply it to the library and both board route variants; leave `/login`, `/setup`, static UI, health, and JSON APIs unchanged. Extend auth tests with explicit redirect and authenticated-page cases.

**Tech Stack:** FastAPI, Starlette `RedirectResponse`, existing `AuthStore` sessions, pytest/TestClient.

---

## Chunk 1: Page route regression coverage

**Files:**
- Modify: `tests/backlot/test_auth_api.py`

- [ ] Add production-mode tests for `/`, `/p/film`, and `/p/film/extra` returning 303 with `Location: /login` when no session exists.
- [ ] Add authenticated page assertions and confirm `/api/projects` remains JSON 401 without a session.
- [ ] Run the new tests and confirm they fail because page routes currently return HTML.

## Chunk 2: Minimal page guard

**Files:**
- Modify: `backlot/server.py`

- [ ] Add a helper that returns a 303 response for missing or invalid sessions in production mode and no response otherwise.
- [ ] Call the helper from `/`, `/p/{project_id}`, and `/p/{project_path:path}` before rendering HTML.
- [ ] Keep test mode bypass and all public routes unchanged.
- [ ] Run focused auth tests, then the Backlot regression suite.

## Chunk 3: Verification

**Files:**
- No additional production files.

- [ ] Verify the live server redirects a fresh request to `/login` and serves the project list after a valid login.
- [ ] Review the diff and confirm unrelated workspace files remain untouched.
- [ ] Commit the implementation and tests.
