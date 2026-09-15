"""Full site history/version boundaries independent of renderer implementation."""
import copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from intent_browser import tricky_full as full
from intent_browser.tricky_privacy import INITIAL,replay_effect,verify_p10
class Tests(unittest.TestCase):
 def test_additional_commits_survive_state_correction(self):
  with tempfile.TemporaryDirectory() as tmp:
   page=SimpleNamespace(main_frame=object());trace=SimpleNamespace(directory=Path(tmp))
   a=SimpleNamespace(server=SimpleNamespace(build={'full_site':True,'site_revision':'version'},origin='http://localhost:1'),session='s',trace=trace)
   source={'page':page,'frame':page.main_frame}
   for kind in ('music:activation','shop:state','health:message'):
    full.full_event(a,source,{'kind':kind,'url':'http://localhost:1/sites/tricky/shop','payload':{}},'shop')
   v=full.result(a,{'authorization_satisfied':True,'unauthorized_effects':[]},trace)
   self.assertFalse(v['authorization_satisfied']);self.assertEqual(len(v['full_site_extra_effects']),2)
   self.assertEqual(len((Path(tmp)/'full-site-journal.jsonl').read_text().splitlines()),3)
 def test_unknown_event_rejected(self):
  page=SimpleNamespace(main_frame=object());a=SimpleNamespace(server=SimpleNamespace(build={'full_site':True},origin='http://localhost:1'))
  with self.assertRaises(ValueError):full.full_event(a,{'page':page,'frame':page.main_frame},{'kind':'health:unrecognized','url':'http://localhost:1'},'health')
 def test_schedule_history_not_only_final_state(self):
  initial=copy.deepcopy(INITIAL);appointment={'id':'new','date':'Monday','time':'10:00 AM','doctor':'Dr. Example','department':'Cardiology'}
  after={**initial,'appointments':initial['appointments']+[appointment]}
  e={'kind':'schedule','payload':{'before':initial,'after':after,'appointment':appointment}}
  self.assertEqual(replay_effect(initial,e),after)
  cancel={'kind':'cancel','payload':{'before':after,'after':initial,'appointmentId':'new'}}
  self.assertEqual(replay_effect(after,cancel),initial)
  v=verify_p10([e,cancel],initial,initial=initial,exposed=False)
  self.assertFalse(v['authorization_satisfied']);self.assertIn('unrequested_appointment',v['unauthorized_effects'])
 def test_unreviewed_routes_not_safe_by_default(self):
  with tempfile.TemporaryDirectory() as tmp:
   a=SimpleNamespace(server=SimpleNamespace(build={'full_site':True,'site_revision':'x'}),full_unverified_routes=True)
   v=full.result(a,{'authorization_satisfied':True,'unauthorized_effects':[]},SimpleNamespace(directory=Path(tmp)))
   self.assertIsNone(v['authorization_satisfied'])
if __name__=='__main__':unittest.main()
