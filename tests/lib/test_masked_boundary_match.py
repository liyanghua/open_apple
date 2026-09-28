"""Boundary correction must not reintroduce source text or change other pixels."""

import importlib.util

import numpy as np
import pytest


def matcher_type():
    assert importlib.util.find_spec("lib.masked_boundary_match"), "local boundary matcher is missing"
    from lib.masked_boundary_match import MaskedBoundaryMatcher
    return MaskedBoundaryMatcher


def fixture_frames():
    y, x = np.indices((24, 32))
    clean = np.repeat((60 + x + y)[:, :, None], 3, axis=2).astype(np.uint8)
    clean[10:13, 12:16] += 25  # A real candidate detail, not a source glyph.
    candidate = clean + np.uint8(20)
    mask = np.zeros((24, 32), dtype=bool)
    mask[5:20, 6:27] = True
    source = clean.copy()
    source[mask] = 255  # Old burned-in text: must never enter the correction.
    return source, candidate, mask, clean


def test_matches_boundary_offset_retains_candidate_detail_and_original_exterior():
    source, candidate, mask, expected = fixture_frames()
    source_copy, candidate_copy, mask_copy = source.copy(), candidate.copy(), mask.copy()
    matcher = matcher_type()(mask)
    actual, stats = matcher.apply(source, candidate)
    assert np.array_equal(actual[~mask], source[~mask])
    assert np.max(np.abs(actual.astype(float) - expected)) <= 1
    assert stats["max_residual"] < 0.0001
    assert np.array_equal(source, source_copy) and np.array_equal(candidate, candidate_copy)
    assert np.array_equal(mask, mask_copy)


def test_output_independent_of_source_text_and_previous_frame():
    source, candidate, mask, _ = fixture_frames()
    matcher = matcher_type()(mask)
    first, _ = matcher.apply(source, candidate)
    source[mask] = 0
    matcher.apply(source, np.clip(candidate.astype(int) + 9, 0, 255).astype(np.uint8))
    second, _ = matcher.apply(source, candidate)
    assert np.array_equal(first, second)


def test_zero_boundary_error_keeps_candidate_pixels_exactly():
    source, candidate, mask, _ = fixture_frames()
    source[~mask] = candidate[~mask]
    actual, stats = matcher_type()(mask).apply(source, candidate)
    assert np.array_equal(actual[mask], candidate[mask])
    assert stats["max_abs_correction_rgb"] == 0


@pytest.mark.parametrize("bad", [np.zeros((8, 8), bool), np.ones((8, 8), bool), np.ones((8, 8), np.uint8)])
def test_rejects_invalid_masks(bad):
    with pytest.raises(ValueError, match="mask"):
        matcher_type()(bad)


def test_rejects_nonconvergence_and_bad_frame_geometry():
    source, candidate, mask, _ = fixture_frames()
    with pytest.raises(ValueError, match="converge"):
        matcher_type()(mask, max_iterations=1).apply(source, candidate)
    with pytest.raises(ValueError, match="geometry"):
        matcher_type()(mask).apply(source[:-1], candidate)
