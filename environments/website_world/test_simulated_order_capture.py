"""Authored lifecycle/store fixtures; these do not certify browser authority."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from . import simulated_order_capture as capture
from .simulated_order_store import OrderStore
from .adapter import digest


class CaptureControls(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.task={'task_id':'authored-task','kind':'place_preloaded_order'}
        baskets=SimpleNamespace(adapter=SimpleNamespace(world={'world_id':'world'},retailers={'a':{}}),plan_id='plan',domain_id='domain')
        self.runtime=SimpleNamespace(orders=OrderStore(baskets,runtime_id='runtime',record_maker=lambda b,r,s,*,order_id:{'order_id':order_id,'retailer_id':r,'submission':deepcopy(s)}))
        self.source=Path(capture.__file__).resolve()
        self.files={str(self.source):sha256(self.source.read_bytes()).hexdigest()}
        self.bound=capture.OrderCapture(self.runtime,self.task,source_files=self.files)
        self.trace=SimpleNamespace(directory=self.root,episode_id='episode')
        (self.root/'metadata.json').write_text(json.dumps({'episode_id':'episode'}))
        (self.root/'steps.jsonl').write_text('{"authored":true}\n')
        self.summary={'stop_reason':'agent_finished','terminated':False,'truncated':False}

    def ready(self):
        self.bound.before(None,self.trace)
        self.runtime.orders.commit('a',{'idempotency_key':'one'})
        self.bound.after(None,self.trace,self.summary)

    def test_full_private_ledger_actual_binding_and_unaccepted_effects_stay_null(self):
        self.ready()
        capsule,complete=self.bound.seal(self.root,self.summary)
        self.assertTrue(complete);self.assertIsNone(capsule['effect_journal'])
        self.assertEqual(capsule['before']['order_snapshot']['orders'],[])
        self.assertEqual(len(capsule['after']['order_snapshot']['orders']),1)
        self.assertEqual(capsule['main_trace_sha256'],sha256((self.root/'steps.jsonl').read_bytes()).hexdigest())
        self.assertEqual(self.bound.binding['episode_binding'],{
            'episode_id':'episode','task_sha256':digest(self.task),'source_union_sha256':digest(self.files),
            'capture_implementation_sha256':self.files[str(self.source)]})
        # Capture is detached, and a sealed episode accepts no further commits.
        self.task['task_id']='changed'
        with self.assertRaises(ValueError):self.runtime.orders.commit('a',{'idempotency_key':'two'})
        self.assertEqual(len(capsule['after']['order_snapshot']['orders']),1)
        with self.assertRaises(ValueError):self.bound.seal(self.root,self.summary)

    def test_late_commit_rejects_sealing_without_rewriting_original_captures(self):
        self.ready()
        originals={name:Path(record['path']).read_bytes() for name,record in self.bound.artifacts.items()}
        self.runtime.orders.commit('a',{'idempotency_key':'two'})
        with self.assertRaisesRegex(ValueError,'ledger changed'):
            self.bound.seal(self.root,self.summary)
        self.assertFalse((self.root/'order-capsule.private.json').exists())
        self.assertEqual(len(self.runtime.orders.snapshot()['orders']),2)
        for name,record in self.bound.artifacts.items():
            self.assertEqual(Path(record['path']).read_bytes(),originals[name])
        with self.assertRaises(ValueError):self.runtime.orders.commit('a',{'idempotency_key':'three'})

    def test_duplicate_missing_and_foreign_phase_rejected(self):
        with self.assertRaises(ValueError):self.bound.after(None,self.trace,self.summary)
        self.bound.before(None,self.trace)
        with self.assertRaises(ValueError):self.bound.before(None,self.trace)
        with self.assertRaises(ValueError):self.bound.after(None,SimpleNamespace(directory=self.root,episode_id='episode'),self.summary)
        self.bound.after(None,self.trace,self.summary)
        with self.assertRaises(ValueError):self.bound.after(None,self.trace,self.summary)
        with self.assertRaises(ValueError):self.bound.seal(self.root/'other',self.summary)

    def test_terminal_failure_retained_and_cannot_become_policy_completion(self):
        self.summary.update(stop_reason='step_limit',truncated=True)
        self.ready()
        capsule,complete=self.bound.seal(self.root,self.summary)
        self.assertFalse(complete);self.assertIsNone(capsule['effect_journal'])

    def test_mismatched_summary_rejected_without_capsule(self):
        self.ready()
        with self.assertRaises(ValueError):self.bound.seal(self.root,{**self.summary,'stop_reason':'step_limit'})
        self.assertFalse((self.root/'order-capsule.private.json').exists())

    def test_tampered_snapshot_or_terminal_document_rejected(self):
        for name in ('after','terminal'):
            with self.subTest(name=name):
                # Fresh independent capture paths per tamper case.
                folder=self.root/name;folder.mkdir()
                trace=SimpleNamespace(directory=folder,episode_id=name)
                (folder/'metadata.json').write_text(json.dumps({'episode_id':name}))
                (folder/'steps.jsonl').write_text('')
                baskets=SimpleNamespace(adapter=SimpleNamespace(world={'world_id':'world'},retailers={'a':{}}),plan_id='p',domain_id='d')
                runtime=SimpleNamespace(orders=OrderStore(baskets,runtime_id=name,record_maker=lambda *a,**kw:{}))
                observer=capture.OrderCapture(runtime,self.task,source_files=self.files)
                observer.before(None,trace);observer.after(None,trace,self.summary)
                record=observer.artifacts['after'] if name=='after' else observer.outcome_artifact
                Path(record['path']).write_text('{}')
                with self.assertRaises(ValueError):observer.seal(folder,self.summary)

    def test_swapped_store_or_source_drift_rejected(self):
        self.bound.before(None,self.trace)
        self.runtime.orders=object()
        with self.assertRaises(ValueError):self.bound.after(None,self.trace,self.summary)
        missing=self.root/'source.py';missing.write_text('initial')
        files={**self.files,str(missing):sha256(missing.read_bytes()).hexdigest()}
        self.runtime.orders=self.bound.store
        observer=capture.OrderCapture(self.runtime,self.task,source_files=files)
        missing.write_text('changed')
        with self.assertRaises(ValueError):observer._check()

    def test_task_wrapper_delegates_ordinary_setup_and_real_private_phase_callbacks(self):
        class BaseTask:
            def __init__(self,public,*,origins,files,attachments,headless,profile_name):
                self.public=public;self.policy_navigation_origins=origins;self.files=files
                self.attachments=attachments;self.headless=headless
                self.supported_harness_profiles=(profile_name,)
            def make_env(self,video=None):
                class Start:
                    def setup(self,page):return 'ordinary-start'
                return SimpleNamespace(unwrapped=SimpleNamespace(task_entrypoint=Start))
            def capture_initial(self,env,observation,info):return {'ordinary_initial':True}
            def evaluate(self,env,trace,outcome):return 'ordinary-evaluation'
        base=BaseTask({'task_id':'task'},origins=['https://shop.test'],files=self.files,
                      attachments={},headless=True,profile_name='profile')
        plan={'authored':'ordinary-cart-plan'}
        task=capture.prepared_task(base,self.bound,plan,self.runtime)
        env=task.make_env();page=object()
        with patch('environments.website_world.short_task_setup.apply',return_value={'ordinary_controls_used':True}) as ordinary:
            self.assertEqual(env.unwrapped.task_entrypoint().setup(page),'ordinary-start')
            ordinary.assert_called_once_with(page,plan,runtime=self.runtime)
        task.trace=self.trace
        initial=task.capture_initial(env,{},{});self.assertTrue(initial['ordinary_initial'])
        self.assertIn('actual_order_baseline',initial)
        self.runtime.orders.commit('a',{'idempotency_key':'one'})
        self.assertEqual(task.evaluate(env,self.trace,self.summary),'ordinary-evaluation')
        capsule,complete=self.bound.seal(self.root,self.summary)
        self.assertTrue(complete);self.assertEqual(len(capsule['after']['order_snapshot']['orders']),1)
        self.assertIsNone(capsule['effect_journal'])


if __name__=='__main__':unittest.main()
