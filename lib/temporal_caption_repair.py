"""Conservative, offline temporal copying for explicitly masked burned captions.

Only supplied, unmodified RGB frames are donors. This is a candidate generator,
not an inpainting engine or production acceptance gate. Local affine registration
cannot prove the content of an occluded scene; human inspection remains required.
Large motions, wide masks, parallax, low texture and occlusion deliberately leave
pixels unresolved. No transform chains, extrapolation, blending or spatial fill.
"""

from __future__ import annotations

import base64
import math
import numbers
import zlib

import cv2
import numpy as np


MAX_FRAMES = 120
MAX_FRAME_PIXELS = 2_100_000
MAX_TOTAL_PIXELS = 40_000_000
MAX_DONORS = 12
TRACKING_RADIUS = 26  # LK 21x21, level 1, pyramid/derivative/bilinear support.
LOCAL_RADIUS = 64
EVIDENCE_RADIUS = 12


def _validate(frames, masks, min_coverage, max_donors):
    if not isinstance(frames, np.ndarray) or frames.dtype != np.uint8:
        raise TypeError("frames must be a uint8 RGB ndarray")
    if frames.ndim != 4 or frames.shape[-1] != 3 or min(frames.shape[:3]) < 1:
        raise ValueError("frames must have nonempty shape [N,H,W,3]")
    count, height, width = frames.shape[:3]
    if count > MAX_FRAMES or height * width > MAX_FRAME_PIXELS or count * height * width > MAX_TOTAL_PIXELS:
        raise ValueError("source context exceeds frame/pixel limit")
    if (isinstance(min_coverage, (bool, np.bool_)) or not isinstance(min_coverage, numbers.Real)
            or not math.isfinite(min_coverage) or not 0 <= min_coverage <= 1):
        raise ValueError("min_coverage must be finite and between 0 and 1")
    if (isinstance(max_donors, (bool, np.bool_)) or not isinstance(max_donors, numbers.Integral)
            or not 1 <= max_donors <= MAX_DONORS):
        raise ValueError("max_donors must be an integer between 1 and 12")
    if not isinstance(masks, np.ndarray) or masks.dtype not in (np.dtype(bool), np.dtype(np.uint8)):
        raise TypeError("masks must be bool or binary uint8 ndarray")
    if masks.shape not in ((height, width), (count, height, width)):
        raise ValueError("masks must have shape [H,W] or [N,H,W]")
    if masks.dtype == np.uint8 and np.any((masks != 0) & (masks != 1)):
        raise ValueError("uint8 masks must contain only 0 and 1")
    return np.broadcast_to(masks.astype(bool, copy=False), (count, height, width))


def _clean_footprint(mask, radius):
    """A center is safe only if its whole square footprint is in bounds/clean."""
    clean = cv2.erode((~mask).astype(np.uint8), np.ones((2 * radius + 1,) * 2, np.uint8),
                      borderType=cv2.BORDER_CONSTANT, borderValue=0)
    return clean.astype(bool)


def _safe_points(clean, points):
    """Require both floor and ceil centers, including subpixel bilinear support."""
    height, width = clean.shape
    finite = np.isfinite(points).all(axis=1)
    safe_points = np.where(finite[:, None], points, -1)
    low = np.floor(safe_points).astype(np.int64)
    high = np.ceil(safe_points).astype(np.int64)
    valid = finite & (low[:, 0] >= 0) & (low[:, 1] >= 0) & (high[:, 0] < width) & (high[:, 1] < height)
    chosen = np.flatnonzero(valid)
    valid[chosen] &= (clean[low[chosen, 1], low[chosen, 0]] & clean[high[chosen, 1], high[chosen, 0]]
                      & clean[low[chosen, 1], high[chosen, 0]] & clean[high[chosen, 1], low[chosen, 0]])
    return valid


