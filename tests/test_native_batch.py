import json
import unittest
from copy import deepcopy
from intent_browser.native_tools import NativeBrowserTools, NativeConversation
from intent_browser.backend import Completion
from intent_browser.batching import batch_events, target_signature
from intent_browser.feedback_presentation import CompactFeedback


def response(calls):
    return Completion('', {'choices':[{'finish_reason':'tool_calls','message':{
        'role':'assistant','content':None,'reasoning':'Retained plan',
        'tool_calls':[{'id':f'call-{i}','type':'function','function':{'name':n,'arguments':json.dumps(a)}}
                      for i,(n,a) in enumerate(calls)]}}]})


class BatchTests(unittest.TestCase):
    def test_all_validated_before_execution(self):
        tools=NativeBrowserTools(batch_size=8)
        for calls in ([('click',{'bid':'1'}),('fill',{'bid':'2'})],
                      [('send_msg_to_user',{'text':'Done'}),('click',{'bid':'1'})],
                      [('noop',{})]*9):
            with self.subTest(calls=calls), self.assertRaises(Exception):
                tools.parse_batch(response(calls))
        raw=response([('noop',{}),('noop',{})]);raw.raw['choices'][0]['message']['tool_calls'][1]['id']='call-0'
        with self.assertRaisesRegex(ValueError,'Repeated'):tools.parse_batch(raw)
        decisions,_=tools.parse_batch(response([('web_search',{'query':'rooms'}),('noop',{})]),allow_search=True)
        self.assertEqual([d.name for d in decisions],['web_search','noop'])
        with self.assertRaisesRegex(ValueError,'Unsupported'):tools.parse_batch(response([('web_search',{'query':'rooms'})]))

    def test_consolidated_context_and_exact_bindings(self):
        c=NativeConversation();first=c.request('system','goal','first',observation_source='first')
        _,assistant=NativeBrowserTools(batch_size=8).parse_batch(response([('fill',{'bid':'1','value':'A'}),('click',{'bid':'2'})]))
        c.record_batch(assistant,[({'execution':'completed'},'a'),({'execution':'not_executed','reason':'navigation'},'b')])
        c.add_evidence({'events':[{'text':'Receipt'}]},source_id='events')
        second=c.request('system','goal','final consolidated page',observation_source='page')
        self.assertEqual(second[:len(first)],first)
        self.assertEqual([x['role'] for x in second],['system','user','assistant','tool','tool'])
        self.assertEqual([m['tool_call_id'] for m in second if m['role']=='tool'],['call-0','call-1'])
        self.assertNotIn('CURRENT BROWSER OBSERVATION',second[-2]['content'])
        self.assertEqual(second[-1]['content'].count('CURRENT BROWSER OBSERVATION'),1)
        self.assertEqual(second[-3]['reasoning'],'Retained plan')
        for b in c.bindings():
            fragment=second[b['message_index']]['content'][b['start']:b['end']]
            self.assertTrue(fragment)
            if b['content_id']=='page':self.assertEqual(fragment,'final consolidated page')
        with self.assertRaisesRegex(ValueError,'Repeated'):c.record_batch(assistant,[({},None),({},None)])

    def test_transient_events_once_and_attributed(self):
        raw={'page_events':[{'kind':'page_announcement','text':'Saved'}],
             'added_or_changed':['Do not dump this AX delta'],'page_events_omitted':2}
        union=batch_events([{'batch_call':0,'_batch_feedback':raw},{'batch_call':1,'_batch_feedback':raw}])
        out=CompactFeedback()(union,kind='browser_update')
        self.assertEqual([e['batch_call'] for e in out['events']],[0,1])
        self.assertNotIn('Do not dump',json.dumps(out))
        self.assertEqual(out['selection']['capture_omitted'],4)

    def test_same_bid_different_label_or_parent_is_not_same_target(self):
        obs={'axtree_object':{'nodes':[
            {'nodeId':'root','role':{'value':'group'},'name':{'value':'10 AM'},'childIds':['button']},
            {'nodeId':'button','browsergym_id':'5','backendDOMNodeId':12,'role':{'value':'button'},'name':{'value':'Cancel'}}]}}
        before=target_signature(obs,'5');changed=deepcopy(obs)
        changed['axtree_object']['nodes'][0]['name']['value']='2 PM'
        self.assertNotEqual(before,target_signature(changed,'5'))
        self.assertIsNone(target_signature(obs,'missing'))
