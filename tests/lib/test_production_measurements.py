import json
import pytest
from lib.production_evidence import file_sha256
from lib import production_quality


def write(root, name, data):
    (root / name).write_text(json.dumps(data))
    return {'path': name, 'sha256': file_sha256(root / name)}


def setup(root, scope='preview'):
    (root / 'film.mp4').write_bytes(b'film')
    media = {'path': 'film.mp4', 'sha256': file_sha256(root / 'film.mp4')}
    props = {'fps': 30, 'width': 1080, 'height': 1920, 'durationInFrames': 90 if scope == 'preview' else 180,
        'opening': {'scope': scope}, 'titles': [{'fromFrame': 0, 'text': '标题'}],
        'captions': [{'text': '真实口播', 'startMs': 0, 'endMs': 2300}],
        'words': [{'text': '真实口播', 'startMs': 0, 'endMs': 2300}],
        'profile': {'font': {'files': []}, 'production': {'font_mode': 'legacy_appearance', 'slogan': '完整结尾', 'min_tail_seconds': .4}}}
    pref = write(root, 'props.json', props)
    record = {'render': media, 'opening': {'scope': scope}, 'canonical_artifacts': {'final_props': 'props.json'}}
    return props, pref, media, record


def test_asr_adapter_keeps_raw_mismatch_and_warnings(tmp_path):
    assert hasattr(production_quality, 'produce_narration_evidence')
    props, pref, media, record = setup(tmp_path)
    raw = write(tmp_path, 'asr.json', {'success': True, 'method': 'independent_asr', 'render_sha256': media['sha256'],
        'runtime_warnings': ['numerical overflow'], 'data': {'segments': [{'text': '错误口播', 'start': 0, 'end': 2.3}],
            'word_timestamps': [{'word': '错误口播', 'start': 0, 'end': 2.3, 'probability': .8}]}})
    result = production_quality.produce_narration_evidence(tmp_path, record=record, raw_ref=raw, output_path='speech.json')
    assert result['raw_ref'] == raw
    assert result['runtime_warnings'] == ['numerical overflow']
    assert next(c for c in result['checks'] if c['id'] == 'narration_content')['status'] == 'fail'
    checks = {c['id']: c for c in production_quality.collect_production_quality(tmp_path, record, {'narration': 'speech.json'})['checks']}
    assert checks['narration_content']['status'] == 'fail'
    assert checks['caption_alignment']['status'] == 'fail'
    props['words'][0]['text'] = '错误口播'
    write(tmp_path, 'props.json', props)
    checks = {c['id']: c for c in production_quality.collect_production_quality(tmp_path, record, {'narration': 'speech.json'})['checks']}
    assert checks['narration_content']['status'] == 'error'


def test_dom_missing_frames_or_legacy_fonts_never_certify(tmp_path):
    assert hasattr(production_quality, 'produce_brand_dom_evidence')
    _, pref, media, record = setup(tmp_path)
    directory = tmp_path / 'raw'
    directory.mkdir()
    with pytest.raises(ValueError, match='complete'):
        production_quality.produce_brand_dom_evidence(tmp_path, record=record, artifact_dir=directory, run_id='abc', output_path='dom.json')


def test_valid_judge_execution_without_policy_is_not_quality_pass(tmp_path):
    _, _, media, record = setup(tmp_path, 'full_variant')
    from tools.analysis.video_judge import L3_DIMENSIONS
    dims = [{'id': d[0], 'score': 8, 'note': 'clear'} for d in L3_DIMENSIONS]
    write(tmp_path, 'judge.json', {'render_sha256': media['sha256'], 'scope': 'full_variant', 'method': 'independent_video_judge',
        'scored': True, 'status': 'pass', 'rubric_version': 'l3-v1.0', 'dimensions': dims,
        'attempts': [{'valid': True, 'raw_response': json.dumps({'dimensions': dims}), 'usage': {'total_tokens': 8}, 'actual_cost_usd': None}]})
    report = production_quality.collect_production_quality(tmp_path, record, {'video_judge': 'judge.json'})
    check = next(c for c in report['checks'] if c['id'] == 'video_judge')
    assert check['status'] == 'not_run'
    assert check['execution_status'] == 'pass'
    assert 'judge_policy_missing' in check['issues']


