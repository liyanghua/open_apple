"""Actual render/ASR evidence producers and cheap deterministic read adapters.

Adapters never invoke a browser, FFmpeg or a speech recognizer. All raw evidence
is retained alongside immutable media and canonical-props bindings.
"""
from __future__ import annotations
import json
import math
import re
from pathlib import Path
from lib.production_evidence import file_sha256, project_file, read_object


def strict_load(root, ref):
    path = project_file(root, ref['path'])
    if file_sha256(path) != ref['sha256']:
        raise ValueError('Measurement dependency hash mismatch')
    return read_object(root, ref['path'])


def binding(root, record):
    path = record['canonical_artifacts']['final_props']
    props = read_object(root, path)
    scope = record['opening']['scope']
    if scope not in ('preview', 'full_variant') or props.get('opening', {}).get('scope') != scope:
        raise ValueError('Measurement props scope mismatch')
    media = {k: record['render'][k] for k in ('path', 'sha256')}
    if file_sha256(project_file(root, media['path'])) != media['sha256']:
        raise ValueError('Measurement media hash mismatch')
    return props, {'version': '1.0', 'scope': scope, 'render_sha256': media['sha256'], 'media_ref': media,
                   'props_ref': {'path': path, 'sha256': file_sha256(project_file(root, path))}}


def save(root, output_path, document):
    path = (Path(root) / output_path).resolve()
    path.relative_to(Path(root).resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False))
    return document


def check(name, status, issues=()):
    return {'id': name, 'status': status, 'issues': list(issues)}


def normalize(text):
    # Deliberately do not paraphrase or silently replace traditional characters.
    return ''.join(c.lower() for c in str(text) if c.isalnum())


def speech_checks(props, raw):
    names = ('narration_content', 'caption_alignment', 'slogan_tail')
    data = raw.get('data', {})
    if raw.get('method') != 'independent_asr' or raw.get('success') is not True:
        return [check(n, 'not_run', ['independent_asr_required']) for n in names]
    if not isinstance(data, dict):
        return [check(n, 'error', ['invalid_asr_data_object']) for n in names]
    segments, words = data.get('segments', []), data.get('word_timestamps', [])
    if (not isinstance(segments, list) or not isinstance(words, list)
            or any(not isinstance(row, dict) or not isinstance(row.get('text'), str) for row in segments)
            or any(not isinstance(row, dict) or not isinstance(row.get('word'), str) for row in words)):
        return [check(n, 'error', ['invalid_asr_segments_or_words']) for n in names]
    if not words or not segments:
        return [check(n, 'not_run', ['independent_word_boundaries_missing']) for n in names]
    duration = props['durationInFrames'] / props['fps']
    previous = -1
    for word in words:
        start, end = word.get('start'), word.get('end')
        if (not all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) for t in (start, end))
                or not 0 <= start < end <= duration + 1 / props['fps'] or start < previous):
            return [check(n, 'error', ['invalid_asr_word_timing']) for n in names]
        previous = end
    spoken = normalize(''.join(s['text'] for s in segments))
    recognized = normalize(''.join(w['word'] for w in words))
    expected = normalize(''.join(w.get('text', w.get('word', '')) for w in props.get('words', [])))
    narration = check('narration_content', 'pass' if expected and spoken == recognized == expected else 'fail',
                      [] if expected and spoken == recognized == expected else ['actual_speech_differs_from_expected_text'])
    captions = props.get('captions', [])
    issues = []
    if not captions:
        issues.append('captions_missing_or_undeclared')
    last = -1
    for cap in captions:
        start, end = cap.get('startMs', -1), cap.get('endMs', -1)
        if not 0 <= start < end <= duration * 1000 or start < last:
            issues.append('caption_overlap_or_invalid_interval')
        last = end
    caption_text = normalize(''.join(c.get('text', '') for c in captions))
    if caption_text != recognized:
        issues.append('captions_differ_from_actual_speech')
    for word in words:
        matches = [c for c in captions if c['startMs'] <= word['start'] * 1000 + 120 and c['endMs'] >= word['end'] * 1000 - 120]
        if not any(normalize(word['word']) in normalize(c.get('text', '')) for c in matches):
            issues.append('spoken_word_not_covered_by_matching_caption')
    alignment = check('caption_alignment', 'fail' if issues else 'pass', sorted(set(issues)))
    tail_issues = []
    if props['opening']['scope'] == 'preview':
        tail = check('slogan_tail', 'not_run')
    else:
        slogan = normalize(props['profile']['production']['slogan'])
        if not slogan or not spoken.endswith(slogan) or not recognized.endswith(slogan):
            tail_issues.append('full_slogan_not_recognized')
        if duration - words[-1]['end'] < max(.4, props['profile']['production'].get('min_tail_seconds', .4)) - 1e-6:
            tail_issues.append('less_than_0_4_seconds_after_last_word')
        tail = check('slogan_tail', 'fail' if tail_issues else 'pass', tail_issues)
    return [narration, alignment, tail]


