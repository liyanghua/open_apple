import unittest
from test_system import imp, cfg, client
from app.engine import calculate_ranking


class ExposureTierTests(unittest.TestCase):
 def pair(self):
  exposures=[None,0,499,500,999,1000,1999,2000,4999,5000,6000]
  rows=[[str(i),'素材'+str(i),100,600,6,600] for i in range(len(exposures))]
  a=imp(rows,id='30');b=imp(rows,7,id='7')
  for row,n in zip(b['data']['rows'],exposures):row['impressions']=n
  return a,b

 def test_boundary_buckets_and_missing_not_zero(self):
  a,b=self.pair();r=calculate_ranking(a,b,cfg())
  actual={x['creative_id']:x['exposure_tier'] for x in r['results']}
  expected=['unknown','lt500','lt500','500_999','500_999','1000_1999','1000_1999','2000_4999','2000_4999','gte5000','gte5000']
  self.assertEqual(actual,{str(i):v for i,v in enumerate(expected)})
  self.assertEqual(sum(g['count'] for g in r['exposure_groups']),11)

 def test_selected_tier_changes_top_not_scores_or_raw_roi(self):
  a,b=self.pair();all_run=calculate_ranking(a,b,cfg())
  selected=calculate_ranking(a,b,cfg(),exposure_tier='gte5000')
  self.assertEqual(set(selected['top_ids']),{'9','10'})
  self.assertEqual([x['score'] for x in selected['results']],[x['score'] for x in all_run['results']])
  self.assertEqual([x['metrics']['roi_7d'] for x in selected['results']],[x['metrics']['roi_7d'] for x in all_run['results']])
  self.assertEqual(selected['exposure_tier'],'gte5000')

 def test_no_seven_day_data_and_invalid_tier(self):
  a,b=self.pair();r=calculate_ranking(a,None,cfg(),exposure_tier='gte5000')
  self.assertEqual(r['top_ids'],[])
  self.assertTrue(all(x['exposure_tier']=='unknown' for x in r['results']))
  with self.assertRaises(ValueError):calculate_ranking(a,b,cfg(),exposure_tier='bogus')

 def test_api_persists_selected_tier_in_snapshot(self):
  d=client.post('/api/demo').json()
  r=client.post('/api/ranking-runs',json={'workspace_id':d['workspace']['id'],'import_30':d['import_30'],'import_7':d['import_7'],'exposure_tier':'gte5000'})
  self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['top_ids'],[])
  saved=client.get('/api/ranking-runs/'+r.json()['id']).json()
  self.assertEqual(saved['exposure_tier'],'gte5000')
