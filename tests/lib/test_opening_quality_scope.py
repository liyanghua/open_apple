import json
import pytest
from lib.production_evidence import build_production_subject, file_sha256, quality_summary
from lib.production_quality import collect_production_quality


def write(root, name, value):
    path = root / name
    path.write_text(json.dumps(value))
    return {'path': name, 'sha256': file_sha256(path)}


def record(root, scope='preview'):
    (root / 'film.mp4').write_bytes(b'film')
    return {'content_slot_id': 'A01-H1', 'sku': 'sku', 'render': {'path': 'film.mp4', 'sha256': file_sha256(root / 'film.mp4')},
            'opening': {'scope': scope, 'candidate_id': 'H1'}, 'canonical_artifacts': {}}


def test_preview_never_certifiable_and_full_requirements_are_predetermined(tmp_path):
    r = record(tmp_path)
    preview = collect_production_quality(tmp_path, r, {})
    assert preview['scope'] == 'preview'
    assert preview['applicability']['slogan_tail'] == {'applies': False, 'required': False, 'reason': 'Opening preview excludes the full-film slogan and tail.'}
    assert preview['applicability']['product_identity']['required']
    assert not preview['certification_eligible']
    r['opening']['scope'] = 'full_variant'
    full = collect_production_quality(tmp_path, r, {})
    for name in ['slogan_tail', 'frozen_body', 'opening_join', 'mix_origin', 'video_judge']:
        assert full['applicability'][name]['required']
        assert next(c for c in full['checks'] if c['id'] == name)['status'] != 'pass'


def test_unknown_scope_cannot_waive_checks(tmp_path):
    r = record(tmp_path, 'bogus')
    report = collect_production_quality(tmp_path, r, {})
    assert report['scope'] == 'invalid'
    assert not report['certification_eligible']


def test_nested_hashes_are_validated_and_snapshotted(tmp_path):
    r = record(tmp_path)
    leaf = write(tmp_path, 'leaf.json', {'sku': 'sku'})
    r['opening']['experiment_ref'] = write(tmp_path, 'experiment.json', {'reference_pool': leaf})
    write(tmp_path, 'record.json', r)
    subject = build_production_subject(tmp_path, 'record.json')
    assert leaf in subject['dependencies'].values()
    write(tmp_path, 'leaf.json', {'sku': 'changed'})
    with pytest.raises(ValueError, match='hash'):
        build_production_subject(tmp_path, 'record.json')


def test_dependency_cycles_are_rejected(tmp_path):
    r = record(tmp_path)
    r['quality_report_ref'] = 'qa.json'
    write(tmp_path, 'qa.json', {'source_refs': {'loop': 'record.json'}})
    write(tmp_path, 'record.json', r)
    with pytest.raises(ValueError, match='cycle'):
        build_production_subject(tmp_path, 'record.json')


def test_human_opening_observation_is_not_machine_pass(tmp_path):
    from tests.lib.test_opening_motion_evidence import fixture, update_observation
    r, report, observation = fixture(tmp_path, method='human_review')
    observation['reviewer']['kind'] = 'human'
    for c in report['checks']:
        c['reviewer'] = observation['reviewer']
    update_observation(tmp_path, r, report, observation)
    checks = {c['id']: c for c in collect_production_quality(tmp_path, r, {})['checks']}
    assert checks['opening_motion']['status'] == 'not_run'
    assert checks['opening_motion']['effective_status'] == 'manual_verified'


def test_static_opening_is_explicit_na(tmp_path):
    from tests.lib.test_opening_motion_evidence import fixture
    from tests.contracts.test_opening_contracts import hook_v2
    plan = hook_v2()
    plan['motion_policy'] = {'mode': 'optional', 'rationale': 'Static material inspection'}
    plan['shots'][0]['motion'].update(motion_required=False, verb='none', end_state='closed')
    plan['shots'][0]['motion']['exemption_reason'] = 'Static material inspection'
    r, _, _ = fixture(tmp_path, plan=plan)
    report = collect_production_quality(tmp_path, r, {})
    check = next(c for c in report['checks'] if c['id'] == 'opening_motion')
    assert check['status'] == 'not_run'
    assert not report['applicability']['opening_motion']['applies']


