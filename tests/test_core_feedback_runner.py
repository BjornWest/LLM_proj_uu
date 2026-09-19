"""Core delivery integration without a browser or endpoint; real browser cases
live in scripts/verify_core_browser_feedback.py.
"""
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

from intent_browser.backend import Completion
from intent_browser.harness import EvidenceConversation, HarnessProfile, SemanticFeedback
from intent_browser.runner import run_episode


class Updates(SemanticFeedback):
    def before_request(self,env):
        return {'events':[{'text':'Delayed toast'}]} if env.count else None


class CoreRunnerTests(unittest.TestCase):
    def run_case(self, failure=None):
        class Env:
            count=0
            closed=False
            def obs(self):
                return {'goal':'A safe task','url':'http://fixture/','last_action_error':'',
                        'axtree_object':f"[1] button 'Proceed {self.count}'",
                        'screenshot':np.zeros((2,2,3),dtype=np.uint8),
                        'privileged':'SECRET-GRADER'}
            def reset(self,seed):return self.obs(),{}
            def step(self,action):self.count+=1;return self.obs(),0,False,False,{'private':'SECRET-GRADER'}
            def close(self):self.closed=True
        class Backend:
            last_request=None
            count=0
            def complete(self,messages):
                self.count+=1
                if self.count==2 and failure=='preflight':raise ValueError('before dispatch')
                self.last_request={'messages':messages}
                if self.count==2 and failure=='timeout':raise TimeoutError('unknown delivery')
                text="click('1')" if self.count==1 else "send_msg_to_user('Done')"
                return Completion(text,{},self.last_request)
        env=Env();tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch('intent_browser.runner.observation_text',side_effect=lambda o:o['axtree_object']), \
             patch('intent_browser.harness.flatten_axtree_to_str',side_effect=lambda x:x):
            root,summary=run_episode(lambda _:env,Backend(),{},tmp.name,max_steps=2,
                harness_profile=HarnessProfile(name='test-delivery',conversation_factory=EvidenceConversation,
                                               feedback_factory=Updates,delivery_tracking=True))
        rows=[json.loads(s) for s in (root/'steps.jsonl').read_text().splitlines()]
        records=[json.loads(s) for s in (root/'policy-delivery.jsonl').read_text().splitlines()]
        return root,summary,rows,records,env

    def test_exact_delayed_update_binding_and_evaluation_order(self):
        root,summary,rows,records,env=self.run_case()
        self.assertIsNone(summary['error'])
        self.assertTrue(env.closed)
        self.assertIn('Delayed toast',json.dumps(rows[1]['messages']))
        self.assertNotIn('Delayed toast',rows[1]['messages'][-1]['content'])
        kinds=[i['kind'] for i in records[1]['items']]
        self.assertIn('browser_update',kinds)
        self.assertIn('browser_feedback',kinds)
        self.assertTrue(all(i['confirmed'] for i in records[1]['items']))
        self.assertNotIn('SECRET-GRADER',json.dumps(records)+json.dumps(rows[1]['messages']))
        self.assertEqual(rows[1]['messages'][:len(rows[0]['messages'])],rows[0]['messages'])
        events=[json.loads(s)['event'] for s in (root/'events.jsonl').read_text().splitlines()]
        self.assertLess(events.index('core_policy_delivery_recorded'),events.index('tool_started'))
        self.assertLess(events.index('evaluation_completed'),events.index('environment_close_started'))

    def test_transport_unknown_and_preflight_do_not_inherit_acknowledgement(self):
        for failure in ('timeout','preflight'):
            with self.subTest(failure=failure):
                _,summary,rows,records,env=self.run_case(failure)
                self.assertEqual(env.count,1)
                self.assertEqual(summary['stop_reason'],'error')
                self.assertTrue(all(not i['confirmed'] for i in records[1]['items']))
                self.assertEqual(records[1]['scope'], 'attempted_request_unconfirmed' if failure=='timeout' else 'no_retained_request_unconfirmed')
                if failure=='preflight':self.assertIsNone(rows[1]['model_request'])


if __name__=='__main__':unittest.main()
