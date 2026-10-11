"""Zero-provider synthetic lifecycle tests; no browser, scheduler or cloud launch."""
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from threading import Event, Thread
import hashlib
import json
import unittest
from unittest.mock import patch

import numpy as np
from intent_browser.backend import Completion
from intent_browser.evaluation import Evaluation
from intent_browser.runner import run_episode
from intent_browser.automatic_grading import AutomaticGrading, file_hash, MANIFEST
from intent_browser.episode_admission import EpisodeAdmissionCancelled, EpisodeReady


def bind(env, trace, obs):
    env.events.append('bind')
    return {'task_id':'admission-fixture', 'goal_sha256':hashlib.sha256(obs['goal'].encode()).hexdigest(),
            'reference_files':{str(env.reference):file_hash(env.reference)},
            'source_files':{str(Path(__file__).resolve()):file_hash(__file__)}}


def grade(env, trace, outcome):
    env.events.append('grade')
    return {'done':env.done, 'closed':env.closed}


def project(raw, binding):
    return Evaluation('admission-state','1',trust='native_state',task_completed=raw['done'],
                      limitations=['Synthetic state only.'])


class AdmissionTests(unittest.TestCase):
    def episode(self, callback=None, *, contract=False, model_failure=False):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        events=[]
        class Env:
            closed=False;done=False;resets=0;captures=0;view='parked'
            reference=root/'reference.json'
            @property
            def unwrapped(self):return self
            def obs(self):
                return {'goal':'Read','url':'http://fixture.local/','view':self.view,
                    'last_action_error':'','axtree_object':{'nodes':[]},
                    'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self,seed):events.append('reset');self.resets+=1;return self.obs(),{}
            def _get_obs(self):events.append('refresh');self.captures+=1;return self.obs()
            def step(self,action):events.append('step');self.done=True;return self.obs(),0,False,False,{}
            def close(self):events.append('close');self.closed=True
        env=Env();env.events=events;env.reference.write_text('{"goal":"Read"}')
        class Backend:
            calls=0;begins=0;messages=None
            def begin_episode(self,ident):events.append('begin');self.begins+=1;return {'session_id':ident}
            def complete(self,messages):
                events.append('provider');self.calls+=1;self.messages=messages
                if model_failure:raise RuntimeError('provider fixture failed')
                return Completion("send_msg_to_user('Done')",{'fixture':True})
        backend=Backend()
        def factory(_):events.append('create');return env
        def wait(ready):
            events.append('ready')
            self.assertIsInstance(ready,EpisodeReady);self.assertEqual(env.resets,1)
            self.assertEqual(backend.begins,0);self.assertEqual(backend.calls,0)
            if contract:self.assertEqual(json.loads((ready.directory/MANIFEST).read_text())['status'],'attached')
            env.view='fresh'
            if callback:return callback(ready,env,backend,events)
        options={'environment_admission':wait} if callback is not False else {}
        if contract:options['automatic_grading']=AutomaticGrading('admission-fixture-v1',bind,grade,project)
        else:options.update(allow_ungraded=True,ungraded_reason='Explicit synthetic admission lifecycle test')
        with patch('intent_browser.runner.observation_text',side_effect=lambda obs,limit=16000:obs['view']):
            directory,summary=run_episode(factory,backend,{'tags':['scripted','admission-test']},root/'runs',max_steps=1,**options)
        return directory,summary,events,env,backend

    def test_default_keeps_old_lease_order_and_does_not_refresh(self):
        _,summary,events,env,backend=self.episode(False)
        self.assertEqual(events[:3],['begin','create','reset']);self.assertEqual(env.captures,0)
        self.assertEqual(backend.calls,1);self.assertEqual(summary['stop_reason'],'agent_finished')

    def test_ready_parks_after_binding_then_fresh_capture_before_session(self):
        directory,summary,events,env,backend=self.episode(contract=True)
        self.assertEqual(events[:6],['create','reset','bind','ready','refresh','begin'])
        self.assertEqual(env.resets,1);self.assertEqual(env.captures,1);self.assertTrue(env.closed)
        self.assertEqual(backend.calls,1);self.assertIn('fresh',json.dumps(backend.messages))
        self.assertEqual(summary['success'],True);self.assertIn('grade',events)
        rows=[json.loads(x) for x in (directory/'events.jsonl').read_text().splitlines()]
        types=[x.get('event') or x.get('kind') for x in rows]
        self.assertTrue(any(x.get('event')=='episode_admitted' or x.get('kind')=='episode_admitted' or x.get('type')=='episode_admitted' for x in rows),rows)

    def test_cancellation_closes_without_lease_provider_or_native_task_verdict(self):
        def cancel(*_):raise EpisodeAdmissionCancelled('Queue stopped')
        directory,summary,events,env,backend=self.episode(cancel,contract=True)
        self.assertEqual(summary['stop_reason'],'admission_cancelled');self.assertEqual(summary['step_count'],0)
        self.assertEqual(backend.begins,0);self.assertEqual(backend.calls,0);self.assertTrue(env.closed)
        self.assertNotIn('grade',events);self.assertEqual(env.captures,0)
        self.assertIsNone(summary['evaluation']['task_completed']);self.assertIsNone(summary['success'])

    def test_cancel_wakes_waiting_owner_without_cross_thread_browser_use(self):
        def callback(*_):
            wake=Event();thread=Thread(target=wake.set);thread.start()
            self.assertTrue(wake.wait(2));thread.join()
            raise EpisodeAdmissionCancelled('Cancelled from scheduler signal')
        _,summary,_,env,backend=self.episode(callback)
        self.assertEqual(summary['stop_reason'],'admission_cancelled');self.assertTrue(env.closed)
        self.assertEqual(backend.calls,0)

    def test_callback_failure_and_invalid_return_do_not_dispatch(self):
        def fail(*_):raise RuntimeError('admission fixture failed')
        for callback in (fail,lambda *_:True):
            with self.subTest(callback=callback):
                _,summary,_,env,backend=self.episode(callback)
                self.assertEqual(summary['stop_reason'],'error');self.assertTrue(env.closed)
                self.assertEqual(backend.begins,0);self.assertEqual(backend.calls,0)

    def test_activation_capture_failure_closes_without_lease(self):
        def callback(_,env,*args):
            def fail():raise RuntimeError('capture fixture failed')
            env._get_obs=fail
        _,summary,_,env,backend=self.episode(callback)
        self.assertIn('capture fixture failed',summary['error']);self.assertEqual(backend.begins,0)
        self.assertTrue(env.closed)

    def test_provider_failure_after_activation_still_closes(self):
        _,summary,events,env,backend=self.episode(model_failure=True)
        self.assertEqual(backend.begins,1);self.assertEqual(backend.calls,1);self.assertTrue(env.closed)
        self.assertIn('provider fixture failed',summary['error'])

    def test_invalid_callback_rejected_before_environment(self):
        with self.assertRaisesRegex(ValueError,'trusted callable'):
            run_episode(lambda _:self.fail('No environment'),SimpleNamespace(),{},environment_admission=42,
                        allow_ungraded=True,ungraded_reason='Explicit test')

    def test_readiness_identity_is_immutable(self):
        ready=EpisodeReady('id',Path('/tmp/fixture'),0.0)
        with self.assertRaises(AttributeError):ready.episode_id='changed'

    def test_invalid_cancellation_reason_rejected(self):
        for reason in ('',None,42):
            with self.assertRaises(ValueError):EpisodeAdmissionCancelled(reason)
