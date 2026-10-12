"""Deterministic Chengfang material and direction diagnosis.

This module intentionally has no storage or HTTP dependencies.  A diagnosis is a
replayable function of two confirmed exports and the frozen plan context.
"""
from __future__ import annotations

from datetime import date, datetime
import math

from .engine import div, exposure_bucket, growth, smooth


_RULE_KEYS = {
    'primary_objective', 'min_creatives',
    'expand_primary_ratio', 'expand_roi_ratio', 'expand_order_ratio',
    'stop_primary_ratio', 'stop_roi_ratio', 'stop_order_ratio',
}
_CONTEXT_OPERATION_KINDS = {
    'roi_target_changed', 'budget_changed', 'capability_changed', 'product_changed', 'landing_changed',
}
_DELIVERY_CONTEXT_KEYS = ('base_delivery', 'star_select', 'creator_marketing', 'creator_commission_bid')
_CAPABILITY_CONTEXT_KEYS = ('status',)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _config_value(plan_context):
    if not isinstance(plan_context, dict):
        raise ValueError('计划上下文无效')
    return plan_context.get('config', plan_context)


def _meta(snapshot):
    return snapshot.get('metadata') or {}


def _identity(snapshot):
    meta = _meta(snapshot)
    return {
        'plan_id': meta.get('plan_id'), 'path': snapshot.get('path', meta.get('path')),
        'partition': meta.get('partition'), 'basis': meta.get('cost_basis'),
    }


def _require_snapshot(snapshot, name):
    if not isinstance(snapshot, dict):
        raise ValueError(f'{name}导入无效')
    if snapshot.get('status') != 'confirmed' or snapshot.get('complete') is not True:
        raise ValueError(f'{name}导入尚未确认')
    identity = _identity(snapshot)
    if identity['partition'] != 'chengfang':
        raise ValueError('诊断只接受成方分区导入')
    if identity['basis'] != 'marketing_cost':
        raise ValueError('成方诊断只接受营销消耗口径')
    if not identity['plan_id'] or identity['path'] not in ('live', 'product') or not isinstance(snapshot.get('scope'), str) or not snapshot['scope']:
        raise ValueError('成方导入缺少计划或路径')
    meta = _meta(snapshot)
    if not isinstance(meta.get('timezone'), str) or not meta['timezone'] or not isinstance(meta.get('base_delivery_only'), bool):
        raise ValueError('成方导入缺少统计上下文')
    if meta.get('cost_grain') != 'material_attributable' or not isinstance(meta.get('delivery_context'), dict) or not isinstance(meta.get('capability_context'), dict):
        raise ValueError('成方导入缺少投放或能力上下文')
    return identity


def _period_ok(snapshot):
    try:
        start = date.fromisoformat(snapshot['period_start'])
        end = date.fromisoformat(snapshot['period_end'])
    except (KeyError, TypeError, ValueError):
        return False
    return end >= start and (end - start).days + 1 == 7 and snapshot.get('window') == 7


def _nonoverlap(earlier, selected):
    if not earlier or not _period_ok(earlier) or not _period_ok(selected):
        return False
    return date.fromisoformat(earlier['period_end']) < date.fromisoformat(selected['period_start'])


def _cost(row, base_delivery_only):
    cost = row.get('marketing_cost')
    if cost is None and base_delivery_only:
        cost = row.get('spend')
    return cost


def _outcome_ok(row):
    return _number(row.get('net_gmv')) and row['net_gmv'] >= 0 and _number(row.get('net_orders')) and row['net_orders'] >= 0


def _canonical(value):
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _operation_overlaps(operation, snapshot):
    kind = str(operation.get('kind', '')).lower()
    if kind not in _CONTEXT_OPERATION_KINDS:
        return False
    try:
        occurred = datetime.fromisoformat(str(operation['occurred_at']).replace('Z', '+00:00')).date()
        return date.fromisoformat(snapshot['period_start']) <= occurred <= date.fromisoformat(snapshot['period_end'])
    except (KeyError, TypeError, ValueError):
        return False


