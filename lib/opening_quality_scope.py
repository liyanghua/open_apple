"""Predetermined opening applicability; never accepts caller waiver flags."""
from collections.abc import Mapping
from lib.production_evidence import REQUIRED_CHECKS, read_object

OPENING_EXTRA = ('opening_motion', 'opening_framing', 'slogan_tail', 'frozen_body', 'opening_join', 'mix_origin', 'video_judge')


def baseline_preparation(root, record):
    opening = record.get('opening') if isinstance(record.get('opening'), Mapping) else {}
    if opening.get('scope') != 'full_variant' or opening.get('candidate_id') != 'B0':
        return False
    try:
        from lib.opening_contracts import verify_opening_experiment_files
        experiment, _ = verify_opening_experiment_files(root, opening['experiment_ref'])
        identity = read_object(root, experiment['baseline_ref']['path'])
        descriptor = read_object(root, experiment['frozen_body_ref']['path'])
        from lib.opening_freeze import create_pending_freeze_descriptor
        rebuilt = create_pending_freeze_descriptor(root, identity=descriptor['identity'], dependencies=descriptor['dependencies'])
        if descriptor != rebuilt or descriptor['identity']['sku'] != record['sku']:
            return False
        for role, key in (('facts', 'facts_ref'), ('brand', 'brand_ref')):
            if any(descriptor['dependencies'][role][k] != experiment[key][k] for k in ('path', 'sha256')):
                return False
        registered = next(c for c in experiment['candidates'] if c['candidate_id'] == 'B0')
        return (identity == {'version': '1.0', 'role': 'baseline_preparation', 'sku': record['sku'],
                             'candidate_id': 'B0', 'content_slot_id': record['content_slot_id']}
                and experiment['sku'] == record['sku'] and registered['hook_plan_ref'] == opening['hook_plan_ref']
                and descriptor.get('state') == 'pending')
    except (ValueError, KeyError, TypeError, OSError, StopIteration):
        return False


def quality_applicability(root, record):
    scope = 'legacy'
    artifacts = record.get('canonical_artifacts') or {}
    props_path = artifacts.get('final_props') if isinstance(artifacts, Mapping) else None
    try:
        props = read_object(root, props_path) if props_path else {}
    except (ValueError, OSError, TypeError):
        props = {}
    props_opening = props.get('opening') if isinstance(props, Mapping) else None
    declared = record.get('opening') if isinstance(record.get('opening'), Mapping) else None
    scope_mismatch = ((props_opening is not None and
                       (not isinstance(props_opening, Mapping) or declared is None
                        or declared.get('scope') != props_opening.get('scope')))
                      or (declared is not None and props_opening is None and props_path is not None))
    if 'opening' in record:
        scope = record['opening'].get('scope') if isinstance(record.get('opening'), Mapping) else None
        if scope not in ('preview', 'full_variant'):
            scope = 'invalid'
        elif baseline_preparation(root, record):
            scope = 'baseline_preparation'
    if scope_mismatch:
        scope = 'invalid'
    if scope in ('preview', 'full_variant', 'baseline_preparation') and props_path is not None:
        try:
            from lib.opening_experiment_evidence import _plan_sources_match
            plan = read_object(root, record['opening']['hook_plan_ref']['path'])
            _plan_sources_match(root, props, plan)
        except (ValueError, OSError, KeyError, TypeError):
            scope = 'invalid'
    names = REQUIRED_CHECKS + (OPENING_EXTRA if scope != 'legacy' else ())
    rules = {name: {'applies': True, 'required': True, 'reason': 'Required for the declared production scope.'} for name in names}
    if scope == 'preview':
        for name, reason in {
            'slogan_tail': 'Opening preview excludes the full-film slogan and tail.',
            'frozen_body': 'Opening preview contains no common body.',
            'opening_join': 'Opening preview contains no opening/body join.',
            'mix_origin': 'Opening preview is not a full-film raw-source mix.',
        }.items():
            rules[name] = {'applies': False, 'required': False, 'reason': reason}
    if scope == 'baseline_preparation':
        rules['frozen_body'] = {'applies': False, 'required': False, 'reason': 'Registered B0 preparation establishes the body before any baseline approval exists.'}
    return scope, rules
