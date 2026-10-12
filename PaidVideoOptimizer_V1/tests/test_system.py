"""Executable acceptance checks: parser, metrics, risk, API and concurrency."""
import os, tempfile, unittest, json, csv, io, math
from pathlib import Path
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
os.environ['OPTIMIZER_DATA_DIR']=tempfile.mkdtemp(prefix='optimizer-tests-')
from fastapi.testclient import TestClient
from app.main import app
from app.importer import parse_file, ImportProblem
from app.engine import calculate_ranking, DEFAULT_CONFIG, recommendation

ROOT=Path(__file__).resolve().parents[1]
client=TestClient(app)

def rawcsv(rows,headers=None):
 o=io.StringIO();w=csv.writer(o);w.writerow(headers or ['素材ID','素材名称','整体消耗','净成交金额','净成交订单数','整体成交金额']);w.writerows(rows);return o.getvalue().encode('utf-8-sig')

def imp(rows,window=30,cut=None,id='test',basis='reported_net'):
 end=date.fromisoformat(cut) if cut else date.today()-timedelta(days=1)
 start=end-timedelta(days=window-1)
 return {'id':id,'workspace_id':'w','path':'live','window':window,'period_end':str(end),'period_start':str(start),
  'basis':basis,'scope':'s','complete':True,'filename':'synthetic.csv','data':parse_file(rawcsv(rows),'synthetic.csv')}

def cfg(**kw):return {**DEFAULT_CONFIG,**kw}

class ParsingTests(unittest.TestCase):
 def test_01_synthetic_example_reconciliation(self):
  expected={'product_30d.csv':(3,3,2,50000,288000,258000),'live_30d.csv':(3,3,2,70000,400000,365000),'product_7d.csv':(3,3,2,15000,91000,82000),'live_7d.csv':(3,3,2,22000,126000,115000)}
  for entry in json.loads((ROOT/'examples/manifest.json').read_text()):
   p=parse_file((ROOT/'examples'/entry['file']).read_bytes(),entry['original_name'])
   self.assertEqual(tuple(p['totals'][k] for k in ('rows','active','active_single','spend','paid_gmv','net_gmv')),expected[entry['file']])
   self.assertTrue(entry['original_name'].startswith('synthetic_'))
   self.assertTrue(all(r['is_aggregate'] or r['creative_id'].startswith('DEMO-') for r in p['rows']))
   self.assertEqual(len(p['issues']),0)
 def test_02_long_ids_are_strings(self):
  p=parse_file(rawcsv([['1234567890123456789','test',100,500,5,550]]),'x.csv')
  self.assertEqual(p['rows'][0]['creative_id'],'1234567890123456789')
 def test_03_missing_optional_not_zero(self):
  p=parse_file(rawcsv([['a','test',100,500,5,550]]),'x.csv')
  self.assertIsNone(p['rows'][0]['clicks'])
 def test_04_duplicate_ids_quarantined(self):
  p=parse_file(rawcsv([['a','x',1,5,1,5],['a','y',2,10,1,10]]),'x.csv')
  self.assertEqual(p['totals']['invalid_rows'],2)
 def test_05_aggregate_retained_not_single(self):
  p=parse_file(rawcsv([['-','aggregate',100,500,5,500],['b','全部',100,600,5,600]]),'x.csv')
  self.assertEqual(p['totals']['spend'],20000);self.assertTrue(p['rows'][0]['is_aggregate']);self.assertFalse(p['rows'][1]['is_aggregate'])
 def test_06_macro_or_unrecognised_file(self):
  with self.assertRaises(ImportProblem):parse_file(b'x','macro.xlsm')
 def test_07_blank_money_stays_missing(self):
  p=parse_file(rawcsv([['a','test','',500,5,500]]),'x.csv')
  self.assertIsNone(p['rows'][0]['spend']);self.assertTrue(p['rows'][0]['errors'])
 def test_08_negative_values_isolated(self):
  p=parse_file(rawcsv([['a','test',100,-5,0,0]]),'x.csv')
  self.assertTrue(p['rows'][0]['errors'])

