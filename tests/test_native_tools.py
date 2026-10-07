import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import httpx
import numpy as np
from jsonschema import ValidationError

from intent_browser.backend import ChatCompletionsBackend, Completion, BackendResponseError
from intent_browser.harness import native_tools_profile, SemanticFeedback
from intent_browser.native_tools import NativeBrowserTools, NativeConversation
from tests.runner_diagnostics import run_episode
from intent_browser.search import ParallelSearch


def response(name='click', arguments=None, call_id='call-1'):
    return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
        'tool_calls':[{'id':call_id,'type':'function','function':{'name':name,
            'arguments':json.dumps({'bid':'1'} if arguments is None else arguments)}}]}}]}


def completion(raw):return Completion((raw['choices'][0]['message'].get('content') or ''),raw)


class NativeToolsTests(unittest.TestCase):
    def test_initial_and_later_updates_share_exact_bound_message_spans(self):
        c=NativeConversation()
        c.initialize('System','Goal')
        c.add_evidence({'notice':'Before first request'},source_id='initial-update')
        first=c.request('System','Goal','Initial page',observation_source='initial-page')
        self.assertEqual([m['role'] for m in first],['system','user'])
        self.assertIn('Before first request',first[-1]['content'])
        _,assistant=NativeBrowserTools().parse_completion(completion(response()))
        feedback={'execution':'call_completed','text':'Transient receipt'}
        c.record('',feedback,feedback_source='feedback',assistant_message=assistant)
        self.assertNotIn('feedback',[b['content_id'] for b in c.bindings()])
        assistant['tool_calls'][0]['id']='caller mutation'
        feedback['text']='caller mutation'
        c.add_evidence({'notice':'Arrived during wait'},source_id='delayed-update')
        second=c.request('System','Goal','Fresh page','\nSearch calls remaining: 2',observation_source='fresh-page')
        self.assertEqual([m['role'] for m in second],['system','user','assistant','tool'])
        self.assertEqual(second[:len(first)],first)
        self.assertEqual(second[-1]['tool_call_id'],'call-1')
        self.assertEqual(second[-1]['content'].count('Fresh page'),1)
        expected={'initial-update':json.dumps({'notice':'Before first request'},sort_keys=True),
                  'initial-page':'Initial page',
                  'feedback':json.dumps({'execution':'call_completed','text':'Transient receipt'},sort_keys=True),
                  'delayed-update':json.dumps({'notice':'Arrived during wait'},sort_keys=True),
                  'fresh-page':'Fresh page'}
        for binding in c.bindings():
            self.assertEqual(second[binding['message_index']]['content'][binding['start']:binding['end']],
                             expected[binding['content_id']])
        self.assertEqual(native_tools_profile().describe()['conversation_layout'],'tool-result-observation-v1')
        with self.assertRaisesRegex(ValueError,'preceding tool result'):
            c.request('System','Goal','Must not create another user message')
        with self.assertRaisesRegex(ValueError,'silently change'):
            c.request('Changed system','Goal','Page')

    def test_reasoning_representations_retained_without_duplicate_plain_projection(self):
        details=[{'type':'reasoning.text','text':'Synthetic plan','signature':'sig','index':0},
                 {'type':'reasoning.encrypted','data':'opaque-fixture','index':1}]
        cases=[({'reasoning_details':details,'reasoning':'Synthetic plan'}, {'reasoning_details':details}),
               ({'reasoning':'Synthetic plan'}, {'reasoning':'Synthetic plan'}),
               ({'reasoning_content':'Local synthetic plan'}, {'reasoning_content':'Local synthetic plan'}),
               ({'reasoning_details':[],'reasoning':'Fallback'}, {'reasoning':'Fallback'}),
               ({'reasoning_details':None,'reasoning':None}, {})]
        for fields,expected in cases:
            with self.subTest(fields=fields):
                raw=response();raw['choices'][0]['message'].update(deepcopy(fields),content='Public note')
                original=deepcopy(raw)
                _,message=NativeBrowserTools().parse_completion(completion(raw))
                self.assertEqual({k:v for k,v in message.items() if k.startswith('reasoning')},expected)
                self.assertEqual(message['content'],'Public note')
                _,stripped=NativeBrowserTools(reasoning_replay='strip').parse_completion(completion(raw))
                self.assertEqual(stripped,{k:v for k,v in message.items() if not k.startswith('reasoning')})
                if 'reasoning_details' in message:message['reasoning_details'][0]['text']='mutated'
                self.assertEqual(raw,original)
        self.assertEqual(native_tools_profile().describe()['reasoning_replay'],'preserve')
        self.assertEqual(native_tools_profile(reasoning_replay='strip').describe()['reasoning_replay'],'strip')
        with self.assertRaises(ValueError):NativeBrowserTools(reasoning_replay='guess')

    def test_malformed_reasoning_fails_before_action_not_silently_stripped(self):
        for fields in ({'reasoning_details':'invalid'},{'reasoning_details':[1]}, {'reasoning':{}}):
            raw=response();raw['choices'][0]['message'].update(fields)
            with self.assertRaises(ValueError):NativeBrowserTools().parse_completion(completion(raw))

    def test_all_prior_reasoning_survives_exact_http_requests_and_prefixes(self):
        for policy in ('preserve','strip'):
            with self.subTest(policy=policy):
                sent=[];raws=[]
                def transport(req):
                    sent.append(json.loads(req.content));i=len(sent)
                    raw=response(call_id=f'call-{i}')
                    raw['choices'][0]['message']['reasoning_details']=[
                        {'type':'reasoning.text','text':f'Synthetic plan {i}','index':0}]
                    raws.append(deepcopy(raw))
                    return httpx.Response(200,json=raw)
                backend=ChatCompletionsBackend('https://example.test/v1','mock')
                self.addCleanup(backend.close);backend.client.close()
                backend.client=httpx.Client(transport=httpx.MockTransport(transport))
                tools=NativeBrowserTools(reasoning_replay=policy)
                backend.configure_tools(tools.request_options());conversation=NativeConversation()
                for i in range(3):
                    messages=conversation.request('System','Goal',f'Page {i}')
                    result=backend.complete(messages)
                    _,assistant=tools.parse_completion(result)
                    conversation.record(result.text,{'execution':'call_completed'},assistant_message=assistant)
                    self.assertEqual(result.raw,raws[i])
                for i in (1,2):
                    self.assertEqual(sent[i]['messages'][:len(sent[i-1]['messages'])],sent[i-1]['messages'])
                history=[m for m in sent[-1]['messages'] if m['role']=='assistant']
                self.assertEqual(len(history),2)
                for i,message in enumerate(history):
                    if policy=='preserve':
                        self.assertEqual(message['reasoning_details'],raws[i]['choices'][0]['message']['reasoning_details'])
                    else:self.assertNotIn('reasoning_details',message)

    def test_all_primitives_and_search_map_to_validated_browser_actions(self):
        samples={'click':{'bid':'1'},'fill':{'bid':'1','value':'A\n"B'},'check':{'bid':'1'},
                 'uncheck':{'bid':'1'},'select_option':{'bid':'1','options':['a','b']},
                 'press':{'bid':'1','key_comb':'Enter'},'scroll':{'delta_x':0,'delta_y':250},
                 'noop':{},'send_msg_to_user':{'text':'Done'},'web_search':{'query':'browser tools'}}
        for name,args in samples.items():
            with self.subTest(name=name):
                decision,msg=NativeBrowserTools().parse_completion(completion(response(name,args)),allow_search=True)
                self.assertEqual(decision.name,name);self.assertEqual(decision.arguments,args)
                self.assertEqual(msg['tool_calls'][0]['id'],'call-1')

    def test_invalid_arguments_and_calls_rejected(self):
        bad=[response('unknown',{}),response('click',{'bid':123}),response('click',{'bid':'1','extra':1}),
             response('scroll',{'delta_x':True,'delta_y':0}),response('noop',{'wait_ms':10001}),
             response('check',{}),response('select_option',{'bid':'1','options':[]}),response('web_search',{'query':'x'})]
        for arg in ('{"bid":"1","bid":"2"}','{"delta_x":NaN,"delta_y":0}',
                    '{"delta_x":1e999,"delta_y":0}', '["1"]', 'not JSON'):
            raw=response('scroll' if 'delta' in arg else 'click')
            raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']=arg;bad.append(raw)
        for variant in ('multi','noid','truncated','text','refusal'):
            raw=response();m=raw['choices'][0]['message']
            if variant=='multi':m['tool_calls']*=2
            elif variant=='noid':m['tool_calls'][0]['id']=''
            elif variant=='truncated':raw['choices'][0]['finish_reason']='length'
            elif variant=='text':m.pop('tool_calls');m['content']='[{"text":"click(\'1\')"}]'
            else:m['refusal']='cannot'
            bad.append(raw)
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises((ValueError,ValidationError)):
                    NativeBrowserTools().parse_completion(completion(raw))

    def test_omitted_parallel_hint_still_rejects_batches(self):
        tools=NativeBrowserTools(parallel_tool_calls=None)
        self.assertNotIn('parallel_tool_calls',tools.request_options())
        raw=response();raw['choices'][0]['message']['tool_calls']*=2
        with self.assertRaises(ValueError):tools.parse_completion(completion(raw))
        backend=ChatCompletionsBackend('https://example.test/v1','mock')
        self.addCleanup(backend.close);backend.configure_tools(tools.request_options())
        self.assertNotIn('parallel_tool_calls',backend.request_options)
        self.assertEqual(native_tools_profile(parallel_tool_calls=None).name,'core-tools-v2')

    def test_strict_is_explicit_and_disabled_tools_rejected(self):
        tool=NativeBrowserTools(names=('click',),strict=True,choice='required')
        d=tool.request_options();self.assertEqual(d['tool_choice'],'required')
        schema=d['tools'][0]['function']['parameters']
        self.assertEqual(set(schema['required']),set(schema['properties']))
        self.assertTrue(d['tools'][0]['function']['strict'])
        with self.assertRaises(ValidationError):tool.parse_completion(completion(response()))
        with self.assertRaises(ValueError):tool.parse_completion(completion(response('noop',{})))
        tool.parse_completion(completion(response('click',{'bid':'1','button':'left','modifiers':[]})))
        self.assertNotIn('strict',NativeBrowserTools().definitions()[0]['function'])

    def test_unadopted_budget_backend_fails_before_dispatch(self):
        class BudgetBackend(ChatCompletionsBackend): pass
        backend=BudgetBackend('https://example.test/v1','mock')
        self.addCleanup(backend.close)
        with self.assertRaisesRegex(ValueError,'schema token budgeting'):
            backend.configure_tools(NativeBrowserTools().request_options())
        self.assertNotIn('tools',backend.request_options)

    def test_http_request_and_native_response_preserved(self):
        backend=ChatCompletionsBackend('https://example.test/v1','mock')
        self.addCleanup(backend.close); backend.client.close();captured=[];raw=response()
        backend.client=httpx.Client(transport=httpx.MockTransport(lambda req:
            captured.append(json.loads(req.content)) or httpx.Response(200,json=raw)))
        opts=NativeBrowserTools().request_options();backend.configure_tools(opts)
        c=backend.complete([{'role':'user','content':'Go'}])
        self.assertEqual(c.raw,raw);self.assertEqual(c.text,'');self.assertEqual(c.request,captured[0])
        for k,v in opts.items():self.assertEqual(c.request[k],v)
        opts['tools'].clear();self.assertEqual(len(c.request['tools']),9)
        with self.assertRaises(ValueError):backend.configure_tools(NativeBrowserTools(choice='required').request_options())


