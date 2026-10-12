import unittest
from test_system import imp,cfg,client
from app.engine import calculate_ranking

class ObjectiveTests(unittest.TestCase):
 def data(self):
  b=imp([['a','曝光强',100,200,1,200],['b','成单强',100,300,5,300],['c','ROI强',100,900,2,900]],7,id='7')
  for row,n in zip(b['data']['rows'],[900,700,600]):row['impressions']=n
  return b
 def test_objectives_and_formula(self):
  b=self.data()
  for goal,winner in [('exposure','a'),('orders','b'),('roi','c')]:
   r=calculate_ranking(None,b,cfg(),objective=goal)
   self.assertEqual(r['top_ids'][0],winner)
   self.assertEqual(r['objective'],goal)
   selected=calculate_ranking(None,b,cfg(),objective=goal,exposure_tier='500_999')
   self.assertEqual(r['results'],selected['results'])
  r=calculate_ranking(None,b,cfg(),objective='orders')
  self.assertAlmostEqual(r['results'][0]['objective_metrics']['orders']['value'],(5+8/3)/2)
 def test_missing_is_reference_not_zero(self):
  b=self.data();b['data']['rows'][0]['net_orders']=None
  r=calculate_ranking(None,b,cfg(),objective='orders')
  x=next(x for x in r['results'] if x['creative_id']=='a')
  self.assertIsNone(x['metrics']['net_orders_7d'])
  self.assertTrue(x['objective_metrics']['orders']['imputed'])
  self.assertEqual(x['objective_metrics']['orders']['value'],3.5)
 def test_unavailable_no_fabricated_efficiency(self):
  r=calculate_ranking(self.data(),None,cfg(),objective='roi')
  self.assertTrue(all(x['objective_metrics']['roi']['value'] is None for x in r['results']))
  with self.assertRaises(ValueError):calculate_ranking(None,self.data(),cfg(),objective='bad')
 def test_api_replay_and_csv(self):
  d=client.post('/api/demo').json()
  r=client.post('/api/ranking-runs',json={'workspace_id':d['workspace']['id'],'import_7':d['import_7'],'objective':'orders'}).json()
  saved=client.get('/api/ranking-runs/'+r['id']).json()
  self.assertEqual(saved['objective'],'orders')
  self.assertEqual(saved['objective_reference'],r['objective_reference'])
  self.assertIn('目标效率',client.get('/api/exports/'+r['id']).text)
