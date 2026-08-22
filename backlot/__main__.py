"""Backlot CLI.

    python -m backlot open [project-id]   # start server if needed, open browser
    python -m backlot serve [--port N]    # run the server in the foreground

``open`` is idempotent and non-fatal by design: agents call it at pipeline
initialization and must continue the production even if it fails.
"""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from backlot import DEFAULT_PORT


def _port() -> int:
    try:
        return int(os.environ.get("BACKLOT_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def _server_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _spawn_server(port: int) -> None:
    """Start the server as a detached background process."""
    cmd = [sys.executable, "-m", "backlot", "serve", "--port", str(port)]
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def cmd_open(project_id: str | None) -> int:
    port = _port()
    if not _server_alive(port):
        try:
            _spawn_server(port)
        except Exception as exc:
            print(f"backlot: could not start server ({exc}) — continuing without the board")
            return 1
        deadline = time.time() + 15
        while time.time() < deadline:
            if _server_alive(port):
                break
            time.sleep(0.4)
        else:
            print("backlot: server did not come up in time — continuing without the board")
            return 1
    url = f"http://127.0.0.1:{port}/"
    if project_id:
        url = f"http://127.0.0.1:{port}/p/{project_id}"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(f"backlot: {url}")
    return 0


def cmd_serve(port: int, host: str = "127.0.0.1") -> int:
    import uvicorn

    if host not in {"127.0.0.1", "::1", "localhost"}:
        from backlot.auth_store import AuthStore

        allowed = os.environ.get("BACKLOT_ALLOWED_ORIGINS", "").strip()
        store = AuthStore(_data_dir() / "backlot.db")
        store.initialize()
        if not allowed or store.user_count() == 0:
            print("backlot: 非本机监听需要已创建管理员并配置 BACKLOT_ALLOWED_ORIGINS")
            return 1
        print("backlot: 警告：正在可信内网地址启动，请确认网络访问边界")
    uvicorn.run("backlot.server:app", host=host, port=port, log_level="warning")
    return 0


def _data_dir() -> Path:
    configured = os.environ.get("BACKLOT_DATA_DIR")
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parents[1] / ".backlot"


def cmd_create_admin(username: str) -> int:
    from backlot.auth_store import AuthStore

    password = getpass.getpass("管理员密码：")
    confirmation = getpass.getpass("再次输入密码：")
    if password != confirmation:
        print("backlot: 两次密码不一致")
        return 1
    store = AuthStore(_data_dir() / "backlot.db")
    store.initialize()
    try:
        store.create_user(username, password, "admin")
    except ValueError as exc:
        print(f"backlot: 无法创建管理员（{exc}）")
        return 1
    print("backlot: 管理员已创建")
    return 0


def cmd_validate(project_id: str, *, refresh: bool = False) -> int:
    """校验一个项目全链：检查点信封一致性 + artifact schema + 派生文件。

    --refresh 时先把漂移的信封从磁盘制品重建（history 归档）再校验。
    """
    from lib.checkpoint import (
        CheckpointValidationError,
        get_completed_stages,
        read_checkpoint,
        refresh_checkpoint_envelopes,
    )
    from lib.paths import PROJECTS_DIR

    pipeline_dir = Path(PROJECTS_DIR)
    project_dir = pipeline_dir / project_id
    if not (project_dir / "project.json").is_file():
        print(f"backlot validate: project not found: {project_dir}")
        return 2

    if refresh:
        report = refresh_checkpoint_envelopes(
            pipeline_dir, project_id, pipeline_type="cinematic-fast"
        )
        if report:
            print("backlot validate: 信封已刷新（history 已归档）:")
            for stage, names in report.items():
                print(f"  {stage}: {', '.join(names)}")
        else:
            print("backlot validate: 无漂移信封，无需刷新")

    failures: list[str] = []
    stages = get_completed_stages(pipeline_dir, project_id, "cinematic-fast")
    for stage in stages:
        try:
            read_checkpoint(pipeline_dir, project_id, stage)
            print(f"backlot validate: {stage:>12} VALID")
        except CheckpointValidationError as exc:
            failures.append(f"{stage}: {exc}")
            print(f"backlot validate: {stage:>12} INVALID — {exc}")

    # B3：research 派生证据文件完整性（独立于检查点状态的额外体检）。
    try:
        from lib.research_validation import validate_research_derived_files

        artifacts = {}
        for name in (
            "research_breakdown", "reference_source_matrix", "caption_style_fingerprint",
        ):
            path = project_dir / "artifacts" / f"{name}.json"
            if path.is_file():
                import json as _json

                artifacts[name] = _json.loads(path.read_text(encoding="utf-8"))
        validate_research_derived_files(project_dir, artifacts)
        print("backlot validate: research 派生证据文件 OK")
    except Exception as exc:
        failures.append(f"derived-files: {exc}")
        print(f"backlot validate: research 派生证据文件缺失 — {exc}")

    if failures:
        print(f"backlot validate: {len(failures)} 项校验失败")
        return 1
    print(f"backlot validate: {project_id} 全链 VALID（{len(stages)} 检查点）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backlot", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    p_open = sub.add_parser("open", help="open the board in the browser (starts server if needed)")
    p_open.add_argument("project_id", nargs="?", default=None)

    p_serve = sub.add_parser("serve", help="run the Backlot server in the foreground")
    p_serve.add_argument("--port", type=int, default=_port())
    p_serve.add_argument("--host", default=os.environ.get("BACKLOT_HOST", "127.0.0.1"))

    p_users = sub.add_parser("users", help="manage Backlot users")
    users_sub = p_users.add_subparsers(dest="users_command")
    p_admin = users_sub.add_parser("create-admin", help="create an administrator")
    p_admin.add_argument("--username", required=True)

    p_validate = sub.add_parser(
        "validate",
        help="校验项目全链（检查点信封 / artifact schema / research 派生文件）",
    )
    p_validate.add_argument("project_id")
    p_validate.add_argument(
        "--refresh", action="store_true",
        help="先重建漂移信封（history 归档）再校验",
    )

    args = parser.parse_args(argv)
    if args.command == "open":
        return cmd_open(args.project_id)
    if args.command == "serve":
        return cmd_serve(args.port, args.host)
    if args.command == "users" and args.users_command == "create-admin":
        return cmd_create_admin(args.username)
    if args.command == "validate":
        return cmd_validate(args.project_id, refresh=args.refresh)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
