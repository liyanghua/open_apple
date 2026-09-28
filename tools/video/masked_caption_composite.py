"""Fixed s01 masked-caption preparation and local review composition."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from lib.masked_boundary_match import MaskedBoundaryMatcher
from lib.masked_caption_media import (
    FPS, HEIGHT, PADDED_FRAMES, SOURCE_FRAMES, WIDTH, composite_frame,
    encode_rgb, padding_map, precondition_frame, stream_rgb, validate_contract, verify_pilot_source,
    verify_video,
)
from tools.base_tool import BaseTool, ResourceProfile, ToolResult, ToolStability, ToolTier
from tools.video.temporal_caption_repair import _capture, _file_path, _output_path, _source_hash


class MaskedCaptionComposite(BaseTool):
    name = "masked_caption_composite"
    version = "0.3.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "local"
    stability = ToolStability.EXPERIMENTAL
    dependencies = ["python:numpy", "python:cv2", "cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = "Install NumPy, OpenCV, FFmpeg and ffprobe."
    capabilities = ["s01_masked_caption_prepare", "s01_masked_caption_composite"]
    best_for = ["Approved s01 38-frame masked-caption review trial"]
    not_good_for = ["Batch shots", "whole-frame generated video", "production acceptance"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, disk_mb=2000, network_required=False)
    side_effects = ["Creates a new directory containing immutable trial media and review evidence"]
    user_visible_verification = ["Review all 38 frames and the normal and half-speed videos before accepting"]
    input_schema = {"type": "object", "required": ["action", "output_dir"],
                    "properties": {"action": {"enum": ["prepare", "composite"]},
                                   "input_path": {"type": "string"}, "mask_path": {"type": "string"},
                                   "single_shot_verified": {"const": True},
                                   "input_preprocessing": {"enum": ["source_rgb", "vace_gray127"]},
                                   "contract_path": {"type": "string"},
                                   "candidate_path": {"type": "string"},
                                   "blend_mode": {"enum": ["hard", "boundary_match"]},
                                   "output_dir": {"type": "string"}}}

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.monotonic()
        try:
            self.check_dependencies()
            if not isinstance(inputs, dict):
                raise ValueError("inputs must be a dictionary")
            action = inputs.get("action")
            if action == "prepare":
                data = self._prepare(inputs)
            elif action == "composite":
                data = self._composite(inputs)
            else:
                raise ValueError("action must be prepare or composite")
            return ToolResult(success=True, data=data, artifacts=data["artifacts"],
                              duration_seconds=round(time.monotonic() - started, 3))
        except Exception as exc:
            return ToolResult(success=False, error=str(exc),
                              duration_seconds=round(time.monotonic() - started, 3))

    @staticmethod
    def _prepare(inputs: dict) -> dict:
        if inputs.get("single_shot_verified") is not True:
            raise ValueError("single_shot_verified must be literal true")
        source = _file_path(inputs.get("input_path"), "input_path")
        mask_path = _file_path(inputs.get("mask_path"), "mask_path")
        output = _output_path(inputs.get("output_dir"), source, mask_path)
        mask = verify_pilot_source(source, mask_path)
        mode = inputs.get("input_preprocessing", "source_rgb")
        if mode not in {"source_rgb", "vace_gray127"}:
            raise ValueError("unsupported input preprocessing")
        output.mkdir(exist_ok=False)
        padded_input = output / "input-padded.mp4"
        padded_mask = output / "mask-padded.mp4"

        def source_frames():
            original = stream_rgb(source, WIDTH, HEIGHT, expected_frames=SOURCE_FRAMES, limit_frames=SOURCE_FRAMES)
            try:
                first = precondition_frame(next(original), mask, mode)
                for _ in range(21):
                    yield first
                yield first
                last = first
                for frame in original:
                    last = precondition_frame(frame, mask, mode)
                    yield last
                for _ in range(22):
                    yield last
            finally:
                original.close()

        encode_rgb(padded_input, source_frames(), WIDTH, HEIGHT, FPS, codec="h264rgb")
        white = (mask.astype(np.uint8) * 255)
        mask_rgb = np.repeat(white[:, :, None], 3, axis=2)
        encode_rgb(padded_mask, (mask_rgb for _ in range(PADDED_FRAMES)), WIDTH, HEIGHT, FPS, codec="h264rgb")
        verify_video(padded_input, WIDTH, HEIGHT, FPS, PADDED_FRAMES)
        verify_video(padded_mask, WIDTH, HEIGHT, FPS, PADDED_FRAMES)
        contract = {
            "version": 2 if mode == "vace_gray127" else 1,
            "pilot": "s01_wan_vace14b_once",
            "source": {"path": str(source), "sha256": _source_hash(source), "frame_interval": [0, 38]},
            "mask": {"path": str(mask_path), "sha256": _source_hash(mask_path), "polarity": "255=replace"},
            "frame_map": padding_map(),
            "geometry": [WIDTH, HEIGHT], "fps": FPS, "padded_frames": PADDED_FRAMES,
            "input_video": {"path": str(padded_input), "sha256": _source_hash(padded_input)},
            "mask_video": {"path": str(padded_mask), "sha256": _source_hash(padded_mask)},
            "encoding": "libx264rgb-crf0", "audio": "absent",
        }
        if mode == "vace_gray127":
            contract["input_preprocessing"] = mode
        contract_path = output / "repair_contract.json"
        with contract_path.open("x", encoding="utf-8") as handle:
            json.dump(contract, handle, indent=2)
        validate_contract(contract_path)
        contract_path.chmod(0o444)
        evidence = _contact_sheets(source, mask, output, prefix="source-mask-coverage", overlay_mask=True,
                                   limit_frames=SOURCE_FRAMES)
        artifacts = [str(contract_path), str(padded_input), str(padded_mask), *(str(p) for p in evidence)]
        return {"contract_path": str(contract_path), "artifacts": artifacts,
                "mask_coverage_evidence": [str(p) for p in evidence], "evidence_frames": SOURCE_FRAMES,
                "accepted_for_production": False}

    @staticmethod
    def _composite(inputs: dict) -> dict:
        blend_mode = inputs.get("blend_mode", "hard")
        if blend_mode not in ("hard", "boundary_match"):
            raise ValueError("unsupported blend_mode")
        contract_path = _file_path(inputs.get("contract_path"), "contract_path")
        contract = validate_contract(contract_path)
        if blend_mode == "boundary_match" and contract["version"] != 2:
            raise ValueError("boundary_match requires a version 2 gray-preconditioned contract")
        source = Path(contract["source"]["path"])
        mask_path = Path(contract["mask"]["path"])
        candidate = _file_path(inputs.get("candidate_path"), "candidate_path")
        if candidate.stat().st_size > 100 * 1024 * 1024:
            raise ValueError("candidate exceeds 100 MiB")
        verify_video(candidate, WIDTH, HEIGHT, FPS, PADDED_FRAMES)
        output = _output_path(inputs.get("output_dir"), source, mask_path)
        mask = verify_pilot_source(source, mask_path)
        matcher = MaskedBoundaryMatcher(mask) if blend_mode == "boundary_match" else None
        correction_stats = []
        output.mkdir(exist_ok=False)
        master = output / "master.mkv"

        def merged_frames():
            original = stream_rgb(source, WIDTH, HEIGHT, expected_frames=SOURCE_FRAMES, limit_frames=SOURCE_FRAMES)
            generated = stream_rgb(candidate, WIDTH, HEIGHT, expected_frames=PADDED_FRAMES)
            try:
                for _ in range(21):
                    next(generated)
                for source_frame in original:
                    candidate_frame = next(generated)
                    if matcher is None:
                        yield composite_frame(source_frame, candidate_frame, mask)
                    else:
                        matched, stats = matcher.apply(source_frame, candidate_frame)
                        correction_stats.append(stats)
                        yield matched
                for _ in range(22):
                    next(generated)
                if next(generated, None) is not None:
                    raise ValueError("candidate has extra frames")
            finally:
                original.close()
                generated.close()

        encode_rgb(master, merged_frames(), WIDTH, HEIGHT, FPS, codec="ffv1")
        verify_video(master, WIDTH, HEIGHT, FPS, SOURCE_FRAMES)
        original = stream_rgb(source, WIDTH, HEIGHT, expected_frames=SOURCE_FRAMES, limit_frames=SOURCE_FRAMES)
        decoded = stream_rgb(master, WIDTH, HEIGHT, expected_frames=SOURCE_FRAMES)
        try:
            for index in range(SOURCE_FRAMES):
                source_frame, result_frame = next(original), next(decoded)
                if not np.array_equal(source_frame[~mask], result_frame[~mask]):
                    raise ValueError(f"master changed pixels outside glyph mask in frame {index}")
            for decoder in (original, decoded):
                if next(decoder, None) is not None:
                    raise ValueError("master or source has extra frames")
        finally:
            original.close()
            decoded.close()

        review = output / "review.mp4"
        comparison = output / "comparison.mp4"
        slow = output / "comparison-slow.mp4"
        _run_ffmpeg(["-i", str(master), "-map", "0:v:0", "-an", "-c:v", "libx264",
                     "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(review)])
        filters = ("[0:v]trim=start_frame=0:end_frame=38,setpts=PTS-STARTPTS[s];"
                   "[1:v]trim=start_frame=21:end_frame=59,setpts=PTS-STARTPTS[c];"
                   "[2:v]setpts=PTS-STARTPTS[m];[s][c][m]hstack=inputs=3[v]")
        _run_ffmpeg(["-i", str(source), "-i", str(candidate), "-i", str(master),
                     "-filter_complex", filters, "-map", "[v]", "-frames:v", "38", "-an",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                     "-pix_fmt", "yuv420p", str(comparison)])
        _run_ffmpeg(["-i", str(comparison), "-vf", "setpts=2*(PTS-STARTPTS)",
                     "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                     "-pix_fmt", "yuv420p", str(slow)])
        sheets = _contact_sheets(master, mask, output)
        candidate_hash = _source_hash(candidate)
        provider_state = {}
        provider_state_path = candidate.parent / "attempt_state.json"
        if provider_state_path.is_file() and not provider_state_path.is_symlink():
            state = json.loads(provider_state_path.read_text())
            if state.get("candidate_sha256") == candidate_hash and state.get("contract_path") == str(contract_path):
                provider_state = state
        code_commit = bytes(_capture(["git", "-C", str(Path(__file__).resolve().parents[2]),
                                      "rev-parse", "HEAD"], limit=256, timeout=10)).decode().strip()
        report = {
            "contract_passed": True, "outside_mask_exact": True,
            "blend_mode": blend_mode,
            "alignment_status": "unverified", "visual_review_status": "pending",
            "accepted_for_production": False, "provenance": "generative_reconstruction",
            "source_sha256": contract["source"]["sha256"], "mask_sha256": contract["mask"]["sha256"],
            "input_video_sha256": contract["input_video"]["sha256"],
            "mask_video_sha256": contract["mask_video"]["sha256"],
            "candidate_sha256": candidate_hash, "master_sha256": _source_hash(master),
            "frame_map": padding_map(), "frames_verified": SOURCE_FRAMES,
            "billing_status": "unknown; see project cost ledger",
            "model_version": "provider_unreported",
            "endpoint": "fal-ai/wan-vace-14b/inpainting", "request_id": provider_state.get("request_id"),
            "generation_settings": provider_state.get("generation_settings", {}),
            "code_commit": code_commit, "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_decode": {"pixel_format": "rgb24", "autorotate": False, "vsync": 0},
            "comparison_columns": ["source", "candidate", "composite"],
            "review_proxy_lossy_not_pixel_verified": True,
            "outputs": {p.name: {"path": str(p), "sha256": _source_hash(p)}
                        for p in (master, review, comparison, slow, *sheets)},
        }
        if matcher is not None:
            report["boundary_match"] = {
                "method": "harmonic_exterior_delta_matrix_free_cg",
                "source_glyph_pixels_used": False,
                "mask_expanded": False, "temporal_smoothing": False,
                "frames": correction_stats,
            }
        report_path = output / "report.json"
        with report_path.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        artifacts = [str(p) for p in (master, review, comparison, slow, *sheets, report_path)]
        return {"report": report, "artifacts": artifacts}


def _run_ffmpeg(arguments: list[str]) -> None:
    _capture(["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-noautorotate", *arguments],
             limit=0, timeout=120)


def _contact_sheets(master: Path, mask: np.ndarray, output: Path, *, prefix="contact-sheet",
                    overlay_mask=False, limit_frames=None) -> list[Path]:
    import cv2

    ys, xs = np.where(mask)
    left, right = max(0, int(xs.min()) - 60), min(WIDTH, int(xs.max()) + 61)
    top, bottom = max(0, int(ys.min()) - 60), min(HEIGHT, int(ys.max()) + 61)
    tiles, paths = [], []
    frames = stream_rgb(master, WIDTH, HEIGHT, expected_frames=SOURCE_FRAMES, limit_frames=limit_frames)
    try:
        for index, frame in enumerate(frames):
            crop = frame[top:bottom, left:right].copy()
            if overlay_mask:
                overlay = crop.copy()
                local_mask = mask[top:bottom, left:right]
                overlay[local_mask] = (255, 0, 180)
                crop = np.concatenate([crop, overlay], axis=1)
            title = np.zeros((24, crop.shape[1], 3), dtype=np.uint8)
            cv2.putText(title, f"source frame {index:02d}" if overlay_mask else f"composite frame {index:02d}",
                        (5, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            tiles.append(np.concatenate([title, crop], axis=0))
            if len(tiles) == 10 or index == SOURCE_FRAMES - 1:
                blank = np.zeros_like(tiles[0])
                padded = tiles + [blank] * (10 - len(tiles))
                rows = [np.concatenate(padded[j:j + 5], axis=1) for j in (0, 5)]
                sheet = np.concatenate(rows, axis=0)
                path = output / f"{prefix}-{len(paths) + 1:02d}.png"
                if not cv2.imwrite(str(path), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR)):
                    raise ValueError("contact sheet write failed")
                paths.append(path)
                tiles = []
    finally:
        frames.close()
    return paths
