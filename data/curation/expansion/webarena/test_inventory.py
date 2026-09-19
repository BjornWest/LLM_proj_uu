import unittest
from data.curation.expansion.webarena.inventory import build,BATCH
from data.curation.expansion.webarena.propose_candidates import diversify
class InventoryTests(unittest.TestCase):
 def test_pinned_counts_and_identity(self):
  rows,s=build();self.assertEqual(len(rows),812);self.assertEqual(s['template_count'],190);self.assertEqual(s['installed_site_tasks'],298);self.assertEqual(s['installed_read_only_candidates'],137);self.assertEqual(len({(r['source_task_id'],r['source_revision']) for r in rows}),812)
 def test_policy_boundary(self):
  rows,_=build()
  for r in rows:
   self.assertEqual(set(r['policy_input']),{'goal','start_urls','results_schema'});self.assertNotIn('expected',r['policy_input']);self.assertIsNone(r['readiness']['browser_positive']);self.assertFalse(r['readiness']['training_ready'])
 def test_first_batch_diversity(self):
  rows,_=build();b=[r for r in rows if r['first_batch']];self.assertEqual(len(b),10);self.assertEqual(len({r['template_id'] for r in b}),10);self.assertEqual({r['site_ids'][0] for r in b},{'reddit','shopping'})
 def test_template_first(self):
  rows=[{'task_id':i,'intent_template_id':t} for i,t in enumerate([1,1,2,3,3])];out=diversify(rows,4);self.assertEqual([x['intent_template_id'] for x in out[:3]],[1,2,3]);self.assertEqual(len({x['task_id'] for x in out}),4)
if __name__=='__main__':unittest.main()
