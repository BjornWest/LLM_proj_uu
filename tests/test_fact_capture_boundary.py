import json
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from intent_browser.fact_provenance import FactCaptureBoundary
from intent_browser.backend import Completion
from tests.runner_diagnostics import run_episode
from tests.test_ax_explorer import TOKENIZER,node,observation
from intent_browser.ax_explorer import AXConfig
from intent_browser.harness import native_tools_profile,SemanticFeedback
from dataclasses import replace


class CaptureBoundaryTests(unittest.TestCase):
    def test_observer_failures_duplicate_invocation_and_wrong_returns_never_recapture(self):
        for mode in ('pass','twice','before_error','after_error','wrong_return','no_capture','browser_error'):
            with self.subTest(mode=mode):
                calls=[];events=[]
                class Env:
                    def _get_obs(self):
                        calls.append('capture')
                        if mode=='browser_error':raise RuntimeError('native capture failed')
                        return {'axtree_object':{'nodes':[]}}
                env=Env()
                def observer(op):
                    if mode=='before_error':raise RuntimeError('private observer failed')
                    if mode=='no_capture':return {}
                    value=op()
                    if mode=='twice':self.assertIs(op(),value)
                    if mode=='after_error':raise RuntimeError('private observer failed')
                    if mode=='wrong_return':return dict(value)
                    return value
                boundary=FactCaptureBoundary(env,observer,SimpleNamespace(event=lambda *a,**k:events.append((a,k))))
                if mode=='browser_error':
                    with self.assertRaisesRegex(RuntimeError,'native capture failed'):env._get_obs()
                else:
                    value=env._get_obs()
                    self.assertEqual(boundary.confirmed(value),mode in ('pass','twice'))
                    self.assertTrue(value['axtree_object']=={'nodes':[]})
                self.assertEqual(calls,['capture'])
                boundary.close();self.assertNotIn('_get_obs',vars(env))

    def test_existing_instance_override_is_restored(self):
        env=SimpleNamespace(_get_obs=lambda:{})
        original=env._get_obs
        boundary=FactCaptureBoundary(env,lambda op:op(),SimpleNamespace(event=lambda *a,**k:None))
        env._get_obs();boundary.close();self.assertIs(env._get_obs,original)

    @unittest.skipUnless(TOKENIZER.is_file(),'Local Qwen tokenizer required')
    def test_runner_brackets_reset_action_and_fresh_capture_with_exact_object(self):
        order=[];exports=[];pairs={}
        class Env:
            def __init__(self):self.unwrapped=self;self.serial=0
            def _get_obs(self):
                self.serial+=1;order.append('capture')
                return {**observation([node(0,'RootWebArea','Page',[1]),node(1,'button','Read',bid=1)]),
                    'goal':'Read','last_action_error':'','screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self,seed):return self._get_obs(),{}
            def step(self,action):order.append('action');return self._get_obs(),0,False,False,{}
            def close(self):order.append('close')
        class Backend:
            def configure_tools(self,options):self.options=options
            def complete(self,messages):
                order.append('provider')
                return Completion('',{'choices':[{'message':{'role':'assistant','tool_calls':[
                    {'id':'end','type':'function','function':{'name':'send_msg_to_user','arguments':'{"text":"Done"}'}}]},
                    'finish_reason':'tool_calls'}]}, {'messages':messages,**self.options})
        def observer(operation):
            order.append('bracket_before');value=operation();order.append('bracket_after')
            pairs[id(value)]=value;return value
        def source(env,obs,ctx):
            self.assertIs(pairs[id(obs)],obs);exports.append(ctx)
            return {'schema':'ax-fact-sources-v1','sources':[]}
        profile=replace(native_tools_profile(ax_config=AXConfig(str(TOKENIZER),incremental=True)),feedback_factory=SemanticFeedback)
        env=Env()
        with tempfile.TemporaryDirectory() as root:
            path,summary=run_episode(lambda _:env,Backend(),{},root,max_steps=1,harness_profile=profile,
                observation_pipeline=None,before_observation=lambda:None,record_fact_provenance=True,
                fact_source_provider=source,fact_capture_observer=observer)
            self.assertIsNone(summary['error']);self.assertTrue(exports)
            self.assertNotIn('_get_obs',vars(env))
            for i,name in enumerate(order):
                if name=='capture':self.assertEqual(order[i-1:i+2],['bracket_before','capture','bracket_after'])
            self.assertGreaterEqual(order.count('capture'),3)
            self.assertEqual(json.loads((path/'metadata.json').read_text())['fact_recording']['capture_boundary'],'native-full-v1')

    def test_disabled_path_never_installs_or_calls_capture_observer(self):
        class Env:
            def __init__(self):self.unwrapped=self
            def _get_obs(self):return {'goal':'Read','last_action_error':'','screenshot':np.zeros((1,1,3),dtype=np.uint8)}
            def reset(self,seed):return self._get_obs(),{}
            def step(self,action):return self._get_obs(),0,False,False,{}
            def close(self):pass
        class Backend:
            def complete(self,messages):return Completion("send_msg_to_user('Done')",{})
        env=Env()
        with tempfile.TemporaryDirectory() as root,patch('intent_browser.runner.observation_text',return_value='page'):
            path,summary=run_episode(lambda _:env,Backend(),{},root,max_steps=1,record_fact_provenance=False,
                fact_source_provider=lambda *a:self.fail('source callback'),
                fact_capture_observer=lambda op:self.fail('capture observer'))
            self.assertIsNone(summary['error']);self.assertNotIn('_get_obs',vars(env))
            self.assertEqual(list(path.glob('fact-*')),[])

    def test_pipeline_and_non_opt_in_are_rejected_before_environment(self):
        from intent_browser.observation_pipeline import ObservationPipelineConfig
        for kwargs in ({'record_fact_provenance':True,'fact_capture_observer':lambda op:op()},
                       {'record_fact_provenance':True,'fact_source_provider':lambda *a:{},
                        'fact_capture_observer':lambda op:op(),
                        'observation_pipeline':ObservationPipelineConfig(static_origins=('http://fixture',))}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                run_episode(lambda _:self.fail('environment created'),object(),{},**kwargs)

if __name__=='__main__':unittest.main()
