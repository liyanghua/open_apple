"""Pin new motion-reference generation instead of allowing an edit classification."""
import pytest

from tools.video.seedance_ark import SeedanceArkVideo


def request(**changes):
    return dict(model_variant='2.5', operation='reference_to_video',
                prompt='Generate a NEW product shot; borrow only the hand action.',
                reference_video_urls=['https://example.test/motion.mp4'],
                reference_video_durations=[2], duration=4, aspect_ratio='9:16',
                resolution='720p', omni_reference_task_type='reference', **changes)


def test_explicit_reference_type_survives_payload_build():
    payload = SeedanceArkVideo()._build_payload(request())
    assert payload['omni_reference_task_type'] == 'reference'
    assert payload['duration'] == 4 and payload['ratio'] == '9:16'


@pytest.mark.parametrize('value', ['edit', 'extend', 'invalid', False])
def test_unsupported_task_types_fail_before_payment(value):
    inputs = request()
    inputs['omni_reference_task_type'] = value
    with pytest.raises(ValueError):
        SeedanceArkVideo()._build_payload(inputs)


def test_reference_type_is_only_available_for_seedance25_reference_operation():
    inputs = request()
    inputs['model_variant'] = 'standard'
    with pytest.raises(ValueError):
        SeedanceArkVideo()._build_payload(inputs)


def test_legacy_payload_default_remains_unchanged():
    inputs = request()
    inputs.pop('omni_reference_task_type')
    assert 'omni_reference_task_type' not in SeedanceArkVideo()._build_payload(inputs)
