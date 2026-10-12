import unittest
from test_system import imp, cfg
from app.engine import calculate_ranking, recommendation


class ScoreFirstTests(unittest.TestCase):
 def test_hold_still_explains_missing_setup(self):
  a=imp([['a','low',100,100,10,100]]);b=imp([['a','low',20,10,2,10]],7)
  r=calculate_ranking(a,b,cfg());p=recommendation(r['results'][0],r,None,cfg(),None)
  self.assertEqual(p['action_type'],'HOLD')
  self.assertIn('当前独立任务配置',p['required_inputs'])
  self.assertIn('工作区预算池',p['required_inputs'])
  self.assertIn('确认ROI规则与净额口径',p['required_inputs'])
  self.assertIsNone(p['budget_new']);self.assertIsNone(p['bid_new'])

 def test_low_roi_small_sample_and_zero_spend_all_rank(self):
  a=imp([['a','low',100,100,10,100],['b','small',10,80,1,80],['c','zero',0,0,0,0]])
  b=imp([['a','low',20,10,2,10],['b','small',2,40,1,40],['c','zero',0,0,0,0]],7)
  r=calculate_ranking(a,b,cfg(reference_roi=3))
  self.assertEqual(set(r['top_ids']),{'a','b','c'})
  self.assertTrue(all(x['score'] is not None for x in r['results']))
  self.assertTrue(all(not x['eligible'] for x in r['results']))

 def test_missing_week_uses_prior_without_fabricating_raw_metrics(self):
  a=imp([['a','missing',100,600,6,600]]);b=imp([],7)
  r=calculate_ranking(a,b,cfg(reference_roi=3));x=r['results'][0]
  self.assertEqual(r['top_ids'],['a']);self.assertIsNone(x['metrics']['roi_7d'])
  self.assertEqual(x['scoring']['roi_7d'],3)
  self.assertEqual(x['breakdown']['trend'],50)
  self.assertTrue(x['scoring']['imputed'])
  self.assertEqual(recommendation(x,r,None,cfg(),100000)['action_type'],'HOLD')

 def test_small_spend_shrinks_more_than_large_spend(self):
  a=imp([['a','small',1,10,1,10],['b','large',1000,10000,100,10000]])
  r=calculate_ranking(a,None,cfg(reference_roi=3))
  self.assertEqual(r['top_ids'],['b','a'])

 def test_no_reference_all_missing_still_scores_finitely(self):
  r=calculate_ranking(imp([['a','zero',0,0,0,0]]),None,cfg())
  self.assertEqual(r['top_ids'],['a']);self.assertEqual(r['results'][0]['score'],0)
