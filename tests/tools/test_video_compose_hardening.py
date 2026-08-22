"""Contract tests for the compose hardening fixes from table-mat-mix-v7.

Regressions covered:
- project-relative media paths 404'd inside Remotion (staging resolved
  against the agent CWD instead of the project dir);
- the final-review subtitle check false-positived for pixel-burned captions
  declared via caption_render_mode/caption_source;
- a full render silently ignored an approved frame cap (sample_frames was
  dropped on the high-level render path).
"""

import subprocess
from pathlib import Path

import pytest

from tools.video.video_compose import VideoCompose


def _tiny_video(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=30",
            "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_stage_remotion_media_resolves_project_relative_source(tmp_path: Path):
    project_dir = tmp_path / "demo"
    media = project_dir / "assets" / "video" / "shot-01.mp4"
    media.parent.mkdir(parents=True)
    _tiny_video(media)
    public_dir = tmp_path / "public"
    public_dir.mkdir()

    payload = {
        "cuts": [
            {
                "id": "shot-01",
                # Project-relative asset-manifest path — the agent CWD cannot
                # resolve it, only the project dir can.
                "source": "assets/video/shot-01.mp4",
                "in_seconds": 0,
                "out_seconds": 1,
            }
        ]
    }
    staged = VideoCompose._stage_remotion_media(payload, public_dir, project_dir)
    assert staged == 1
    # The staged reference must now be the staticFile() basename, and the
    # staged copy must exist inside the public dir.
    staged_name = payload["cuts"][0]["source"]
    assert "/" not in staged_name
    assert (public_dir / staged_name).is_file()


def test_stage_remotion_media_leaves_unresolvable_source_untouched(
    tmp_path: Path,
):
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    payload = {"cuts": [{"id": "x", "source": "assets/video/missing.mp4"}]}
    staged = VideoCompose._stage_remotion_media(
        payload, tmp_path / "public", project_dir
    )
    assert staged == 0
    assert payload["cuts"][0]["source"] == "assets/video/missing.mp4"


def test_final_review_subtitle_check_accepts_declared_burned_in_captions(
    tmp_path: Path,
):
    """remotion_overlay captions burned into pixels are not a subtitle stream
    and have no sidecar file — the declaration must count as present."""
    output = tmp_path / "out.mp4"
    _tiny_video(output)

    tool = VideoCompose()
    review = tool._run_final_review(
        output,
        edit_decisions={
            "render_runtime": "remotion",
            "renderer_family": "product-reveal",
            "subtitles": {"enabled": True, "source": "artifacts/final_props.json"},
            "caption_render_mode": "remotion_overlay",
            "caption_source": "artifacts/final_props.json#captions",
            "safe_zone_profile": "douyin_9_16",
        },
    )
    sub_check = review["checks"]["subtitle_check"]
    assert sub_check["subtitles_expected"] is True
    assert sub_check["subtitles_present"] is True
    assert sub_check["detection"] == "declared_burned_in"
    assert not any("Subtitles expected but not found" in i for i in review.get("issues_found", []))


def test_final_review_subtitle_check_still_flags_undeclared_missing(
    tmp_path: Path,
):
    output = tmp_path / "out.mp4"
    _tiny_video(output)

    tool = VideoCompose()
    review = tool._run_final_review(
        output,
        edit_decisions={
            "render_runtime": "remotion",
            "renderer_family": "product-reveal",
            "subtitles": {"enabled": True},
        },
    )
    sub_check = review["checks"]["subtitle_check"]
    assert sub_check["subtitles_present"] is False
    assert any(
        "Subtitles expected but not found" in i
        for i in sub_check["issues"]
    )


def test_render_path_forwards_sample_frames_and_pixel_format(monkeypatch):
    """The high-level render path must forward the frame cap and pixel format
    to _remotion_render — previously both were silently dropped, so a full
    render padded past the approved timeline and emitted yuvj420p."""
    forwarded: dict = {}

    class FakeCompose(VideoCompose):
        def _remotion_available(self) -> bool:
            return True

        def _needs_remotion(self, cuts):
            return True

        def _remotion_render(self, inputs):
            forwarded.update(inputs)
            from tools.base_tool import ToolResult
            return ToolResult(success=True, data={"output": inputs.get("output_path", "x")})

        def _run_final_review(self, *args, **kwargs):
            return {"status": "pass", "checks": {}, "issues_found": []}

    tool = FakeCompose()
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    result = tool.execute(
        {
            "operation": "render",
            "output_path": str(Path("projects/demo/renders/final.mp4")),
            "edit_decisions": {
                "version": "1.0",
                "render_runtime": "remotion",
                "renderer_family": "product-reveal",
                "cuts": [
                    {"id": "c1", "source": "a.mp4", "in_seconds": 0, "out_seconds": 1}
                ],
            },
            "asset_manifest": {"assets": []},
            "render_plan": {"mode": "full"},
            "profile": "social_vertical_1080p30",
            "sample_frames": "0-449",
            "pixel_format": "yuv420p",
        }
    )
    assert result.success
    assert forwarded.get("sample_frames") == "0-449"
    assert forwarded.get("pixel_format") == "yuv420p"
