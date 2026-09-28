from copy import deepcopy
from dataclasses import replace
import json
import tempfile
import unittest
from unittest.mock import patch
import httpx
import numpy as np
from intent_browser.input_budget import OpaqueReasoningInputCounter, QwenInputCounter
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.runner import run_episode
from intent_browser.harness import native_tools_profile, SemanticFeedback
from tests.test_native_tools import response
from tests.test_ax_explorer import TOKENIZER

BLOCK={'type':'reasoning.encrypted','data':'synthetic-opaque-payload','format':'google-gemini-v1','id':'call-1','index':0}
BASE=[{'role':'system','content':'You are helpful.'},{'role':'user','content':'Inspect then finish.'}]

def completion(name='noop',args=None,*,usage=True):
    raw=response(name,args or {},'call-1');raw['id']='response-1'
    raw['choices'][0]['message']['reasoning_details']=[deepcopy(BLOCK)]
    if usage:raw['usage']={'prompt_tokens':1200,'completion_tokens':100,'completion_tokens_details':{'reasoning_tokens':40}}
    return raw

def next_messages(raw):
    return BASE+[deepcopy(raw['choices'][0]['message']),{'role':'tool','tool_call_id':'call-1','content':'Page unchanged.'}]

class CounterTests(unittest.TestCase):
    def counter(self):return OpaqueReasoningInputCounter(QwenInputCounter(TOKENIZER))
    def test_plain_default_exact_and_opaque_preserved_with_usage_anchor(self):
        c=self.counter();self.assertEqual(c(BASE,[]),QwenInputCounter(TOKENIZER)(BASE,[]))
        raw=completion();req={'messages':deepcopy(BASE),'tools':[]};prior=deepcopy(raw)
        c.observe_completion(req,raw);messages=next_messages(raw);original=deepcopy(messages)
        result=c(messages,[])
        self.assertEqual(messages,original);self.assertEqual(raw,prior)
        self.assertEqual(result['retained_hidden_tokens_estimate'],40)
        self.assertEqual(result['provider_anchor']['prompt_tokens'],1200)
        self.assertGreater(result['input_tokens'],1200)
        self.assertFalse(result['exact_provider_tokens'])
        self.assertNotIn(BLOCK['data'],json.dumps(result))
    def test_completion_fallback_and_mixed_plaintext(self):
        c=self.counter();raw=completion();raw['usage'].pop('completion_tokens_details')
        raw['choices'][0]['message']['reasoning_details'].append({'type':'reasoning.text','text':'Visible plan.'})
        c.observe_completion({'messages':BASE},raw);r=c(next_messages(raw),[])
        self.assertEqual(r['retained_hidden_tokens_estimate'],100)
        self.assertEqual(r['opaque_usage_evidence'][0]['basis'],'reported_completion_tokens_upper_estimate')
    def test_no_origin_or_changed_block_fails_closed(self):
        c=self.counter();raw=completion();messages=next_messages(raw)
        with self.assertRaisesRegex(ValueError,'matching provider usage'):c(messages,[])
        c.observe_completion({'messages':BASE},raw)
        messages[2]['reasoning_details'][0]['data']='changed'
        with self.assertRaisesRegex(ValueError,'matching provider usage'):c(messages,[])
    def test_removed_history_and_changed_prefix_do_not_accumulate(self):
        c=self.counter();c(BASE,[]);raw=completion();c.observe_completion({'messages':BASE},raw)
        messages=next_messages(raw);first=c(messages,[]);again=c(messages,[])
        self.assertEqual(first,again)
        messages[0]['content']='New system';r=c(messages,[])
        self.assertIsNone(r['provider_anchor']);self.assertEqual(r['input_tokens'],r['visible_input_tokens']+40)
        self.assertEqual(c(BASE,[]),QwenInputCounter(TOKENIZER)(BASE,[]))
    def test_multiple_blocks_one_charge_and_duplicate_retained_message_two_charges(self):
        c=self.counter();raw=completion();raw['choices'][0]['message']['reasoning_details'].append({**BLOCK,'data':'second'})
        c.observe_completion({'messages':BASE},raw);messages=next_messages(raw)
        self.assertEqual(c(messages,[])['retained_hidden_tokens_estimate'],40)
        self.assertEqual(c(messages+deepcopy(messages[2:]),[])['retained_hidden_tokens_estimate'],80)
    def test_missing_usage_only_blocks_next_input(self):
        c=self.counter();raw=completion(usage=False);c.observe_completion({'messages':BASE},raw)
        with self.assertRaisesRegex(ValueError,'matching provider usage'):c(next_messages(raw),[])
    def test_bad_usage_not_trusted(self):
        for value in [-2,True,1.5,'40']:
            with self.subTest(value=value):
                c=self.counter();raw=completion();raw['usage']={'completion_tokens':value}
                c.observe_completion({'messages':BASE},raw)
                with self.assertRaises(ValueError):c(next_messages(raw),[])

