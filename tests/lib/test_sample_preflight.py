from __future__ import annotations

from lib.sample_preflight import validate_sample_inputs


def test_sample_preflight_accepts_valid_window_and_timeline() -> None:
    result = validate_sample_inputs({
        "shot_execution_plan": {"shots": [{"id": "shot-01", "screen_copy": "一铺即护"}]},
        "final_props": {"fps": 30, "scenes": [{"id": "shot-01"}],
                        "captions": [{"text": "一铺即护", "startMs": 0, "endMs": 2300}]},
        "sample_report": {"window": {"startFrame": 0, "endFrameExclusive": 300}},
    })

    assert result == {"ok": True, "issues": []}


def test_sample_preflight_reports_invalid_window_before_render() -> None:
    result = validate_sample_inputs({
        "shot_execution_plan": {"shots": [{"id": "shot-01"}]},
        "final_props": {"fps": 30, "scenes": [{"id": "shot-01"}]},
        "sample_report": {"window": {"startFrame": 0, "endFrameExclusive": 90}},
    })

    assert result["ok"] is False
    assert "样片窗口应为 10-15 秒" in result["issues"]


def test_opening_preflight_does_not_rewrite_through_generic_sample():
    p = {'fps': 30, 'scenes': [{'id': 's01', 'fromFrame': 0}], 'captions': [{'text': '标题', 'startMs': 0, 'endMs': 2300}]}
    p.update(opening={'scope': 'preview', 'endFrameExclusive': 90, 'transitionFrames': 5}, durationInFrames=90,
             finalMix={'path': 'mix.wav', 'sha256': 'a' * 64, 'mode': 'external_mux'})
    p.pop('audio', None)
    p['scenes'] = [{**p['scenes'][0], 'fromFrame': 0, 'durationInFrames': 90, 'role': 'hook'}]
    result = validate_sample_inputs({'shot_execution_plan': {'shots': [{'id': 's01', 'screen_copy': '标题'}]},
        'final_props': p, 'sample_report': {'window': {'startFrame': 0, 'endFrameExclusive': 90}}})
    assert '样片窗口应为 10-15 秒' not in result['issues']
    assert not any('generic sample adaptation' in i for i in result['issues'])
