from lib.voice_alignment import segment_drift_ms, within_tolerance


def test_segment_drift_and_tolerance():
    assert segment_drift_ms(0.2, 1.2, 0.25, 1.31) == (50, 110)
    assert within_tolerance(110, 160)
    assert not within_tolerance(161, 160)