class MetricTests(unittest.TestCase):
 def pair(self):
  return imp([['A','教学',3000,18000,120,20000]],id='30'),imp([['A','教学',1000,7000,40,8000]],window=7,id='7')
 def test_10_golden_score(self):
  a,b=self.pair();r=calculate_ranking(a,b,cfg(reference_roi=3));m=r['results'][0]['metrics']
  self.assertAlmostEqual(r['results'][0]['score'],63.64494,places=4)
  self.assertAlmostEqual(m['roi_growth'],.2727272727);self.assertAlmostEqual(m['gmv_growth'],1.0909090909)
  self.assertAlmostEqual(m['net_discount_ratio'],.125);self.assertEqual(r['top_ids'],['A'])
 def test_11_only_30_no_fake_week(self):
  a,b=self.pair();r=calculate_ranking(a,None,cfg());self.assertEqual(r['mode'],'HISTORY_30D');self.assertIsNone(r['results'][0]['metrics']['roi_7d'])
 def test_12_zero_spend_not_infinite(self):
  r=calculate_ranking(imp([['a','zero',0,500,1,500]]),None,cfg());self.assertIsNone(r['results'][0]['metrics']['roi_30d']);self.assertEqual(len(r['top_ids']),1)
 def test_13_spend_no_sales_zero(self):
  r=calculate_ranking(imp([['a','none',100,0,0,0]]),None,cfg());self.assertEqual(r['results'][0]['metrics']['roi_30d'],0)
 def test_14_one_order_not_main(self):
  a=imp([['a','one',100,1000,2,1000]]);b=imp([['a','one',10,500,1,500]],7);r=calculate_ranking(a,b,cfg(reference_roi=3,smoothing_yuan=0));self.assertEqual(len(r['top_ids']),1);self.assertEqual(r['results'][0]['queue'],'explore')
 def test_15_window_mismatch(self):
  a,b=self.pair();b['period_end']=str(date.today()-timedelta(days=2));r=calculate_ranking(a,b,cfg());self.assertEqual(len(r['top_ids']),1);self.assertIsNone(r['results'][0]['metrics']['roi_growth'])
 def test_16_seven_over_thirty(self):
  a,b=self.pair();b['data']['rows'][0]['spend']=400000;r=calculate_ranking(a,b,cfg());self.assertEqual(r['results'][0]['queue'],'data')
 def test_17_new_has_no_infinite_growth(self):
  a=imp([['a','new',100,600,6,600]]);b=imp([['a','new',100,600,6,600]],7);r=calculate_ranking(a,b,cfg(reference_roi=6));self.assertIsNone(r['results'][0]['metrics']['roi_growth']);self.assertEqual(r['results'][0]['queue'],'explore')
 def test_18_missing_week_not_zero(self):
  a,b=self.pair();b['data']['rows']=[];r=calculate_ranking(a,b,cfg());self.assertEqual(r['results'][0]['queue'],'data');self.assertIsNone(r['results'][0]['metrics']['spend_7d'])
 def test_19_three_nonoverlapping_weeks(self):
  a,b=self.pair();end=date.fromisoformat(b['period_end']);weeks=[imp([['A','教学',1000,5500,30,5500]],7,str(end-timedelta(days=7)),id='w1'),imp([['A','教学',1000,3000,20,3000]],7,str(end-timedelta(days=14)),id='w2')]
  r=calculate_ranking(a,b,cfg(reference_roi=3),weeks=weeks,requested_mode='rolling');self.assertAlmostEqual(r['results'][0]['metrics']['stability'],200/3)
 def test_20_overlapping_daily_not_independent(self):
  a,b=self.pair();end=date.fromisoformat(b['period_end']);weeks=[imp([['A','教学',1000,6000,30,6000]],7,str(end-timedelta(days=x))) for x in (1,2)]
  r=calculate_ranking(a,b,cfg(reference_roi=3),weeks=weeks);self.assertIsNone(r['results'][0]['metrics']['stability'])
 def test_21_stale_is_labeled(self):
  a,b=self.pair();r=calculate_ranking(a,b,cfg(),as_of=str(date.today()+timedelta(days=10)));self.assertTrue(r['stale'])