def _profiles(material_profiles, identity):
    values = {}
    for profile in material_profiles or []:
        if not isinstance(profile, dict) or not profile.get('creative_id') or profile.get('plan_id') != identity['plan_id'] or profile.get('path') != identity['path']:
            continue
        labels = profile.get('labels') or []
        if isinstance(labels, dict):
            labels = list(labels.values())
        if not isinstance(labels, (list, tuple)):
            labels = []
        values[str(profile['creative_id'])] = {
            'labels': [str(label) for label in labels if str(label)],
            'revision': profile.get('revision'),
        }
    return values


def _context_matches(snapshot, context):
    meta = _meta(snapshot)
    expected_delivery = {key: context.get(key) for key in _DELIVERY_CONTEXT_KEYS}
    expected_capability = {key: context.get(key) for key in _CAPABILITY_CONTEXT_KEYS}
    return (meta.get('base_delivery_only') == bool(context.get('base_delivery_only')) and
            meta.get('delivery_context') == expected_delivery and meta.get('capability_context') == expected_capability)


def _snapshot_context(snapshot):
    meta = _meta(snapshot)
    return {
        'scope': snapshot.get('scope'), 'timezone': meta.get('timezone'),
        'base_delivery_only': meta.get('base_delivery_only'), 'cost_grain': meta.get('cost_grain'),
        'delivery_context': meta.get('delivery_context'), 'capability_context': meta.get('capability_context'),
    }


def _scoped_operations(operation_log, identity):
    values = []
    for operation in operation_log or []:
        if not isinstance(operation, dict):
            continue
        if operation.get('plan_id') != identity['plan_id'] or operation.get('path') != identity['path']:
            continue
        values.append(_canonical(operation))
    values.sort(key=lambda item: (str(item.get('occurred_at', '')), str(item.get('id', '')), str(item.get('kind', ''))))
    return values


def _reason_codes(row, snapshot, base_delivery_only):
    codes = []
    if row.get('is_aggregate'):
        codes.append('AGGREGATE_ROW')
    if row.get('errors'):
        codes.append('ROW_INVALID')
    if not _period_ok(snapshot):
        codes.append('MISMATCHED_RANGE')
    meta = _meta(snapshot)
    if meta.get('cost_grain') != 'material_attributable':
        codes.append('NON_ATTRIBUTABLE_COST')
    reconciliation = meta.get('reconciliation') or {}
    if not reconciliation.get('reconciled', False):
        codes.append('UNRECONCILED_COST')
    if not _number(row.get('impressions')) or row['impressions'] < 0:
        codes.append('MISSING_EXPOSURE')
    cost = _cost(row, base_delivery_only)
    if not _number(cost) or cost <= 0:
        codes.append('MISSING_MARKETING_COST')
    if not _outcome_ok(row):
        codes.append('MISSING_OUTCOME')
    return list(dict.fromkeys(codes))


def _raw_metrics(row, cost):
    return {
        'exposure': row.get('impressions'), 'marketing_cost': cost,
        'net_gmv': row.get('net_gmv'), 'orders': row.get('net_orders'),
        'roi': div(row.get('net_gmv'), cost),
    }


def _reference(snapshot, base_delivery_only, smoothing_fen):
    valid = []
    for row in ((snapshot.get('data') or {}).get('rows') or []):
        if _reason_codes(row, snapshot, base_delivery_only):
            continue
        valid.append((row, _cost(row, base_delivery_only)))
    spend = sum(cost for _, cost in valid)
    exposure = sum(row['impressions'] for row, _ in valid)
    orders = sum(row['net_orders'] for row, _ in valid)
    gmv = sum(row['net_gmv'] for row, _ in valid)
    roi = div(gmv, spend)
    return {
        'exposure': div(exposure, spend), 'orders': div(orders, spend), 'roi': roi,
        'smoothed_roi': smooth(roi, spend, roi, smoothing_fen) if roi is not None else None,
        'creative_count': len(valid), 'spend': spend,
    }


