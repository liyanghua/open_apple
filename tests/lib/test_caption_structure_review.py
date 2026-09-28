"""Crop evidence cannot approve source restoration."""
import importlib

import numpy as np
import pytest


def classify(*args):
    try:
        module = importlib.import_module("lib.caption_structure_review")
    except ModuleNotFoundError:
        pytest.fail("crop evidence classifier is not implemented")
    return module.classify_structure(*args)


def scene():
    source = np.full((5, 31, 41, 3), 140, dtype=np.uint8)
    mask = np.zeros((31, 41), bool)
    mask[5:26, 5:36] = True
    candidate = source.copy()
    source[:, 12:15, 18:21] = 245
    source[:, 15:17, 18:21] = 20
    return source, candidate, mask


def test_stationary_text_outline_and_guard_are_risk_over_varying_background():
    source, candidate, mask = scene()
    for t in range(5):
        candidate[t] = 120 + t * 10
        source[t, :10] = candidate[t, :10]
    labels, stats = classify(source, candidate, mask)
    assert np.all(labels[:, 10:19, 16:23] == 1)
    assert stats["thresholds"]["bright_q10"] == 180


def test_spatially_supported_matching_background_is_possible_preservation():
    source, candidate, mask = scene()
    labels, _ = classify(source, candidate, mask)
    assert np.all(labels[:, 7, 7] == 2)
    assert np.all(labels[:, 13, 19] == 1)


def test_moving_bright_matching_structure_is_not_text_from_brightness_alone():
    source, candidate, mask = scene()
    for t in range(5):
        source[t, 7:10, 7+t:10+t] = 250
        candidate[t, 7:10, 7+t:10+t] = 250
    labels, _ = classify(source, candidate, mask)
    assert np.all(labels[:, 7:10, 7:14] != 1)


def test_disagreement_and_matching_island_disconnected_from_exterior_are_uncertain():
    source, candidate, mask = scene()
    candidate[:, 17:26, 25:36] = 170
    candidate[:, 20:23, 29:32] = source[:, 20:23, 29:32]
    labels, _ = classify(source, candidate, mask)
    assert np.all(labels[:, 21, 30] == 3)
    assert np.all(labels[:, 19, 27] == 3)


def test_matching_candidate_without_text_signal_does_not_prove_background():
    source, _, mask = scene()
    labels, _ = classify(source, source.copy(), mask)
    assert np.all(labels[:, mask] == 3)


def test_determinism_partition_and_no_input_mutation():
    args = scene()
    before = [x.copy() for x in args]
    labels, stats = classify(*args)
    again, again_stats = classify(*args)
    assert labels.dtype == np.uint8
    assert labels.shape == args[0].shape[:3]
    assert np.all(labels[:, ~args[2]] == 0)
    assert np.all((labels[:, args[2]] >= 1) & (labels[:, args[2]] <= 3))
    assert np.array_equal(labels, again) and stats == again_stats
    assert all(np.array_equal(a, b) for a, b in zip(args, before))
    assert all(sum(row.values()) == int(args[2].sum()) for row in stats["per_frame_counts"])


@pytest.mark.parametrize("case", ["dtype", "shape", "short", "long", "small", "huge", "maskdtype", "empty", "border"])
def test_rejects_invalid_inputs_before_classification(case):
    source, candidate, mask = scene()
    if case == "dtype": source = source.astype(np.float32)
    if case == "shape": candidate = candidate[:, :-1]
    if case == "short": source = candidate = source[:2]
    if case == "long": source = candidate = np.zeros((39, 31, 41, 3), np.uint8)
    if case == "small": source = candidate = np.zeros((3, 6, 41, 3), np.uint8)
    if case == "huge": source = candidate = np.broadcast_to(np.uint8(0), (3, 400, 400, 3))
    if case == "maskdtype": mask = mask.astype(np.uint8)
    if case == "empty": mask[:] = False
    if case == "border": mask[0, 0] = True
    with pytest.raises(ValueError):
        classify(source, candidate, mask)