class RunnerTests(unittest.TestCase):
    def run_case(self,*,limit=100000,usage=True,terminal_first=False):
        requests=[];actions=[]
        class Env:
            def obs(self):return {'goal':'Inspect','url':'http://fixture/','last_action_error':'',
                'axtree_object':{'nodes':[{'nodeId':'1','role':{'value':'StaticText'},'name':{'value':'[1] button Inspect'}}]},'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self,seed):return self.obs(),{}
            def step(self,action):actions.append(action);return self.obs(),0,False,False,{}
            def close(self):pass
        def transport(req):
            requests.append(json.loads(req.content));n=len(requests)
            raw=completion('send_msg_to_user',{'text':'Done'},usage=usage) if terminal_first else completion(usage=usage)
            if n==2:
                raw=response('send_msg_to_user',{'text':'Done'},'call-2');raw['usage']={'prompt_tokens':1500,'completion_tokens':10}
            return httpx.Response(200,json=raw)
        backend=ChatCompletionsBackend('https://fixture.invalid','google/gemini-3.8-flash')
        backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport));self.addCleanup(backend.close)
        with tempfile.TemporaryDirectory() as tmp,patch('intent_browser.runner.observation_text',side_effect=lambda o:o['axtree_object']['nodes'][0]['name']['value']),patch('intent_browser.harness.flatten_axtree_to_str',side_effect=lambda x:x['nodes'][0]['name']['value']):
            path,summary=run_episode(lambda _:Env(),backend,{},tmp,max_steps=3,
                harness_profile=replace(native_tools_profile(),feedback_factory=SemanticFeedback),
                max_input_tokens=limit,input_counter=OpaqueReasoningInputCounter(QwenInputCounter(TOKENIZER)))
            rows=[json.loads(line) for line in (path/'steps.jsonl').read_text().splitlines()]
        return summary,rows,requests,actions
    def test_second_request_keeps_exact_encrypted_block_and_prefix(self):
        summary,rows,requests,actions=self.run_case()
        self.assertIsNone(summary['error']);self.assertEqual(len(requests),2)
        assistant=next(m for m in requests[1]['messages'] if m['role']=='assistant')
        self.assertEqual(assistant['reasoning_details'],[BLOCK])
        self.assertEqual(requests[1]['messages'][:len(requests[0]['messages'])],requests[0]['messages'])
        self.assertEqual(requests[0]['tools'],requests[1]['tools'])
        self.assertEqual(rows[1]['input_budget']['retained_hidden_tokens_estimate'],40)
    def test_limit_still_blocks_before_next_request(self):
        # First local tool definition input is larger than 1200; make a native anchor larger.
        # Use actual implementation; a larger provider anchor is supplied through completion.
        base=completion
        def large(*args,**kwargs):
            raw=base(*args,**kwargs)
            if 'usage' in raw:raw['usage']['prompt_tokens']=200000
            return raw
        with patch(__name__+'.completion',side_effect=large):summary,rows,requests,actions=self.run_case()
        self.assertEqual(summary['stop_reason'],'max_input_tokens');self.assertEqual(len(requests),1)
        self.assertIsNone(summary['error']);self.assertTrue(rows[1]['model_dispatch_skipped'])
    def test_last_answer_not_failed_for_missing_usage(self):
        summary,rows,requests,actions=self.run_case(usage=False,terminal_first=True)
        self.assertEqual(summary['stop_reason'],'agent_finished');self.assertIsNone(summary['error'])
        self.assertEqual(len(requests),1)

if __name__=='__main__':unittest.main()