class PolicyTests(unittest.TestCase):
 def setup_values(self):
  a=imp([['A','教学',3000,18000,120,20000]]);b=imp([['A','教学',1000,7000,40,8000]],7)
  c=cfg(reference_roi=3,threshold_confirmed=True);r=calculate_ranking(a,b,c)
  t={'task_id':'A-task','revision':1,'bid':2400,'bid_cap':2600,'bid_step':1,'budget':30000,'spent':28500,'addon_cap':10000,'risk_remaining':5000,'review_hours':24,
    'product_ok':True,'scope_confirmed':True,'context_confirmed':True,'config_fresh':True,'task_result_verified':True,'maturity':'matured','task_basis':'reported_net','task_net_gmv':190000,'diagnosis':'budget','diagnosis_note':'核实预算限制'}
  return r,c,t
 def test_30_demo_budget_300_to315(self):
  r,c,t=self.setup_values();p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['budget_new'],31500);self.assertEqual(p['bid_new'],2400);self.assertEqual(p['reserve'],1500)
 def test_31_missing_task_no_numeric(self):
  r,c,t=self.setup_values();p=recommendation(r['results'][0],r,None,c,15000);self.assertEqual(p['action_type'],'WAIT_INPUT');self.assertIsNone(p['budget_new'])
 def test_32_missing_cap_blocks(self):
  r,c,t=self.setup_values();t['bid_cap']=None;p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['action_type'],'WAIT_INPUT')
 def test_33_pending_prevents_compounding(self):
  r,c,t=self.setup_values();p=recommendation(r['results'][0],r,t,c,15000,pending=True);self.assertEqual(p['action_type'],'WAIT_REVIEW')
 def test_34_replay_history_no_action(self):
  r,c,t=self.setup_values();r['stale']=True;p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['action_type'],'HISTORY_ONLY')
 def test_35_bid_only_fixed_budget(self):
  r,c,t=self.setup_values();t.update(diagnosis='bid',diagnosis_note='明确出价依据');p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['bid_new'],2520);self.assertEqual(p['budget_new'],30000);self.assertEqual(p['reserve'],0)
 def test_36_price_cap_floor(self):
  r,c,t=self.setup_values();t.update(diagnosis='bid',bid_cap=2518,bid_step=10);p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['bid_new'],2510)
 def test_37_small_bid_space_hold(self):
  r,c,t=self.setup_values();t.update(diagnosis='bid',bid_cap=2405,bid_step=10);p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['action_type'],'HOLD')
 def test_38_gross_risk_exposure(self):
  r,c,t=self.setup_values();t['risk_remaining']=1000;p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['action_type'],'STOP_REVIEW')
 def test_39_task_own_results_required(self):
  r,c,t=self.setup_values();t['task_net_gmv']=10000;p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['action_type'],'STOP_REVIEW')
 def test_40_budget_shared_cap(self):
  r,c,t=self.setup_values();p=recommendation(r['results'][0],r,t,c,1000);self.assertEqual(p['reserve'],1000)
 def test_41_no_budget_not_low_bid(self):
  r,c,t=self.setup_values();t['diagnosis']='unknown';p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['action_type'],'HOLD')
 def test_42_new_fixed_not_percentage(self):
  r,c,t=self.setup_values();t.update(budget=0,spent=0,fixed_test_budget=5000,risk_remaining=6000);p=recommendation(r['results'][0],r,t,c,4000);self.assertEqual(p['budget_new'],4000);self.assertEqual(p['action_type'],'NEW_BOOST_TEST')

