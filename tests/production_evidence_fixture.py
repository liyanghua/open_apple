"""Synthetic bound source-report fixtures; never real media/VI certification."""
import json
from pathlib import Path

from lib.production_quality import collect_production_quality


def create_bound_quality(root, record, *, prefix="fixture-evidence"):
    root = Path(root)

    def put(name, data):
        ref = f"{prefix}/{name}.json"
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return ref

    render = record["render"]
    sha = render["sha256"]
    if not record.get("canonical_artifacts"):
        record["canonical_artifacts"] = {"final_props": put("props", {"fixture_only": True})}
    refs = {"technical": put("technical", {
        "fixture_only": True, "metadata": {"media_sha256": sha},
        "checks": {"media_integrity": {"decode_ok": True, "profile_ok": True},
                   "technical_probe": {"duration_seconds": render.get("seconds", 4), "has_audio": True}},
    })}
    for source, names, method in (
        ("brand_dom", ("font_identity", "text_layout"), "rendered_browser_measurement"),
        ("narration", ("narration_content",), "independent_asr"),
        ("alignment", ("caption_alignment",), "measured_word_alignment"),
        ("product_review", ("fact_source", "product_identity"), "product_evidence_review"),
        ("continuity", ("visual_continuity",), "rendered_continuity_check"),
    ):
        refs[source] = put(source, {"fixture_only": True, "render_sha256": sha,
            "method": method, "checks": [{"id": name, "status": "pass", "issues": []} for name in names]})
    return collect_production_quality(root, record, refs)


