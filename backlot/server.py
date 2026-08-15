"""Backlot server — FastAPI app: board state API, SSE change feed, media.

The watcher observes ``projects/`` with watchfiles; on any change it bumps a
per-project version and wakes SSE subscribers, who tell the browser to
refetch state. The server never writes to project directories.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backlot.operator_state import load_operator_state
from backlot.operator_errors import OperatorError
from backlot.state import PROJECTS_DIR, REPO_ROOT, list_projects, load_board_state, summarize_project
from backlot.state_cache import invalidate_state_cache

UI_DIR = Path(__file__).resolve().parent / "ui"
THUMB_CACHE_DIR = REPO_ROOT / ".backlot" / "thumbs"
THUMB_WIDTHS = (320, 640, 960)

# Paths inside a project whose changes are pure noise for the board.
_IGNORE_PARTS = {"node_modules", ".git", "__pycache__", ".cache"}

SSE_HEARTBEAT_SECONDS = 15


def _ui_html(name: str, assets: tuple[str, ...]) -> HTMLResponse:
    html = (UI_DIR / name).read_text(encoding="utf-8")
    for asset in assets:
        path = UI_DIR / asset
        if path.is_file():
            version = str(int(path.stat().st_mtime))
            html = html.replace(f"/ui/{asset}", f"/ui/{asset}?v={version}")
    return HTMLResponse(html)


class ChangeHub:
    """Fan-out of project-change notifications to SSE subscribers.

    Subscriptions are filtered: a board subscribed to one project only ever
    receives that project's ids, so unrelated-project bursts can't flood its
    queue and starve out the one notification it actually needs.
    """

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue, Optional[str]] = {}

    def subscribe(self, project_id: Optional[str] = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subscribers[q] = project_id
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.pop(q, None)

    def publish(self, project_id: str) -> None:
        for q, only in list(self._subscribers.items()):
            if only is not None and only != project_id:
                continue
            try:
                q.put_nowait(project_id)
            except asyncio.QueueFull:
                # Queue holds only THIS subscriber's relevant ids, so a full
                # queue already guarantees a pending wake-up → safe to drop.
                pass


hub = ChangeHub()


async def _project_event_stream(
    project_id: str,
    request: Request,
    *,
    business_facing: bool,
):
    """Yield one project's change events for legacy and operator consumers."""
    q = hub.subscribe(project_id)
    try:
        hello = {"type": "hello", "project_id": project_id}
        if business_facing:
            hello["message"] = "已连接项目进度"
        yield _sse(hello)
        while True:
            if await request.is_disconnected():
                return
            try:
                await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                heartbeat = {"type": "heartbeat", "ts": time.time()}
                if business_facing:
                    heartbeat["message"] = "项目进度连接正常"
                yield _sse(heartbeat)
                continue
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
            change = {"type": "change", "project_id": project_id}
            if business_facing:
                change["message"] = "项目进度已更新"
            yield _sse(change)
    finally:
        hub.unsubscribe(q)

# Library summaries are expensive to derive (full state parse per project);
# cache per project and invalidate from the watcher.
_summary_cache: dict[str, dict] = {}


def _invalidate_summary(project_id: str) -> None:
    _summary_cache.pop(project_id, None)
    invalidate_state_cache(PROJECTS_DIR / project_id)