class ApiTests(unittest.TestCase):
 def make_demo(self):
  d=client.post('/api/demo',json={});self.assertEqual(d.status_code,200,d.text);return d.json()
 def rank_demo(self,d):
  r=client.post('/api/ranking-runs',json={'workspace_id':d['workspace']['id'],'import_30':d['import_30'],'import_7':d['import_7']});self.assertEqual(r.status_code,200,r.text);return r.json()
 def test_50_synthetic_example_pipeline_and_idempotency(self):
  a=client.post('/api/examples/load',json={});self.assertEqual(a.status_code,200,a.text);wid=a.json()['id'];b=client.post('/api/examples/load',json={});self.assertEqual(wid,b.json()['id'])
  imports=client.get(f'/api/workspaces/{wid}/imports').json();self.assertEqual(len(imports),4)
  thirty=next(i for i in imports if i['path']=='live' and i['window']==30);seven=next(i for i in imports if i['path']=='live' and i['window']==7)
  r=client.post('/api/ranking-runs',json={'workspace_id':wid,'import_30':thirty['id'],'import_7':seven['id']}).json();self.assertEqual(r['summary_30']['active_single'],2);self.assertTrue(r['stale']);self.assertLessEqual(len(r['top_ids']),3)
 def test_51_end_to_end_action_review(self):
  d=self.make_demo();r=self.rank_demo(d);wid=d['workspace']['id']
  p=client.post('/api/recommendation-runs',json={'run_id':r['id']});self.assertEqual(p.status_code,200,p.text)
  budget=next(x for x in p.json()['proposals'] if x['action_type']=='BUDGET_TEST');pid=budget['id']
  p2=client.post('/api/recommendation-runs',json={'run_id':r['id']}).json();self.assertEqual([x['id'] for x in p.json()['proposals']],[x['id'] for x in p2['proposals']])
  for _ in range(2):self.assertEqual(client.post(f'/api/recommendations/{pid}/approve',json={'confirm':True}).status_code,200)
  led=client.get(f'/api/workspaces/{wid}/ledger').json();self.assertEqual(led['reserved'],1500)
  bad=client.post(f'/api/actions/{pid}/execution',json={'confirm_platform_done':True,'budget_new':9999999,'bid_new':2400});self.assertEqual(bad.status_code,400)
  ex=client.post(f'/api/actions/{pid}/execution',json={'confirm_platform_done':True,'budget_new':budget['budget_new'],'bid_new':budget['bid_new']});self.assertEqual(ex.status_code,200,ex.text)
  pend=client.post('/api/recommendation-runs',json={'run_id':r['id']}).json();self.assertTrue(any(x['action_type']=='WAIT_REVIEW' for x in pend['proposals']))
  rev=client.post(f'/api/actions/{pid}/review',json={'maturity':'matured','cohort_spend':10000,'cohort_net_gmv':60000,'net_orders':6,'settled_spend':1200,'passed':True,'reservation_closed':True,'note':'教学复核'});self.assertEqual(rev.status_code,200,rev.text)
  led=client.get(f'/api/workspaces/{wid}/ledger').json();self.assertEqual(led['reserved'],0);self.assertEqual(led['settled'],1200)
 def test_52_cancel_releases_only_unexecuted(self):
  d=self.make_demo();r=self.rank_demo(d);p=client.post('/api/recommendation-runs',json={'run_id':r['id']}).json()['proposals'];p=next(x for x in p if x['action_type']=='BUDGET_TEST')
  client.post(f'/api/recommendations/{p["id"]}/approve',json={'confirm':True});self.assertEqual(client.post(f'/api/actions/{p["id"]}/cancel',json={}).status_code,200)
  self.assertEqual(client.get(f'/api/workspaces/{d["workspace"]["id"]}/ledger').json()['reserved'],0)
 def test_53_concurrent_same_approval_once(self):
  d=self.make_demo();r=self.rank_demo(d);p=next(x for x in client.post('/api/recommendation-runs',json={'run_id':r['id']}).json()['proposals'] if x['action_type']=='BUDGET_TEST')
  with ThreadPoolExecutor(max_workers=4) as pool:responses=list(pool.map(lambda _:client.post(f'/api/recommendations/{p["id"]}/approve',json={'confirm':True}),range(4)))
  self.assertTrue(all(x.status_code==200 for x in responses));self.assertEqual(client.get(f'/api/workspaces/{d["workspace"]["id"]}/ledger').json()['reserved'],1500)
 def test_54_csv_export(self):
  d=self.make_demo();r=self.rank_demo(d);resp=client.get(f'/api/exports/{r["id"]}');self.assertEqual(resp.status_code,200);self.assertIn('素材ID',resp.text)
 def test_55_cross_origin_denied(self):
  r=client.post('/api/workspaces',headers={'origin':'https://evil.example'},json={'name':'bad'});self.assertEqual(r.status_code,403)
 def test_56_static_app(self):
  self.assertEqual(client.get('/').status_code,200);self.assertEqual(client.get('/app.js').status_code,200);self.assertEqual(client.get('/app.css').status_code,200)
 def test_57_unknown_current_values_stay_unknown(self):
  d=self.make_demo();wid=d['workspace']['id'];self.assertIsNone(client.get(f'/api/workspaces/{wid}/tasks/live/DOES-NOT-EXIST').json())
 def test_58_config_invalid_values(self):
  d=self.make_demo();c=d['workspace']['config'];c['roi_min']=0;res=client.put(f'/api/workspaces/{d["workspace"]["id"]}/config',json=c);self.assertEqual(res.status_code,400)

