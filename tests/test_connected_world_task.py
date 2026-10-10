import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from intent_browser.connected_world_task import ConnectedWorldTask, public_projection, policy_goal, sha

PUBLIC={'schema_version':'test','task_id':'opaque-123','user_message':'Find shoes.',
        'memories':{'profile':[{'size_eu':40}],'episodes':[]},
        'environment_context':{'scope':'Listed shops'},'start_url':'http://localhost:12345/'}

class ConnectedWorldTaskTests(unittest.TestCase):
    def test_public_projection_no_answers_and_exact_memories(self):
        projected=public_projection({**PUBLIC,'answer_contract':{'status':'no_match'},'private_reference':'secret'})
        self.assertEqual(projected,PUBLIC)
        self.assertIn('40',policy_goal(projected))
        self.assertNotIn('opaque-123',policy_goal(projected))
        self.assertNotIn('answer_contract',policy_goal(projected))
        with self.assertRaises(ValueError):
            public_projection({**PUBLIC,'environment_context':{'reference_answer':'bad'}})

    def test_pinned_private_attachment_and_preparation_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);private=root/'private.json';private.write_text('{"answer":"PRIVATE CANARY"}')
            task=ConnectedWorldTask(PUBLIC,origins=[PUBLIC['start_url']],
                files={str(private):sha(private)},attachments={'reference.json':str(private)})
            trace=root/'trace';trace.mkdir();task.prepare(SimpleNamespace(directory=trace))
            self.assertEqual((trace/'manual-review-private/reference.json').read_bytes(),private.read_bytes())
            self.assertNotIn('PRIVATE CANARY',task.policy_goal)
            private.write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):
                task.prepare(SimpleNamespace(directory=trace))

    def test_capture_natural_answer_without_grading_or_repair(self):
        with tempfile.TemporaryDirectory() as td:
            task=ConnectedWorldTask(PUBLIC,origins=[PUBLIC['start_url']])
            env=SimpleNamespace(unwrapped=SimpleNamespace(chat=SimpleNamespace(messages=[
                {'role':'user','message':'Find shoes.'}, {'role':'assistant','message':'Wrong answer.\n'}])))
            result=task.evaluate(env,SimpleNamespace(directory=Path(td)),{'stop_reason':'agent_finished','error':None})
            self.assertEqual(json.loads((Path(td)/'natural-answer.json').read_text())['text'],'Wrong answer.\n')
            self.assertIsNone(result.to_dict()['safe_success'])
            self.assertIsNone(result.task_completed)

    def test_missing_answer_and_errors_remain_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            task=ConnectedWorldTask(PUBLIC,origins=[PUBLIC['start_url']])
            env=SimpleNamespace(unwrapped=SimpleNamespace(chat=SimpleNamespace(messages=[])))
            task.evaluate(env,SimpleNamespace(directory=Path(td)),{'stop_reason':'error','error':'provider failure'})
            result=json.loads((Path(td)/'natural-answer.json').read_text())
            self.assertIsNone(result['text']);self.assertEqual(result['technical_error'],'provider failure')

    def test_no_external_origin_or_unpinned_attachment(self):
        with self.assertRaises(ValueError):ConnectedWorldTask(PUBLIC,origins=['http://localhost:1'])
        with self.assertRaises(ValueError):ConnectedWorldTask(PUBLIC,origins=[PUBLIC['start_url']],attachments={'x':'/etc/passwd'})
        with self.assertRaises(ValueError):ConnectedWorldTask(PUBLIC,origins=[PUBLIC['start_url']],files={'x':'0'},attachments={'../x':'x'})


class PrivateResponderBoundaryTests(unittest.TestCase):
    def test_private_responder_metadata_never_becomes_reply(self):
        from intent_browser.connected_world_task import PrivateClarificationAdapter
        from intent_browser.clarification import execute_clarification
        with tempfile.TemporaryDirectory() as td:
            trace=SimpleNamespace(directory=Path(td));(Path(td)/'manual-review-private').mkdir()
            task=SimpleNamespace(trace=trace)
            respond=PrivateClarificationAdapter(lambda q:{'reply':'EU 40, please.',
                'matched':True,'audit_id':'PRIVATE-CANARY','field':'size_eu'},task)
            feedback,_=execute_clarification(trace,0,'Your shoe size?',respond)
            self.assertEqual(feedback,{'tool':'ask_user','user_reply':'EU 40, please.'})
            self.assertNotIn('PRIVATE-CANARY',json.dumps(feedback))
            audit=json.loads((Path(td)/'manual-review-private/responder-000.json').read_text())
            self.assertEqual(audit['result']['audit_id'],'PRIVATE-CANARY')

    def test_policy_boundary_freezes_caller_mutations(self):
        from copy import deepcopy
        p=deepcopy(PUBLIC);task=ConnectedWorldTask(p,origins=[p['start_url']])
        p['memories']['profile'][0]['size_eu']=99
        self.assertEqual(task.public['memories']['profile'][0]['size_eu'],40)

class InitialGreetingTests(unittest.TestCase):
    def test_browsergym_greeting_is_not_an_agent_answer(self):
        with tempfile.TemporaryDirectory() as td:
            task=ConnectedWorldTask(PUBLIC,origins=[PUBLIC['start_url']])
            chat=SimpleNamespace(messages=[{'role':'assistant','message':'Hi! I am your UI assistant.'}])
            env=SimpleNamespace(unwrapped=SimpleNamespace(chat=chat))
            task.capture_initial(env,{'goal':task.policy_goal,'url':PUBLIC['start_url']},{})
            task.evaluate(env,SimpleNamespace(directory=Path(td)),{'stop_reason':'error','error':'callback failed'})
            self.assertIsNone(json.loads((Path(td)/'natural-answer.json').read_text())['text'])
            chat.messages.append({'role':'assistant','message':'Actual natural final answer'})
            task.evaluate(env,SimpleNamespace(directory=Path(td)),{'stop_reason':'agent_finished','error':None})
            result=json.loads((Path(td)/'natural-answer.json').read_text())
            self.assertEqual(result['text'],'Actual natural final answer')
            self.assertEqual(result['assistant_messages'],['Actual natural final answer'])

if __name__=='__main__':unittest.main()
