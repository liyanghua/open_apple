import json
import math
import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

os.environ['OPTIMIZER_DATA_DIR'] = tempfile.mkdtemp(prefix='optimizer-chengfang-tests-')

from app import storage as st
from app.engine import DEFAULT_CONFIG, validate_config
from app.importer import parse_file
from app.main import app, create_workspace, store_preview, confirm
from app.chengfang import diagnose

client = TestClient(app)


def chengfang_csv(rows, headers):
 import csv
 import io
 output = io.StringIO()
 writer = csv.writer(output)
 writer.writerow(headers)
 writer.writerows(rows)
 return output.getvalue().encode('utf-8-sig')


def valid_context(plan_id='plan-a', **changes):
 context = {
  'plan_id': plan_id, 'path': 'live', 'status': 'active',
  'started_at': '2026-01-01T08:00:00+08:00', 'marketing_roi_target': 2.5,
  'base_delivery': True, 'star_select': False, 'creator_marketing': False,
  'creator_commission_bid': False, 'basis_note': '直播间归因口径',
 }
 context.update(changes)
 return context


class ConfigTests(unittest.TestCase):
 def test_legacy_workspace_gets_delivery_mode_default(self):
  workspace = create_workspace('旧版工作区')
  self.assertEqual(workspace['config']['delivery_mode'], 'independent_boost')

 def test_old_persisted_config_merges_defaults_without_rewrite(self):
  workspace_id = st.uid()
  old_config = {key: value for key, value in DEFAULT_CONFIG.items() if key != 'delivery_mode'}
  with st.transaction() as c:
   c.execute('INSERT INTO workspaces(id,name,kind,config,created_at) VALUES(?,?,?,?,?)',
    (workspace_id, '旧存储', 'live', st.dumps(old_config), st.now()))
  loaded = st.get_workspace(workspace_id)
  self.assertEqual(loaded['config']['delivery_mode'], 'independent_boost')
  with st.connect() as c:
   persisted = json.loads(c.execute('SELECT config FROM workspaces WHERE id=?', (workspace_id,)).fetchone()['config'])
  self.assertNotIn('delivery_mode', persisted)

 def test_delivery_mode_rejects_unknown_empty_and_none(self):
  for value in ('unknown', '', None):
   with self.assertRaisesRegex(ValueError, '投放模式'):
    validate_config({**DEFAULT_CONFIG, 'delivery_mode': value})

 def test_diagnosis_thresholds_accept_positive_values(self):
  cfg = validate_config({**DEFAULT_CONFIG, 'diagnosis_min_impressions': 500,
   'diagnosis_min_spend_yuan': 100.0, 'diagnosis_required_periods': 2})
  self.assertEqual(cfg['diagnosis_min_impressions'], 500)
  self.assertEqual(cfg['diagnosis_min_spend_yuan'], 100.0)
  self.assertEqual(cfg['diagnosis_required_periods'], 2)

 def test_diagnosis_thresholds_reject_invalid_numbers(self):
  for key, value in (
   ('diagnosis_min_impressions', 0), ('diagnosis_min_impressions', 1.5),
   ('diagnosis_min_impressions', math.inf), ('diagnosis_min_spend_yuan', 0),
   ('diagnosis_min_spend_yuan', -1), ('diagnosis_min_spend_yuan', math.inf),
  ):
   with self.assertRaises(ValueError):
    validate_config({**DEFAULT_CONFIG, key: value})

 def test_diagnosis_required_periods_must_be_at_least_two(self):
  with self.assertRaises(ValueError):
   validate_config({**DEFAULT_CONFIG, 'diagnosis_required_periods': 1})

 def test_direction_rules_validation(self):
  valid = {'primary_objective': 'orders', 'min_creatives': 3,
   'expand_primary_ratio': .2, 'expand_roi_ratio': .2, 'expand_order_ratio': .2,
   'stop_primary_ratio': .2, 'stop_roi_ratio': .2, 'stop_order_ratio': .2}
  self.assertEqual(validate_config({**DEFAULT_CONFIG, 'direction_rules': valid})['direction_rules'], valid)
  for bad in (
   {key: value for key, value in valid.items() if key != 'stop_order_ratio'},
   {**valid, 'min_creatives': 3.5},
   {**valid, 'expand_roi_ratio': 0},
   {**valid, 'stop_order_ratio': 1.1},
   {**valid, 'expand_order_ratio': math.inf},
  ):
   with self.assertRaises(ValueError):
    validate_config({**DEFAULT_CONFIG, 'direction_rules': bad})


