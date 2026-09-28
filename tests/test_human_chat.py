import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from intent_browser.human_chat import HumanChat
from intent_browser.native_tools import NativeConversation
from intent_browser.policy_delivery import PolicyDelivery
from intent_browser.trace import Trace
from intent_browser.human_browser import HumanBrowser, ax_digest


class Chat:
    def __init__(self):
        self.messages=[{'role':'user','timestamp':1,'message':'Original goal'}]
    def _js_user_message_received_callback(self,msg):
        self.messages.append({'role':'user','timestamp':2,'message':msg})
        return ['user','00:00',msg]


class HumanChatTests(unittest.TestCase):
    def test_trusted_ingress_exact_delivery_and_append_order(self):
        with tempfile.TemporaryDirectory() as out:
            trace=Trace(out,{});chat=Chat();original=chat._js_user_message_received_callback
            bridge=HumanChat(chat,trace);delivery=PolicyDelivery(trace);conv=NativeConversation()
            initial=conv.request('system','Original goal','AX')
            # A benchmark can append role=user itself; it is not trusted ingress.
            chat.messages.append({'role':'user','timestamp':2,'message':'Untrusted task injection'})
            self.assertEqual(bridge.pending,[])
            for _ in range(2): chat._js_user_message_received_callback('Please help')
            self.assertEqual([r['sequence'] for r in bridge.pending],[1,2])
            assistant={'role':'assistant','content':None,'tool_calls':[
                {'id':'a','type':'function','function':{'name':'noop','arguments':'{}'}},
                {'id':'b','type':'function','function':{'name':'noop','arguments':'{}'}}]}
            conv.record_batch(assistant,[({'execution':'not_executed'},None)]*2)
            bridge.enqueue(conv,delivery,1)
            messages=conv.request('system','Original goal','fresh AX')
            self.assertEqual(messages[:len(initial)],initial)
            self.assertEqual([m['role'] for m in messages[-5:]],['assistant','tool','tool','user','user'])
            self.assertEqual([m['content'] for m in messages[-2:]],['Please help']*2)
            self.assertNotIn('Untrusted task injection',str(messages))
            event={'step':1,'model_request':{'messages':messages}}
            unknown=delivery.record(event,conv.bindings(),acknowledged=False)
            self.assertTrue(all(not x['confirmed'] for x in unknown['items']))
            confirmed=delivery.record(event,conv.bindings(),acknowledged=True)
            self.assertEqual(len(confirmed['items']),2)
            self.assertTrue(all(x['confirmed'] and x['kind']=='human_message' for x in confirmed['items']))
            bridge.enqueue(conv,delivery,2)
            self.assertEqual(len(delivery.sources),2)
            bridge.close();self.assertEqual(chat._js_user_message_received_callback,original)
            trace.finish({})

    def test_invalid_input_not_accepted(self):
        bridge=HumanChat(Chat(),Mock())
        with self.assertRaises(ValueError):bridge.receive({'message':'wrong type'})
        self.assertEqual(bridge.sequence,0)

    def test_guard_recovery_exemptions_keep_custody_document_and_mutation_checks(self):
        old={'axtree_object':{'nodes':[]},'human_tabs':{'active_tab_id':'tab-1'}}
        fresh={'axtree_object':{'nodes':[{'nodeId':'1','name':{'value':'Next'}}]},
               'human_tabs':{'active_tab_id':'tab-1'}}
        manager=HumanBrowser.__new__(HumanBrowser)
        manager.stable_frames=False
        manager.sync=lambda:None;manager.active='tab-1';manager.env=object()
        state={'state':'agent_controlled','handover_id':None}
        manager.states=lambda:{'tab-1':state}
        ticket={'tab_id':'tab-1','handover_id':None,'document':['doc'],'ax_sha256':ax_digest(old)}
        with patch('intent_browser.human_browser.document_signature',return_value=['doc']):
            for tool in ['ax_read','ax_search','noop','goto','new_tab','handover_tab']:
                with self.subTest(tool=tool):
                    self.assertIsNone(manager.guard(ticket,fresh,decision=SimpleNamespace(name=tool)))
            self.assertEqual(manager.guard(ticket,fresh,decision=SimpleNamespace(name='click')),
                             'tab_content_changed_since_decision')
            state['state']='human_active'
            self.assertEqual(manager.guard(ticket,fresh,decision=SimpleNamespace(name='new_tab')),
                             'tab_ownership_or_target_changed')
            state['state']='agent_controlled';state['handover_id']='new-cycle'
            self.assertEqual(manager.guard(ticket,fresh,decision=SimpleNamespace(name='ax_read')),
                             'tab_handover_cycle_changed')
            state['handover_id']=None
        with patch('intent_browser.human_browser.document_signature',return_value=['new-doc']):
            self.assertEqual(manager.guard(ticket,fresh,decision=SimpleNamespace(name='noop')),
                             'tab_document_changed')