def produce_narration_evidence(root, *, record, raw_ref, output_path):
    props, doc = binding(root, record)
    raw = strict_load(root, raw_ref)
    if raw.get('render_sha256') != doc['render_sha256']:
        raise ValueError('ASR raw media binding mismatch')
    doc.update(method='independent_asr', raw_ref=raw_ref, checks=speech_checks(props, raw),
               runtime_warnings=raw.get('runtime_warnings', []))
    return save(root, output_path, doc)


def run_narration_evidence(root, *, record, output_path, model_size='small', language=None):
    """Opt-in local transcriber execution, never run during quality reads."""
    from tools.analysis.transcriber import Transcriber
    import warnings
    props, bound = binding(root, record)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        result = Transcriber().execute({'input_path': str(project_file(root, bound['media_ref']['path'])),
                                       'model_size': model_size, 'language': language})
    raw_path = str(Path(output_path).with_name(Path(output_path).stem + '-raw.json'))
    raw = {'success': result.success, 'data': result.data, 'error': result.error,
           'method': 'independent_asr', 'render_sha256': bound['render_sha256'],
           'runtime_warnings': [str(w.message) for w in caught], 'cost_usd': result.cost_usd}
    save(root, raw_path, raw)
    return produce_narration_evidence(root, record=record,
        raw_ref={'path': raw_path, 'sha256': file_sha256(project_file(root, raw_path))}, output_path=output_path)