def _features(gray, mask):
    local = cv2.dilate(mask.astype(np.uint8), np.ones((2 * LOCAL_RADIUS + 1,) * 2, np.uint8))
    allowed = _clean_footprint(mask, TRACKING_RADIUS) & local.astype(bool)
    points = cv2.goodFeaturesToTrack(gray, maxCorners=180, qualityLevel=0.025, minDistance=6,
                                    mask=allowed.astype(np.uint8), blockSize=5)
    if points is None:
        return np.empty((0, 2), np.float32)
    points = points.reshape(-1, 2)
    return points[_safe_points(allowed, points)]


def _register(target_gray, donor_gray, target_mask, donor_mask, points, donor_id):
    evidence = {"frame_id": int(donor_id), "accepted": False, "reason": "insufficient_local_features",
                "feature_count": int(len(points)), "inlier_count": 0, "registration_confidence": 0.0,
                "copied_pixels": 0}
    if len(points) < 6:
        return None, evidence
    lk = dict(winSize=(21, 21), maxLevel=1, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.005))
    tracked, forward_status, _ = cv2.calcOpticalFlowPyrLK(target_gray, donor_gray, points[:, None], None, **lk)
    if tracked is None:
        evidence["reason"] = "tracking_failed"
        return None, evidence
    returned, reverse_status, _ = cv2.calcOpticalFlowPyrLK(donor_gray, target_gray, tracked, None, **lk)
    if returned is None:
        evidence["reason"] = "reverse_tracking_failed"
        return None, evidence
    tracked, returned = tracked[:, 0], returned[:, 0]
    fb = np.linalg.norm(returned - points, axis=1)
    valid = ((forward_status[:, 0] != 0) & (reverse_status[:, 0] != 0) & np.isfinite(fb) & (fb <= 0.35)
             & _safe_points(_clean_footprint(target_mask, TRACKING_RADIUS), points)
             & _safe_points(_clean_footprint(donor_mask, TRACKING_RADIUS), tracked)
             & _safe_points(_clean_footprint(target_mask, TRACKING_RADIUS), returned))
    if np.count_nonzero(valid) < 6:
        evidence["reason"] = "insufficient_clean_bidirectional_tracks"
        return None, evidence
    start, end = points[valid], tracked[valid]
    matrix, inliers = cv2.estimateAffinePartial2D(start, end, method=cv2.RANSAC, ransacReprojThreshold=0.6,
                                                maxIters=1000, confidence=0.999, refineIters=10)
    if matrix is None or inliers is None or not np.isfinite(matrix).all():
        evidence["reason"] = "invalid_ransac_transform"
        return None, evidence
    use = inliers[:, 0].astype(bool)
    if use.sum() < 6 or use.mean() < 0.7:
        evidence["reason"] = "insufficient_ransac_consensus"
        return None, evidence
    start, end = start[use], end[use]
    track_fb = fb[valid][use]
    # Re-evaluate the same direct pair with the measured transform as LK's
    # initialization. This recovers locally convergent tracks, not chained
    # correspondences; the unchanged RANSAC model must still fit each track.
    initial = (points @ matrix[:, :2].T + matrix[:, 2]).astype(np.float32)
    refined, forward_status, _ = cv2.calcOpticalFlowPyrLK(
        target_gray, donor_gray, points[:, None], initial[:, None].copy(),
        flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **lk)
    if refined is not None:
        returned, reverse_status, _ = cv2.calcOpticalFlowPyrLK(
            donor_gray, target_gray, refined, points[:, None].copy(),
            flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **lk)
        if returned is not None:
            refined, returned = refined[:, 0], returned[:, 0]
            refined_fb = np.linalg.norm(returned - points, axis=1)
            refined_residual = np.linalg.norm(refined - initial, axis=1)
            clean = ((forward_status[:, 0] != 0) & (reverse_status[:, 0] != 0)
                     & np.isfinite(refined_fb) & (refined_fb <= 0.35) & (refined_residual <= 0.6)
                     & _safe_points(_clean_footprint(target_mask, TRACKING_RADIUS), points)
                     & _safe_points(_clean_footprint(donor_mask, TRACKING_RADIUS), refined)
                     & _safe_points(_clean_footprint(target_mask, TRACKING_RADIUS), returned))
            if clean.sum() >= len(start):
                start, end, track_fb = points[clean], refined[clean], refined_fb[clean]
    residuals = np.linalg.norm(start @ matrix[:, :2].T + matrix[:, 2] - end, axis=1)
    scale = float(np.linalg.norm(matrix[:, 0]))
    angle = abs(float(np.arctan2(matrix[1, 0], matrix[0, 0])))
    spread = np.ptp(start, axis=0)
    if (not 0.98 <= scale <= 1.02 or angle > 0.035 or np.max(np.abs(matrix[:, 2])) > LOCAL_RADIUS
            or float(residuals.max()) > 0.6 or min(spread) < 12):
        evidence["reason"] = "unsupported_motion_or_spatial_support"
        return None, evidence
    # Reject extrapolation outside the area with measured motion.
    hull = cv2.convexHull(start.astype(np.float32)).reshape(-1, 2)
    evidence.update(accepted=True, reason="registered_requires_pixel_evidence", inlier_count=int(len(start)),
                    registration_confidence=float(use.mean() * max(0, 1 - np.median(residuals) / 0.6)),
                    max_reprojection_error=float(residuals.max()), max_forward_backward_error=float(track_fb.max()),
                    target_to_donor=matrix.tolist(), target_points=start.tolist(), donor_points=end.tolist())
    return (matrix, hull), evidence