class StorageTests(unittest.TestCase):
 def setUp(self):
  self.workspace = create_workspace('成方上下文')
  self.workspace_id = self.workspace['id']

 def audit_count(self):
  with st.connect() as c:
   return c.execute('SELECT COUNT(*) FROM audit WHERE workspace_id=?', (self.workspace_id,)).fetchone()[0]

 def test_context_save_increments_revision_and_audits_once_per_write(self):
  before = self.audit_count()
  first = st.save_plan_context(self.workspace_id, 'live', 'plan-a', {'name': 'A'})
  second = st.save_plan_context(self.workspace_id, 'live', 'plan-a', {'name': 'A2'})
  self.assertEqual((first['revision'], second['revision']), (1, 2))
  self.assertEqual(self.audit_count() - before, 2)

 def test_profiles_are_scoped_to_plan_and_lists_filter_and_order(self):
  before = self.audit_count()
  first = st.save_material_profile(self.workspace_id, 'live', 'plan-a', 'creative-b', ['b'])
  revised = st.save_material_profile(self.workspace_id, 'live', 'plan-a', 'creative-b', ['b2'])
  st.save_material_profile(self.workspace_id, 'live', 'plan-a', 'creative-a', ['a'])
  st.save_material_profile(self.workspace_id, 'live', 'plan-b', 'creative-a', ['other'])
  self.assertEqual((first['revision'], revised['revision']), (1, 2))
  self.assertEqual(self.audit_count() - before, 4)
  self.assertEqual([p['creative_id'] for p in st.list_material_profiles(self.workspace_id, 'live', 'plan-a')], ['creative-a', 'creative-b'])
  self.assertEqual(st.get_material_profile(self.workspace_id, 'live', 'plan-a', 'creative-a')['labels'], ['a'])

 def test_operations_order_diagnosis_retrieval_and_each_write_audits_once(self):
  before = self.audit_count()
  st.append_plan_operation(self.workspace_id, 'live', 'plan-a', '2026-01-02T00:00:00+00:00', 'expand', {'n': 2})
  st.append_plan_operation(self.workspace_id, 'live', 'plan-a', '2026-01-01T00:00:00+00:00', 'stop', {'n': 1})
  diagnosis = st.create_diagnosis_run(self.workspace_id, 'live', 'plan-a', {'state': 'ok'})
  operations = st.list_plan_operations(self.workspace_id, 'live', 'plan-a')
  self.assertEqual([operation['kind'] for operation in operations], ['stop', 'expand'])
  self.assertEqual(st.get_diagnosis_run(diagnosis['id'])['payload'], {'state': 'ok'})
  self.assertEqual(self.audit_count() - before, 3)

 def test_operations_keep_append_order_for_exact_time_ties(self):
  when = '2026-01-01T00:00:00+00:00'
  with patch('app.storage.uid', side_effect=['z-first', 'audit-first', 'a-second', 'audit-second']):
   st.append_plan_operation(self.workspace_id, 'live', 'plan-a', when, 'first', {})
   st.append_plan_operation(self.workspace_id, 'live', 'plan-a', when, 'second', {})
  self.assertEqual([operation['id'] for operation in st.list_plan_operations(self.workspace_id, 'live', 'plan-a')], ['z-first', 'a-second'])

 def test_new_records_reject_invalid_path(self):
  with self.assertRaises(ValueError):
   st.save_plan_context(self.workspace_id, 'bad', 'plan-a', {})


