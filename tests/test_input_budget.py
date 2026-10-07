import base64
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from intent_browser.backend import Completion
from intent_browser.input_budget import QwenInputCounter, DEFAULT_MAX_STEPS, DEFAULT_MAX_INPUT_TOKENS
from intent_browser.harness import native_tools_profile, SemanticFeedback
from tests.runner_diagnostics import run_episode
from intent_browser.delegation import AgentLimits
from intent_browser.evaluation import Evaluation
from tests.test_ax_explorer import TOKENIZER
from tests.test_native_tools import response


class InputLimitTests(unittest.TestCase):
    def run_case(self, counts, limit=100000, *, done_first=False, terminated=False, graded=False):
        actions=[];requests=[];measurements=[]
        class Env:
            def obs(self): return {'goal':'Inspect', 'url':'http://fixture/', 'last_action_error':'',
                'axtree_object':{'nodes':[{'nodeId':'1','role':{'value':'StaticText'},'name':{'value':'[1] button Inspect'}}]}, 'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self,seed): return self.obs(),{}
            def step(self,action): actions.append(action);return self.obs(),int(terminated),terminated,False,{}
            def close(self): pass
        class Task:
            supported_harness_profiles=(native_tools_profile().name,)
            def prepare(self,trace): return {}
            def capture_initial(self,*args): return {}
            def evaluate(self,env,trace,outcome):
                return Evaluation('offline-test','1',task_completed=bool(actions),
                                  authorization_satisfied=True,unauthorized_effects=[])
        class Backend:
            def configure_tools(self,options): self.options=options
            def complete(self,messages):
                requests.append(deepcopy(messages));n=len(requests)
                raw=response('noop',{},f'call-{n}') if n==1 and not done_first else response('send_msg_to_user',{'text':'Done'},f'call-{n}')
                raw['usage']={'prompt_tokens':10,'completion_tokens':999999,'total_tokens':1000009}
                return Completion('',raw,{'messages':messages,**self.options})
        def counter(messages,tools):
            self.assertTrue(tools);self.assertTrue(any(m['role']=='system' for m in messages))
            self.assertIn('CURRENT BROWSER OBSERVATION',messages[-1]['content'])
            count=counts[len(measurements)];measurements.append(count)
            return {'input_tokens':count,'method':'offline-deterministic-test'}
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        with patch('intent_browser.runner.observation_text',side_effect=lambda o:o['axtree_object']['nodes'][0]['name']['value']), \
             patch('intent_browser.harness.flatten_axtree_to_str',side_effect=lambda o:o['nodes'][0]['name']['value']):
            p,s=run_episode(lambda _:Env(),Backend(),{},temp.name,max_steps=200,
                harness_profile=replace(native_tools_profile(),feedback_factory=SemanticFeedback),
                max_input_tokens=limit,input_counter=counter,episode_task=Task() if graded else None)
        rows=[json.loads(l) for l in (p/'steps.jsonl').read_text().splitlines()]
        return s,rows,actions,requests,p

    def test_over_limit_first_prompt_never_dispatches_or_executes(self):
        s,rows,actions,requests,p=self.run_case([100001])
        self.assertEqual(s['stop_reason'],'max_input_tokens');self.assertTrue(s['truncated'])
        self.assertIsNone(s['error']);self.assertEqual(requests,[]);self.assertEqual(actions,[])
        self.assertIsNone(rows[0]['model_request']);self.assertTrue(rows[0]['model_dispatch_skipped'])
        self.assertNotIn('policy_delivery',rows[0])
        self.assertEqual(json.loads((p/'metadata.json').read_text())['max_input_tokens'],100000)

    def test_equality_allowed_then_next_input_checked_without_cumulative_or_output_cap(self):
        s,rows,actions,requests,p=self.run_case([100000,100001])
        self.assertEqual(len(requests),1);self.assertEqual(len(actions),1)
        self.assertEqual(s['stop_reason'],'max_input_tokens')
        self.assertEqual(rows[0]['model_response']['usage']['completion_tokens'],999999)
        self.assertTrue(rows[1]['input_budget']['exceeded'])
        events=[json.loads(l)['event'] for l in (p/'events.jsonl').read_text().splitlines()]
        self.assertEqual(events.count('model_started'),1)
        self.assertLess(events.index('evaluation_completed'),events.index('environment_close_started'))
        s,_,actions,requests,_=self.run_case([60000,60000])
        self.assertEqual(s['stop_reason'],'agent_finished');self.assertEqual(len(requests),2)

    def test_guard_defaults_and_invalid_counter(self):
        self.assertEqual(DEFAULT_MAX_STEPS,200);self.assertEqual(AgentLimits().total_model_calls,200)
        self.assertEqual(DEFAULT_MAX_INPUT_TOKENS,100000)
        s,_,_,requests,_=self.run_case([True])
        self.assertIn('nonnegative',s['error']);self.assertEqual(requests,[])

    def test_completion_does_not_trigger_another_input_check(self):
        # No second count exists: a post-completion check would fail this test.
        # The fake response also contains 999999 output tokens, intentionally
        # larger than the input ceiling; these must never turn success to failure.
        for options,reason in [({'done_first':True},'agent_finished'),
                               ({'terminated':True},'terminated')]:
            with self.subTest(reason=reason):
                s,rows,actions,requests,path=self.run_case([100000],graded=True,**options)
                self.assertEqual(s['stop_reason'],reason)
                self.assertFalse(s['truncated']);self.assertIsNone(s['error'])
                self.assertTrue(json.loads((path/'evaluation-before-close.json').read_text())['safe_success'])
                self.assertEqual(len(rows),1);self.assertEqual(len(requests),1)

    def test_next_input_limit_preserves_already_completed_verifier_result(self):
        s,rows,actions,requests,p=self.run_case([100000,100001],graded=True)
        self.assertEqual(s['stop_reason'],'max_input_tokens')
        record=json.loads((p/'evaluation-before-close.json').read_text())
        self.assertTrue(record['task_completed'])
        self.assertTrue(record['safe_success'])
        self.assertIsNone(s['evaluation']['technical_error'])
        self.assertEqual(len(requests),1)


@unittest.skipUnless(TOKENIZER.with_name('chat_template.jinja').is_file(),'Local Qwen assets required')
class LocalCounterTests(unittest.TestCase):
    def test_tools_reasoning_and_images_count_without_mutating_request(self):
        counter=QwenInputCounter(TOKENIZER)
        messages=[{'role':'system','content':'Inspect'},{'role':'user','content':'Find the room'}]
        tools=native_tools_profile().tools.definitions()
        plain=counter(messages,[])['input_tokens'];with_tools=counter(messages,tools)['input_tokens']
        self.assertGreater(with_tools,plain)
        messages += [{'role':'assistant','content':None,'reasoning_details':[{'type':'reasoning.text','text':'Inspect carefully. '*30}],
                      'tool_calls':[{'id':'a','type':'function','function':{'name':'noop','arguments':'{}'}}]},
                     {'role':'tool','tool_call_id':'a','content':'Page unchanged'}]
        original=deepcopy(messages);a=counter(messages,tools)
        self.assertEqual(messages,original);self.assertGreater(a['input_tokens'],with_tools)
        output=BytesIO();Image.new('RGB',(1000,850)).save(output,format='PNG')
        messages[-1]['content']=[{'type':'text','text':'Page unchanged'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()}}]
        b=counter(messages,tools)
        self.assertEqual(b['images'],1)
        self.assertGreaterEqual(b['input_tokens']-a['input_tokens'],837)
        self.assertLess(b['input_tokens']-a['input_tokens'],850)
        messages[2]['reasoning_details']=[{'type':'reasoning.encrypted','data':'opaque'}]
        with self.assertRaisesRegex(ValueError,'opaque'):counter(messages,tools)

if __name__=='__main__':unittest.main()
