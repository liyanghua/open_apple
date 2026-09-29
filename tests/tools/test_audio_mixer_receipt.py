import json
from tools.audio.audio_mixer import AudioMixer
from tests.tools.test_audio_mixer_target_duration import _tone
from lib.production_evidence import file_sha256


def test_full_mix_emits_actual_bound_execution_receipt(tmp_path):
    speech = tmp_path / 'speech.wav'
    music = tmp_path / 'music.wav'
    _tone(speech, 440, 4)
    _tone(music, 220, 4)
    result = AudioMixer().execute({'operation': 'full_mix', 'project_dir': str(tmp_path),
        'opening_scope': 'full_variant', 'receipt_path': 'mix-receipt.json',
        'tracks': [{'path': str(speech), 'role': 'speech'}, {'path': str(music), 'role': 'music'}],
        'target_duration': 4, 'normalize': False, 'output_path': str(tmp_path / 'mix.wav')})
    assert result.success, result.error
    assert (tmp_path / 'mix-receipt.json').is_file()
    receipt = json.loads((tmp_path / 'mix-receipt.json').read_text())
    assert receipt['output_ref']['sha256'] == file_sha256(tmp_path / 'mix.wav')
    assert receipt['input_refs'][0]['sha256'] == file_sha256(speech)
    assert receipt['scope'] == 'full_variant'
    assert receipt['command'][0] == 'ffmpeg'
    assert receipt['returncode'] == 0