class ChengfangImportTests(unittest.TestCase):
 def setUp(self):
  self.workspace = create_workspace('成方导入', config={**DEFAULT_CONFIG, 'delivery_mode': 'chengfang'})
  self.workspace_id = self.workspace['id']

 def save_context(self, **changes):
  response = client.put(f'/api/workspaces/{self.workspace_id}/chengfang/context', json=valid_context(**changes))
  self.assertEqual(response.status_code, 200, response.text)
  return response.json()

 def preview(self, headers, rows):
  return store_preview(self.workspace_id, chengfang_csv(rows, headers), 'chengfang_2026-01-01_2026-01-07.csv')

 def confirm(self, imported, **changes):
  body = {
   'plan_id': 'plan-a', 'path': 'live', 'partition': 'chengfang',
   'period_start': '2026-01-01', 'period_end': '2026-01-07',
   'scope': '成方单计划导出', 'scope_confirmed': True,
   'cost_basis': 'marketing_cost', 'cost_grain': 'material_attributable',
   'plan_marketing_cost': 100,
  }
  body.update(changes)
  return confirm(imported['id'], body)

 def test_parser_keeps_chengfang_metadata_and_content_type_is_raw_only(self):
  headers = ['素材ID', '整体消耗', '净成交金额', '计划ID', '分区', '营销消耗', '营销ROI', '达人佣金', '内容类型']
  parsed = parse_file(chengfang_csv([['creative-a', 40, 100, 'plan-a', 'chengfang', 38, 2.63, 5, '口播']], headers), 'x.csv')
  row = parsed['rows'][0]
  self.assertEqual(row['spend'], 4000)
  self.assertEqual(row['marketing_cost'], 3800)
  self.assertEqual(row['plan_id'], 'plan-a')
  self.assertEqual(row['partition'], 'chengfang')
  self.assertEqual(row['content_type'], '口播')
  self.assertEqual(row['raw']['content_type'], '口播')
  self.assertEqual(st.list_material_profiles(self.workspace_id, 'live', 'plan-a'), [])

 def test_context_api_requires_complete_boolean_caps_and_lists_saved_contexts(self):
  incomplete = valid_context()
  incomplete.pop('star_select')
  response = client.put(f'/api/workspaces/{self.workspace_id}/chengfang/context', json=incomplete)
  self.assertEqual(response.status_code, 400)
  nonbool = client.put(f'/api/workspaces/{self.workspace_id}/chengfang/context', json=valid_context(base_delivery=1))
  self.assertEqual(nonbool.status_code, 400)
  saved = self.save_context(status='paused', base_delivery_only=True)
  self.assertEqual(saved['config']['status'], 'paused')
  self.assertTrue(saved['config']['base_delivery_only'])
  contexts = client.get(f'/api/workspaces/{self.workspace_id}/chengfang/contexts').json()
  self.assertEqual([(item['path'], item['plan_id']) for item in contexts], [('live', 'plan-a')])

 def test_confirmation_reconciles_nonaggregate_material_cost_and_keeps_dash_total(self):
  self.save_context()
  headers = ['素材ID', '整体消耗', '净成交金额', '计划ID', '营销消耗', '内容类型']
  imported = self.preview(headers, [
   ['creative-a', 100, 300, 'plan-a', 100, '口播'],
   ['-', 999, 999, 'other-plan', 999, '合计'],
  ])
  confirmed = self.confirm(imported)
  metadata = confirmed['metadata']
  self.assertEqual(confirmed['totals']['spend'], 109900)
  self.assertEqual(metadata['material_cost_sum'], 10000)
  self.assertEqual(metadata['eligible_material_ids'], ['creative-a'])
  self.assertTrue(metadata['reconciliation']['reconciled'])
  self.assertEqual(metadata['reconciliation']['unattributed_cost_fen'], 0)
  self.assertNotIn('content_type', metadata)

 def test_reuse_confirmed_history_as_chengfang_snapshot_without_changing_source(self):
  legacy = create_workspace('历史上传数据')
  source = store_preview(legacy['id'], chengfang_csv([
   ['creative-a', 100, 300, 3, 800],
  ], ['素材ID', '整体消耗', '净成交金额', '净订单', '曝光']), 'history.csv')
  confirm(source['id'], {'path': 'live', 'period_start': '2026-01-01', 'period_end': '2026-01-07',
   'scope': '原始计划导出', 'scope_confirmed': True})
  client.put(f"/api/workspaces/{legacy['id']}/config", json={**DEFAULT_CONFIG, 'delivery_mode': 'chengfang'})
  self.assertEqual(client.put(f"/api/workspaces/{legacy['id']}/chengfang/context",
   json=valid_context(base_delivery_only=True)).status_code, 200)
  response = client.post(f"/api/workspaces/{legacy['id']}/chengfang/imports/{source['id']}/reuse", json={
   'plan_id': 'plan-a', 'path': 'live', 'scope': '历史计划导出',
   'cost_basis': 'marketing_cost', 'cost_grain': 'material_attributable', 'plan_marketing_cost': 100,
  })
  self.assertEqual(response.status_code, 200, response.text)
  reused = response.json()
  self.assertNotEqual(reused['id'], source['id'])
  self.assertEqual(reused['metadata']['reused_from_import_id'], source['id'])
  self.assertEqual(reused['metadata']['partition'], 'chengfang')
  self.assertTrue(reused['metadata']['reconciliation']['reconciled'])
  self.assertNotIn('partition', client.get(f"/api/imports/{source['id']}").json()['metadata'])

 def test_confirmation_rejects_bad_partition_and_nonaggregate_plan_mismatch(self):
  self.save_context()
  headers = ['素材ID', '整体消耗', '净成交金额', '计划ID', '营销消耗']
  imported = self.preview(headers, [['creative-a', 100, 300, 'other-plan', 100]])
  with self.assertRaisesRegex(ValueError, '分区'):
   self.confirm(imported, partition='bad')
  with self.assertRaisesRegex(ValueError, '计划ID'):
   self.confirm(imported)

 def test_base_delivery_only_falls_back_to_canonical_spend_when_marketing_cost_is_absent(self):
  self.save_context(base_delivery_only=True)
  headers = ['素材ID', '整体消耗', '净成交金额', '计划ID']
  confirmed = self.confirm(self.preview(headers, [['creative-a', 100, 300, 'plan-a']]))
  self.assertEqual(confirmed['metadata']['material_cost_sum'], 10000)
  self.assertTrue(confirmed['metadata']['base_delivery_only'])

 def test_non_base_delivery_rejects_a_material_without_marketing_cost(self):
  self.save_context()
  headers = ['素材ID', '整体消耗', '净成交金额', '计划ID', '营销消耗']
  imported = self.preview(headers, [['creative-a', 100, 300, 'plan-a', '']])
  with self.assertRaisesRegex(ValueError, '营销消耗'):
   self.confirm(imported)

 def test_confirmation_rejects_non_material_or_unknown_cost_grain(self):
  self.save_context()
  headers = ['素材ID', '整体消耗', '净成交金额', '计划ID', '营销消耗']
  for grain in ('plan_total_repeated', 'unknown'):
   imported = self.preview(headers, [['creative-a', 100, 300, 'plan-a', 100]])
   with self.assertRaisesRegex(ValueError, '成本粒度'):
    self.confirm(imported, cost_grain=grain)

 def test_failed_reconciliation_is_recorded_and_missing_plan_column_is_manual_confirmation(self):
  self.save_context()
  headers = ['素材ID', '整体消耗', '净成交金额', '营销消耗']
  confirmed = self.confirm(self.preview(headers, [['creative-a', 100, 300, 70]]), plan_marketing_cost=100)
  reconciliation = confirmed['metadata']['reconciliation']
  self.assertFalse(reconciliation['reconciled'])
  self.assertEqual(reconciliation['unattributed_cost_fen'], 3000)
  self.assertEqual(confirmed['metadata']['plan_id_confirmation'], 'manual_confirmed')
  blocked = client.post('/api/ranking-runs', json={'workspace_id': self.workspace_id, 'import_7': confirmed['id']})
  self.assertEqual(blocked.status_code, 400)
  self.assertIn('对账', blocked.json()['detail'])

 def test_independent_boost_import_with_chengfang_named_columns_stays_legacy(self):
  headers = ['素材ID', '整体消耗', '净成交金额', '营销消耗', '分区']
  legacy_workspace = create_workspace('独立加热导入')
  imported = store_preview(legacy_workspace['id'], chengfang_csv([['creative-a', 100, 300, 80, 'chengfang']], headers), 'legacy.csv')
  confirmed = confirm(imported['id'], {
   'path': 'live', 'period_start': '2026-01-01', 'period_end': '2026-01-07',
   'scope': '独立加热导出', 'scope_confirmed': True,
  })
  self.assertEqual(confirmed['status'], 'confirmed')
  self.assertNotIn('plan_id', confirmed['metadata'])
  self.assertNotIn('reconciliation', confirmed['metadata'])