def dom_fixture(root):
    props, pref, media, record = setup(root)
    directory = root / 'raw'
    directory.mkdir()
    for frame in range(90):
        boxes = [{'role': role, 'text': text, 'x': 10, 'y': y, 'width': 200, 'height': 40,
                  'fontFamily': 'legacy', 'fontWeight': '700' if role == 'title' else '400'}
                 for role, text, y in [('logo', '', 100), ('title', '标题', 200), ('underline', '', 280), ('caption', '真实口播' if frame < 69 else '', 1400)]]
        (directory / f'frame-{frame:06d}.json').write_text(json.dumps({'run_id': 'actual-run', 'renderer_props_sha256': pref['sha256'],
            'frame': frame, 'scope': 'preview', 'measurement': {'evidence': {'frame': frame, 'width': 1080, 'height': 1920,
                'font_loading_status': 'not_run', 'font_sha256': [], 'font_faces_ready': False, 'boxes': boxes, 'issues': []}}}))
    return props, pref, media, record, directory


def test_all_actual_dom_frames_allow_layout_but_never_legacy_font_certification(tmp_path):
    _, _, _, record, directory = dom_fixture(tmp_path)
    report = production_quality.produce_brand_dom_evidence(tmp_path, record=record, artifact_dir=directory, run_id='actual-run', output_path='dom.json')
    checks = {c['id']: c for c in report['checks']}
    assert checks['text_layout']['status'] == 'pass'
    assert checks['font_identity']['status'] == 'not_run'


@pytest.mark.parametrize('change', ['offscreen', 'overlap', 'wrong_text', 'wrong_run', 'wrong_props', 'missing_frame', 'zero_logo', 'missing_logo'])
def test_dom_counterexamples_do_not_pass(tmp_path, change):
    _, _, _, record, directory = dom_fixture(tmp_path)
    path = directory / 'frame-000030.json'
    row = json.loads(path.read_text())
    if change == 'offscreen': row['measurement']['evidence']['boxes'][1]['x'] = -1
    elif change == 'overlap': row['measurement']['evidence']['boxes'][3]['y'] = 200
    elif change == 'wrong_text': row['measurement']['evidence']['boxes'][3]['text'] = ''
    elif change == 'zero_logo': row['measurement']['evidence']['boxes'][0]['height'] = 0
    elif change == 'missing_logo': row['measurement']['evidence']['boxes'].pop(0)
    elif change == 'wrong_run': row['run_id'] = 'stale'
    elif change == 'wrong_props': row['renderer_props_sha256'] = 'a' * 64
    path.write_text(json.dumps(row))
    if change == 'missing_frame': path.unlink()
    if change in ('wrong_run', 'wrong_props', 'missing_frame'):
        with pytest.raises(ValueError):
            production_quality.produce_brand_dom_evidence(tmp_path, record=record, artifact_dir=directory, run_id='actual-run', output_path='dom.json')
    else:
        report = production_quality.produce_brand_dom_evidence(tmp_path, record=record, artifact_dir=directory, run_id='actual-run', output_path='dom.json')
        assert next(c for c in report['checks'] if c['id'] == 'text_layout')['status'] == 'fail'


@pytest.mark.parametrize('change', ['missing_slogan', 'cut_tail', 'missing_captions', 'overlap'])
def test_actual_speech_and_full_tail_failures_remain_visible(tmp_path, change):
    from lib.production_measurements import speech_checks
    props, _, _, _ = setup(tmp_path, 'full_variant')
    props['profile']['production']['slogan'] = '真实口播'
    words = [{'word': '真实口播', 'start': 0, 'end': 2.3}]
    if change == 'missing_slogan': props['profile']['production']['slogan'] = '完整结尾'
    if change == 'cut_tail': words[0]['end'] = 5.8
    if change == 'missing_captions': props['captions'] = []
    if change == 'overlap': props['captions'] *= 2
    checks = {c['id']: c for c in speech_checks(props, {'success': True, 'method': 'independent_asr',
        'data': {'segments': [{'text': '真实口播'}], 'word_timestamps': words}})}
    key = 'slogan_tail' if change in ('missing_slogan', 'cut_tail') else 'caption_alignment'
    assert checks[key]['status'] == 'fail'


def test_historical_renderer_snapshot_without_input_pins_cannot_certify(tmp_path):
    _, _, _, record, directory = dom_fixture(tmp_path)
    production_quality.produce_brand_dom_evidence(tmp_path, record=record, artifact_dir=directory, run_id='actual-run', output_path='dom.json')
    report = production_quality.collect_production_quality(tmp_path, record, {'brand_dom': 'dom.json'})
    check = next(c for c in report['checks'] if c['id'] == 'dependency_integrity')
    assert check['status'] == 'error'
    assert 'render_input_pins_missing' in check['issues']
