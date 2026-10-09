import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch
import httpx
import numpy as np
from jsonschema import Draft202012Validator, ValidationError
from intent_browser.backend import ChatCompletionsBackend, BackendResponseError
from intent_browser.harness import native_tools_profile, SemanticFeedback
from intent_browser.retry_policy import DecisionRetryPolicy, retry_after_seconds, argument_diagnostic
from intent_browser.native_tools import NativeBrowserTools
from tests.test_native_tools import response, completion
from tests.runner_diagnostics import run_episode


def reply(bad=False, reason='tool_calls'):
    message={'role':'assistant','content':None,'reasoning':'Retained synthetic plan'}
    if not bad:
        message['tool_calls']=[{'id':'finish-1','type':'function','function':{'name':'send_msg_to_user','arguments':'{"text":"Done"}'}}]
    return {'id':'offline-test','choices':[{'finish_reason':reason,'message':message}],'usage':{'cost':0.001}}


class DecisionRetryTests(unittest.TestCase):
    def run_case(self,case='missing',max_steps=3,enabled=True):
        order=[];requests=[]
        class Env:
            count=0;fresh=0
            def obs(self):return {'goal':'Finish','url':'http://fixture/','last_action_error':'',
                'axtree_object':{'nodes':[{'nodeId':'1','role':{'value':'StaticText'},'name':{'value':f'[1] button fresh-{self.fresh}'}}]},'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self,seed):return self.obs(),{}
            def step(self,action):
                order.append('action');self.count+=1
                if case=='browser_failure':raise TimeoutError('Click may have taken effect')
                return self.obs(),0,False,False,{}
            def close(self):order.append('close')
        env=Env()
        def transport(req):
            order.append('request');requests.append(json.loads(req.content));n=len(requests)
            if n==1 and case=='429':return httpx.Response(429,json={'error':{'code':429}},headers={'Retry-After':'7'})
            if n==1 and case=='long_wait':return httpx.Response(503,json={'error':{'code':503}},headers={'Retry-After':'120'})
            if n==1 and case=='401':return httpx.Response(401,json={'error':{'code':401}})
            if n==1 and case=='timeout':raise httpx.ReadTimeout('No response',request=req)
            raw=reply((n==1 or case=='twice') and case!='browser_failure')
            if case=='length':raw=reply(True,'length')
            if case=='refusal':raw['choices'][0]['message']['refusal']='No'
            if case=='multiple' and n==1:
                raw=reply();raw['choices'][0]['message']['tool_calls']*=2
            if case=='bad_options' and n==1:
                raw=response('select_option', {'bid':'1','options':50})
            if case=='invalid_json' and n==1:
                raw=reply();raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"text":'
            return httpx.Response(200,json=raw)
        class BudgetBackend(ChatCompletionsBackend):
            supports_native_tools=True
            calls=0
            def complete(self,messages):
                self.calls+=1
                if self.calls==2 and case=='budget':
                    raise ValueError('Budget exhausted before dispatch')
                return super().complete(messages)
        backend=BudgetBackend('https://example.test/v1','mock');backend.client.close()
        backend.client=httpx.Client(transport=httpx.MockTransport(transport));self.addCleanup(backend.close)
        def wait():order.append('pacing');return {'test':True}
        def fresh(e):order.append('fresh');e.fresh+=1;return e.obs()
        def sleep(n):order.append('sleep:'+str(n))
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        with patch('intent_browser.runner.observation_text',side_effect=lambda o:o['axtree_object']['nodes'][0]['name']['value']),patch('intent_browser.harness.flatten_axtree_to_str',side_effect=lambda x:x['nodes'][0]['name']['value']),patch('intent_browser.runner.refresh_observation',side_effect=fresh),patch('intent_browser.runner.time.sleep',side_effect=sleep):
            path,summary=run_episode(lambda _:env,backend,{},temp.name,max_steps=max_steps,harness_profile=replace(native_tools_profile(),feedback_factory=SemanticFeedback),before_observation=wait,retry_policy=DecisionRetryPolicy() if enabled else None)
        rows=[json.loads(x) for x in (path/'steps.jsonl').read_text().splitlines()]
        return env,requests,rows,summary,order

    def test_missing_call_recovers_without_losing_response_reasoning_or_prefix(self):
        env,reqs,rows,summary,order=self.run_case()
        self.assertIsNone(summary['error']);self.assertEqual(summary['decision_retry_count'],1)
        self.assertEqual(env.count,1);self.assertEqual(len(reqs),2)
        self.assertIn('Expected exactly one',rows[0]['error']);self.assertNotIn('tool_calls',rows[0]['model_response']['choices'][0]['message'])
        self.assertEqual(reqs[1]['messages'][:len(reqs[0]['messages'])],reqs[0]['messages'])
        self.assertEqual(reqs[0]['tools'],reqs[1]['tools']);self.assertEqual(reqs[1]['messages'][-2]['reasoning'],'Retained synthetic plan')
        self.assertIn('HARNESS RECOVERY NOTICE',reqs[1]['messages'][-1]['content']);self.assertIn('fresh-2',reqs[1]['messages'][-1]['content'])
        self.assertEqual(rows[1]['retry_of_step'],0);self.assertEqual(order,['pacing','fresh','request','pacing','fresh','request','action','close'])
        self.assertTrue(all(item['confirmed'] for item in rows[1]['policy_delivery']['items']))

    def test_multiple_calls_are_not_partially_executed_or_resent_as_live_calls(self):
        env,reqs,rows,s,_=self.run_case('multiple');self.assertIsNone(s['error']);self.assertEqual(env.count,1)
        prior=reqs[1]['messages'][-2];self.assertNotIn('tool_calls',prior);self.assertIn('Rejected, unexecuted',prior['content'])
        self.assertEqual(len(rows[0]['model_response']['choices'][0]['message']['tool_calls']),2)

    def test_exact_argument_diagnostic_reaches_next_request_and_trace(self):
        for case in ('bad_options','invalid_json'):
            with self.subTest(case=case):
                env,reqs,rows,s,_=self.run_case(case)
                self.assertIsNone(s['error']);self.assertEqual(env.count,1)
                self.assertEqual(len(reqs),2);self.assertEqual(s['decision_retry_count'],0)
                notice=reqs[1]['messages'][-1]['content']
                diagnostic=rows[0]['batch_calls'][0]['policy_feedback']['argument_error']
                self.assertIn(json.dumps(diagnostic,ensure_ascii=False,sort_keys=True),notice)
                self.assertIn('Correct the identified arguments',notice)
                self.assertEqual(reqs[0]['tools'],reqs[1]['tools'])
                self.assertEqual(reqs[1]['messages'][:len(reqs[0]['messages'])],reqs[0]['messages'])
                if case=='bad_options':
                    self.assertEqual(diagnostic['parameter'],'/options')
                    self.assertEqual(diagnostic['received_type'],'integer')
                    self.assertIn('string or array of string',diagnostic['requirement'])
                else:self.assertEqual(diagnostic['problem'],'Arguments are not valid JSON')

    def test_backoff_before_fresh_observation_and_retained_http_failure(self):
        _,reqs,rows,s,order=self.run_case('429');self.assertIsNone(s['error']);self.assertEqual(rows[0]['model_error_http_status'],429)
        self.assertEqual(rows[0]['model_error_retry_after'],'7');self.assertEqual(order[3:6],['sleep:7.0','pacing','fresh'])
        self.assertEqual(len(reqs),2)

    def test_transport_unknown_response_is_retained_not_faked(self):
        _,reqs,rows,s,_=self.run_case('timeout');self.assertIsNone(s['error']);self.assertIsNone(rows[0]['model_response'])
        self.assertEqual(rows[0]['model_request'],reqs[0]);self.assertEqual(len(reqs),2)

    def test_stop_boundaries(self):
        for case,count in [('twice',2),('length',1),('refusal',1),('401',1),('long_wait',1),('browser_failure',1),('budget',1)]:
            with self.subTest(case=case):
                env,reqs,rows,s,order=self.run_case(case)
                self.assertIsNotNone(s['error']);self.assertEqual(len(reqs),count)
                if case!='browser_failure':self.assertEqual(env.count,0)
        _,reqs,_,s,_=self.run_case(max_steps=1);self.assertEqual(len(reqs),1);self.assertEqual(s['decision_retry_count'],0)
        _,reqs,_,s,_=self.run_case(enabled=False);self.assertEqual(len(reqs),1);self.assertNotIn('decision_retry_count',s)

    def test_policy_does_not_retry_cancellation_or_unrelated_errors(self):
        policy=DecisionRetryPolicy()
        for exc,phase in [(KeyboardInterrupt(),'model'),(ValueError('budget'),'model'),(TimeoutError(),'browser_step')]:
            self.assertIsNone(policy.select(exc,phase,{},used=0,remaining_calls=2))
        self.assertIsNone(retry_after_seconds('NaN'));self.assertEqual(retry_after_seconds('12'),12)
        for value in [-1,2,True]:
            with self.assertRaises(ValueError):DecisionRetryPolicy(max_retries=value)


class ArgumentDiagnosticTests(unittest.TestCase):
    def test_both_saved_failure_shapes_against_actual_tool_schemas(self):
        tools=NativeBrowserTools(ax_tools=True,incremental_ax=True)
        for name,args,path,requirement in [
            ('select_option',{'bid':'1276','options':50},'/options','string or array of string'),
            ('ax_read',{'node_ref':'d8n106','view':'subtree','depth':6,'limit':60},'/limit','maximum is 50'),
        ]:
            with self.subTest(tool=name):
                raw=response(name,args)
                with self.assertRaises(ValidationError) as caught:
                    tools.parse_completion(completion(raw))
                selected=DecisionRetryPolicy().select(caught.exception,'action_parse',
                    {'model_response':raw},used=0,remaining_calls=1)
                d=selected['argument_diagnostic']
                self.assertEqual(d['parameter'],path)
                self.assertIn(requirement,d['requirement'])
                self.assertIsNone(DecisionRetryPolicy().select(caught.exception,'action_parse',
                    {'model_response':raw},used=1,remaining_calls=1))

    def test_nested_paths_unknown_constraints_and_no_raw_value_echo(self):
        schema={'type':'object','properties':{'items':{'type':'array','items':{
            'type':'object','properties':{'a/b~c':{'type':'integer'}}}}}}
        value={'items':[{'a/b~c':'PRIVATE-VALUE'*10000}]}
        exc=next(Draft202012Validator(schema).iter_errors(value))
        d=argument_diagnostic(exc)
        self.assertEqual(d['parameter'],'/items/0/a~1b~0c')
        self.assertNotIn('PRIVATE-VALUE',json.dumps(d));self.assertLess(len(json.dumps(d)),600)
        exc=next(Draft202012Validator({'pattern':'^expected$'}).iter_errors('PRIVATE-VALUE'))
        self.assertIn('Check this parameter',argument_diagnostic(exc)['requirement'])
        self.assertIsNone(argument_diagnostic(RuntimeError('not a validator error')))

if __name__=='__main__':unittest.main()