def _complete_rules(config):
    rules = config.get('direction_rules') if isinstance(config, dict) else None
    if not isinstance(rules, dict) or set(rules) != _RULE_KEYS:
        return None
    if rules.get('primary_objective') not in ('exposure', 'orders', 'roi'):
        return None
    if not isinstance(rules.get('min_creatives'), int) or rules['min_creatives'] < 1:
        return None
    for key in _RULE_KEYS - {'primary_objective', 'min_creatives'}:
        if not _number(rules.get(key)) or not 0 < rules[key] <= 1:
            return None
    return _canonical(rules)


def _direction_metrics(rows, base_delivery_only):
    spend = sum(_cost(row, base_delivery_only) for row in rows)
    return {
        'exposure': div(sum(row['impressions'] for row in rows), spend),
        'orders': div(sum(row['net_orders'] for row in rows), spend),
        'roi': div(sum(row['net_gmv'] for row in rows), spend),
        'spend': spend,
    }


def _relative(metrics, reference):
    return {key: div(metrics.get(key), reference.get(key)) for key in ('exposure', 'orders', 'roi')}


def _brief(labels, creative_count, current, previous, primary):
    ratio = div(current.get(primary), previous.get(primary)) if previous else None
    direction = 'UP' if ratio is not None and ratio > 1 else 'DOWN' if ratio is not None and ratio < 1 else 'FLAT'
    return {
        'retain_labels': labels[:-1], 'change_label': labels[-1] if labels else None,
        'produce_count': creative_count, 'comparison_direction': direction,
    }