def create_bound_opening_quality(root, record, *, prefix='fixture-evidence'):
    """Synthetic raw instrument outputs for contract unit tests; no real certification.

    Exercises the actual read adapters, never mocks eligibility or deletes gates.
    """
    from lib.production_evidence import file_sha256, read_object
    from lib.production_measurements import produce_brand_dom_evidence, produce_narration_evidence
    from tools.analysis.video_judge import L3_DIMENSIONS
    root = Path(root)
    def put(name, doc):
        path = root / (prefix + '/' + name + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))
        return {'path': path.relative_to(root).as_posix(), 'sha256': file_sha256(path)}
    def ref(path):
        return {'path': path, 'sha256': file_sha256(root / path)}
    props_ref = ref(record['canonical_artifacts']['final_props'])
    props = read_object(root, props_ref['path'])
    sha = record['render']['sha256']
    opening = record['opening']
    scope = opening['scope']
    base = create_bound_quality(root, record, prefix=prefix)
    sources = base['source_refs']
    technical = read_object(root, sources['technical'])
    technical['scope'] = scope
    (root / sources['technical']).write_text(json.dumps(technical))
    for source in ('product_review', 'continuity'):
        semantic = read_object(root, sources[source])
        semantic.update(scope=scope, props_ref=props_ref, method='independent_semantic_review',
            reviewer={'kind': 'semantic_verifier', 'id': 'fixture-verifier', 'reviewed_at': '2026-09-29T00:00:00Z'})
        (root / sources[source]).write_text(json.dumps(semantic))
    # All output frames carry synthetic DOM bounds + actual source file pins.
    directory = root / prefix / 'raw-dom'
    directory.mkdir(parents=True, exist_ok=True)
    for frame in range(props['durationInFrames']):
        ms = frame * 1000 / props['fps']
        caption = next((c['text'] for c in props['captions'] if c['startMs'] <= ms < c['endMs']), '')
        title = next((t['text'] for t in reversed(props['titles']) if t['fromFrame'] <= frame), '')
        boxes = [{'role': role, 'text': text, 'x': 1, 'y': i * 12 + 1, 'width': 20, 'height': 6,
                  'fontFamily': 'ProductionBrand-fixture', 'fontWeight': '700' if role == 'title' else '400'}
                 for i, (role, text) in enumerate([('logo', ''), ('title', title), ('underline', ''), ('caption', caption)])]
        row = {'run_id': 'fixture', 'renderer_props_sha256': props_ref['sha256'], 'frame': frame, 'scope': scope,
            'measurement': {'evidence': {'frame': frame, 'width': props['width'], 'height': props['height'], 'boxes': boxes,
                'issues': [], 'font_loading_status': 'pass', 'font_faces_ready': True,
                'font_sha256': [f['sha256'] for f in props['profile']['font']['files']]}}}
        (directory / f'frame-{frame:06d}.json').write_text(json.dumps(row))
    sources['brand_dom'] = prefix + '/brand-dom-bound.json'
    produce_brand_dom_evidence(root, record=record, artifact_dir=directory, run_id='fixture', output_path=sources['brand_dom'])
    words = [{'word': w['text'], 'start': w['startMs'] / 1000, 'end': w['endMs'] / 1000, 'probability': .99} for w in props['words']]
    raw_asr = put('asr-raw', {'fixture_only': True, 'method': 'independent_asr', 'success': True, 'render_sha256': sha,
        'data': {'segments': [{'text': ''.join(w['word'] for w in words), 'start': words[0]['start'], 'end': words[-1]['end']}], 'word_timestamps': words}})
    sources['narration'] = prefix + '/asr-bound.json'
    produce_narration_evidence(root, record=record, raw_ref=raw_asr, output_path=sources['narration'])
    dims = [{'id': d[0], 'score': 8, 'note': 'synthetic fixture'} for d in L3_DIMENSIONS]
    policy = put('judge-policy', {'version': '1.0', 'rubric_version': 'l3-v1.0', 'minimum_scores': {d[0]: 7 for d in L3_DIMENSIONS}})
    sources['video_judge'] = put('judge', {'render_sha256': sha, 'scope': scope, 'method': 'independent_video_judge', 'scored': True,
        'status': 'pass', 'rubric_version': 'l3-v1.0', 'dimensions': dims, 'policy_ref': policy,
        'attempts': [{'valid': True, 'raw_response': json.dumps({'dimensions': dims}), 'usage': {}, 'actual_cost_usd': None}]})['path']
    # B0 preparation needs the actual bounded join even before the body comparison applies.
    frames = [{'frame': i, 'pts': i, 'size': 10, 'md5': 'a' * 32} for i in range(75, 105)]
    measurement = {'method': 'ffmpeg_native_interval_v1', 'media_sha256': sha, 'fps': 30, 'interval_frames': [75, 105],
        'total_video_frames': props['durationInFrames'], 'duration_seconds': props['durationInFrames'] / 30,
        'video': {'frames': frames, 'timestamps_seconds': [i / 30 for i in range(75, 105)],
                  'raw_framemd5': '\n'.join(f"0, {i}, {i}, 1, 10, " + 'a' * 32 for i in range(75, 105))},
        'audio': {'sample_rate': 1000, 'channels': 1, 'samples': 1000, 'decoded_pcm_sha256': 'a' * 64}}
    join = put('join', {'version': '1.0', 'method': 'actual_opening_join_decode', 'media_ref': record['render'],
                       'duration_frames': props['durationInFrames'], 'measurement': measurement})
    experiment = read_object(root, opening['experiment_ref']['path'])
    mix_ref = ref(record['canonical_artifacts']['mix_plan'])
    manifest = put('freeze-evidence', {'version': '1.0', 'candidate_id': opening['candidate_id'],
        'experiment_ref': opening['experiment_ref'], 'hook_plan_ref': opening['hook_plan_ref'],
        'freeze_ref': experiment['frozen_body_ref'], 'candidate_props_ref': props_ref, 'candidate_mix_plan_ref': mix_ref,
        'media_ref': record['render'], 'join_measurement_ref': join})
    report = read_object(root, opening['validation_report_ref']['path'])
    report['dependencies']['freeze_evidence'] = manifest
    (root / opening['validation_report_ref']['path']).write_text(json.dumps(report))
    opening['validation_report_ref'] = ref(opening['validation_report_ref']['path'])
    return collect_production_quality(root, record, sources)
