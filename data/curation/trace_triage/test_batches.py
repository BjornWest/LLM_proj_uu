import unittest
from . import test_triage as fixtures
from .core import analyze, tokens

class BatchTriageTests(unittest.TestCase):
    setUp=fixtures.TriageTests.setUp
    episode=fixtures.TriageTests.episode

    def test_members_fix_false_positive_without_multiplying_request_metrics(self):
        members=[{'batch_call':0,'action':"click('1')",'browser_stepped':True},
                 {'batch_call':1,'action':"click('2')",'not_executed':True,'browser_stepped':False}]
        p=self.episode('batch',safe=True,overrides={0:{'action':None,'batch_calls':members,
            'model_response':{'usage':{'prompt_tokens':12,'completion_tokens':3}}}})
        e,ev=analyze(p)
        self.assertNotIn('completion_without_state_action',[f['code'] for f in e['flags']])
        self.assertEqual(e['action_counts'],{'recorded':2,'skipped':1,'returned_browser_steps':1})
        self.assertEqual(len(e['timeline']),1);self.assertEqual(len(e['timeline'][0]['batch_actions']),2)
        self.assertEqual(e['operational_metrics']['totals']['prompt_tokens']['known_sum'],12)
        self.assertTrue(ev.unchanged());self.assertEqual(len(tokens(e)),1)

    def test_skipped_only_and_read_only_do_not_imply_state_action(self):
        for name,members in [('skipped',[{'action':"click('1')",'not_executed':True}]),
                             ('read',[{'action':"ax_read(node_ref='d1n1')",'browser_stepped':False}])]:
            with self.subTest(name=name):
                p=self.episode(name,safe=True,overrides={0:{'action':None,'batch_calls':members}})
                e,_=analyze(p)
                self.assertIn('completion_without_state_action',[f['code'] for f in e['flags']])

    def test_member_errors_preserved_and_unknown_targets_do_not_match_runs(self):
        cases=[]
        for name in ('a','b'):
            p=self.episode(name,safe=True,overrides={0:{'action':None,'batch_calls':[
                {'batch_call':0,'action':"click('999')",'action_error':'Timeout','browser_stepped':True}]}})
            e,_=analyze(p);cases.append(e)
            self.assertIn('action_error',[f['code'] for f in e['flags']])
            self.assertIn('completion_with_errors',[f['code'] for f in e['flags']])
        self.assertNotEqual(tokens(cases[0]),tokens(cases[1]))
