import json
from pathlib import Path
import tempfile
import threading
import unittest

import httpx

from intent_browser.demo import DemoBackend, EXAMPLES, World, verify


class DemoTests(unittest.TestCase):
    def test_checkout_uses_server_prices_and_goal_checks_do_not_guess_free_text(self):
        world=World();before=world.snapshot()
        world.action({'type':'cart','product':'notebook','delta':1})
        world.action({'type':'cart','product':'notebook','delta':1})
        self.assertEqual(world.public()['total'],157)
        world.action({'type':'shipping','value':'pickup'})
        world.action({'type':'checkout','total':0})
        self.assertEqual(world.snapshot()['orders'][0]['total'],118)
        self.assertEqual(verify('shop',EXAMPLES['shop']['goal'],before,world.snapshot()),(True,True))
        self.assertEqual(verify('shop','Get me something nice',before,world.snapshot()),(None,None))
        world.action({'type':'cart','product':'mug','delta':1});world.action({'type':'checkout'})
        self.assertEqual(verify('shop',EXAMPLES['shop']['goal'],before,world.snapshot()),(False,False))

    def test_bookings_validate_values_and_preferences_do_not_change_other_state(self):
        world=World();before=world.snapshot()
        with self.assertRaises(ValueError):
            world.action({'type':'book','room_id':'a101','day':'Tuesday','time':'25:00','duration':'30','people':'3'})
        self.assertEqual(world.snapshot(),before)
        world.action({'type':'preferences','frequency':'monthly','tips':False})
        self.assertEqual(verify('preferences',EXAMPLES['preferences']['goal'],before,world.snapshot()),(True,True))
        world.action({'type':'book','room_id':'a101','day':'Tuesday','time':'14:00','duration':'30','people':'3'})
        self.assertEqual(verify('preferences',EXAMPLES['preferences']['goal'],before,world.snapshot()),(True,False))

    def test_demo_action_reminder_is_logged_without_mutating_selected_context(self):
        with tempfile.TemporaryDirectory() as root:
            config={'model':'qwen/qwen3.8-27b','key':'test-secret','providers':'parasail'}
            backend=DemoBackend(Path(root)/'budget.json',config,threading.Lock(),action_format=True)
            self.addCleanup(backend.close);backend.begin_episode('format-test');backend.client.close()
            def respond(request):
                payload=json.loads(request.content)
                self.assertIn('ACTION RESPONSE FORMAT',payload['messages'][-1]['content'])
                return httpx.Response(200,json={'model':config['model'],'provider':'Parasail',
                    'choices':[{'message':{'content':"click('12')"}}],
                    'usage':{'cost':0.00001,'prompt_tokens':100,'completion_tokens':5}})
            backend.client=httpx.Client(transport=httpx.MockTransport(respond))
            original=[{'role':'user','content':'A visible page'}]
            result=backend.complete(original)
            self.assertEqual(original[0]['content'],'A visible page')
            ledger=json.loads((Path(root)/'budget.json').read_text())
            self.assertEqual(result.request,ledger['requests'][0]['model_request'])

    def test_cost_audit_persists_and_reservation_precedes_send(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'budget.json';lock=threading.Lock()
            config={'model':'qwen/qwen3.8-27b','key':'test-secret','providers':'parasail'}
            backend=DemoBackend(path,config,lock);self.addCleanup(backend.close)
            backend.begin_episode('demo-test');backend.client.close()
            calls=[]
            def response(request):
                calls.append(request)
                data=json.loads(path.read_text())
                self.assertEqual(data['requests'][-1]['model_request'],json.loads(request.content))
                self.assertGreater(float(data['reserved_usd']),0)
                return httpx.Response(200,json={'choices':[{'message':{'content':'noop()'}}],
                    'provider':'Parasail','model':config['model'],
                    'usage':{'cost':2,'prompt_tokens':100,'completion_tokens':3}})
            backend.client=httpx.Client(transport=httpx.MockTransport(response))
            backend.complete([{'role':'user','content':'test'}])
            restarted=DemoBackend(path,config,lock);self.addCleanup(restarted.close)
            restarted.begin_episode('new-demo')
            with self.assertRaisesRegex(ValueError,'audit needs review'):
                restarted.complete([{'role':'user','content':'test'}])
            self.assertEqual(len(calls),1)
            self.assertNotIn('test-secret',path.read_text())


if __name__=='__main__': unittest.main()