def dom_checks(props, frames, run_id):
    if not isinstance(frames, list) or any(not isinstance(row, dict) for row in frames):
        raise ValueError('Invalid DOM frames: expected object rows')
    if len(frames) != props['durationInFrames'] or {f.get('frame') for f in frames} != set(range(props['durationInFrames'])):
        raise ValueError('DOM evidence must cover the complete rendered frame range')
    layout, fonts = [], []
    files = props['profile']['font'].get('files', [])
    strict = props['profile']['production']['font_mode'] == 'strict'
    # Match the renderer's JS regex, which replaces each UTF-16 code unit.
    family = 'ProductionBrand-' + re.sub(r'[^a-zA-Z0-9_-]',
        lambda match: '_' * (len(match.group().encode('utf-16-le', 'surrogatepass')) // 2),
        props['profile'].get('profile_id', ''))
    for row in frames:
        if row.get('run_id') != run_id or row.get('scope') != props['opening']['scope']:
            raise ValueError('DOM evidence run/scope mismatch')
        measurement = row.get('measurement')
        if not isinstance(measurement, dict) or not isinstance(measurement.get('evidence'), dict):
            raise ValueError('Invalid DOM measurement evidence object')
        evidence = measurement['evidence']
        if evidence['frame'] != row['frame'] or (evidence['width'], evidence['height']) != (props['width'], props['height']):
            raise ValueError('DOM evidence frame geometry mismatch')
        if strict and (evidence.get('font_loading_status') != 'pass' or evidence.get('font_sha256') != [f['sha256'] for f in files]
                       or {f['weight'] for f in files} != {400, 700} or evidence.get('font_faces_ready') is not True):
            fonts.append('actual_render_font_not_ready_or_wrong_hash')
        boxes = evidence['boxes']
        if not isinstance(boxes, list) or any(not isinstance(box, dict) for box in boxes):
            raise ValueError('Invalid DOM boxes: expected object rows')
        for role in ('logo', 'title', 'underline', 'caption'):
            if sum(b.get('role') == role for b in boxes) != 1:
                layout.append('missing_or_duplicate_' + role)
        for box in boxes:
            values = [box.get(k) for k in ('x', 'y', 'width', 'height')]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                raise ValueError('Invalid DOM bounds: expected finite numbers')
            x, y, w, h = values
            if (box['role'] in ('logo', 'underline') or box.get('text')) and (w <= 0 or h <= 0):
                layout.append('required_brand_element_has_zero_bounds')
            if box.get('imageReady') is False:
                layout.append('required_brand_image_not_loaded')
            if x < 0 or y < 0 or w < 0 or h < 0 or x + w > props['width'] + .5 or y + h > props['height'] + .5:
                layout.append('text_or_brand_out_of_frame')
            if strict and box['role'] in ('title', 'caption') and (box.get('fontFamily', '').strip('"\'') != family
                    or str(box.get('fontWeight')) != ('700' if box['role'] == 'title' else '400')):
                fonts.append('computed_font_family_or_weight_mismatch')
        for i, box in enumerate(boxes):
            for other in boxes[i + 1:]:
                if box['width'] > 0 and other['width'] > 0 and box['x'] < other['x'] + other['width'] and other['x'] < box['x'] + box['width'] and box['y'] < other['y'] + other['height'] and other['y'] < box['y'] + box['height']:
                    layout.append('rendered_brand_overlap')
        ms = row['frame'] * 1000 / props['fps']
        expected_caption = next((c['text'] for c in props.get('captions', []) if c['startMs'] <= ms < c['endMs']), '')
        expected_title = next((t['text'] for t in reversed(props['titles']) if t['fromFrame'] <= row['frame']), '')
        for role, expected in (('caption', expected_caption), ('title', expected_title)):
            if not any(b['role'] == role and b['text'] == expected for b in boxes):
                layout.append('rendered_' + role + '_text_mismatch')
        layout.extend(evidence.get('issues', []))
    if not props.get('captions'):
        layout.append('captions_missing_or_undeclared')
    caps = props.get('captions', [])
    if any(a['endMs'] > b['startMs'] for a, b in zip(caps, caps[1:])):
        layout.append('caption_overlap')
    return [check('font_identity', ('fail' if fonts else 'pass') if strict else 'not_run', sorted(set(fonts)) or ([] if strict else ['legacy_font_identity_unmeasured'])),
            check('text_layout', 'fail' if layout else 'pass', sorted(set(layout)))]


def produce_brand_dom_evidence(root, *, record, artifact_dir, run_id, output_path, renderer_props_ref=None):
    props, doc = binding(root, record)
    frames = [json.loads(p.read_text()) for p in sorted(Path(artifact_dir).glob('frame-*.json'))]
    renderer_props_ref = renderer_props_ref or doc['props_ref']
    rendered_props = strict_load(root, renderer_props_ref)
    _same_render_inputs(props, rendered_props)
    checks = dom_checks(props, frames, run_id)
    if any(f.get('renderer_props_sha256') != renderer_props_ref['sha256'] for f in frames):
        raise ValueError('DOM actual renderer props hash mismatch')
    raw_path = str(Path(output_path).with_name(Path(output_path).stem + '-raw.json'))
    save(root, raw_path, {'version': '1.0', 'run_id': run_id, 'frames': frames})
    doc.update(method='rendered_browser_measurement', run_id=run_id, renderer_props_ref=renderer_props_ref,
               raw_ref={'path': raw_path, 'sha256': file_sha256(project_file(root, raw_path))}, checks=checks)
    return save(root, output_path, doc)


def evaluate_measurement(root, record, doc):
    props, bound = binding(root, record)
    for key in ('scope', 'render_sha256', 'media_ref', 'props_ref'):
        if doc.get(key) != bound[key]:
            raise ValueError('Measurement canonical dependency binding mismatch')
    raw = strict_load(root, doc['raw_ref'])
    if doc['method'] == 'independent_asr':
        if raw.get('render_sha256') != bound['render_sha256']:
            raise ValueError('Raw ASR render mismatch')
        return speech_checks(props, raw)
    if doc['method'] == 'rendered_browser_measurement':
        rendered = strict_load(root, doc['renderer_props_ref'])
        _same_render_inputs(props, rendered)
        checks = dom_checks(props, raw['frames'], doc['run_id'])
        if any(f.get('renderer_props_sha256') != doc['renderer_props_ref']['sha256'] for f in raw['frames']):
            raise ValueError('DOM actual renderer props hash mismatch')
        return checks
    raise ValueError('Unsupported measurement producer')


def _same_render_inputs(canonical, rendered):
    keys = ('profile', 'fps', 'width', 'height', 'durationInFrames', 'logoSrc', 'footage', 'titles', 'captions', 'words',
            'timingSource', 'recipe', 'audio', 'opening', 'finalMix')
    if any(canonical.get(k) != rendered.get(k) for k in keys):
        raise ValueError('Canonical props differ from actual renderer inputs')
    scene_keys = ('id', 'footageKey', 'fromFrame', 'durationInFrames', 'sourceInSeconds', 'sourceDurationSeconds',
                  'playbackRate', 'cropScale', 'role', 'sourceFps', 'framing')
    def scenes(props):
        return [{k: row.get(k) for k in scene_keys} for row in props.get('scenes', [])]
    if scenes(canonical) != scenes(rendered):
        raise ValueError('Canonical scenes differ from actual renderer inputs')
