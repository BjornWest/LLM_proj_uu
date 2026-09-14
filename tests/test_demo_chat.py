import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import httpx

from intent_browser.backend import Completion
from intent_browser.demo import EXAMPLES, World, verify
from intent_browser.demo_chat import DemoChat
from intent_browser.demo_rooms import first_available


class FakeBackend:
    model = 'test-model'
    base_url = 'https://example.test'
    max_tokens = 512
    request_options = {}

    def begin_episode(self, episode):
        self.session = episode
        return {'session_id': episode}

    def complete(self, messages):
        self.last_request = {'model': self.model, 'messages': messages, 'session_id': self.session}
        return Completion('There are two rooms.', {'usage': {'cost': 0}, 'choices': []}, self.last_request)

    def close(self):
        pass


class DemoChatTests(unittest.TestCase):
    def test_context_excludes_verifier_state_and_prefers_actual_running_observation(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root); (path/'episode').mkdir()
            (path/'episode/observation-001.txt').write_text('Visible room Å101, 09:00 free')
            app = SimpleNamespace(jobs={'j': {'id':'j','world':'w','episode':'episode','status':'running','goal':'book a room','mode':'live','error':None}},
                status=lambda key: {'activity':['Selected Building'], 'result':{'secret':'EXPECTED_SENTINEL'}}, ledger=path/'ledger.json')
            chat = DemoChat(app, FakeBackend, path)
            context = chat.context('w', 'stale iframe', 'Rooms')
            self.assertIn('Å101', context['page_text'])
            self.assertNotIn('EXPECTED_SENTINEL', json.dumps(context))
            self.assertNotIn('stale iframe', context['page_text'])
            self.assertIsNone(chat.context('other', 'other page', 'Other')['latest_run'])

    def test_question_logs_exact_request_and_never_dispatches_browser_action(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)
            app=SimpleNamespace(jobs={},ledger=path/'ledger.json')
            chat=DemoChat(app,FakeBackend,path)
            def turn(question, world='w'):
                return {'world':world,'question':question,'context':chat.context(world,'Room information','Rooms'),
                        'status':'running','answer':None,'error':None,'episode':None,'cost':None,'alerts':[]}
            first=turn('What rooms are here?');chat.respond(first)
            second=turn('What about the first one?');chat.respond(second)
            row=json.loads((path/second['episode']/'steps.jsonl').read_text())
            self.assertEqual(row['model_request']['messages'],row['messages'])
            self.assertEqual(row['model_request']['session_id'],second['episode'])
            self.assertIn('What rooms are here?',json.dumps(row['messages']))
            self.assertIsNone(row['action']);self.assertFalse(row['browser_stepped'])
            self.assertNotIn('other',chat.history)
            summary=json.loads((path/second['episode']/'episode.json').read_text())
            self.assertEqual(summary['browser_step_count'],0)
            self.assertEqual(summary['interaction_kind'],'read_only_chat')
            self.assertEqual(summary['runtime']['observation_adapter'],'demo-chat-context-v1')
            self.assertIsNone(summary['runtime']['action_parser'])
            self.assertIsNone(summary['evaluation'])

    def test_timeout_retains_attempted_request_and_surfaces_failure(self):
        class TimeoutBackend(FakeBackend):
            def complete(self,messages):
                self.last_request={'model':self.model,'messages':messages}
                raise httpx.ReadTimeout('timed out')
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);app=SimpleNamespace(jobs={},ledger=path/'ledger.json')
            chat=DemoChat(app,TimeoutBackend,path)
            turn={'world':'w','question':'Hello','context':chat.context('w','Page','Title'),
                  'status':'running','answer':None,'error':None,'episode':None,'cost':None,'alerts':[]}
            chat.respond(turn)
            row=json.loads((path/turn['episode']/'steps.jsonl').read_text())
            self.assertEqual(row['model_request']['model'],'test-model')
            self.assertIsNone(row['model_response'])
            self.assertEqual(turn['status'],'finished');self.assertIn('timed out',turn['error'])


class RoomTests(unittest.TestCase):
    def test_first_available_changes_after_booking_and_rejects_overlaps(self):
        world=World();before=world.snapshot()
        booking=first_available('Ångström','Tuesday',30,3,[])
        self.assertEqual((booking['room_id'],booking['time']),('a101','09:00'))
        world.action({'type':'book',**booking})
        self.assertEqual(verify('booking',EXAMPLES['booking']['goal'],before,world.snapshot()),(True,True))
        with self.assertRaisesRegex(ValueError,'no longer available'):
            world.action({'type':'book',**booking,'duration':60})
        next_booking=first_available('Ångström','Tuesday',30,3,world.snapshot()['bookings'])
        self.assertEqual(next_booking['time'],'09:30')
        next_before=world.snapshot();world.action({'type':'book',**next_booking})
        self.assertEqual(verify('booking',EXAMPLES['booking']['goal'],next_before,world.snapshot()),(True,True))
        room=next(r for r in world.public()['rooms'] if r['id']=='a101')
        self.assertNotIn('09:00',room['availability']['Tuesday'])
        self.assertIn('10:00',room['availability']['Thursday'])

    def test_an_accepted_wrong_room_is_still_rejected_by_goal_verifier(self):
        world=World();before=world.snapshot()
        wrong=first_available('Ekonomikum','Tuesday',30,3,[])
        world.action({'type':'book',**wrong})
        self.assertEqual(len(world.snapshot()['bookings']),1)
        self.assertEqual(verify('booking',EXAMPLES['booking']['goal'],before,world.snapshot()),(False,False))

    def test_room_capacity_interval_and_catalog_are_checked_server_side(self):
        world=World()
        for values in ({'room_id':'e203','people':3,'time':'09:00'},
                       {'room_id':'a101','people':3,'time':'09:30','duration':60},
                       {'room_id':'not-a-room','people':1,'time':'09:00'}):
            with self.assertRaises(ValueError):
                world.action({'type':'book','day':'Tuesday','duration':30,**values})
        self.assertEqual(world.snapshot()['bookings'],[])


if __name__=='__main__': unittest.main()
