"""Source-only repair contracts; synthetic scenes have known clean ground truth."""

import base64
import importlib
import json
import zlib

import cv2
import numpy as np
import pytest


def repair(*args, **kwargs):
    try:
        module = importlib.import_module("lib.temporal_caption_repair")
    except ModuleNotFoundError:
        pytest.fail("temporal source-pixel repair capability is missing")
    return module.repair_frames(*args, **kwargs)


def scene(shifts=(-8, -4, 0, 4, 8), height=160, width=192):
    rng = np.random.default_rng(735)
    texture = rng.integers(0, 256, (height + 40, width, 3), dtype=np.uint8)
    texture = cv2.GaussianBlur(texture, (5, 5), 0.9)
    clean = np.stack([texture[20 + shift:20 + shift + height] for shift in shifts])
    mask = np.zeros((height, width), bool)
    mask[77:83, 65:126] = True
    burned = clean.copy()
    burned[:, mask] = [255, 0, 255]
    return burned, mask, clean


def assignments(frame_report):
    provenance = frame_report["provenance"]
    raw = zlib.decompress(base64.b64decode(provenance["assignments_zlib_base64"]))
    return np.frombuffer(raw, dtype=np.int8).reshape(provenance["shape"])


def test_empty_mask_is_independent_identity_with_serializable_report():
    frames, mask, _ = scene()
    candidate, report = repair(frames, np.zeros_like(mask))
    np.testing.assert_array_equal(candidate, frames)
    assert not np.shares_memory(candidate, frames)
    assert report["coverage"] == 1.0
    assert report["unresolved_pixels"] == report["changed_pixels"] == 0
    assert report["human_review_required"] is True
    assert report["accepted_for_production"] is False
    json.dumps(report, allow_nan=False)


def test_translated_texture_recovers_exact_original_rgb_and_preserves_inputs():
    frames, mask, clean = scene()
    original_frames, original_mask = frames.copy(), mask.copy()
    frames.flags.writeable = False
    mask.flags.writeable = False
    candidate, report = repair(frames, mask)
    np.testing.assert_array_equal(frames, original_frames)
    np.testing.assert_array_equal(mask, original_mask)
    np.testing.assert_array_equal(candidate[:, ~mask], frames[:, ~mask])
    np.testing.assert_array_equal(candidate[:, mask], clean[:, mask])
    assert report["status"] == "candidate_requires_visual_review"
    assert report["coverage"] == 1.0
    assert report["changed_pixels"] == int(mask.sum()) * len(frames)
    assert report["unresolved_pixels"] == 0
    json.dumps(report, allow_nan=False)


def test_every_copy_has_reconstructible_unmasked_in_bounds_original_provenance():
    frames, mask, _ = scene()
    candidate, report = repair(frames, mask)
    for target_id, entry in enumerate(report["frames"]):
        assigned = assignments(entry)
        assert np.all(assigned[~mask] == -1)
        for slot, donor in enumerate(entry["donors"]):
            ys, xs = np.where(assigned == slot)
            if not len(xs):
                continue
            matrix = np.asarray(donor["target_to_donor"])
            mapped = np.c_[xs, ys, np.ones(len(xs))] @ matrix.T
            sx, sy = np.floor(mapped + 0.5).astype(int).T
            assert np.all((sx >= 0) & (sx < mask.shape[1]))
            assert np.all((sy >= 0) & (sy < mask.shape[0]))
            assert not np.any(mask[sy, sx])
            np.testing.assert_array_equal(candidate[target_id, ys, xs], frames[donor["frame_id"], sy, sx])
        assert np.count_nonzero(assigned >= 0) == entry["resolved_pixels"]


def test_fully_occluded_stationary_region_fails_closed():
    frames, mask, _ = scene(shifts=(0, 0, 0))
    candidate, report = repair(frames, mask)
    np.testing.assert_array_equal(candidate, frames)
    assert report["status"] == "insufficient_evidence"
    assert report["coverage"] == 0.0
    assert report["unresolved_pixels"] == int(mask.sum()) * len(frames)