class ChengfangDiagnosisTests(unittest.TestCase):
 def context(self, **changes):
  value = valid_context()
  value.update(changes)
  return {'revision': 4, 'config': value}

 def profile(self, creative_id, labels, revision=1, plan_id='plan-a', path='live'):
  return {'creative_id': creative_id, 'labels': labels, 'revision': revision, 'plan_id': plan_id, 'path': path}

 def snapshot(self, rows, *, import_id='week-current', start='2026-01-08', end='2026-01-14',
              partition='chengfang', path='live', plan_id='plan-a', basis='marketing_cost', reconciled=True,
              status='confirmed', complete=True, scope='chengfang-scope', timezone='Asia/Shanghai',
              base_delivery_only=False, delivery_context=None, capability_context=None, cost_grain='material_attributable'):
  delivery_context = delivery_context or {'base_delivery': True, 'star_select': False, 'creator_marketing': False, 'creator_commission_bid': False}
  capability_context = capability_context or {'status': 'active'}
  return {
   'id': import_id, 'path': path, 'basis': basis, 'period_start': start, 'period_end': end,
   'window': 7, 'complete': complete, 'status': status, 'scope': scope,
   'metadata': {'plan_id': plan_id, 'partition': partition, 'cost_basis': basis,
    'cost_grain': cost_grain, 'timezone': timezone, 'base_delivery_only': base_delivery_only,
    'delivery_context': delivery_context, 'capability_context': capability_context,
    'reconciliation': {'reconciled': reconciled}},
   'data': {'rows': rows},
  }

 def row(self, creative_id='a', *, exposure=1000, cost=10000, gmv=30000, orders=3,
         aggregate=False, errors=None):
  return {'creative_id': creative_id, 'creative_name': creative_id.upper(), 'is_aggregate': aggregate,
   'errors': errors or [], 'impressions': exposure, 'marketing_cost': cost, 'spend': cost,
   'net_gmv': gmv, 'net_orders': orders}

 def cfg(self, **changes):
  return {**DEFAULT_CONFIG, 'smoothing_yuan': 100, 'diagnosis_min_impressions': 500,
   'diagnosis_min_spend_yuan': 100, 'diagnosis_required_periods': 2, **changes}

 def test_high_roi_below_exposure_threshold_is_observe(self):
  result = diagnose(self.snapshot([self.row(exposure=499, gmv=100000)]), None, self.context(),
   [self.profile('a', ['口播'])], self.cfg(), [])
  card = result['material_cards'][0]
  self.assertEqual(card['sample_state'], 'LOW_EXPOSURE')
  self.assertEqual(card['decision'], 'OBSERVE')
  self.assertIn('LOW_EXPOSURE', card['reason_codes'])

 def test_missing_labels_keep_material_result_but_exclude_direction_conclusion(self):
  result = diagnose(self.snapshot([self.row('a'), self.row('b')]), None, self.context(),
   [self.profile('a', ['口播']), self.profile('b', [])], self.cfg(), [])
  self.assertEqual({card['creative_id'] for card in result['material_cards']}, {'a', 'b'})
  self.assertEqual([card['labels'] for card in result['direction_cards']], [['口播']])
  self.assertIn('MISSING_LABELS', result['warnings'])

 def test_mixed_partitions_are_rejected(self):
  selected = self.snapshot([self.row()])
  earlier = self.snapshot([self.row()], import_id='week-earlier', start='2026-01-01', end='2026-01-07', partition='overall')
  with self.assertRaisesRegex(ValueError, '分区'):
   diagnose(selected, earlier, self.context(), [self.profile('a', ['口播'])], self.cfg(), [])

 def test_incomplete_material_inputs_are_needs_data(self):
  selected = self.snapshot([
   self.row('no-exposure', exposure=None), self.row('no-cost', cost=None),
   self.row('bad-row', errors=['source problem']),
  ], reconciled=False)
  result = diagnose(selected, None, self.context(), [
   self.profile('no-exposure', ['口播']), self.profile('no-cost', ['口播']), self.profile('bad-row', ['口播']),
  ], self.cfg(), [])
  cards = {card['creative_id']: card for card in result['material_cards']}
  self.assertTrue(all(card['decision'] == 'NEEDS_DATA' for card in cards.values()))
  self.assertIn('MISSING_EXPOSURE', cards['no-exposure']['reason_codes'])
  self.assertIn('MISSING_MARKETING_COST', cards['no-cost']['reason_codes'])
  self.assertIn('UNRECONCILED_COST', cards['bad-row']['reason_codes'])
  invalid_prior = self.snapshot([self.row('a')], import_id='bad-range', start='2026-01-01', end='2026-01-08')
  range_result = diagnose(self.snapshot([self.row('a')]), invalid_prior, self.context(),
   [self.profile('a', ['口播'])], self.cfg(), [])
  self.assertEqual(range_result['material_cards'][0]['decision'], 'NEEDS_DATA')
  self.assertIn('MISMATCHED_RANGE', range_result['material_cards'][0]['reason_codes'])

 def test_low_spend_and_one_period_restrict_to_test_variant(self):
  low_spend = diagnose(self.snapshot([self.row(cost=9999)]), None, self.context(),
   [self.profile('a', ['口播'])], self.cfg(), [])['material_cards'][0]
  self.assertEqual(low_spend['decision'], 'TEST_VARIANT')
  two_periods = diagnose(self.snapshot([self.row('a'), self.row('b')]),
   self.snapshot([self.row('a'), self.row('b')], import_id='week-earlier', start='2026-01-01', end='2026-01-07'),
   self.context(), [self.profile('a', ['口播']), self.profile('b', ['口播'])], self.cfg(), [])
  self.assertTrue(all(card['decision'] != 'EXPAND_DIRECTION' for card in two_periods['material_cards']))

 def test_low_exposure_rows_never_produce_a_stop_direction(self):
  rules = {'primary_objective': 'orders', 'min_creatives': 3, 'expand_primary_ratio': .1,
   'expand_roi_ratio': .1, 'expand_order_ratio': .1, 'stop_primary_ratio': .1,
   'stop_roi_ratio': .1, 'stop_order_ratio': .1}
  rows = [self.row('a', exposure=500, orders=1, gmv=10000), self.row('b', exposure=500, orders=1, gmv=10000),
   self.row('low', exposure=499, orders=1, gmv=10000),
   self.row('c', exposure=1000, orders=10, gmv=100000), self.row('d', exposure=1000, orders=10, gmv=100000), self.row('e', exposure=1000, orders=10, gmv=100000)]
  prior = self.snapshot(rows, import_id='prior', start='2026-01-01', end='2026-01-07')
  result = diagnose(self.snapshot(rows), prior, self.context(),
   [self.profile('a', ['弱']), self.profile('b', ['弱']), self.profile('low', ['弱']), self.profile('c', ['强']), self.profile('d', ['强']), self.profile('e', ['强'])], self.cfg(direction_rules=rules), [])
  weak = next(card for card in result['direction_cards'] if card['labels'] == ['弱'])
  self.assertEqual((weak['creative_count'], weak['decision']), (2, 'OBSERVE'))
  self.assertIn('INSUFFICIENT_CREATIVE_COUNT', weak['reason_codes'])
  self.assertEqual(next(card for card in result['material_cards'] if card['creative_id'] == 'low')['decision'], 'OBSERVE')

 def test_low_spend_rows_never_produce_an_expand_direction(self):
  rules = {'primary_objective': 'orders', 'min_creatives': 3, 'expand_primary_ratio': .1,
   'expand_roi_ratio': .1, 'expand_order_ratio': .1, 'stop_primary_ratio': .1,
   'stop_roi_ratio': .1, 'stop_order_ratio': .1}
  rows = [self.row('a', exposure=1000, orders=10, gmv=100000), self.row('b', exposure=1000, orders=10, gmv=100000),
   self.row('low', exposure=1000, cost=9999, orders=10, gmv=100000),
   self.row('c', exposure=500, orders=1, gmv=10000), self.row('d', exposure=500, orders=1, gmv=10000), self.row('e', exposure=500, orders=1, gmv=10000)]
  prior = self.snapshot(rows, import_id='prior', start='2026-01-01', end='2026-01-07')
  result = diagnose(self.snapshot(rows), prior, self.context(),
   [self.profile('a', ['强']), self.profile('b', ['强']), self.profile('low', ['强']), self.profile('c', ['弱']), self.profile('d', ['弱']), self.profile('e', ['弱'])], self.cfg(direction_rules=rules), [])
  strong = next(card for card in result['direction_cards'] if card['labels'] == ['强'])
  self.assertEqual((strong['creative_count'], strong['decision']), (2, 'OBSERVE'))
  self.assertIn('INSUFFICIENT_CREATIVE_COUNT', strong['reason_codes'])
  self.assertEqual(next(card for card in result['material_cards'] if card['creative_id'] == 'low')['decision'], 'TEST_VARIANT')

 def test_no_stop_or_expand_without_complete_rules_and_two_periods(self):
  no_rules = diagnose(self.snapshot([self.row('a'), self.row('b')]), None, self.context(),
   [self.profile('a', ['口播']), self.profile('b', ['口播'])], self.cfg(), [])
  self.assertTrue(all(card['decision'] not in ('STOP_PRODUCTION', 'EXPAND_DIRECTION') for card in no_rules['direction_cards']))
  rules = {'primary_objective': 'orders', 'min_creatives': 2, 'expand_primary_ratio': .1,
   'expand_roi_ratio': .1, 'expand_order_ratio': .1, 'stop_primary_ratio': .1,
   'stop_roi_ratio': .1, 'stop_order_ratio': .1}
  still_one_period = diagnose(self.snapshot([self.row('a'), self.row('b')]), None, self.context(),
   [self.profile('a', ['口播']), self.profile('b', ['口播'])], self.cfg(direction_rules=rules), [])
  self.assertTrue(all(card['decision'] not in ('STOP_PRODUCTION', 'EXPAND_DIRECTION') for card in still_one_period['direction_cards']))

 def test_operation_overlap_forces_context_changed(self):
  result = diagnose(self.snapshot([self.row('a'), self.row('b')]), None, self.context(),
   [self.profile('a', ['口播']), self.profile('b', ['口播'])], self.cfg(), [
    {'occurred_at': '2026-01-10T10:00:00+08:00', 'kind': 'budget_changed', 'plan_id': 'plan-a', 'path': 'live', 'payload': {}},
   ])
  self.assertEqual(result['direction_cards'][0]['decision'], 'OBSERVE')
  self.assertIn('CONTEXT_CHANGED', result['direction_cards'][0]['reason_codes'])
  self.assertIn('OPERATION_CONTEXT_CHANGED', result['material_cards'][0]['warnings'])

 def test_brief_has_one_changed_label_and_evidence(self):
  previous = self.snapshot([self.row('a', orders=1), self.row('b', orders=1)], import_id='week-earlier', start='2026-01-01', end='2026-01-07')
  current = self.snapshot([self.row('a', orders=4), self.row('b', orders=4)])
  rules = {'primary_objective': 'orders', 'min_creatives': 2, 'expand_primary_ratio': .1,
   'expand_roi_ratio': .1, 'expand_order_ratio': .1, 'stop_primary_ratio': .1,
   'stop_roi_ratio': .1, 'stop_order_ratio': .1}
  result = diagnose(current, previous, self.context(), [self.profile('a', ['口播', '开场']), self.profile('b', ['口播', '开场'])], self.cfg(direction_rules=rules), [])
  brief = result['direction_cards'][0]['brief']
  self.assertEqual(brief['retain_labels'], ['口播'])
  self.assertEqual(brief['change_label'], '开场')
  self.assertEqual(brief['produce_count'], 2)
  self.assertEqual(brief['comparison_direction'], 'UP')

 def test_missing_or_invalid_prior_material_withholds_direction_evidence(self):
  current = self.snapshot([self.row('a'), self.row('b')])
  prior = self.snapshot([self.row('a'), self.row('b', errors=['bad prior'])], import_id='prior', start='2026-01-01', end='2026-01-07')
  result = diagnose(current, prior, self.context(), [self.profile('a', ['口播']), self.profile('b', ['口播'])], self.cfg(), [])
  cards = {card['creative_id']: card for card in result['material_cards']}
  self.assertEqual(cards['b']['period_count'], 1)
  self.assertIn(cards['b']['decision'], ('TEST_VARIANT', 'NEEDS_DATA'))
  self.assertTrue(all(card['decision'] == 'OBSERVE' for card in result['direction_cards']))
  self.assertTrue(all('INSUFFICIENT_COMPARABLE_PERIODS' in card['reason_codes'] for card in result['direction_cards']))
  missing = diagnose(current, self.snapshot([self.row('a')], import_id='missing', start='2026-01-01', end='2026-01-07'),
   self.context(), [self.profile('a', ['口播']), self.profile('b', ['口播'])], self.cfg(), [])
  self.assertEqual(next(card for card in missing['material_cards'] if card['creative_id'] == 'b')['period_count'], 1)

 def test_comparable_direction_at_plan_reference_retains_race(self):
  prior = self.snapshot([self.row('a'), self.row('b')], import_id='prior', start='2026-01-01', end='2026-01-07')
  rules = {'primary_objective': 'orders', 'min_creatives': 2, 'expand_primary_ratio': .1,
   'expand_roi_ratio': .1, 'expand_order_ratio': .1, 'stop_primary_ratio': .1,
   'stop_roi_ratio': .1, 'stop_order_ratio': .1}
  result = diagnose(self.snapshot([self.row('a'), self.row('b')]), prior, self.context(),
   [self.profile('a', ['口播']), self.profile('b', ['口播'])], self.cfg(direction_rules=rules), [])
  self.assertEqual(result['direction_cards'][0]['decision'], 'RETAIN_RACE')

 def test_reference_includes_valid_unlabelled_material(self):
  prior = self.snapshot([self.row('a'), self.row('b'), self.row('unlabelled', gmv=90000)], import_id='prior', start='2026-01-01', end='2026-01-07')
  result = diagnose(self.snapshot([self.row('a'), self.row('b'), self.row('unlabelled', gmv=90000)]), prior, self.context(),
   [self.profile('a', ['口播']), self.profile('b', ['口播']), self.profile('unlabelled', [])], self.cfg(), [])
  self.assertEqual(result['direction_cards'][0]['plan_reference']['roi'], 5.0)

 def test_all_standard_operation_kinds_and_earlier_overlap_force_context_changed(self):
  prior = self.snapshot([self.row('a'), self.row('b')], import_id='prior', start='2026-01-01', end='2026-01-07')
  for kind in ('roi_target_changed', 'budget_changed', 'capability_changed', 'product_changed', 'landing_changed'):
   result = diagnose(self.snapshot([self.row('a'), self.row('b')]), prior, self.context(),
    [self.profile('a', ['口播']), self.profile('b', ['口播'])], self.cfg(), [
     {'occurred_at': '2026-01-04T10:00:00+08:00', 'kind': kind, 'plan_id': 'plan-a', 'path': 'live'},
    ])
   self.assertEqual(result['direction_cards'][0]['decision'], 'OBSERVE')
   self.assertIn('CONTEXT_CHANGED', result['direction_cards'][0]['reason_codes'])

 def test_external_profiles_and_operations_are_masked(self):
  result = diagnose(self.snapshot([self.row('a'), self.row('b')]), None, self.context(), [
   self.profile('a', ['口播']), self.profile('b', ['口播']), self.profile('outside', ['外部'], plan_id='other'),
  ], self.cfg(), [
   {'occurred_at': '2026-01-10T10:00:00+08:00', 'kind': 'budget_changed', 'plan_id': 'other', 'path': 'live'},
   {'occurred_at': '2026-01-10T10:00:00+08:00', 'kind': 'budget_changed', 'plan_id': 'plan-a', 'path': 'product'},
  ])
  self.assertNotIn('OPERATION_CONTEXT_CHANGED', result['warnings'])
  self.assertNotIn('outside', result['frozen_inputs']['profile_revisions'])

 def test_strict_snapshot_context_compatibility(self):
  current = self.snapshot([self.row()])
  for changes in (
   {'status': 'preview'}, {'complete': False},
  ):
   with self.assertRaises(ValueError):
    diagnose(self.snapshot([self.row()], **changes), None, self.context(), [self.profile('a', ['口播'])], self.cfg(), [])
  for changes in (
   {'scope': 'different'}, {'timezone': 'UTC'}, {'base_delivery_only': True},
   {'cost_grain': 'plan_total_repeated'}, {'delivery_context': {'base_delivery': False}}, {'capability_context': {'status': 'paused'}},
  ):
   prior = self.snapshot([self.row()], import_id='prior', start='2026-01-01', end='2026-01-07', **changes)
   with self.assertRaises(ValueError):
    diagnose(current, prior, self.context(), [self.profile('a', ['口播'])], self.cfg(), [])


