"""Dual-stream Remotion progress runner tests (P1-①)."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lib.events import read_events
from tools.base_tool import ToolCommandError
from tools.video.video_compose import VideoCompose

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_SUCCESS_SCRIPT = (
    "import sys, time\n"
    "print('bundling...', flush=True)\n"
    "print('(300/900)', flush=True)\n"
    "print('(600/900)', flush=True)\n"
    "print('Rendered 900 frames in 10.0s', flush=True)\n"
)

_FAILURE_SCRIPT = (
    "import sys\n"
    "print('(10/900)', flush=True)\n"
    "print('Error: Delayed render timed out', file=sys.stderr, flush=True)\n"
    "sys.exit(1)\n"
)


def test_parser_extracts_progress_from_stdout_and_stderr():
    state: dict = {"frame": None}
    total: list = [None]
    for line in ["(300/900)", "frame 450/900", "Rendered 900 frames", "frame 700", "50%"]:
        VideoCompose._parse_progress_line(line, state, total)
    assert state["frame"] == 900
    assert total[0] == 900

    # noise must not pollute progress
    state2: dict = {"frame": None}
    total2: list = [900]
    for line in ["2026-08-17T10:00:00Z", "path/to/900/frames", "elapsed 2s"]:
        VideoCompose._parse_progress_line(line, state2, total2)
    assert state2["frame"] is None


def test_parser_rejects_ratio_noise_but_accepts_bare_progress():
    state: dict = {"frame": None}
    total: list = [None]
    VideoCompose._parse_progress_line("450/900", state, total)
    assert state["frame"] == 450 and total[0] == 900
    # inverted ratio (2026/08 style noise) must be dropped
    state["frame"] = None
    VideoCompose._parse_progress_line("2026/08", state, total)
    assert state["frame"] is None


def test_runner_parses_stdout_progress_into_terminal_event(tmp_path: Path):
    tool = VideoCompose()
    project = tmp_path / "proj"
    project.mkdir()
    out = tmp_path / "out.mp4"
    out.write_bytes(b"x")
    result = tool._run_remotion_command(
        [sys.executable, "-c", _SUCCESS_SCRIPT],
        cwd=tmp_path,
        timeout=60,
        project_dir=project,
        run_id="r-stdout",
        operation="remotion_render",
    )
    assert result.returncode == 0
    events = read_events(project)
    run_events = [e for e in events if e.get("schema_version") == "1.0"]
    assert [e["status"] for e in run_events] == ["queued", "succeeded"]
    unit = run_events[1]["unit"]
    assert unit == {"kind": "frame", "current": 900, "total": 900}


def test_runner_surfaces_stderr_detail_on_failure(tmp_path: Path):
    tool = VideoCompose()
    project = tmp_path / "proj"
    project.mkdir()
    with pytest.raises(ToolCommandError) as excinfo:
        tool._run_remotion_command(
            [sys.executable, "-c", _FAILURE_SCRIPT],
            cwd=tmp_path,
            timeout=60,
            project_dir=project,
            run_id="r-fail",
            operation="remotion_render",
        )
    assert "Delayed render timed out" in excinfo.value.stderr
    events = read_events(project)
    run_events = [e for e in events if e.get("schema_version") == "1.0"]
    assert [e["status"] for e in run_events] == ["queued", "failed"]
    assert "Delayed render timed out" in run_events[1]["message"]