class AdditionalBoundaryTests(unittest.TestCase):
 def test_60_net_above_gross_isolated(self):
  p=parse_file(rawcsv([['a','test',100,700,5,600]]),'x.csv');self.assertTrue(p['rows'][0]['errors'])
 def test_61_different_basis_no_trend(self):
  a=imp([['a','x',300,1800,18,1800]]);b=imp([['a','x',100,700,7,700]],7,basis='net_1h')
  r=calculate_ranking(a,b,cfg());self.assertIsNone(r['results'][0]['metrics']['roi_growth']);self.assertEqual(len(r['top_ids']),1)
 def test_62_no_probability_in_output(self):
  a=imp([['a','x',300,1800,18,1800]]);b=imp([['a','x',100,700,7,700]],7)
  r=calculate_ranking(a,b,cfg());self.assertIsNone(r['results'][0]['success_probability']);self.assertIsNone(r['results'][0]['predicted_incremental_gmv'])
 def test_63_null_optional_totals_not_zero(self):
  p=parse_file(rawcsv([['a','x',100,600,6,600]]),'x.csv');self.assertIsNone(p['totals']['impressions'])
 def test_64_actual_bid_above_cap_no_raise(self):
  r,c,t=PolicyTests().setup_values();t['bid_cap']=2300
  p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['action_type'],'STOP_REVIEW')
 def test_65_old_task_settings_blocked(self):
  r,c,t=PolicyTests().setup_values();t['updated_at']='2020-01-01T00:00:00+00:00'
  p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['action_type'],'WAIT_INPUT')
 def test_66_task_event_basis_mismatch(self):
  r,c,t=PolicyTests().setup_values();t['task_basis']='matured_net'
  p=recommendation(r['results'][0],r,t,c,15000);self.assertEqual(p['action_type'],'WAIT_INPUT')
 def test_67_money_rounding(self):
  p=parse_file(rawcsv([['a','x','1,234.56','7,654.32',5,8000]]),'x.csv')
  self.assertEqual(p['rows'][0]['spend'],123456);self.assertEqual(p['rows'][0]['net_gmv'],765432)

if __name__=='__main__':unittest.main(verbosity=2)