class ChengfangApiTests(unittest.TestCase):
 def setUp(self):
  self.workspace = create_workspace('成方 API', config={**DEFAULT_CONFIG, 'delivery_mode': 'chengfang'})
  self.workspace_id = self.workspace['id']
  response = client.put(f'/api/workspaces/{self.workspace_id}/chengfang/context', json=valid_context())
  self.assertEqual(response.status_code, 200, response.text)

 def imported(self, creative_id, start, end):
  headers = ['素材ID', '整体消耗', '净成交金额', '净成交订单数', '计划ID', '营销消耗', '曝光量']
  source = chengfang_csv([[creative_id, 100, 300, 3, 'plan-a', 100, 1000]], headers)
  preview = store_preview(self.workspace_id, source, f'{creative_id}.csv')
  return confirm(preview['id'], {
   'plan_id': 'plan-a', 'path': 'live', 'partition': 'chengfang',
   'period_start': start, 'period_end': end, 'scope': '素材诊断指标范围',
   'scope_confirmed': True, 'cost_basis': 'marketing_cost',
   'cost_grain': 'material_attributable', 'plan_marketing_cost': 100,
  })

 def test_material_labels_are_schema_valid_and_frozen_in_diagnosis(self):
  labels = {'content_type': '口播', 'hook': '三秒开场', 'value_proposition': '省心',
   'person': '主播', 'scene': '直播间', 'price_expression': '限时价', 'duration_band': '15-30秒'}
  saved = client.put(f'/api/workspaces/{self.workspace_id}/chengfang/plans/plan-a/materials/creative-a',
   json={'path': 'live', 'labels': labels})
  self.assertEqual(saved.status_code, 200, saved.text)
  self.assertEqual(saved.json()['labels'], labels)
  bad = client.put(f'/api/workspaces/{self.workspace_id}/chengfang/plans/plan-a/materials/creative-b',
   json={'path': 'live', 'labels': {**labels, 'hook': ''}})
  self.assertEqual(bad.status_code, 400)
  current = self.imported('creative-a', '2026-01-08', '2026-01-14')
  created = client.post('/api/chengfang/diagnosis-runs', json={
   'workspace_id': self.workspace_id, 'plan_id': 'plan-a', 'path': 'live', 'current_import_id': current['id'],
  })
  self.assertEqual(created.status_code, 200, created.text)
  diagnosis_id = created.json()['id']
  client.put(f'/api/workspaces/{self.workspace_id}/chengfang/plans/plan-a/materials/creative-a',
   json={'path': 'live', 'labels': {**labels, 'hook': '后来改了'}})
  frozen = client.get(f'/api/chengfang/diagnosis-runs/{diagnosis_id}')
  self.assertEqual(frozen.status_code, 200)
  self.assertEqual(frozen.json()['payload']['material_cards'][0]['labels'][1], '三秒开场')

 def test_operations_are_validated_and_diagnosis_freezes_context_config_and_operations(self):
  invalid = client.post(f'/api/workspaces/{self.workspace_id}/chengfang/operations', json={
   'path': 'live', 'plan_id': 'plan-a', 'kind': 'budget_changed', 'occurred_at': 'not-iso', 'note': '', 'payload': {},
  })
  self.assertEqual(invalid.status_code, 400)
  operation = client.post(f'/api/workspaces/{self.workspace_id}/chengfang/operations', json={
   'path': 'live', 'plan_id': 'plan-a', 'kind': 'budget_changed', 'occurred_at': '2026-01-10T09:00:00+08:00',
   'note': '提高预算', 'payload': {'budget': 200},
  })
  self.assertEqual(operation.status_code, 200, operation.text)
  current = self.imported('creative-op', '2026-01-08', '2026-01-14')
  created = client.post('/api/chengfang/diagnosis-runs', json={
   'workspace_id': self.workspace_id, 'plan_id': 'plan-a', 'path': 'live', 'current_import_id': current['id'],
  })
  self.assertEqual(created.status_code, 200, created.text)
  run_id = created.json()['id']
  client.put(f'/api/workspaces/{self.workspace_id}/chengfang/context', json=valid_context(marketing_roi_target=3.2))
  client.put(f'/api/workspaces/{self.workspace_id}/config', json={**DEFAULT_CONFIG, 'delivery_mode': 'chengfang', 'smoothing_yuan': 333})
  frozen = client.get(f'/api/chengfang/diagnosis-runs/{run_id}').json()['payload']
  self.assertEqual(frozen['frozen_inputs']['operation_entries'][0]['payload']['note'], '提高预算')
  self.assertEqual(frozen['frozen_inputs']['config']['smoothing_yuan'], DEFAULT_CONFIG['smoothing_yuan'])
  self.assertEqual(frozen['frozen_inputs']['context_revision'], 1)

 def test_diagnosis_rejects_mixed_windows_and_export_escapes_formula_cells(self):
  current = self.imported('=attack', '2026-01-08', '2026-01-14')
  prior = self.imported('prior', '2026-01-01', '2026-01-07')
  mixed = client.post('/api/chengfang/diagnosis-runs', json={
   'workspace_id': self.workspace_id, 'plan_id': 'plan-a', 'path': 'live', 'current_import_id': current['id'], 'prior_import_id': prior['id'],
  })
  self.assertEqual(mixed.status_code, 200, mixed.text)
  csv_export = client.get(f"/api/chengfang/diagnosis-runs/{mixed.json()['id']}/export")
  self.assertEqual(csv_export.status_code, 200)
  self.assertIn("'=attack", csv_export.text)
  bad = client.post('/api/chengfang/diagnosis-runs', json={
   'workspace_id': self.workspace_id, 'plan_id': 'plan-a', 'path': 'live', 'current_import_id': current['id'], 'prior_import_id': current['id'],
  })
  self.assertEqual(bad.status_code, 400)

 def test_chengfang_blocks_legacy_proposals_without_mutation(self):
  before_ledger = st.ledger(self.workspace_id)
  with st.transaction() as c:
   c.execute('INSERT INTO runs VALUES(?,?,?,?,?)', ('chengfang-run', self.workspace_id, 'live', st.now(), st.dumps({
    'workspace_revision': self.workspace['revision'], 'path': 'live', 'top_ids': [], 'results': [],
   })))
   before_proposals = c.execute('SELECT COUNT(*) FROM proposals WHERE workspace_id=?', (self.workspace_id,)).fetchone()[0]
   before_audit = c.execute('SELECT COUNT(*) FROM audit WHERE workspace_id=?', (self.workspace_id,)).fetchone()[0]
  blocked = client.post('/api/recommendation-runs', json={'run_id': 'chengfang-run'})
  self.assertEqual(blocked.status_code, 409)
  self.assertEqual(blocked.json()['detail'], '乘方模式只生成素材诊断，不生成单素材预算或出价提案')
  with st.connect() as c:
   self.assertEqual(c.execute('SELECT COUNT(*) FROM proposals WHERE workspace_id=?', (self.workspace_id,)).fetchone()[0], before_proposals)
   self.assertEqual(c.execute('SELECT COUNT(*) FROM audit WHERE workspace_id=?', (self.workspace_id,)).fetchone()[0], before_audit)
  self.assertEqual(st.ledger(self.workspace_id), before_ledger)


if __name__ == '__main__':
 unittest.main(verbosity=2)
