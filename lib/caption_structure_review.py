"""Pure bounded crop heuristics. Labels are unapproved evidence, not truth."""
from __future__ import annotations

import cv2
import numpy as np

THRESHOLDS = {"bright_q10": 180, "bright_residual_q10": 30,
              "dark_q90": 110, "dark_residual_q90": -20,
              "guard_radius": 2, "rgb_difference": 8,
              "sobel_difference": 4, "sobel_scale": 0.125,
              "agreement_neighbourhood": 3, "exterior_ring_radius": 5}


def classify_structure(source_crops, candidate_crops, allowed_mask):
    """Return labels 0 outside, 1 text risk, 2 possible preservation, 3 uncertain.

    Matching pixels only become a preservation proposal when their agreeing
    component reaches agreeing exterior pixels. No label approves restoration.
    """
    for item in (source_crops, candidate_crops):
        if not isinstance(item, np.ndarray) or item.dtype != np.uint8 or item.ndim != 4:
            raise ValueError("crops must be uint8 (T,H,W,3) arrays")
    if source_crops.shape != candidate_crops.shape:
        raise ValueError("crop geometries must match")
    count, height, width, channels = source_crops.shape
    if channels != 3 or not 3 <= count <= 38 or min(height, width) < 7 or height * width > 100000:
        raise ValueError("crop dimensions exceed bounded classification contract")
    if (not isinstance(allowed_mask, np.ndarray) or allowed_mask.dtype != np.bool_
            or allowed_mask.shape != (height, width) or not allowed_mask.any()
            or allowed_mask[0].any() or allowed_mask[-1].any()
            or allowed_mask[:, 0].any() or allowed_mask[:, -1].any()):
        raise ValueError("mask must be nonempty interior boolean (H,W) with exterior border")
    # Float grayscale and signed residual preserve the dark-core sign.
    gray = np.stack([cv2.cvtColor(x, cv2.COLOR_RGB2GRAY).astype(np.float32) for x in source_crops])
    other = np.stack([cv2.cvtColor(x, cv2.COLOR_RGB2GRAY).astype(np.float32) for x in candidate_crops])
    residual = gray - other
    bright = (np.quantile(gray, .1, axis=0) >= 180) & (np.quantile(residual, .1, axis=0) >= 30)
    dark = (np.quantile(gray, .9, axis=0) <= 110) & (np.quantile(residual, .9, axis=0) <= -20)
    core = (bright | dark) & allowed_mask
    guard = cv2.dilate(core.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & allowed_mask
    ring = cv2.dilate(allowed_mask.astype(np.uint8), np.ones((11, 11), np.uint8)).astype(bool) & ~allowed_mask
    labels = np.zeros((count, height, width), np.uint8)
    labels[:, allowed_mask] = 3
    labels[:, guard] = 1
    if core.any():
        for t in range(count):
            agreement = np.max(np.abs(source_crops[t].astype(np.int16) - candidate_crops[t].astype(np.int16)), axis=2) <= 8
            for dx, dy in ((1, 0), (0, 1)):
                a = cv2.Sobel(gray[t], cv2.CV_32F, dx, dy, ksize=3, scale=.125)
                b = cv2.Sobel(other[t], cv2.CV_32F, dx, dy, ksize=3, scale=.125)
                agreement &= np.abs(a - b) <= 4
            agreement = cv2.erode(agreement.astype(np.uint8), np.ones((3, 3), np.uint8),
                                  borderType=cv2.BORDER_CONSTANT, borderValue=0).astype(bool)
            agreement &= ~guard & (allowed_mask | ring)
            _, components = cv2.connectedComponents(agreement.astype(np.uint8), connectivity=8)
            connected = np.unique(components[agreement & ring])
            connected = connected[connected != 0]
            labels[t, allowed_mask & agreement & np.isin(components, connected)] = 2
    names = {1: "text_risk", 2: "possible_preservation", 3: "uncertain"}
    stats = {"thresholds": dict(THRESHOLDS), "text_core_pixels": int(core.sum()),
             "text_guard_pixels": int(guard.sum()), "mask_pixels": int(allowed_mask.sum()),
             "per_frame_counts": [{name: int((frame == value).sum()) for value, name in names.items()} for frame in labels],
             "proposal_only": True, "approved_for_restore": False}
    return labels, stats
