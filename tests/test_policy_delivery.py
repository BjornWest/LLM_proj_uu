import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from intent_browser.harness import EvidenceConversation
from intent_browser.policy_delivery import PolicyDelivery


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.ledger=PolicyDelivery(SimpleNamespace(directory=Path(self.tmp.name),event=lambda *a,**k:None))
        self.context=EvidenceConversation()
        self.context.initialize('system','Warranty is forbidden')

    def request(self,text='Public page'):
        content=self.ledger.register('page_observation',text,step=0)
        messages=self.context.request('system','Warranty is forbidden',text,observation_source=content)
        return {'step':0,'messages':messages,'model_request':{'messages':messages}},self.context.bindings()

    def test_goal_text_is_not_registered_as_page_evidence(self):
        event,bindings=self.request()
        record=self.ledger.record(event,bindings,acknowledged=True)
        self.assertEqual(len(record['items']),1)
        self.assertEqual(record['items'][0]['message_span']['message_index'],2)
        self.assertEqual(self.ledger.sources['content-0000']['text'],'Public page')

    def test_feedback_has_exact_own_span_and_not_model_authored_claim(self):
        event,bindings=self.request()
        self.ledger.record(event,bindings,acknowledged=True)
        value={'events':[{'text':'Insurance added'}]}
        content=self.ledger.register('browser_feedback',json.dumps(value,ensure_ascii=False,sort_keys=True),step=0)
        self.context.record("send_msg_to_user('I saw another thing')",value,feedback_source=content)
        event,bindings=self.request('Next page')
        record=self.ledger.record(event,bindings,acknowledged=True)
        self.assertEqual([i['first_confirmed_delivery'] for i in record['items']],[False,True,True])
        self.assertNotIn('I saw another thing',json.dumps(self.ledger.sources))
        self.assertEqual(record['items'][1]['kind'],'browser_feedback')

    def test_failed_transport_and_missing_request_remain_unconfirmed(self):
        for retained in [True,False]:
            event,bindings=self.request()
            if not retained:event['model_request']=None
            record=self.ledger.record(event,bindings,acknowledged=False)
            self.assertTrue(all(not item['confirmed'] for item in record['items']))
            self.assertFalse(record['http_dispatch_observed_by_ledger'])

    def test_matching_text_elsewhere_cannot_hide_rewritten_bound_span(self):
        event,bindings=self.request('Warranty offer')
        event['model_request']={'messages':[{'role':'user','content':'Warranty offer'}]}
        record=self.ledger.record(event,bindings,acknowledged=True)
        self.assertFalse(record['items'][0]['confirmed'])

    def test_recipient_has_independent_first_delivery(self):
        event,bindings=self.request()
        self.ledger.record(event,bindings,acknowledged=True,recipient='helper-1')
        record=self.ledger.record(event,bindings,acknowledged=True,recipient='main')
        self.assertTrue(record['items'][0]['first_confirmed_delivery'])

    def test_binding_copies_do_not_mutate_past_evidence(self):
        event,bindings=self.request()
        bindings[0]['start']=999
        record=self.ledger.record(event,self.context.bindings(),acknowledged=True)
        self.assertTrue(record['items'][0]['confirmed'])


if __name__=='__main__':unittest.main()