def _cached_summaries() -> list[dict]:
    if not PROJECTS_DIR.is_dir():
        return []
    summaries = []
    for entry in sorted(PROJECTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        cached = _summary_cache.get(entry.name)
        if cached is None:
            try:
                cached = summarize_project(entry)
            except Exception:
                cached = {
                    "project_id": entry.name, "title": entry.name,
                    "pipeline_type": "unknown", "has_pipeline_state": False,
                    "poster": None, "live": False, "last_activity": 0,
                    "active_stage": None, "awaiting_human": False,
                    "stage_states": [], "completed_count": 0,
                    "render_count": 0, "scene_count": 0, "error": "unreadable",
                }
            _summary_cache[entry.name] = cached
        summaries.append(cached)
    summaries.sort(key=lambda s: (not s["live"], -(s["last_activity"] or 0)))
    return summaries


# Watch-loop hot path: pure string comparison, no per-path filesystem calls
# (change batches can be thousands of paths during a render).
import os as _os

_PROJECTS_ROOT_STR = _os.path.normcase(str(PROJECTS_DIR.resolve()))


def _project_of_change(path_str: str) -> Optional[str]:
    """Map a changed filesystem path to a project id (None = irrelevant)."""
    norm = _os.path.normcase(_os.path.normpath(path_str))
    if not norm.startswith(_PROJECTS_ROOT_STR):
        return None
    rel = norm[len(_PROJECTS_ROOT_STR):].lstrip("\\/")
    if not rel:
        return None
    parts = rel.replace("\\", "/").split("/")
    if _IGNORE_PARTS.intersection(parts):
        return None
    return parts[0]


async def _watch_projects() -> None:
    """Background task: watch projects/ and publish debounced changes."""
    try:
        from watchfiles import awatch
    except ImportError:
        return  # watcher unavailable → board still works via manual refresh
    if not PROJECTS_DIR.is_dir():
        return
    async for changes in awatch(PROJECTS_DIR, recursive=True, step=400):
        touched: set[str] = set()
        for _change, path_str in changes:
            pid = _project_of_change(path_str)
            if pid:
                touched.add(pid)
        for pid in touched:
            _invalidate_summary(pid)
            hub.publish(pid)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Own and cleanly stop the project watcher with FastAPI's lifespan API."""

    task = asyncio.create_task(_watch_projects())
    app.state.watch_task = task
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app(*, auth_store=None, auth_mode: str = "production") -> FastAPI:
    if auth_mode not in {"production", "test"}:
        raise ValueError("Unknown Backlot auth mode")
    app = FastAPI(title="Backlot", docs_url=None, redoc_url=None, lifespan=_lifespan)
    login_attempts: dict[str, list[float]] = {}

    def get_auth_store():
        nonlocal auth_store
        if auth_store is None:
            import os
            from backlot.auth_store import AuthStore

            configured = os.environ.get("BACKLOT_DATA_DIR")
            data_dir = Path(configured).expanduser() if configured else REPO_ROOT / ".backlot"
            auth_store = AuthStore(data_dir / "backlot.db")
            auth_store.initialize()
        return auth_store

    def require_access(
        request: Request,
        project_id: str | None = None,
        action: str = "read",
        *,
        csrf: bool = False,
    ):
        from backlot.auth import authorize_project, require_csrf, require_session
        from backlot.auth_store import SessionRecord, UserRecord

        if auth_mode == "test":
            return SessionRecord(
                UserRecord("test-admin", "test-admin", "admin"),
                "test-csrf",
                "2999-01-01T00:00:00+00:00",
            )
        session = require_session(request, get_auth_store())
        if csrf:
            require_csrf(request, session)
        if project_id is not None and not authorize_project(
            get_auth_store(), session.actor, project_id, action
        ):
            raise OperatorError("forbidden", "你没有访问该项目的权限", 403)
        return session

    @app.exception_handler(OperatorError)
    async def operator_error_handler(_request: Request, exc: OperatorError) -> JSONResponse:
        return JSONResponse(exc.to_public_dict(), status_code=exc.status_code)

    # ---- API ----------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "app": "backlot"}

    @app.post("/api/v2/auth/login")
    async def auth_login(request: Request) -> JSONResponse:
        from backlot.auth import SESSION_COOKIE, require_same_origin
        from urllib.parse import parse_qs

        require_same_origin(request)
        now = time.monotonic()
        client = request.client.host if request.client else "unknown"
        recent = [stamp for stamp in login_attempts.get(client, []) if now - stamp < 60]
        if len(recent) >= 6:
            raise OperatorError("auth_required", "登录尝试过多，请稍后再试", 429)
        recent.append(now)
        login_attempts[client] = recent
        if request.headers.get("content-type", "").split(";", 1)[0] == "application/x-www-form-urlencoded":
            fields = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
            body = {key: values[-1] for key, values in fields.items() if values}
        else:
            try:
                body = await request.json()
            except Exception:
                body = {}
        if body.get("schema_version", body.get("version")) != "1.0":
            raise OperatorError.validation_failed("登录信息格式不正确")
        actor = get_auth_store().authenticate(
            str(body.get("username") or ""), str(body.get("password") or "")
        )
        if actor is None:
            raise OperatorError("auth_required", "用户名或密码不正确", 401)
        credentials = get_auth_store().create_session(actor.user_id)
        response = JSONResponse({
            "user": {
                "user_id": actor.user_id,
                "username": actor.username,
                "system_role": actor.system_role,
            }
        })
        response.set_cookie(
            SESSION_COOKIE,
            credentials.session_token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )
        return response

    @app.get("/api/v2/auth/me")
    async def auth_me(request: Request) -> dict:
        from backlot.auth import require_session

        session = require_session(request, get_auth_store())
        return {
            "user": {
                "user_id": session.actor.user_id,
                "username": session.actor.username,
                "system_role": session.actor.system_role,
            },
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at,
        }

    @app.post("/api/v2/auth/logout")
    async def auth_logout(request: Request) -> JSONResponse:
        from backlot.auth import SESSION_COOKIE, require_csrf, require_session

        store = get_auth_store()
        session = require_session(request, store)
        require_csrf(request, session)
        store.revoke_session(request.cookies.get(SESSION_COOKIE, ""))
        response = JSONResponse({"status": "logged_out"})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/api/projects")
    async def projects(request: Request) -> list:
        session = require_access(request)
        summaries = await asyncio.to_thread(_cached_summaries)
        if auth_mode == "test" or session.actor.system_role == "admin":
            return summaries
        from backlot.auth import authorize_project
        return [
            item for item in summaries
            if authorize_project(get_auth_store(), session.actor, item["project_id"], "read")
        ]

    @app.get("/api/project/{project_id}/state")
    async def project_state(project_id: str, request: Request) -> dict:
        require_access(request, project_id, "diagnostics")
        project_dir = _safe_project_dir(project_id)
        return await asyncio.to_thread(load_board_state, project_dir)

    @app.get("/api/v2/projects/{project_id}/operator-state")
    async def operator_project_state(project_id: str, request: Request) -> dict:
        session = require_access(request, project_id, "read")
        project_dir = _safe_project_dir(project_id)
        from backlot.auth import authorize_project
        permissions = ["view"]
        for capability, public in (
            ("edit", "edit"), ("review", "review"), ("manage_members", "manage")
        ):
            if auth_mode == "test" or authorize_project(
                get_auth_store(), session.actor, project_id, capability
            ):
                permissions.append(public)
        return await asyncio.to_thread(
            load_operator_state, project_dir, permissions=tuple(permissions)
        )

    @app.get("/api/project/{project_id}/events")
    async def project_events(project_id: str, request: Request) -> StreamingResponse:
        require_access(request, project_id, "read")
        _safe_project_dir(project_id)  # 404 early for unknown projects
        return StreamingResponse(_project_event_stream(
            project_id,
            request,
            business_facing=False,
        ), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    @app.get("/api/v2/projects/{project_id}/events")
    async def operator_project_events(project_id: str, request: Request) -> StreamingResponse:
        require_access(request, project_id, "read")
        _safe_project_dir(project_id)
        return StreamingResponse(_project_event_stream(
            project_id,
            request,
            business_facing=True,
        ), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    @app.get("/api/library/events")
    async def library_events(request: Request) -> StreamingResponse:
        require_access(request)
        async def stream():
            q = hub.subscribe()
            try:
                yield _sse({"type": "hello"})
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        changed = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        yield _sse({"type": "heartbeat", "ts": time.time()})
                        continue
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    yield _sse({"type": "change", "project_id": changed})
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    # ---- Thumbnails (downscaled, cached on disk) ------------------------

    @app.get("/thumb/{project_id}/{file_path:path}")
    async def thumb(project_id: str, file_path: str, request: Request, w: int = 640) -> FileResponse:
        require_access(request, project_id, "read")
        project_dir = _safe_project_dir(project_id)
        target = (project_dir / file_path).resolve()
        try:
            target.relative_to(project_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="path escapes project")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        width = min(THUMB_WIDTHS, key=lambda x: abs(x - w))
        cached = await asyncio.to_thread(_thumbnail_for, target, width)
        if cached is None:
            # Never fall back to raw video bytes for an <img> consumer (F-03);
            # non-thumbable images are safe to serve as-is.
            if target.suffix.lower() in {".mp4", ".webm", ".mov"}:
                raise HTTPException(status_code=404, detail="no poster frame available")
            return FileResponse(target)
        return FileResponse(cached, media_type="image/jpeg")

    # ---- Media (range requests handled by FileResponse) ---------------

    @app.get("/media/{project_id}/{file_path:path}")
    async def media(project_id: str, file_path: str, request: Request) -> FileResponse:
        require_access(request, project_id, "read")
        project_dir = _safe_project_dir(project_id)
        target = (project_dir / file_path).resolve()
        try:
            target.relative_to(project_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="path escapes project")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        return FileResponse(target)

    # ---- UI ------------------------------------------------------------

    @app.get("/login")
    async def login_page() -> HTMLResponse:
        return _ui_html("login.html", ("operator/styles.css", "operator/login.js"))

    @app.get("/setup")
    async def setup_page(request: Request) -> HTMLResponse:
        client = request.client.host if request.client else ""
        if client not in {"127.0.0.1", "::1", "testclient"} or get_auth_store().user_count() > 0:
            raise HTTPException(status_code=404, detail="not found")
        return HTMLResponse(
            '<!DOCTYPE html><html lang="zh-CN"><meta charset="UTF-8">'
            '<title>初始化项目工作台</title><body><main><h1>创建首个管理员</h1>'
            '<p>请在本机终端运行 backlot users create-admin</p></main></body></html>'
        )

    @app.get("/diagnostics/p/{project_id}")
    async def diagnostic_board_page(project_id: str, request: Request) -> HTMLResponse:
        require_access(request, project_id, "diagnostics")
        return _ui_html("board.html", ("board.css", "board.js"))

    @app.get("/p/{project_id}")
    async def board_page(project_id: str) -> HTMLResponse:
        return _ui_html(
            "operator.html",
            (
                "operator/styles.css",
                "operator/app.js",
                "operator/api.js",
                "operator/store.js",
                "operator/language.js",
                "operator/editors.js",
                "operator/impact.js",
                "operator/revisions.js",
            ),
        )

    @app.get("/p/{project_path:path}")
    async def board_page_path(project_path: str) -> HTMLResponse:
        return _ui_html(
            "operator.html",
            (
                "operator/styles.css",
                "operator/app.js",
                "operator/api.js",
                "operator/store.js",
                "operator/language.js",
                "operator/editors.js",
                "operator/impact.js",
                "operator/revisions.js",
            ),
        )

    @app.get("/")
    async def library_page() -> HTMLResponse:
        return _ui_html("index.html", ("board.css", "library.js"))

    from backlot.operator_routes import create_operator_router

    operator_router = create_operator_router(
        resolve_project=_safe_project_dir,
        projects_dir=lambda: PROJECTS_DIR,
        auth_store=get_auth_store,
        authenticate=require_access,
    )
    app.router.routes.extend(operator_router.routes)

    if UI_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    # The board is a long-lived SPA: a tab keeps running whatever board.js it
    # loaded, and browsers heuristically cache /ui assets. no-cache forces a
    # conditional revalidation (cheap 304 via ETag) on every load so UI fixes
    # show up on a plain refresh. Media/thumb responses keep normal caching.
    @app.middleware("http")
    async def ui_no_cache(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if (
            path == "/"
            or path.startswith("/ui")
            or path.startswith("/p/")
            or path.startswith("/diagnostics/")
        ):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app


def _safe_project_dir(project_id: str) -> Path:
    # ':' rejects Windows drive-relative ids like "C:" (PROJECTS_DIR / "C:"
    # collapses back to PROJECTS_DIR itself).
    if any(c in project_id for c in "/\\:") or project_id in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid project id")
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"unknown project: {project_id}")
    return project_dir


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _thumbnail_for(source: Path, width: int) -> Optional[Path]:
    """Downscale an image (or extract a video poster frame) to a cached JPEG."""
    suffix = source.suffix.lower()
    is_image = suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    is_video = suffix in {".mp4", ".webm", ".mov"}
    if not (is_image or is_video):
        return None
    try:
        import hashlib
        stat = source.stat()
        key = hashlib.sha1(
            f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode()
        ).hexdigest()[:20]
        cached = THUMB_CACHE_DIR / f"{key}.jpg"
        if cached.is_file():
            return cached
        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Unique temp per request — concurrent misses for the same source
        # must not write (and replace from) the same temp file.
        import uuid
        tmp = THUMB_CACHE_DIR / f"{key}.{uuid.uuid4().hex[:8]}.tmp.jpg"
        if is_video:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5",
                 "-i", str(source), "-frames:v", "1",
                 "-vf", f"scale={width}:-2", str(tmp)],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0 or not tmp.is_file():
                return None
        else:
            from PIL import Image
            with Image.open(source) as img:
                img = img.convert("RGB")
                img.thumbnail((width, width * 3))
                img.save(tmp, "JPEG", quality=82)
        tmp.replace(cached)
        return cached
    except Exception:
        return None


app = create_app()
