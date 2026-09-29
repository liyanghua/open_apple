"""Read-only checks for actual judge executions and actual audio mix receipts."""
import json
import math
import re
from pathlib import Path
from lib.production_measurements import strict_load


def judge_check(root, record, document, report_path):
    check = {'id': 'video_judge', 'status': 'not_run', 'execution_status': 'not_run', 'method': 'independent_video_judge',
             'evidence_refs': [report_path], 'issues': []}
    try:
        if document.get('scope') != record['opening']['scope'] or document.get('render_sha256') != record['render']['sha256']:
            raise ValueError('Judge scope/media binding mismatch')
        if document.get('method') != 'independent_video_judge':
            raise ValueError('Independent judge execution required')
        if document.get('status') == 'error' or not document.get('scored'):
            return {**check, 'status': 'error', 'execution_status': 'error', 'issues': [document.get('error') or 'judge_execution_invalid']}
        from tools.analysis.video_judge import RUBRICS, _parse_dimensions
        rubric = RUBRICS[document['rubric_version']]
        attempts = document['attempts']
        if not 1 <= len(attempts) <= 2 or attempts[-1].get('valid') is not True:
            raise ValueError('Invalid judge attempts')
        raw = attempts[-1]['raw_response']
        match = re.search(r'\{[\s\S]*\}', raw)
        dims = _parse_dimensions(json.loads(match.group(0) if match else raw), rubric)
        if dims != _parse_dimensions(document, rubric):
            raise ValueError('Judge score projection differs from raw response')
        check['execution_status'] = 'pass'
        policy_ref = document.get('policy_ref')
        if not policy_ref:
            return {**check, 'issues': ['judge_policy_missing']}
        policy = strict_load(root, policy_ref)
        if policy.get('version') != '1.0' or policy.get('rubric_version') != document['rubric_version']:
            raise ValueError('Judge policy rubric mismatch')
        minimum = policy['minimum_scores']
        if set(minimum) != {d[0] for d in rubric} or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 10 for v in minimum.values()):
            raise ValueError('Judge policy must cover every rubric dimension')
        check['evidence_refs'].append(policy_ref['path'])
        failures = [d['id'] for d in dims if d['score'] < minimum[d['id']]]
        return {**check, 'status': 'fail' if failures else 'pass', 'issues': failures}
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
        return {**check, 'status': 'error', 'issues': [str(exc)]}


def mix_origin_check(root, record):
    check = {'id': 'mix_origin', 'status': 'not_run', 'method': 'actual_audio_mixer_receipt', 'evidence_refs': [],
             'issues': ['actual_mix_execution_receipt_missing'], 'source_provenance_status': 'not_run'}
    try:
        opening = record.get('opening') or {}
        if not isinstance(opening, dict) or opening.get('scope') != 'full_variant' or not opening.get('validation_report_ref'):
            return check
        report = strict_load(root, opening['validation_report_ref'])
        evidence = strict_load(root, report['dependencies']['freeze_evidence'])
        mix = strict_load(root, evidence['candidate_mix_plan_ref'])
        props = strict_load(root, evidence['candidate_props_ref'])
        if not mix.get('execution_receipt_ref'):
            return check
        receipt_ref = mix['execution_receipt_ref']
        receipt = strict_load(root, receipt_ref)
        from lib.opening_freeze import _mix_body, _walk_refs
        _mix_body(root, mix, props['finalMix'])
        _walk_refs(root, receipt)
        check['evidence_refs'] = [receipt_ref['path'], evidence['candidate_mix_plan_ref']['path']]
        args = receipt['arguments']
        if (receipt.get('tool') != 'audio_mixer' or receipt.get('operation') != 'full_mix' or receipt.get('scope') != 'full_variant'
                or receipt.get('returncode') != 0 or args.get('operation') != 'full_mix' or args.get('opening_scope') != 'full_variant'
                or receipt['output_ref'] != mix['output_ref'] or receipt['output_ref'] != {k: props['finalMix'][k] for k in ('path', 'sha256')}
                or args.get('target_duration') != props['durationInFrames'] / props['fps']):
            raise ValueError('Actual full mix execution/output/scope mismatch')
        tracks = args['tracks']
        if len(tracks) != len(receipt['input_refs']) or not tracks:
            raise ValueError('Mix execution input inventory mismatch')
        declared = {(r['path'], r['sha256']) for r in mix['raw_refs']}
        actual = {(r['path'], r['sha256']) for r in receipt['input_refs']}
        if declared != actual:
            raise ValueError('Actual mix did not execute the declared raw inputs')
        for track, ref in zip(tracks, receipt['input_refs']):
            if Path(track['path']).resolve() != (Path(root) / ref['path']).resolve():
                raise ValueError('Mix executed track path differs from receipt')
        if receipt['command'][0] != 'ffmpeg' or '-filter_complex' not in receipt['command']:
            raise ValueError('Actual mix command missing')
        # Execution establishes which bytes were mixed, not how those source bytes
        # originated or whether their content is semantically continuous/audible.
        return {**check, 'status': 'pass', 'issues': []}
    except KeyError:
        return check
    except (ValueError, TypeError, OSError) as exc:
        return {**check, 'status': 'error', 'issues': [str(exc)]}
