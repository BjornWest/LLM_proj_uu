import json,unittest
from pathlib import Path
from data.curation.expansion.tricky.lookup_tasks import verify_answer,HERE
class LookupTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.tasks=json.loads((HERE/'contracts.json').read_text())['tasks']
 def test_all_canonical_and_wrong_answers(self):
  for task in self.tasks:
   with self.subTest(task=task['id']):
    for answer in task['grader_input']['accepted_answers']:self.assertTrue(verify_answer(task,answer))
    for bad in [None,'','incorrect','not '+task['grader_input']['accepted_answers'][0],task['grader_input']['accepted_answers'][0]+' or something else']:
     self.assertFalse(verify_answer(task,bad))
 def test_negated_numeric_and_overlong_answer_rejected(self):
  t=self.tasks[0]
  for bad in ['1629.99','629.999','Not 629.99','$629.99, actually $999.99']:
   self.assertFalse(verify_answer(t,bad))
 def test_oldest_title_upstream_typo_rejected(self):
  t=next(t for t in self.tasks if t['id']=='TX09')
  self.assertFalse(verify_answer(t,'Tech Giants Rport Record Earnings'))
  self.assertTrue(verify_answer(t,'Tech Giants Report Record Earnings'))
 def test_policy_projection_excludes_answers(self):
  for t in self.tasks:
   self.assertEqual(list(t['policy_input']),['goal']);self.assertEqual(t['policy_input']['goal'],t['original_prompt'])
 def test_procedure_does_not_determine_answer_outcome(self):
  t=dict(self.tasks[0]);t['procedure_observations']=[]
  self.assertTrue(verify_answer(t,'629.99'))
 def test_count_no_variation_padding(self):
  inventory=json.loads((HERE/'inventory.json').read_text())
  self.assertEqual(inventory['original_no_hint_task_enum_count'],32)
  self.assertEqual(inventory['semantic_task_count_upper_bound'],31)
  self.assertEqual(len({t['source_task_id'] for t in self.tasks}),10)
if __name__=='__main__':unittest.main()