def _box_sum(array, radius=EVIDENCE_RADIUS):
    return cv2.boxFilter(array.astype(np.float32), -1, (2 * radius + 1,) * 2, normalize=False,
                         borderType=cv2.BORDER_CONSTANT)


def _pixel_evidence(target, donor, target_mask, donor_mask, matrix, hull):
    """Visible local evidence, with both endpoint footprints clean, gates copying."""
    height, width = target_mask.shape
    yy, xx = np.indices((height, width), dtype=np.float32)
    # Float64 agrees exactly with the report's mapping formula at rounding ties.
    sx = matrix[0, 0] * xx.astype(np.float64) + matrix[0, 1] * yy + matrix[0, 2]
    sy = matrix[1, 0] * xx.astype(np.float64) + matrix[1, 1] * yy + matrix[1, 2]
    ix, iy = np.floor(sx + 0.5).astype(np.int32), np.floor(sy + 0.5).astype(np.int32)
    inside = (sx >= 2) & (sy >= 2) & (sx < width - 2) & (sy < height - 2)
    cx, cy = np.clip(ix, 0, width - 1), np.clip(iy, 0, height - 1)
    # All four bilinear taps plus a one-pixel clean support border must be clean.
    donor_clean = _clean_footprint(donor_mask, 1)
    low_x = np.clip(np.floor(sx).astype(np.int32), 0, width - 1)
    low_y = np.clip(np.floor(sy).astype(np.int32), 0, height - 1)
    high_x, high_y = np.minimum(low_x + 1, width - 1), np.minimum(low_y + 1, height - 1)
    source_safe = inside & donor_clean[low_y, low_x] & donor_clean[high_y, high_x]
    source_safe &= donor_clean[low_y, high_x] & donor_clean[high_y, low_x]
    visible = source_safe & ~target_mask
    # This nearest RGB comparison is stricter than a bilinear residual; output is
    # always an exact original donor triplet, so validate that same sampling rule.
    warped = donor[cy, cx]
    error = np.max(np.abs(target.astype(np.int16) - warped.astype(np.int16)), axis=2).astype(np.float32)
    support = _box_sum(visible)
    errors = _box_sum(error * visible) / np.maximum(support, 1)
    bad_fraction = _box_sum(visible & (error > 10)) / np.maximum(support, 1)
    gray = cv2.cvtColor(target, cv2.COLOR_RGB2GRAY).astype(np.float32)
    mean = _box_sum(gray * visible) / np.maximum(support, 1)
    variance = _box_sum(gray * gray * visible) / np.maximum(support, 1) - mean * mean
    # Require clean evidence on opposite sides of each hidden pixel, not only a
    # remote patch that happens to fit the same global affine transform.
    valid_support = visible.astype(np.float32)
    top_kernel = np.zeros((25, 25), np.float32)
    top_kernel[:12, :] = 1
    bottom_kernel = top_kernel[::-1].copy()
    left_kernel, right_kernel = top_kernel.T.copy(), bottom_kernel.T.copy()
    halves = [cv2.filter2D(valid_support, -1, kernel, borderType=cv2.BORDER_CONSTANT)
              for kernel in (top_kernel, bottom_kernel, left_kernel, right_kernel)]
    bracketed = ((halves[0] >= 12) & (halves[1] >= 12)) | ((halves[2] >= 12) & (halves[3] >= 12))
    measured = np.zeros((height, width), np.uint8)
    cv2.fillConvexPoly(measured, np.rint(hull).astype(np.int32), 1)
    eligible = (target_mask & source_safe & measured.astype(bool) & bracketed & (support >= 48)
                & (errors <= 3.0) & (bad_fraction <= 0.02) & (variance >= 9))
    evidence = {"eligible_pixels": int(eligible.sum()), "photometric_mean_error_limit": 3.0,
                "photometric_bad_fraction_limit": 0.02, "minimum_clean_support_pixels": 48}
    return eligible, ix, iy, evidence


