"""Read-only document races must stop proposals, not replay or lose them."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import numpy as np
from playwright.sync_api import Error as PlaywrightError
from intent_browser.batching import DocumentScanInvalidated, document_signature
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.harness import native_tools_profile, SemanticFeedback
from tests.runner_diagnostics import run_episode


class SignatureTests(unittest.TestCase):
    def fixture(self):
        browser = SimpleNamespace(is_connected=lambda: True)
        ctx = SimpleNamespace(browser=browser, pages=[])
        main = SimpleNamespace(evaluate=lambda _: ['http://main/', 1], is_detached=lambda: False)
        page = SimpleNamespace(context=ctx, main_frame=main, frames=[main], is_closed=lambda: False)
        ctx.pages = [page]
        return SimpleNamespace(unwrapped=SimpleNamespace(page=page)), page

    def test_child_target_closed_does_not_mean_active_page_closed(self):
        env, page = self.fixture()
        def fail(_): raise PlaywrightError('Frame.evaluate: Target page, context or browser has been closed')
        page.frames.append(SimpleNamespace(evaluate=fail, is_detached=lambda: True))
        with self.assertRaises(DocumentScanInvalidated) as cm: document_signature(env)
        self.assertFalse(cm.exception.detail['main_frame'])
        self.assertTrue(cm.exception.detail['frame_detached'])
        self.assertIn('Target page', cm.exception.detail['error'])

    def test_main_closed_target_and_unrelated_js_error_are_fatal(self):
        for message in ('Target page, context or browser has been closed', 'ReferenceError: unexpected script'):
            env, page = self.fixture()
            def fail(_): raise PlaywrightError(message)
            page.main_frame.evaluate = fail
            with self.assertRaises(PlaywrightError): document_signature(env)

    def test_main_navigation_invalidates(self):
        env, page = self.fixture()
        def fail(_): raise PlaywrightError('Execution context was destroyed, most likely because of a navigation')
        page.main_frame.evaluate = fail
        with self.assertRaises(DocumentScanInvalidated): document_signature(env)

    def test_closed_browser_or_page_is_fatal_even_without_frames(self):
        for which in ('page', 'browser'):
            env, page = self.fixture(); page.frames=[]; page.context.pages=[]
            if which=='page': page.is_closed=lambda:True
            else: page.context.browser.is_connected=lambda:False
            with self.assertRaises(PlaywrightError): document_signature(env)

    def test_topology_change_is_never_a_valid_partial_signature(self):
        env, page = self.fixture()
        def change(_):
            page.frames.append(SimpleNamespace());return ['http://main/', 1]
        page.main_frame.evaluate=change
        with self.assertRaises(DocumentScanInvalidated): document_signature(env)


class RunnerGuardTests(unittest.TestCase):
    def run_case(self, scan_number, fatal=False, action_failure=False):
        calls, requests = [], []
        class Env:
            def obs(self):
                return {'goal':'Guard test','url':'http://fixture/', 'last_action_error':'',
                        'axtree_object':{'nodes':[{'nodeId':'1','browsergym_id':'1','role':{'value':'button'},'name':{'value':'Continue'}}]},
                        'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self,seed): return self.obs(),{}
            def step(self,action):
                calls.append(action)
                if action_failure=='capture' and len(calls)==1:
                    raise DocumentScanInvalidated({'reason':'post_action_capture_failed'})
                if action_failure: raise RuntimeError('action dispatch failed')
                return self.obs(),0,False,False,{}
            def close(self): pass
        env=Env()
        def transport(req):
            request=json.loads(req.content);requests.append(request);n=len(requests)
            selected=[('noop',{}),('noop',{})] if n==1 else [('send_msg_to_user',{'text':'Done'})]
            return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{
                'role':'assistant','content':None,'tool_calls':[{'id':f'{n}-{i}','type':'function',
                'function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(selected)]}}]})
        backend=ChatCompletionsBackend('https://offline.invalid/v1','mock')
        backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport));self.addCleanup(backend.close)
        count=0
        def signature(e):
            nonlocal count
            count+=1
            if count==scan_number:
                if fatal:raise PlaywrightError('Target page, context or browser has been closed')
                raise DocumentScanInvalidated({'frame_index':1,'error':'Frame was detached'})
            return ['same-document']
        profile=replace(native_tools_profile(),feedback_factory=SemanticFeedback)
        profile=replace(profile,tools=replace(profile.tools,batch_size=4))
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.enter_context(patch('intent_browser.runner.observation_text',return_value='[1] button Continue'))
            stack.enter_context(patch('intent_browser.harness.flatten_axtree_to_str',return_value='[1] button Continue'))
            stack.enter_context(patch('intent_browser.runner.refresh_observation',side_effect=lambda e:e.obs()))
            stack.enter_context(patch('intent_browser.batching.document_signature',side_effect=signature))
            path,summary=run_episode(lambda _:env,backend,{},tmp,max_steps=2,harness_profile=profile)
            rows=[json.loads(l) for l in (path/'steps.jsonl').read_text().splitlines()]
        return summary, rows, calls, requests

    def test_initial_and_pre_dispatch_races_record_both_skipped_calls_and_continue(self):
        for scan in (1,2):
            with self.subTest(scan=scan):
                summary,rows,calls,requests=self.run_case(scan)
                self.assertIsNone(summary['error']);self.assertEqual(len(requests),2)
                self.assertEqual(rows[0]['batch_stop_reason'],'document_scan_invalidated')
                self.assertEqual(len(rows[0]['batch_calls']),2)
                for c in rows[0]['batch_calls']:
                    self.assertTrue(c['not_executed']);self.assertFalse(c['action_dispatch_started'])
                self.assertEqual(len(calls),1);self.assertIn('send_msg_to_user',calls[0])
                self.assertEqual([m['role'] for m in requests[1]['messages'][-3:]],['assistant','tool','tool'])
                self.assertIn('not_executed',requests[1]['messages'][-1]['content'])

    def test_post_dispatch_race_keeps_completed_result_and_skips_remaining(self):
        summary,rows,calls,_=self.run_case(3)
        self.assertIsNone(summary['error']);self.assertEqual(len(calls),2)
        first,second=rows[0]['batch_calls']
        self.assertTrue(first['browser_stepped']);self.assertTrue(first['action_dispatch_started'])
        self.assertNotIn('not_executed',first);self.assertIsNone(first['policy_feedback'].get('error'))
        self.assertTrue(second['not_executed']);self.assertFalse(second['action_dispatch_started'])

    def test_fatal_guard_keeps_proposals_and_no_retry(self):
        for scan in (1,2,3):
            with self.subTest(scan=scan):
                summary,rows,calls,requests=self.run_case(scan,fatal=True)
                self.assertIsNotNone(summary['error']);self.assertEqual(len(requests),1)
                self.assertEqual(len(rows[0]['batch_calls']),2)
                self.assertEqual(len(calls),1 if scan==3 else 0)
                self.assertTrue(rows[0]['batch_calls'][-1]['not_executed'])
                if scan==3:
                    self.assertIsNone(rows[0]['batch_calls'][0]['policy_feedback'].get('error'))
                else:self.assertEqual(rows[0]['actions'],[])

    def test_actual_action_exception_remains_effects_unknown(self):
        summary,rows,calls,requests=self.run_case(100,action_failure=True)
        self.assertIn('action dispatch failed',summary['error']);self.assertEqual(len(requests),1)
        self.assertEqual(len(calls),1)
        self.assertEqual(rows[0]['batch_calls'][0]['policy_feedback']['execution'],'failed_effects_unknown')
        self.assertTrue(rows[0]['batch_calls'][1]['not_executed'])

    def test_capture_exception_after_dispatch_never_claims_not_executed(self):
        summary,rows,calls,requests=self.run_case(100,action_failure='capture')
        first=rows[0]['batch_calls'][0]
        self.assertTrue(first['action_dispatch_started'])
        self.assertFalse(first['browser_stepped'])
        self.assertFalse(first.get('not_executed',False))
        self.assertEqual(first['policy_feedback']['execution'],'failed_effects_unknown')
        self.assertIn('Do not repeat',first['policy_feedback']['instruction'])
        self.assertTrue(rows[0]['batch_calls'][1]['not_executed'])
        self.assertEqual(calls.count('noop()'),1)

if __name__=='__main__': unittest.main()