def test_unrelated_corrupted_donor_is_rejected():
    frames, mask, _ = scene(shifts=(0, 0))
    frames[1] = np.random.default_rng(44).integers(0, 256, frames[1].shape, dtype=np.uint8)
    frames[1, mask] = 0
    candidate, report = repair(frames, mask)
    np.testing.assert_array_equal(candidate, frames)
    assert report["coverage"] == 0


def test_registration_alone_cannot_authorize_local_occlusion():
    frames, mask, _ = scene(shifts=(0, 4))
    # Good global motion around the caption, bad local visible evidence.
    frames[1, 71:86, 60:131] = [12, 220, 11]
    candidate, report = repair(frames, mask)
    np.testing.assert_array_equal(candidate, frames)
    assert report["coverage"] == 0


def test_no_features_from_caption_or_distant_foreground():
    rng = np.random.default_rng(6)
    frames = np.full((2, 240, 220, 3), 90, np.uint8)
    frames[:, :50] = rng.integers(0, 256, (2, 50, 220, 3), dtype=np.uint8)
    mask = np.zeros((240, 220), bool)
    mask[180:190, 60:160] = True
    frames[:, mask] = rng.integers(0, 256, (2, int(mask.sum()), 3), dtype=np.uint8)
    candidate, report = repair(frames, mask)
    np.testing.assert_array_equal(candidate, frames)
    assert report["coverage"] == 0
    assert all(d["feature_count"] == 0 for f in report["frames"] for d in f["donors"])


def test_registration_and_copy_support_exclude_masks_at_both_ends():
    frames, mask, _ = scene()
    masks = np.broadcast_to(mask, frames.shape[:3]).copy()
    masks[1, 45:58, 80:112] = True
    frames[1, masks[1]] = [0, 255, 0]
    _, report = repair(frames, masks)
    radius = report["limits"]["tracking_support_radius"]
    for frame_id, entry in enumerate(report["frames"]):
        for donor in entry["donors"]:
            for key, owner in (("target_points", frame_id), ("donor_points", donor["frame_id"])):
                for x, y in donor.get(key, []):
                    x0, x1 = int(np.floor(x)) - radius, int(np.ceil(x)) + radius
                    y0, y1 = int(np.floor(y)) - radius, int(np.ceil(y)) + radius
                    assert x0 >= 0 and y0 >= 0 and x1 < masks.shape[2] and y1 < masks.shape[1]
                    assert not masks[owner, y0:y1 + 1, x0:x1 + 1].any()
            assigned = assignments(entry)
            ys, xs = np.where(assigned == entry["donors"].index(donor))
            if len(xs):
                mapped = np.c_[xs, ys, np.ones(len(xs))] @ np.asarray(donor["target_to_donor"]).T
                for x, y in mapped:
                    assert not masks[donor["frame_id"], int(np.floor(y)) - 1:int(np.ceil(y)) + 2,
                                     int(np.floor(x)) - 1:int(np.ceil(x)) + 2].any()


@pytest.mark.parametrize("setting", [float("nan"), float("inf"), -0.1, 1.1, True, "0.9"])
def test_invalid_coverage_rejected(setting):
    frames, mask, _ = scene(shifts=(0,))
    with pytest.raises((ValueError, TypeError)):
        repair(frames, mask, min_coverage=setting)


@pytest.mark.parametrize("setting", [0, 13, 1.5, True, float("nan")])
def test_invalid_donor_limit_rejected(setting):
    frames, mask, _ = scene(shifts=(0,))
    with pytest.raises((ValueError, TypeError)):
        repair(frames, mask, max_donors=setting)


