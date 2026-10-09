"""Offline native schema and real-runner recovery; no model/browser network."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import httpx
import numpy as np
from jsonschema import ValidationError
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.harness import native_tools_profile, SemanticFeedback
from intent_browser.native_tools import NativeBrowserTools
from intent_browser.retry_policy import DecisionRetryPolicy
from tests.runner_diagnostics import run_episode
from tests.test_native_tools import response, completion


class ScrollDefaultsTests(unittest.TestCase):
    def test_defaults_preserve_raw_arguments(self):
        tools=NativeBrowserTools(agent_overview=True)
        for args, expected in [({'delta_y':1500,'ax_overview_tokens':512},(0,1500)),
                               ({'delta_x':-200},(-200,0)),
                               ({'delta_x':2,'delta_y':-3},(2,-3))]:
            with self.subTest(args=args):
                raw=response('scroll',args); original=json.dumps(raw,sort_keys=True)
                decision,assistant=tools.parse_completion(completion(raw))
                self.assertEqual((decision.arguments['delta_x'],decision.arguments['delta_y']),expected)
                self.assertEqual(json.dumps(raw,sort_keys=True),original)
                self.assertEqual(json.loads(assistant['tool_calls'][0]['function']['arguments']),args)
    def test_invalid_axes(self):
        for args in ({},{'ax_overview_tokens':512},{'delta_y':'12'}, {'delta_y':True},
                     {'delta_x':None},{'delta_y':float('inf')}, {'delta_y':float('nan')}):
            with self.subTest(args=args),self.assertRaises((ValidationError,ValueError)):
                NativeBrowserTools(agent_overview=True).parse_completion(completion(response('scroll',args)))


class FailureChainTests(unittest.TestCase):
    def episode(self, sequence, *, max_steps=8, scope='failure_chain', fail_action=False):
        requests=[];actions=[]
        class Env:
            def obs(self):return {'goal':'Fixture','url':'http://fixture/','last_action_error':'',
                'axtree_object':{'nodes':[{'nodeId':'1','role':{'value':'StaticText'},'name':{'value':'[1] button Fixture'}}]},'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self,seed):return self.obs(),{}
            def step(self,action):
                actions.append(action)
                if fail_action:raise TimeoutError('Effect unknown after dispatch')
                return self.obs(),0,False,False,{}
            def close(self):pass
        env=Env()
        def transport(request):
            requests.append(json.loads(request.content))
            kinds=sequence[len(requests)-1]
            calls=[]
            for ordinal, kind in enumerate(kinds.split('+')):
                if kind == 'missing':
                    continue
                name,args=({'bad':('fill',{'bid':'1'}),'wait':('noop',{'wait_ms':0}),
                            'finish':('send_msg_to_user',{'text':'Done'})}[kind])
                call=response(name,args)['choices'][0]['message']['tool_calls'][0]
                call['id']=f'call-{len(requests)}-{ordinal}';calls.append(call)
            raw=response();raw['choices'][0]['message']['tool_calls']=calls
            return httpx.Response(200,json=raw)
        backend=ChatCompletionsBackend('https://test.invalid/v1','mock');backend.client.close()
        backend.client=httpx.Client(transport=httpx.MockTransport(transport));self.addCleanup(backend.close)
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.enter_context(patch('intent_browser.runner.observation_text',side_effect=lambda o:o['axtree_object']['nodes'][0]['name']['value']))
            stack.enter_context(patch('intent_browser.harness.flatten_axtree_to_str',side_effect=lambda o:o['nodes'][0]['name']['value']))
            stack.enter_context(patch('intent_browser.runner.refresh_observation',side_effect=lambda e:e.obs()))
            stack.enter_context(patch('intent_browser.batching.document_signature',return_value=[]))
            profile=native_tools_profile()
            profile=replace(profile,tools=replace(profile.tools,batch_size=4),feedback_factory=SemanticFeedback)
            path,summary=run_episode(lambda _:env,backend,{},tmp,max_steps=max_steps,harness_profile=profile,
                retry_policy=DecisionRetryPolicy(scope=scope))
            rows=[json.loads(s) for s in (path/'steps.jsonl').read_text().splitlines()]
        return summary,rows,requests,actions
    def test_allowance_replenishes_and_entire_invalid_batch_skipped(self):
        summary,rows,requests,actions=self.episode(['wait+bad','wait','bad','finish'])
        self.assertIsNone(summary['error']);self.assertEqual(summary['decision_retry_count'],0)
        self.assertEqual(len(requests),4);self.assertEqual(len(actions),2)
        self.assertEqual([r['batch_stop_reason'] for r in rows if r.get('batch_stop_reason')=='invalid_tool_arguments'],['invalid_tool_arguments','invalid_tool_arguments'])
        self.assertEqual(rows[0]['model_response']['choices'][0]['message']['tool_calls'][0]['function']['name'],'noop')
        self.assertEqual(rows[0]['batch_calls'][1]['policy_feedback']['reason'],'invalid_tool_arguments')
        self.assertIn('value',rows[0]['batch_calls'][1]['policy_feedback']['argument_error']['requirement'])
        for a,b in zip(requests,requests[1:]):
            self.assertEqual(a['tools'],b['tools']);self.assertEqual(a['messages'],b['messages'][:len(a['messages'])])
        self.assertTrue(all(x['confirmed'] for x in rows[1]['policy_delivery']['items']))
    def test_consecutive_argument_errors_allow_fresh_valid_response(self):
        summary,rows,requests,actions=self.episode(['bad','bad','finish'])
        self.assertIsNone(summary['error']);self.assertEqual(len(requests),3);self.assertEqual(len(actions),1)
        self.assertEqual(summary['decision_retry_count'],0)
        self.assertTrue(all(row['batch_stop_reason']=='invalid_tool_arguments' for row in rows[:2]))
    def test_argument_feedback_does_not_consume_transport_retry_allowance(self):
        summary,rows,requests,actions=self.episode(['bad','wait','bad','finish'],scope='episode')
        self.assertIsNone(summary['error']);self.assertEqual(len(requests),4);self.assertEqual(len(actions),2)
        self.assertEqual(summary['decision_retry_count'],0)
    def test_final_call_exhaustion_has_no_extra_request(self):
        summary,rows,requests,actions=self.episode(['bad'],max_steps=1)
        self.assertIsNone(summary['error']);self.assertEqual(summary['stop_reason'],'max_steps')
        self.assertEqual(len(requests),1);self.assertEqual(actions,[])
        self.assertEqual(summary['decision_retry_count'],0)
    def test_true_failure_chain_still_stops_after_second_missing_response(self):
        summary,rows,requests,actions=self.episode(['missing','missing','finish'])
        self.assertEqual(summary['stop_reason'],'error')
        self.assertEqual(rows[-1]['decision_retry_unavailable']['reason'],'failure_chain_limit')
        self.assertEqual(len(requests),2);self.assertEqual(actions,[])
    def test_true_missing_response_at_final_call_has_no_hidden_retry(self):
        summary,rows,requests,actions=self.episode(['missing'],max_steps=1)
        self.assertEqual(summary['stop_reason'],'error')
        self.assertEqual(rows[-1]['decision_retry_unavailable']['reason'],'episode_call_limit')
        self.assertEqual(len(requests),1);self.assertEqual(actions,[])
    def test_argument_rejection_does_not_reset_unresolved_failure_chain(self):
        summary,rows,requests,actions=self.episode(['missing','bad','missing','finish'])
        self.assertEqual(summary['stop_reason'],'error')
        self.assertEqual(rows[-1]['decision_retry_unavailable']['reason'],'failure_chain_limit')
        self.assertEqual(len(requests),3);self.assertEqual(actions,[])
    def test_uncertain_executed_action_is_not_replayed(self):
        summary,rows,requests,actions=self.episode(['wait','finish'],fail_action=True)
        self.assertIsNotNone(summary['error']);self.assertEqual(len(requests),1);self.assertEqual(len(actions),1)
        self.assertEqual(summary['decision_retry_count'],0)

if __name__=='__main__':unittest.main()