def _donor_order(frame_id, count, max_donors):
    """Prioritize direct short motion; spend remaining budget across the context."""
    nearby = sorted((i for i in range(count) if i != frame_id), key=lambda i: (abs(i - frame_id), i))
    chosen = nearby[:min(6, max_donors)]
    # Distributed choices help reveal pixels while every mapping is still direct.
    for i in np.linspace(0, count - 1, min(count, max_donors), dtype=int):
        if int(i) != frame_id and int(i) not in chosen and len(chosen) < max_donors:
            chosen.append(int(i))
    for i in nearby:
        if i not in chosen and len(chosen) < max_donors:
            chosen.append(i)
    return chosen


def repair_frames(frames, masks, *, min_coverage=0.98, max_donors=12):
    """Return an independent RGB candidate and a JSON-serializable evidence report.

    ``masks`` is bool or uint8 0/1, shared [H,W] or per frame [N,H,W]. All
    provenance frame IDs are indices within *only* the supplied source context.
    Decode each int8 assignment map with base64, zlib, then reshape to its shape.
    A value -1 means no copy; other values index that frame's ``donors`` list.
    For target (x,y), its exact donor coordinate is floor(M @ [x,y,1] + 0.5).
    Only resolved masked pixels are assigned, even if their RGB did not change.
    Recovery status describes completeness independently of the numeric gate.
    ``coverage_gate_passed`` requires every frame to meet ``min_coverage``;
    partial recovery never becomes complete or production-approved by passing it.

    Source context and the candidate together use at most 240 MB. Processing is
    one target/donor pair at a time; no dense flow or all-pairs image tensors are
    retained. The conservative working-set estimate below includes source,
    output, masks, grayscale cache, provenance and pairwise scratch arrays.
    """
    masks = _validate(frames, masks, min_coverage, max_donors)
    count, height, width = frames.shape[:3]
    candidate = frames.copy()
    gray_cache = {}
    report = {"schema_version": 1, "method": "local_lk_ransac_source_pixel_copy",
              "status": "insufficient_evidence", "human_review_required": True, "accepted_for_production": False,
              "source_frame_count": int(count), "min_coverage": float(min_coverage), "frames": [],
              "registration_attempts": 0, "masked_pixels": 0, "resolved_pixels": 0, "unresolved_pixels": 0,
              "changed_pixels": 0, "coverage": 0.0,
              "limits": {"max_frames": MAX_FRAMES, "max_frame_pixels": MAX_FRAME_PIXELS,
                         "max_total_pixels": MAX_TOTAL_PIXELS, "max_donors": int(max_donors),
                         "max_registrations": int(count * max_donors), "tracking_support_radius": TRACKING_RADIUS,
                         "local_feature_radius": LOCAL_RADIUS, "pixel_evidence_radius": EVIDENCE_RADIUS,
                         "estimated_peak_working_bytes": int(12 * count * height * width + 160 * height * width + 64 * 1024**2),
                         "working_memory_target_bytes": 1024**3},
              "limitations": ["Direct near-rigid local motion only; no transform chains.",
                              "Unresolved pixels retain original source values.",
                              "Visible support cannot prove hidden content; visual review is mandatory."]}

    def gray(index):
        if index not in gray_cache:
            gray_cache[index] = cv2.cvtColor(frames[index], cv2.COLOR_RGB2GRAY)
        return gray_cache[index]

    for frame_id in range(count):
        mask = masks[frame_id]
        masked_count = int(mask.sum())
        assigned = np.full((height, width), -1, np.int8)
        entry = {"frame_id": frame_id, "masked_pixels": masked_count, "donors": [], "used_donor_frame_ids": []}
        if masked_count:
            target_gray = gray(frame_id)
            points = _features(target_gray, mask)
            for donor_id in _donor_order(frame_id, count, int(max_donors)):
                if not np.any(mask & (assigned < 0)):
                    break
                registration, donor_report = _register(target_gray, gray(donor_id), mask, masks[donor_id], points, donor_id)
                slot = len(entry["donors"])
                entry["donors"].append(donor_report)
                report["registration_attempts"] += 1
                if registration is None:
                    continue
                matrix, hull = registration
                eligible, sx, sy, pixel_report = _pixel_evidence(frames[frame_id], frames[donor_id], mask,
                                                                 masks[donor_id], matrix, hull)
                eligible &= assigned < 0
                copied = int(eligible.sum())
                donor_report.update(pixel_report, copied_pixels=copied)
                if not copied:
                    donor_report.update(accepted=False, reason="no_clean_local_pixel_evidence")
                    continue
                candidate[frame_id, eligible] = frames[donor_id, sy[eligible], sx[eligible]]
                assigned[eligible] = slot
                donor_report["reason"] = "source_pixels_copied_requires_visual_review"
                entry["used_donor_frame_ids"].append(int(donor_id))
        resolved = int(np.count_nonzero(assigned >= 0))
        changed = int(np.count_nonzero(np.any(candidate[frame_id] != frames[frame_id], axis=2)))
        coverage = float(resolved / masked_count) if masked_count else 1.0
        entry.update(resolved_pixels=resolved, unresolved_pixels=masked_count - resolved, changed_pixels=changed,
                     coverage=coverage, coverage_gate_passed=bool(coverage >= min_coverage),
                     recovery_status="complete" if resolved == masked_count else "partial" if resolved else "unresolved",
                     provenance={"shape": [height, width], "dtype": "int8", "unassigned": -1,
                                 "assignment_values": "indices into this frame's donors list",
                                 "rounding": "floor(target_to_donor @ [x,y,1] + 0.5)",
                                 "assignments_zlib_base64": base64.b64encode(zlib.compress(assigned.tobytes())).decode("ascii")})
        report["frames"].append(entry)
        for key in ("masked_pixels", "resolved_pixels", "unresolved_pixels", "changed_pixels"):
            report[key] += entry[key]
    report["coverage"] = report["resolved_pixels"] / report["masked_pixels"] if report["masked_pixels"] else 1.0
    report["coverage_gate_passed"] = all(entry["coverage_gate_passed"] for entry in report["frames"])
    if report["unresolved_pixels"] == 0:
        report["status"] = "candidate_requires_visual_review"
    elif report["resolved_pixels"]:
        report["status"] = "partial_requires_visual_review"
    return candidate, report
