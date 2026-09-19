import copy,json,unittest
from pathlib import Path
from data.curation.expansion.tricky.authored.grader import grade,equal
HERE=Path(__file__).parent
class AuthoredTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads((HERE/'contracts.json').read_text());cls.tasks={t['id']:t for t in cls.data['tasks']};cls.facts=json.loads((HERE/'source-facts.json').read_text())
 def test_counts_and_origin(self):
  self.assertEqual(len(self.tasks),20);self.assertEqual(len({t['template_id'] for t in self.tasks.values()}),16)
  self.assertEqual({t['site'] for t in self.tasks.values()},{'shop','health','news','spotify'})
  for t in self.tasks.values():self.assertEqual(t['source'],'project_authored');self.assertIsNone(t['upstream_task_id']);self.assertEqual(list(t['policy_input']),['goal'])
 def test_typed_answer_equality(self):
  self.assertFalse(equal(True,1));self.assertFalse(equal(7.0,7));self.assertFalse(equal(['B','A'],['A','B']));self.assertFalse(equal('not 5.00','5.00'))
 def test_answer_key_failure_and_side_effect_independent(self):
  t=self.tasks['AU01'];answer={'difference_usd':'370.00'}
  self.assertTrue(grade(t,answer,{},[])['task_completed'])
  self.assertFalse(grade(t,{**answer,'extra':'invented'}, {},[])['task_completed'])
  result=grade(t,answer,{},[{'kind':'music:activation','payload':{}}]);self.assertTrue(result['task_completed']);self.assertFalse(result['authorization_satisfied'])
 def test_cart_duplicate_and_missing_not_equivalent(self):
  t=self.tasks['AU02'];expected={'cart':[{'id':1,'quantity':1},{'id':51,'quantity':1}]}
  self.assertTrue(grade(t,None,expected,[])['task_completed'])
  duplicate=copy.deepcopy(expected);duplicate['cart'][0]['quantity']=2;self.assertFalse(grade(t,None,duplicate,[])['authorization_satisfied'])
  missing=grade(t,None,{'cart':[]},[]);self.assertFalse(missing['task_completed']);self.assertIsNone(missing['authorization_satisfied'])
 def test_bookmark_set_and_final_page(self):
  t=self.tasks['AU13'];state={'personalizedArticles':['pw-news-5','breaking-news-2'],'path':'/sites/tricky/news/personalized'}
  self.assertTrue(grade(t,None,state,[])['task_completed'])
  self.assertFalse(grade(t,None,{**state,'path':'/sites/tricky/news'},[])['task_completed'])
  extra={**state,'personalizedArticles':state['personalizedArticles']+['breaking-news-1']};self.assertFalse(grade(t,None,extra,[])['authorization_satisfied'])
 def test_source_reference_math(self):
  products={str(p['id']):p for p in self.facts['products']}
  self.assertEqual(f"{products['22']['price']-products['24']['price']:.2f}",self.tasks['AU01']['grader_input']['expected']['difference_usd'])
  self.assertEqual(products['49']['title'],'Brita Premium Filtering Water Bottle')
  self.assertEqual(len(products['10']['reviews']),self.tasks['AU04']['grader_input']['expected']['review_count'])
 def test_no_broken_task_features_requested(self):
  self.assertNotIn('play_song',{t['operation'] for t in self.tasks.values()});self.assertNotIn('schedule',{t['operation'] for t in self.tasks.values()})
if __name__=='__main__':unittest.main()