def diagnose(selected_confirmed_7_day_import, optional_earlier_nonoverlap_import, plan_context,
             material_profiles, config, operation_log):
    """Return a deterministic Chengfang diagnosis with no side effects.

    Costs are integer fen, matching importer records.  Efficiencies are therefore
    per-fen except ROI, whose currency units cancel out.
    """
    current_identity = _require_snapshot(selected_confirmed_7_day_import, '选中')
    earlier_identity = None
    if optional_earlier_nonoverlap_import is not None:
        earlier_identity = _require_snapshot(optional_earlier_nonoverlap_import, '前期')
        for key in ('plan_id', 'path', 'partition', 'basis'):
            if earlier_identity[key] != current_identity[key]:
                raise ValueError('两期导入的计划、路径、分区或成本口径不一致')
        if _snapshot_context(optional_earlier_nonoverlap_import) != _snapshot_context(selected_confirmed_7_day_import):
            raise ValueError('两期导入的范围或投放上下文不一致')

    context = _config_value(plan_context)
    if context.get('plan_id') != current_identity['plan_id'] or context.get('path') != current_identity['path']:
        raise ValueError('计划上下文与导入不一致')
    if not _context_matches(selected_confirmed_7_day_import, context):
        raise ValueError('计划上下文与导入投放条件不一致')
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError('诊断配置无效')
    base_delivery_only = bool(context.get('base_delivery_only'))
    smoothing_fen = float(config.get('smoothing_yuan', 100)) * 100
    min_exposure = config.get('diagnosis_min_impressions', 500)
    min_spend = float(config.get('diagnosis_min_spend_yuan', 100)) * 100
    required_periods = config.get('diagnosis_required_periods', 2)
    if not isinstance(min_exposure, int) or min_exposure < 1 or not _number(min_spend) or min_spend <= 0:
        raise ValueError('诊断阈值无效')
    if not isinstance(required_periods, int) or required_periods < 2:
        raise ValueError('诊断周期要求无效')

    profiles = _profiles(material_profiles, current_identity)
    current_rows = list((selected_confirmed_7_day_import.get('data') or {}).get('rows') or [])
    earlier_rows = list(((optional_earlier_nonoverlap_import or {}).get('data') or {}).get('rows') or [])
    earlier_by_id = {str(row.get('creative_id')): row for row in earlier_rows if row.get('creative_id') is not None}
    current_range_ok = _period_ok(selected_confirmed_7_day_import)
    earlier_range_ok = optional_earlier_nonoverlap_import is None or _period_ok(optional_earlier_nonoverlap_import)
    periods_comparable = bool(optional_earlier_nonoverlap_import and current_range_ok and earlier_range_ok and
                              _nonoverlap(optional_earlier_nonoverlap_import, selected_confirmed_7_day_import))
    operation_entries = _scoped_operations(operation_log, current_identity)
    context_changed = any(_operation_overlaps(operation, selected_confirmed_7_day_import) or
                          (optional_earlier_nonoverlap_import is not None and _operation_overlaps(operation, optional_earlier_nonoverlap_import))
                          for operation in operation_entries)

    material_reference = _reference(selected_confirmed_7_day_import, base_delivery_only, smoothing_fen)
    cards = []
    direction_rows = []
    reference_rows = []
    warnings = []
    for index, row in enumerate(current_rows):
        creative_id = str(row.get('creative_id') or f'aggregate-{index + 1}')
        profile = profiles.get(creative_id, {'labels': [], 'revision': None})
        cost = _cost(row, base_delivery_only)
        codes = _reason_codes(row, selected_confirmed_7_day_import, base_delivery_only)
        if optional_earlier_nonoverlap_import is not None and not earlier_range_ok:
            codes.append('MISMATCHED_RANGE')
        raw_codes = list(codes)
        previous = earlier_by_id.get(creative_id)
        previous_cost = _cost(previous, base_delivery_only) if previous else None
        raw = _raw_metrics(row, cost)
        prior_raw = _raw_metrics(previous, previous_cost) if previous else None
        period_count = 2 if periods_comparable and previous is not None and not _reason_codes(previous, optional_earlier_nonoverlap_import, base_delivery_only) else 1
        if codes:
            sample_state, decision = 'NEEDS_DATA', 'NEEDS_DATA'
        elif row['impressions'] < min_exposure:
            sample_state, decision = 'LOW_EXPOSURE', 'OBSERVE'
            codes.append('LOW_EXPOSURE')
        elif cost < min_spend:
            sample_state, decision = 'LOW_SPEND', 'TEST_VARIANT'
            codes.append('LOW_COMPARABLE_SPEND')
        elif period_count < required_periods:
            sample_state, decision = 'ONE_PERIOD', 'TEST_VARIANT'
            codes.append('INSUFFICIENT_COMPARABLE_PERIODS')
        else:
            sample_state, decision = 'READY', 'OBSERVE'
        card_warnings = []
        if context_changed:
            card_warnings.append('OPERATION_CONTEXT_CHANGED')
        card = {
            'creative_id': creative_id, 'labels': profile['labels'], 'sample_state': sample_state,
            'raw_metrics': raw,
            'objective_metrics': {
                'exposure': raw['exposure'], 'orders': raw['orders'], 'roi': raw['roi'],
                'smoothed_roi': smooth(raw['roi'], cost, material_reference['roi'], smoothing_fen),
            },
            'previous_period_change': {
                'exposure': growth(raw['exposure'], prior_raw['exposure']) if prior_raw else None,
                'orders': growth(raw['orders'], prior_raw['orders']) if prior_raw else None,
                'roi': growth(raw['roi'], prior_raw['roi']) if prior_raw else None,
            },
            'period_count': period_count, 'decision': decision,
            'reason_codes': list(dict.fromkeys(codes)), 'warnings': card_warnings,
        }
        cards.append(card)
        if not raw_codes and sample_state not in ('LOW_EXPOSURE', 'LOW_SPEND'):
            reference_rows.append(row)
        if not raw_codes and sample_state not in ('LOW_EXPOSURE', 'LOW_SPEND') and profile['labels']:
            direction_rows.append((row, profile['labels']))

    if any(not card['labels'] for card in cards):
        warnings.append('MISSING_LABELS')
    if context_changed:
        warnings.append('OPERATION_CONTEXT_CHANGED')
    if not current_range_ok or not earlier_range_ok:
        warnings.append('MISMATCHED_RANGE')
    if not periods_comparable and optional_earlier_nonoverlap_import is not None:
        warnings.append('NONCOMPARABLE_PERIODS')

    rules = _complete_rules(config)
    direction_cards = []
    if direction_rows:
        grouped = {}
        for row, labels in direction_rows:
            key = tuple(labels)
            grouped.setdefault(key, []).append(row)
        reference = _direction_metrics(reference_rows, base_delivery_only)
        for labels, rows in sorted(grouped.items(), key=lambda item: item[0]):
            current = _direction_metrics(rows, base_delivery_only)
            group_comparable = periods_comparable and all(
                (previous := earlier_by_id.get(str(row.get('creative_id')))) is not None and
                not _reason_codes(previous, optional_earlier_nonoverlap_import, base_delivery_only)
                for row in rows)
            previous = None
            if group_comparable:
                previous_rows = [earlier_by_id[str(row.get('creative_id'))] for row in rows]
                previous = _direction_metrics(previous_rows, base_delivery_only)
            relative = _relative(current, reference)
            codes = []
            decision = 'OBSERVE'
            if context_changed:
                codes.append('CONTEXT_CHANGED')
            elif not group_comparable:
                codes.append('INSUFFICIENT_COMPARABLE_PERIODS')
            elif not rules:
                codes.append('DIRECTION_RULES_INCOMPLETE')
            elif len(rows) < rules['min_creatives']:
                codes.append('INSUFFICIENT_CREATIVE_COUNT')
            else:
                primary = rules['primary_objective']
                expand = (relative[primary] is not None and relative[primary] >= 1 + rules['expand_primary_ratio'] and
                          relative['roi'] is not None and relative['roi'] >= 1 + rules['expand_roi_ratio'] and
                          relative['orders'] is not None and relative['orders'] >= 1 + rules['expand_order_ratio'])
                stop = (relative[primary] is not None and relative[primary] <= 1 - rules['stop_primary_ratio'] and
                        relative['roi'] is not None and relative['roi'] <= 1 - rules['stop_roi_ratio'] and
                        relative['orders'] is not None and relative['orders'] <= 1 - rules['stop_order_ratio'])
                if expand:
                    decision, codes = 'EXPAND_DIRECTION', ['EXPAND_GUARDRAILS_MET']
                elif stop:
                    decision, codes = 'STOP_PRODUCTION', ['STOP_GUARDRAILS_MET']
                elif all(relative[key] is not None and relative[key] >= 1 for key in ('exposure', 'orders', 'roi')):
                    decision, codes = 'RETAIN_RACE', ['RETAIN_PLAN_REFERENCE']
                else:
                    codes.append('PLAN_REFERENCE_GUARDRAILS_NOT_MET')
            direction_cards.append({
                'labels': list(labels), 'creative_count': len(rows), 'period_count': 2 if group_comparable else 1,
                'objective_metrics': current, 'plan_reference': reference,
                'relative_efficiencies': relative, 'decision': decision, 'reason_codes': codes,
                'operation_warnings': ['OPERATION_CONTEXT_CHANGED'] if context_changed else [],
                'brief': _brief(list(labels), len(rows), current, previous, (rules or {'primary_objective': 'roi'})['primary_objective']),
            })

    cards.sort(key=lambda card: card['creative_id'])
    return {
        'partition': 'chengfang', 'basis': 'marketing_cost', 'material_reference': material_reference,
        'material_cards': cards, 'direction_cards': direction_cards,
        'frozen_inputs': {
            'import_ids': [selected_confirmed_7_day_import.get('id')] + ([optional_earlier_nonoverlap_import.get('id')] if optional_earlier_nonoverlap_import else []),
            'context_revision': plan_context.get('revision') if isinstance(plan_context, dict) else None,
            'plan_context': _canonical(context),
            'profile_revisions': {key: profiles[key]['revision'] for key in sorted(profiles)},
            'operation_entries': operation_entries, 'config': _canonical(config), 'cost_basis': 'marketing_cost',
        },
        'warnings': sorted(set(warnings)),
    }