@pytest.mark.parametrize("bad_frames,bad_mask", [
    (np.zeros((1, 5, 5, 3), np.float32), np.zeros((5, 5), bool)),
    (np.zeros((1, 5, 5, 4), np.uint8), np.zeros((5, 5), bool)),
    (np.zeros((0, 5, 5, 3), np.uint8), np.zeros((5, 5), bool)),
    (np.zeros((1, 5, 5, 3), np.uint8), np.zeros((4, 5), bool)),
    (np.zeros((1, 5, 5, 3), np.uint8), np.full((5, 5), 2, np.uint8)),
    (np.zeros((1, 5, 5, 3), np.uint8), np.zeros((5, 5), float)),
])
def test_invalid_shapes_and_dtypes_rejected(bad_frames, bad_mask):
    with pytest.raises((ValueError, TypeError)):
        repair(bad_frames, bad_mask)


@pytest.mark.parametrize("shape", [(121, 1, 1, 3), (1, 1450, 1450, 3), (21, 1400, 1400, 3)])
def test_hard_source_context_bounds_before_large_allocation(shape):
    frames = np.broadcast_to(np.uint8(0), shape)
    mask = np.broadcast_to(False, shape[1:3])
    with pytest.raises(ValueError, match="limit"):
        repair(frames, mask)


def test_single_frame_cannot_supply_hidden_pixels():
    frames, mask, _ = scene(shifts=(0,))
    candidate, report = repair(frames, mask)
    np.testing.assert_array_equal(candidate, frames)
    assert report["coverage"] == 0
    assert report["frames"][0]["donors"] == []


def test_determinism_and_bounded_registrations():
    frames, mask, _ = scene()
    first, first_report = repair(frames, mask, max_donors=2)
    second, second_report = repair(frames, mask, max_donors=2)
    np.testing.assert_array_equal(first, second)
    assert first_report == second_report
    assert first_report["registration_attempts"] <= len(frames) * 2


def test_coverage_is_not_the_number_of_changed_pixels():
    frames, mask, clean = scene()
    frames[:, mask] = clean[:, mask]
    candidate, report = repair(frames, mask)
    np.testing.assert_array_equal(candidate, frames)
    assert report["coverage"] == 1.0
    assert report["changed_pixels"] == 0


def test_partial_never_claims_complete_even_with_zero_threshold():
    frames, mask, _ = scene(shifts=(0, 4))
    _, report = repair(frames, mask, min_coverage=0)
    assert 0 < report["coverage"] < 1
    assert report["status"] == "partial_requires_visual_review"
    assert report["accepted_for_production"] is False


def test_partial_recovery_is_explicit_when_default_coverage_gate_fails():
    frames, mask, _ = scene(shifts=(0, 4))
    _, report = repair(frames, mask)
    assert 0 < report["coverage"] < 0.98
    assert report["status"] == "partial_requires_visual_review"
    assert report["coverage_gate_passed"] is False
    assert report["accepted_for_production"] is False
    for entry in report["frames"]:
        assert 0 < entry["resolved_pixels"] < entry["masked_pixels"]
        assert entry["recovery_status"] == "partial"
        assert entry["coverage_gate_passed"] is False


@pytest.mark.parametrize("shifts,threshold,state,gate", [
    ((0,), 0.98, "unresolved", False),
    ((-8, -4, 0, 4, 8), 0.98, "complete", True),
    ((0, 4), 0, "partial", True),
])
def test_recovery_state_and_numeric_gate_are_independent(shifts, threshold, state, gate):
    frames, mask, _ = scene(shifts=shifts)
    _, report = repair(frames, mask, min_coverage=threshold)
    assert report["coverage_gate_passed"] is gate
    for entry in report["frames"]:
        assert entry["recovery_status"] == state
        assert entry["coverage_gate_passed"] is gate


def test_empty_mask_has_complete_recovery_state_and_passes_gate():
    frames, mask, _ = scene(shifts=(0,))
    _, report = repair(frames, np.zeros_like(mask))
    assert report["coverage_gate_passed"] is True
    assert report["frames"][0]["recovery_status"] == "complete"
    assert report["frames"][0]["coverage_gate_passed"] is True