class NativeRunnerTests(unittest.TestCase):
    def run_case(self,case='normal'):
        class Env:
            count=0;closed=False;fresh=0
            def obs(self):return {'goal':'Click then finish','url':'http://fixture/','last_action_error':
                'pointer intercepted' if case=='action_error' and self.count else '',
                'axtree_object':{'nodes':[{'nodeId':'1','role':{'value':'StaticText'},'name':{'value':f"[1] button 'Proceed fresh {self.fresh}'"}}]},'screenshot':np.zeros((2,2,3),dtype=np.uint8),
                'privileged':'SECRET-GRADER'}
            def reset(self,seed):return self.obs(),{}
            def step(self,action):self.count+=1;return self.obs(),0,False,False,{}
            def close(self):self.closed=True
        env=Env();requests=[]
        def transport(req):
            requests.append(json.loads(req.content));i=len(requests)
            if i==2 and case=='timeout':raise httpx.ReadTimeout('unknown delivery',request=req)
            raw=response() if i==1 else response('send_msg_to_user',{'text':'Done'},'call-2')
            raw['choices'][0]['message']['reasoning']='Synthetic next-step plan'
            if case=='search' and i==1:raw=response('web_search',{'query':'fixture question'})
            if case=='duplicate' and i==2:raw['choices'][0]['message']['tool_calls'][0]['id']='call-1'
            if case=='invalid_first':raw['choices'][0]['message']['tool_calls']*=2
            return httpx.Response(200,json=raw)
        backend=ChatCompletionsBackend('https://example.test/v1','mock')
        backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport))
        self.addCleanup(backend.close)
        search=None
        if case=='search':
            search=ParallelSearch('fixture-key',transport=httpx.MockTransport(lambda req:
                httpx.Response(200,json={'results':[{'title':'Fixture','url':'https://example.test','excerpts':['Useful answer']}]})))
            self.addCleanup(search.close)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        class Updates(SemanticFeedback):
            def before_request(self,env):
                return {'notice':'During pacing'} if case=='paced' and env.count else None
        profile=replace(native_tools_profile(),feedback_factory=Updates)
        def wait():
            if case=='pacing_failure' and env.count:
                raise RuntimeError('Stopped before fresh capture')
            env.fresh+=1
            return {'offline_wait':True}
        with patch('intent_browser.runner.observation_text',side_effect=lambda o:o['axtree_object']['nodes'][0]['name']['value']), \
             patch('intent_browser.runner.refresh_observation',side_effect=lambda e:e.obs()), \
             patch('intent_browser.harness.flatten_axtree_to_str',side_effect=lambda x:x['nodes'][0]['name']['value']):
            path,summary=run_episode(lambda _:env,backend,{},tmp.name,max_steps=2,harness_profile=profile,
                                    search_backend=search,before_observation=wait if case in ('paced','pacing_failure') else None)
        rows=[json.loads(x) for x in (path/'steps.jsonl').read_text().splitlines()]
        return env,requests,rows,summary,path

    def test_native_history_feedback_and_delivery(self):
        env,reqs,rows,s,path=self.run_case()
        self.assertIsNone(s['error']);self.assertEqual(env.count,2);self.assertTrue(env.closed)
        self.assertEqual(reqs[1]['messages'][:len(reqs[0]['messages'])],reqs[0]['messages'])
        replies=[m for m in reqs[1]['messages'] if m['role']=='tool']
        self.assertEqual(len(replies),1);self.assertEqual(replies[0]['tool_call_id'],'call-1')
        self.assertIn(json.dumps(rows[0]['policy_feedback'],ensure_ascii=False,sort_keys=True),replies[0]['content'])
        self.assertEqual([m['role'] for m in reqs[1]['messages']],['system','user','assistant','tool'])
        self.assertIn('CURRENT BROWSER OBSERVATION',replies[0]['content'])
        self.assertNotIn('SECRET-GRADER',json.dumps(reqs))
        self.assertNotIn('Output exactly ONE action call',reqs[0]['messages'][0]['content'])
        self.assertTrue(all(i['confirmed'] for i in rows[1]['policy_delivery']['items']))
        self.assertEqual(rows[0]['model_output'],'');self.assertEqual(rows[0]['tool_call_id'],'call-1')
        assistant=next(m for m in reqs[1]['messages'] if m['role']=='assistant')
        self.assertEqual(assistant['reasoning'],'Synthetic next-step plan')
        self.assertEqual(json.loads((path/'metadata.json').read_text())['harness_profile']['reasoning_replay'],'preserve')

    def test_fresh_capture_after_pacing_and_update_are_in_tool_response(self):
        _,reqs,rows,s,path=self.run_case('paced')
        self.assertIsNone(s['error'])
        result=reqs[1]['messages'][-1]
        self.assertEqual(result['role'],'tool')
        self.assertIn("[1] button 'Proceed fresh 2'",result['content'])
        self.assertNotIn("[1] button 'Proceed fresh 1'",result['content'])
        self.assertIn('During pacing',result['content'])
        self.assertIn('fresh 1',(path/'observation-001.txt').read_text())
        self.assertIn('fresh 2',(path/'decision-observation-001.txt').read_text())
        delivered=rows[1]['policy_delivery']['items']
        self.assertTrue(all(i['confirmed'] for i in delivered))
        fresh=[i for i in delivered if i['first_confirmed_delivery']]
        self.assertEqual({i['kind'] for i in fresh},{'page_observation','browser_feedback','browser_update'})
        self.assertTrue(all(i['message_span']['message_index']==3 for i in fresh))

    def test_pending_result_is_retained_but_not_claimed_delivered_when_wait_fails(self):
        env,reqs,rows,s,path=self.run_case('pacing_failure')
        self.assertEqual(len(reqs),1)
        self.assertEqual(env.count,1)
        self.assertIn('Stopped before fresh capture',s['error'])
        self.assertIsNotNone(rows[0]['policy_feedback'])
        self.assertIsNone(rows[1]['model_request'])
        self.assertNotIn('policy_delivery',rows[1])
        sources=[json.loads(p.read_text()) for p in path.glob('policy-content-*.json')]
        self.assertIn('browser_feedback',[s['kind'] for s in sources])
        deliveries=[json.loads(line) for line in (path/'policy-delivery.jsonl').read_text().splitlines()]
        self.assertEqual(len(deliveries),1)
        self.assertEqual([i['kind'] for i in deliveries[0]['items']],['page_observation'])

    def test_invalid_batch_duplicate_and_timeout_do_not_replay(self):
        for case,expected in [('invalid_first',0),('duplicate',1),('timeout',1)]:
            with self.subTest(case=case):
                env,reqs,rows,s,path=self.run_case(case)
                self.assertEqual(env.count,expected);self.assertIsNotNone(s['error']);self.assertTrue(env.closed)
                if case=='timeout':
                    self.assertEqual(rows[1]['model_request'],reqs[1])
                    self.assertTrue(all(not i['confirmed'] for i in rows[1]['policy_delivery']['items']))

    def test_optional_search_uses_same_native_protocol(self):
        env,reqs,rows,s,_=self.run_case('search')
        self.assertIsNone(s['error']);self.assertEqual(env.count,1)
        self.assertEqual(s['search_request_count'],1)
        self.assertEqual(len(reqs[0]['tools']),10)
        self.assertEqual(rows[0]['kind'],'search')
        result=next(m for m in reqs[1]['messages'] if m['role']=='tool')
        self.assertEqual(result['tool_call_id'],'call-1')
        self.assertIn('Useful answer',result['content'])
        self.assertIn('search_result',[i['kind'] for i in rows[1]['policy_delivery']['items']])

    def test_browser_error_returned_as_tool_result(self):
        _,reqs,rows,s,_=self.run_case('action_error')
        self.assertIsNone(s['error'])
        result=next(m['content'] for m in reqs[1]['messages'] if m['role']=='tool')
        self.assertIn('pointer intercepted',result)

if __name__=='__main__':unittest.main()
