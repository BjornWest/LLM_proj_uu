"""Offline transport tests of trusted clarification in the actual episode loop."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np

from intent_browser.backend import ChatCompletionsBackend
from intent_browser.harness import native_tools_profile, with_clarification, SemanticFeedback
from tests.runner_diagnostics import run_episode
from intent_browser.retry_policy import DecisionRetryPolicy


class RunnerClarificationTests(unittest.TestCase):
    def run_case(self, *, batch=False, invalid_order=False, callback_failure=False,
                 max_steps=3, enabled=True):
        requests, calls, actions, order = [], [], [], []
        class Env:
            def obs(self):
                return {'goal':'Choose a size after asking me.', 'url':'http://fixture/',
                    'last_action_error':'', 'axtree_object':{'nodes':[{'nodeId':'1','role':{'value':'StaticText'},'name':{'value':'[1] button Continue'}}]},
                    'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self, seed): order.append('reset');return self.obs(), {}
            def step(self, action):
                actions.append(action);order.append('action')
                return self.obs(), 0, False, False, {}
            def close(self):order.append('close')
        env=Env()
        question='  Which size?\n';reply='EU 40, please.\nKeep the blue one.'
        def callback(value):
            self.assertNotIn('close',order)
            order.append('callback');calls.append(value)
            if callback_failure:raise RuntimeError('Responder offline')
            return reply
        def transport(req):
            request=json.loads(req.content);requests.append(request);n=len(requests)
            names=([('ask_user',{'question':question})] if n==1 else
                   [('send_msg_to_user',{'text':'I will use EU 40.'})])
            if n==1 and batch:names.insert(0,('noop',{}))
            if n==1 and invalid_order:names.append(('noop',{}))
            tool_calls=[{'id':f'call-{n}-{i}','type':'function','function':{
                'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(names)]
            return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{
                'role':'assistant','content':None,'tool_calls':tool_calls}}], 'usage':{'cost':0}})
        backend=ChatCompletionsBackend('https://offline.invalid/v1','mock')
        backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport))
        self.addCleanup(backend.close)
        profile=replace(native_tools_profile(), feedback_factory=SemanticFeedback)
        profile=replace(profile, tools=replace(profile.tools,batch_size=4 if batch or invalid_order else 1))
        if enabled:profile=with_clarification(profile)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        with ExitStack() as stack:
            stack.enter_context(patch('intent_browser.runner.observation_text',side_effect=lambda o:o['axtree_object']['nodes'][0]['name']['value']))
            stack.enter_context(patch('intent_browser.harness.flatten_axtree_to_str',side_effect=lambda x:x['nodes'][0]['name']['value']))
            stack.enter_context(patch('intent_browser.runner.refresh_observation',side_effect=lambda e:e.obs()))
            stack.enter_context(patch('intent_browser.batching.document_signature',return_value=['same-document']))
            path,summary=run_episode(lambda _:env,backend,{},temp.name,max_steps=max_steps,
                harness_profile=profile,clarification_callback=callback if enabled else None,
                clarification_audit_id='private-audit-42' if enabled else None,
                retry_policy=DecisionRetryPolicy())
        rows=[json.loads(line) for line in (path/'steps.jsonl').read_text().splitlines()]
        return path, summary, rows, requests, calls, actions, order, reply

    def test_exact_reply_same_episode_and_confirmed_delivery(self):
        for batch in (False, True):
            with self.subTest(batch=batch):
                path,s,rows,reqs,calls,actions,order,reply=self.run_case(batch=batch)
                self.assertIsNone(s['error']);self.assertEqual(s['stop_reason'],'agent_finished')
                self.assertEqual(calls,['  Which size?\n']);self.assertEqual(order.count('reset'),1)
                self.assertEqual(len(actions),2 if batch else 1)
                self.assertFalse(any('ask_user' in a for a in actions))
                row=rows[0]['batch_calls'][-1] if batch else rows[0]
                self.assertFalse(row['browser_stepped']);self.assertIsNone(row['reward'])
                if batch:self.assertEqual(rows[0]['batch_stop_reason'],'clarification_boundary')
                saved=json.loads((path/row['clarification_artifact']).read_text())
                self.assertEqual(saved['reply'],reply);self.assertEqual(saved['question'],calls[0])
                self.assertEqual(saved['audit_id'],'private-audit-42')
                source=[i for i in rows[1]['policy_delivery']['items'] if i['kind']=='clarification_result']
                self.assertEqual(len(source),1);self.assertTrue(source[0]['confirmed'])
                evidence=json.loads((path/source[0]['artifact']).read_text())
                self.assertEqual(json.loads(evidence['text']),{'tool':'ask_user','user_reply':reply})
                b=source[0]['message_span'];msg=reqs[1]['messages'][b['message_index']]
                self.assertEqual(msg['role'],'tool')
                self.assertEqual(msg['content'][b['start']:b['end']],evidence['text'])
                self.assertNotIn('private-audit-42',json.dumps(reqs))
                self.assertEqual(reqs[0]['tools'],reqs[1]['tools'])
                self.assertEqual(reqs[1]['messages'][:len(reqs[0]['messages'])],reqs[0]['messages'])
                events=[json.loads(l)['event'] for l in (path/'events.jsonl').read_text().splitlines()]
                self.assertLess(events.index('evaluation_completed'),events.index('environment_close_started'))

    def test_unrequested_subsequent_action_rejected_before_any_effect(self):
        _,s,rows,reqs,calls,actions,_,_=self.run_case(invalid_order=True,max_steps=1)
        self.assertIn('ask_user must be',s['error']);self.assertEqual(calls,[]);self.assertEqual(actions,[])
        self.assertEqual(len(reqs),1)

    def test_callback_failure_is_technical_not_retried_or_answered(self):
        for batch in (False,True):
            with self.subTest(batch=batch):
                path,s,rows,reqs,calls,actions,_,_=self.run_case(batch=batch,callback_failure=True)
                self.assertIn('Responder offline',s['error']);self.assertEqual(len(reqs),1)
                self.assertEqual(s['decision_retry_count'],0);self.assertEqual(len(calls),1)
                saved=json.loads(next(path.glob('clarification-*.json')).read_text())
                self.assertIsNone(saved['reply']);self.assertIn('Responder offline',saved['error'])
                self.assertIsNone(s['evaluation']['safe_success'])
                self.assertEqual(len(actions),1 if batch else 0)

    def test_last_step_answer_is_retained_but_not_claimed_delivered(self):
        path,s,rows,reqs,calls,actions,_,_=self.run_case(max_steps=1)
        self.assertEqual(s['stop_reason'],'max_steps');self.assertEqual(actions,[])
        self.assertTrue(list(path.glob('clarification-*.json')))
        self.assertFalse(any(i['kind']=='clarification_result' for i in rows[0]['policy_delivery']['items']))

    def test_disabled_tool_is_not_published_or_executed(self):
        _,s,_,reqs,calls,actions,_,_=self.run_case(enabled=False,max_steps=1)
        self.assertIsNotNone(s['error']);self.assertEqual(calls,[]);self.assertEqual(actions,[])
        self.assertNotIn('ask_user',[t['function']['name'] for t in reqs[0]['tools']])

    def test_misconfiguration_fails_before_env_or_model(self):
        profile=with_clarification(native_tools_profile())
        for p,options in [(profile,{}),(profile,{'clarification_callback':3}),
                          (profile,{'clarification_callback':lambda q:'ok','clarification_audit_id':''}),
                          (native_tools_profile(),{'clarification_callback':lambda q:'ok'})]:
            with self.subTest(options=options),self.assertRaises(ValueError):
                run_episode(lambda _:self.fail('environment created'),object(),{},harness_profile=p,**options)

if __name__=='__main__':unittest.main()
