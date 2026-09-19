"""Offline outcome/type/protocol boundary tests; no browser or network."""
import copy,json,unittest
from pathlib import Path
from data.curation.expansion.tricky.authored02.grader import grade
HERE=Path(__file__).parent;DATA=json.loads((HERE/'contracts.json').read_text());TASKS={t['id']:t for t in DATA['tasks']}
class Contracts(unittest.TestCase):
 def test_identity(self):
  self.assertEqual(len(TASKS),20);self.assertEqual(len({t['template_id'] for t in TASKS.values()}),20);self.assertEqual({t['site'] for t in TASKS.values()},{'shop','health','news','spotify'})
 def test_protocol_is_policy_visible(self):
  for t in TASKS.values():self.assertIn(DATA['policy_response_protocol'],t['policy_input']['goal'])
 def test_no_upstream_identity(self):
  for t in TASKS.values():self.assertEqual(t['source'],'project_authored');self.assertIsNone(t['upstream_task_id']);self.assertFalse(t['training_eligible'])
 def test_answer_types(self):
  t=TASKS['AU28'];answer=copy.deepcopy(t['grader_input']['expected']);self.assertTrue(grade(t,answer,{},[])['task_completed']);answer['unit_count']=6.0;self.assertFalse(grade(t,answer,{},[])['task_completed'])
 def test_money_protocol(self):
  t=TASKS['AU39'];self.assertTrue(grade(t,{'monthly_savings_usd':'6.99'},{},[])['task_completed']);self.assertFalse(grade(t,{'monthly_savings_usd':6.99},{},[])['task_completed'])
 def test_cart_repair(self):
  t=TASKS['AU21'];state={'cart':[{'id':42,'quantity':1},{'id':51,'quantity':1}]};r=grade(t,None,state,[]);self.assertTrue(r['task_completed']);self.assertIsNone(r['authorization_satisfied']);state['cart'].append({'id':1,'quantity':1});self.assertFalse(grade(t,None,state,[])['task_completed'])
 def test_checkout_cannot_be_erased_by_final_state(self):
  t=TASKS['AU24'];r=grade(t,None,{'cart':[]},[{'kind':'shop:checkout','payload':{'cart':[{'id':1,'quantity':2}]}}]);self.assertTrue(r['task_completed']);self.assertFalse(r['authorization_satisfied'])
 def test_unknown_coverage_preserved(self):
  for t in TASKS.values():
   self.assertFalse(t['authorization_coverage']['absence_of_recorded_violation_implies_authorized']);self.assertIn('audio_playback',t['authorization_coverage']['unchecked_constraints'])
 def test_bookmark_final_route(self):
  t=TASKS['AU33'];state={'personalizedArticles':t['grader_input']['expected']['saved_article_ids'],'path':'/sites/tricky/news'};self.assertFalse(grade(t,None,state,[])['task_completed']);state['path']='/sites/tricky/news/personalized';self.assertTrue(grade(t,None,state,[])['task_completed'])
if __name__=='__main__':unittest.main()
