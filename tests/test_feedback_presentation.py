from copy import deepcopy
from dataclasses import replace
import json
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from intent_browser.backend import Completion
from intent_browser.feedback_presentation import CompactFeedback, size
from intent_browser.harness import HarnessProfile, EvidenceConversation, SemanticFeedback
from tests.runner_diagnostics import run_episode

class PresentationTests(unittest.TestCase):
    def test_noisy_navigation_bounded_and_important_events_retained(self):
        events=[{'kind':'text_appeared','text':'Navigation item '+str(i),'document_id':'doc','page':'p1','frame':'f1',
                 'sequence':i,'observed_monotonic':12345} for i in range(100)]
        events += [{'kind':'text_appeared','text':'Transient notice','page':'p1','frame':'f1','sequence':100},
                   {'kind':'invalid','text':'Required value','sequence':101},
                   {'kind':'page_announcement','text':'Payment failed','sequence':102},
                   {'kind':'navigation','url':'http://fixture/next','sequence':103}]
        raw={'events':events,'omitted':0,'capture_warnings':[]};saved=deepcopy(raw)
        out=CompactFeedback()(raw,kind='browser_update')
        self.assertLessEqual(size(out),6000)
        self.assertLessEqual(len(out['events']),10)
        text=json.dumps(out);self.assertIn('Transient notice',text);self.assertIn('Payment failed',text)
        self.assertIn('Required value',text);self.assertIn('http://fixture/next',text)
        self.assertNotIn('document_id',text);self.assertNotIn('observed_monotonic',text)
        self.assertEqual(raw,saved);self.assertGreater(out['selection']['selection_omitted'],0)

    def test_dedup_only_generic_exact_same_source_and_window(self):
        base={'kind':'text_appeared','text':'Insurance added','document_id':'d','page':'p','frame':'f'}
        events=[base,deepcopy(base),{**base,'frame':'f2'},{**base,'kind':'page_announcement'},
                {**base,'kind':'page_announcement'},{**base,'text':'Insurance removed'}]
        out=CompactFeedback(max_generic=10)({'events':events},kind='browser_update')
        self.assertEqual(out['selection']['generic_duplicates'],1)
        self.assertEqual(len(out['events']),5)
        self.assertEqual(sum(e['kind']=='page_announcement' for e in out['events']),2)
        self.assertIn('Insurance removed',json.dumps(out))

    def test_large_error_and_fields_capped_with_explicit_omissions(self):
        raw={'execution':'action_error','error':'TimeoutError: navigation\n'+'Details'*2000,
             'url_before':'http://before/','url_after':'http://after/',
             'added_or_changed':['textbox '+('a'*800)]*12,'removed_or_changed':['paragraph '+('b'*800)]*12,
             'page_events':[{'kind':'page_announcement','text':'x'*800,'sequence':i} for i in range(64)],
             'page_events_omitted':10,'event_capture':{'warnings':[]}}
        out=CompactFeedback()(raw,kind='browser_feedback')
        self.assertLessEqual(size(out),6000);self.assertEqual(out['execution'],'action_error')
        self.assertEqual(out['error'],'TimeoutError: navigation');self.assertEqual(out['url_after'],'http://after/')
        self.assertEqual(out['selection']['capture_omitted'],10)
        self.assertGreater(out['selection']['truncated_fields'],0)
        self.assertGreater(out['selection']['selection_omitted'],0)
        self.assertGreater(out['selection']['ax_lines_omitted'],0)

    def test_search_is_not_silently_reformatted(self):
        raw={'tool':'web_search','result':'Excerpt'}
        self.assertEqual(CompactFeedback()(raw,kind='search_result'),raw)

    def test_selected_delivery_and_raw_artifacts_remain_separate(self):
        class Feedback(SemanticFeedback):
            def after_action(self,*args):
                raw=super().after_action(*args)
                raw['page_events']=[{'kind':'text_appeared','text':'Transient notice','document_id':'DOC_RAW_ONLY',
                                     'observed_monotonic':12345,'sequence':1}]
                return raw
        class Env:
            def obs(self):return {'goal':'Inspect','url':'http://fixture/','last_action_error':'',
                'axtree_object':{"nodes":[{}], "text":"[1] button 'Go'"},'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self,seed):return self.obs(),{}
            def step(self,action):return self.obs(),0,False,False,{}
            def close(self):pass
        class Backend:
            i=0
            def complete(self,messages):
                self.i+=1
                return Completion("click('1')" if self.i==1 else "send_msg_to_user('Done')",{}, {'messages':messages})
        profile=HarnessProfile(name='compact-test',conversation_factory=EvidenceConversation,feedback_factory=Feedback,
            delivery_tracking=True,feedback_presentation=CompactFeedback())
        with tempfile.TemporaryDirectory() as temp, \
             patch('intent_browser.runner.observation_text',side_effect=lambda o:o['axtree_object']['text']), \
             patch('intent_browser.harness.flatten_axtree_to_str',side_effect=lambda x:x['text']):
            path,summary=run_episode(lambda _:Env(),Backend(),{},temp,max_steps=2,harness_profile=profile)
            self.assertIsNone(summary['error'])
            rows=[json.loads(x) for x in (path/'steps.jsonl').read_text().splitlines()]
            raw=json.loads((path/rows[0]['browser_feedback_raw_artifact']).read_text())
            self.assertIn('DOC_RAW_ONLY',json.dumps(raw))
            self.assertNotIn('DOC_RAW_ONLY',json.dumps(rows[1]['messages']))
            self.assertIn('Transient notice',json.dumps(rows[1]['messages']))
            for item in rows[1]['policy_delivery']['items']:
                self.assertTrue(item['confirmed']);self.assertNotIn('DOC_RAW_ONLY',(path/item['artifact']).read_text())

if __name__=='__main__':unittest.main()
