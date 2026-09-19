import copy,unittest
from data.curation.expansion.webarena_votes.grader import judge,parse_votes
class Checks(unittest.TestCase):
 def evidence(self,choice=1,latest=1):return {'status':200,'forms':[{'id':'7','choice':str(choice)}],'db':{'ui_newest':[{'id':7}],'vote':[]if choice==0 else[{'username':'u','upvote':choice==1}],'timestamp_newest':[{'timestamp':latest}],'target':[{'timestamp':1}]}}
 def test_positive(self):self.assertTrue(judge(self.evidence(),7,'u')['task_completed'])
 def test_wrong_and_undo(self):
  for n in [-1,0]:self.assertFalse(judge(self.evidence(n),7,'u')['task_completed'])
 def test_publication_disagreement_retains_diagnostic_only(self):
  r=judge(self.evidence(latest=2),7,'u');self.assertIsNone(r['task_completed']);self.assertTrue(r['source_target_upvoted']);self.assertFalse(r['chronological_target_agreement'])
 def test_missing(self):self.assertIsNone(judge(None,7,'u')['task_completed'])
 def test_wrong_user_and_render_db_disagreement(self):
  self.assertIsNone(judge(self.evidence(),7,'other')['task_completed']);e=self.evidence();e['forms'][0]['choice']='0';self.assertIsNone(judge(e,7,'u')['task_completed'])
 def test_wrong_top_and_duplicate(self):
  e=self.evidence();e['forms'].insert(0,{'id':'8','choice':'1'});self.assertIsNone(judge(e,7,'u')['task_completed'])
  e=self.evidence();e['forms']*=2;self.assertIsNone(judge(e,7,'u')['task_completed'])
 def test_actual_html_attribute_parser(self):
  self.assertEqual(parse_votes('<form data-vote-route-value="submission_vote" data-vote-id-value="7" data-vote-choice-value="1" action="/sv/7"></form>'),[{'id':'7','choice':'1','action':'/sv/7'}])
if __name__=='__main__':unittest.main()
