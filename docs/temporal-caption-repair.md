# Temporal caption repair diagnostic

`temporal_caption_repair` is an experimental, local `video_post` tool. It borrows source RGB pixels from other frames in one caller-verified continuous shot. It does not infer hidden ground truth, edit audio, approve an asset, or advance a production checkpoint.

## Input contract

Call the discovered registry tool with:

```python
from tools.tool_registry import registry

registry.discover()
tool = registry.get("temporal_caption_repair")
result = tool.execute({
    "input_path": "/absolute/path/to/source.mkv",
    "mask_path": "/absolute/path/to/mask.pgm",
    "start_frame": 0,
    "end_frame_exclusive": 38,
    "output_dir": "/absolute/path/to/new-diagnostic-directory",
    "single_shot_verified": True,
    "min_coverage": 0.98,
    "max_donors": 12,
})
```

`single_shot_verified` must be the literal boolean `True`; the tool cannot detect cuts or prove the interval is one shot. The interval is zero-based and half-open. The mask is one 8-bit binary P5 PGM image of the exact decoded width and height, with `0` for unaffected pixels and `255` for the caption region. The adapter converts it to a boolean mask for the core. It must be nonempty and cover at most 10% of each frame. The source and mask must be local regular files. The output directory must have an existing, non-symlink parent and must not already exist. It is reserved exclusively, without overwrite.

The interval is limited to 1–120 frames, 2,100,000 pixels per frame, and 40,000,000 total decoded pixels. The shared core resource estimator also rejects combined dimensions that exceed its conservative 1 GiB working-memory target. These gates run before the adapter decodes source frames. FFprobe metadata runs first; a separate bounded per-frame scan then proves the frame timestamps, count, and constant geometry. Inconsistent or unavailable timing proof, variable frame rate, invalid frame intervals, and mismatched masks fail closed. FFmpeg and FFprobe only receive local `file` and `pipe` protocols for source reads.

## Outputs and interpretation

Successful execution creates `master.mkv` (lossless FFV1), `review.mp4` (lossy H.264 diagnostic review proxy), and `report.json`. Neither video has audio or subtitles added; these are not audiovisual replacements. The proxy may still contain original caption pixels wherever evidence was insufficient. `master.mkv` is decoded frame by frame after encoding, and every RGB pixel outside the mask must equal the decoded source pixel. The lossy proxy is labelled separately and is not claimed pixel exact.

The report includes source and mask SHA-256 hashes, source interval, count, geometry, frame rate, per-stage elapsed time, full core evidence and compressed donor assignment maps, and verification results. Its `provider` is `local`, `model` is `none`, `human_review_required` is always `true`, and `accepted_for_production` is always `false`. A completed run returns `ToolResult.success=True` even if reconstruction is partial or impossible; read `status` and `coverage_gate_passed` for quality. `candidate_requires_visual_review` means all masked pixels received supported source copies. `partial_requires_visual_review` means some did. `insufficient_evidence` means none did. Errors return `success=False`; if the adapter already owns the new output directory, it retains artifacts and writes `error.json` for diagnosis.

No status is automatic approval. A numerical coverage pass cannot prove the hidden original image. Parallax, occlusion, camera changes, old text shadows, table edges, temporal flicker, and donor ghosting require human visual rejection when present. Donors must remain inside the verified single shot; cross-shot borrowing is forbidden.

## Release gate

1. Run `/Users/yichen/Desktop/open_source_vedio_gen_projects/OpenMontage-main/.venv/bin/python -m pytest tests/lib/test_temporal_caption_repair.py tests/tools/test_temporal_caption_repair.py tests/tools/test_base_tool_dependencies.py tests/tools/test_frame_sampler_cache.py -q`.
2. Confirm the result is discoverable in the registry, reports local zero-cost experimental status, and fails closed when dependencies are absent.
3. For each proposed production interval, inspect the original and diagnostic at the start, middle, and end; sample at least six repaired frames and play the entire shot at normal speed. Compare old glyphs/shadows, texture, edges, flicker, and ghosting.
4. Verify the interval really is one shot and inspect `report.json` coverage, donor evidence, source hashes, exact outside-mask master check, and unresolved regions. Preserve failed diagnostics; seek separate human approval before any production use or batch expansion.