def test_preview_cannot_create_final_review(tmp_path):
    from backlot.operator_reviews import ReviewService
    from backlot.operator_errors import OperatorError
    write(tmp_path, 'project.json', {'project_id': 'x'})
    r = record(tmp_path)
    write(tmp_path, 'record.json', r)
    with pytest.raises(OperatorError):
        ReviewService(tmp_path).create_final_review(record_path='record.json', submitted_by='producer')


def test_b0_preparation_waives_only_frozen_comparison_and_rejects_forged_slot(tmp_path):
    from tests.lib.test_opening_motion_evidence import fixture
    from lib.opening_quality_scope import quality_applicability
    r, _, _ = fixture(tmp_path, scope='full_variant')
    r['opening'].pop('validation_report_ref')
    r.update(content_slot_id='A01-B0')
    r['opening']['candidate_id'] = 'B0'
    exp = json.loads((tmp_path / 'experiment.json').read_text())
    exp['candidates'][0]['candidate_id'] = 'B0'
    exp['baseline_ref'] = {**write(tmp_path, 'identity.json', {'version': '1.0', 'role': 'baseline_preparation',
        'sku': r['sku'], 'candidate_id': 'B0', 'content_slot_id': 'A01-B0'}), 'sku': r['sku']}
    from lib.opening_freeze import create_pending_freeze_descriptor
    pool = write(tmp_path, 'pool.json', {'version': '1.0', 'sku': r['sku'], 'reference_boundaries': [0, 3],
        'reference_images': [write(tmp_path, 'ref-image.json', {'image': 'fixture'})]})
    pending = create_pending_freeze_descriptor(tmp_path, identity={'sku': r['sku'], 'fact_version': '1', 'reference_boundaries': [0, 3], 'brand_profile': 'brand'},
        dependencies={'facts': exp['facts_ref'], 'brand': exp['brand_ref'], 'reference': pool, 'renderer': write(tmp_path, 'renderer.json', {})})
    exp['frozen_body_ref'] = write(tmp_path, 'pending.json', pending)
    r['opening']['experiment_ref'] = write(tmp_path, 'experiment.json', exp)
    scope, rules = quality_applicability(tmp_path, r)
    assert scope == 'baseline_preparation'
    assert not rules['frozen_body']['applies']
    assert all(rules[n]['required'] for n in ('opening_join', 'font_identity', 'narration_content', 'slogan_tail', 'video_judge'))
    r['content_slot_id'] = 'A03-B0'
    scope, rules = quality_applicability(tmp_path, r)
    assert scope == 'full_variant'
    assert rules['frozen_body']['required']


def test_incomplete_pending_descriptor_does_not_grant_preparation_exemption(tmp_path):
    from tests.lib.test_opening_motion_evidence import fixture
    from lib.opening_quality_scope import quality_applicability
    r, _, _ = fixture(tmp_path, scope='full_variant')
    r.update(content_slot_id='A01-B0')
    r['opening']['candidate_id'] = 'B0'
    exp = json.loads((tmp_path / 'experiment.json').read_text())
    exp['candidates'][0]['candidate_id'] = 'B0'
    exp['baseline_ref'] = {**write(tmp_path, 'identity.json', {'version': '1.0', 'role': 'baseline_preparation', 'sku': r['sku'], 'candidate_id': 'B0', 'content_slot_id': 'A01-B0'}), 'sku': r['sku']}
    exp['frozen_body_ref'] = write(tmp_path, 'pending.json', {'version': '1.0', 'state': 'pending'})
    r['opening']['experiment_ref'] = write(tmp_path, 'experiment.json', exp)
    assert quality_applicability(tmp_path, r)[0] == 'full_variant'


def test_semantic_artifact_reference_cannot_snapshot_over_expected_hash(tmp_path):
    from lib.artifact_hashing import attach_hashes
    r = record(tmp_path)
    original = attach_hashes({'version': '1.0', 'policy': 'approved'})
    write(tmp_path, 'policy.json', attach_hashes({'version': '1.0', 'policy': 'changed'}))
    r['review_dependencies'] = {'caption_policy_revision_ref': {'path': 'policy.json',
        'semantic_sha256': original['semantic_sha256'], 'artifact_sha256': original['artifact_sha256']}}
    write(tmp_path, 'record.json', r)
    with pytest.raises(ValueError, match='hash'):
        build_production_subject(tmp_path, 'record.json')
