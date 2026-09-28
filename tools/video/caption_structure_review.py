"""Local evidence-only crop review of the exact approved s01 candidate."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from lib.caption_structure_review import classify_structure
from lib.masked_caption_media import (
    FPS, HEIGHT, MAX_CANDIDATE_BYTES, PADDED_FRAMES, SOURCE_FRAMES, WIDTH,
    stream_rgb, validate_contract, verify_pilot_source, verify_video,
)
from tools.base_tool import BaseTool, ResourceProfile, ToolResult, ToolStability, ToolTier
from tools.video.temporal_caption_repair import _capture, _file_path, _output_path, _source_hash

CANDIDATE_SHA256 = "e2346ec5a1b18e4f8e1f6cb3fb2bd9ef377a4186dbbe717c64000d50f32305df"
BANNER = "PROPOSAL ONLY - NOT REPAIRED VIDEO"
COLORS = np.array([[0, 0, 0], [255, 64, 64], [32, 220, 96], [255, 210, 0]], np.uint8)


def _strip(source, candidate, labels, index):
    height, width = source.shape[:2]
    overlay = source.copy()
    marked = labels != 0
    overlay[marked] = np.rint(.55 * source[marked] + .45 * COLORS[labels[marked]]).astype(np.uint8)
    canvas = Image.new("RGB", (3 * width, height + 64), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 5), f"{BANNER} | SOURCE {index:02d} / CANDIDATE {index + 21:02d}", fill="white")
    draw.text((8, 22), "RED: text risk | GREEN: possible preservation, UNAPPROVED | YELLOW: uncertain", fill="white")
    for column, (title, pixels) in enumerate((("SOURCE", source), ("COLORED OVERLAY ONLY", overlay), ("CANDIDATE", candidate))):
        draw.text((column * width + 8, 43), title, fill="white")
        canvas.paste(Image.fromarray(pixels), (column * width, 64))
    return canvas


def _save_png(image, path):
    with path.open("xb") as handle:
        image.save(handle, format="PNG")


class CaptionStructureReview(BaseTool):
    name = "caption_structure_review"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "local"
    stability = ToolStability.EXPERIMENTAL
    dependencies = ["python:numpy", "python:cv2", "python:PIL", "cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = "Install NumPy, OpenCV, Pillow, FFmpeg and ffprobe."
    capabilities = ["unapproved_caption_structure_evidence"]
    best_for = ["Evidence review of the exact approved s01 gray127 candidate"]
    not_good_for = ["Source restoration", "text-removal acceptance", "production output"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=512, disk_mb=500, network_required=False)
    side_effects = ["Creates a new output directory with unapproved overlay evidence"]
    user_visible_verification = ["Review all proposals; labels do not prove background or approve restoration"]
    input_schema = {"type": "object", "required": ["contract_path", "candidate_path", "output_dir", "diagnostic_only"],
                    "properties": {"contract_path": {"type": "string"}, "candidate_path": {"type": "string"},
                                   "output_dir": {"type": "string"}, "diagnostic_only": {"const": True}}}

    def execute(self, inputs):
        started = time.monotonic()
        try:
            if not isinstance(inputs, dict) or inputs.get("diagnostic_only") is not True:
                raise ValueError("diagnostic_only must be literal true")
            self.check_dependencies()
            contract_path = _file_path(inputs.get("contract_path"), "contract_path")
            if contract_path.stat().st_size > 1024 * 1024:
                raise ValueError("contract exceeds 1 MiB")
            header = json.loads(contract_path.read_text(encoding="utf-8"))
            if header.get("version") != 2 or header.get("input_preprocessing") != "vace_gray127":
                raise ValueError("structure review requires version 2 gray127 contract")
            candidate = _file_path(inputs.get("candidate_path"), "candidate_path")
            output = _output_path(inputs.get("output_dir"), contract_path, candidate)
            if candidate.stat().st_size > MAX_CANDIDATE_BYTES:
                raise ValueError("candidate exceeds 100 MiB")
            if _source_hash(candidate) != CANDIDATE_SHA256:
                raise ValueError("candidate hash differs from exact approved evidence candidate")
            verify_video(candidate, WIDTH, HEIGHT, FPS, PADDED_FRAMES)
            contract = validate_contract(contract_path)
            source, mask_path = Path(contract["source"]["path"]), Path(contract["mask"]["path"])
            _output_path(output, source, mask_path)
            mask = verify_pilot_source(source, mask_path)
            ys, xs = np.nonzero(mask)
            x0, y0 = max(0, int(xs.min()) - 60), max(0, int(ys.min()) - 60)
            x1, y1 = min(WIDTH, int(xs.max()) + 61), min(HEIGHT, int(ys.max()) + 61)
            width, height = x1 - x0, y1 - y0
            if width * height > 100000 or min(width, height) < 7:
                raise ValueError("crop exceeds bounded structure review geometry")
            crops = []
            for media, count, limit in ((source, SOURCE_FRAMES, SOURCE_FRAMES), (candidate, PADDED_FRAMES, None)):
                crop = np.empty((SOURCE_FRAMES, height, width, 3), np.uint8)
                decoder = stream_rgb(media, WIDTH, HEIGHT, expected_frames=count, limit_frames=limit)
                try:
                    for index, frame in enumerate(decoder):
                        target = index if media == source else index - 21
                        if 0 <= target < SOURCE_FRAMES:
                            crop[target] = frame[y0:y1, x0:x1]
                finally:
                    decoder.close()
                crops.append(crop)
            allowed = mask[y0:y1, x0:x1]
            labels, stats = classify_structure(crops[0], crops[1], allowed)
            classified_at = time.monotonic()
            # Nothing is written before all contract, geometry, and stream checks pass.
            output.mkdir(exist_ok=False)
            strips, sheets = [], []
            for index in range(SOURCE_FRAMES):
                path = output / f"frame-{index:02d}-proposal.png"
                _save_png(_strip(crops[0][index], crops[1][index], labels[index], index), path)
                strips.append(path)
            for first in range(0, SOURCE_FRAMES, 5):
                group = strips[first:first + 5]
                sheet = Image.new("RGB", (width * 3, (height + 64) * len(group)))
                for row, path in enumerate(group):
                    with Image.open(path) as image:
                        sheet.paste(image, (0, row * (height + 64)))
                path = output / f"contact-{first // 5:02d}-proposal.png"
                _save_png(sheet, path)
                sheets.append(path)
            proposals = output / "unapproved-label-proposals.npz"
            with proposals.open("xb") as handle:
                np.savez_compressed(handle, labels=labels, allowed_mask=allowed,
                                    crop_xyxy_exclusive=np.array([x0, y0, x1, y1], np.int32))
            video = output / "overlay-diagnostic.mp4"
            video_width, video_height = width * 3 + (width * 3) % 2, height + 64 + (height + 64) % 2

            _capture(["ffmpeg", "-hide_banner", "-loglevel", "error", "-n",
                      "-protocol_whitelist", "file,pipe", "-framerate", str(FPS), "-start_number", "0",
                      "-i", str(output / "frame-%02d-proposal.png"), "-frames:v", str(SOURCE_FRAMES),
                      "-vf", f"pad={video_width}:{video_height}:0:0", "-an", "-sn",
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                      "-movflags", "+faststart", str(video)], limit=256 * 1024, timeout=120)
            verify_video(video, video_width, video_height, FPS, SOURCE_FRAMES)
            hashes = {"source": _source_hash(source), "mask": _source_hash(mask_path),
                      "candidate": _source_hash(candidate), "contract": _source_hash(contract_path)}
            if (hashes["source"] != contract["source"]["sha256"] or hashes["mask"] != contract["mask"]["sha256"]
                    or hashes["candidate"] != CANDIDATE_SHA256):
                raise ValueError("immutable input changed during review")
            commit = _capture(["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],
                              limit=256, timeout=10).decode().strip()
            outputs = [*strips, *sheets, proposals, video]
            report = {"tool": self.name, "version": self.version, "code_commit": commit,
                      "proposal_only": True, "diagnostic_only": True, "overlay_only": True,
                      "approved_for_restore": False, "accepted_for_production": False,
                      "disclaimers": [BANNER, "Heuristics are not semantic truth.",
                                      "Green is possible preservation pending human review; NPZ is not a release mask."],
                      "acceptance": {"text": "unknown", "temporal": "unknown", "geometry": "unknown"},
                      "input_hashes": hashes, "crop_xyxy_exclusive": [x0, y0, x1, y1],
                      "evidence_frames": SOURCE_FRAMES, "fps": FPS, "audio": "absent",
                      "frame_map": [{"source": i, "candidate": i + 21} for i in range(SOURCE_FRAMES)],
                      "thresholds": stats["thresholds"], "per_frame_counts": stats["per_frame_counts"],
                      "classification": stats, "frame_strips": [str(p) for p in strips],
                      "contact_sheets": [str(p) for p in sheets], "label_proposals": str(proposals),
                      "overlay_diagnostic_video": str(video),
                      "timing_seconds": {"validation_and_classification": round(classified_at - started, 3),
                                         "total": round(time.monotonic() - started, 3)},
                      "outputs": [{"path": str(p), "sha256": _source_hash(p)} for p in outputs]}
            report_path = output / "report.json"
            with report_path.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)
            artifacts = [str(report_path), *[str(p) for p in outputs]]
            return ToolResult(success=True, data={"report_path": str(report_path), "artifacts": artifacts,
                "proposal_only": True, "approved_for_restore": False, "accepted_for_production": False},
                artifacts=artifacts, duration_seconds=round(time.monotonic() - started, 3))
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), duration_seconds=round(time.monotonic() - started, 3))
