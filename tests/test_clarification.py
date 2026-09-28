import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace

from intent_browser.backend import Completion
from intent_browser.clarification import execute_clarification
from intent_browser.harness import native_tools_profile, with_clarification


def completion(*names):
    calls = [{'id':str(i),'type':'function','function':{'name':name,
        'arguments':json.dumps({'question':'What shoe size do you wear?'} if name=='ask_user' else
                               {'text':'Finished'} if name=='send_msg_to_user' else {'bid':'1'})}}
             for i,name in enumerate(names)]
    return Completion('', {'choices':[{'finish_reason':'tool_calls','message':{
        'role':'assistant','content':None,'tool_calls':calls}}]})


class ClarificationTests(unittest.TestCase):
    def test_disabled_default_and_explicit_profile(self):
        original = native_tools_profile()
        with self.assertRaisesRegex(ValueError,'Unsupported native tool'):
            original.tools.parse_completion(completion('ask_user'))
        profile = with_clarification(original)
        self.assertIn('ask_user',profile.describe()['tools'])
        decision, _ = profile.tools.parse_completion(completion('ask_user'))
        self.assertEqual(decision.arguments,{'question':'What shoe size do you wear?'})
        self.assertNotIn('ask_user', original.describe()['tools'])

    def test_question_ends_batch_and_no_speculative_second_question(self):
        tools=replace(with_clarification(native_tools_profile()).tools,batch_size=8)
        self.assertEqual(len(tools.parse_batch(completion('click','ask_user'))[0]),2)
        for names in [('ask_user','click'),('ask_user','send_msg_to_user'),('ask_user','ask_user')]:
            with self.assertRaisesRegex(ValueError,'ask_user must be'):
                tools.parse_batch(completion(*names))

    def test_exact_reply_and_private_audit_never_in_feedback(self):
        with tempfile.TemporaryDirectory() as td:
            trace=SimpleNamespace(directory=Path(td))
            reply, artifact=execute_clarification(trace,0,'  Shoe size? ',lambda q:'EU 40, please.\n',audit_id='private-id')
            self.assertEqual(reply,{'tool':'ask_user','user_reply':'EU 40, please.\n'})
            saved=json.loads((Path(td)/artifact).read_text())
            self.assertEqual(saved['question'],'  Shoe size? ')
            self.assertEqual(saved['audit_id'],'private-id')
            with self.assertRaisesRegex(ValueError,'already exists'):
                execute_clarification(trace,0,'Again?',lambda q:'EU 41')

    def test_failure_and_wrong_return_do_not_create_user_answer(self):
        with tempfile.TemporaryDirectory() as td:
            trace=SimpleNamespace(directory=Path(td))
            def fail(q): raise RuntimeError('Responder unavailable')
            for i,callback in enumerate([fail, lambda q:{'reply':'LEAK','hidden_size':40},lambda q:'']):
                with self.assertRaises((ValueError,RuntimeError)):
                    execute_clarification(trace,i,'What size?',callback)
                saved=json.loads((Path(td)/f'clarification-{i:03d}.json').read_text())
                self.assertIsNone(saved['reply']);self.assertIsNotNone(saved['error'])

if __name__=='__main__':unittest.main()
