"""Prospective dispatch gate and real shared viewer; no model/network/browser calls."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tempfile
import sys

# Same explicitly positioned sibling dependency as the documented local viewer.
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"common_agent_util"))
import unittest
from unittest.mock import patch
import numpy as np

from intent_browser.automatic_grading import (AutomaticGrading, GradingGate, file_hash,
    canonical_viewer_check, finalize_external, validate_options)
from intent_browser.backend import Completion
from intent_browser.evaluation import Evaluation
from intent_browser.runner import run_episode


def binding(env,trace,obs):
    return {'task_id':'synthetic-native','goal_sha256':hashlib.sha256(obs['goal'].encode()).hexdigest(),
        'reference_files':{str(env.reference):file_hash(env.reference)},
        'source_files':{str(p):file_hash(p) for p in
            (Path(__file__).resolve(),Path(__import__('intent_browser.automatic_grading',fromlist=['x']).__file__).resolve(),
             Path(__import__('agent_trace.adapters.browsergym',fromlist=['x']).__file__).resolve())}}


def grade(env,trace,outcome):
    record=json.loads((trace.directory/'native-state.json').read_text())
    return {'task_id':'synthetic-native','closed':record['closed'],'done':record['done']}


def project(raw,bound):
    return Evaluation('synthetic-state','v1',trust='native_state',task_completed=raw['done'],
        authorization_satisfied=True,limitations=['Synthetic native state only'])


def bad_viewer(trace,value):return None


def manual_project(raw,bound):return Evaluation('manual-review','1',task_completed=True)


def manual_trust_project(raw,bound):
    return Evaluation('native-looking-name','1',trust='manual_browser_phase',task_completed=True)


def tamper_viewer(trace,value):
    (trace.directory/'automatic-grade.json').write_text('{}')
    return canonical_viewer_check(trace,value)


class GradingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ref=self.root/'reference.json';self.ref.write_text('{"goal":"Read"}')
        self.contract=AutomaticGrading('synthetic:v1',binding,grade,project)

    def episode(self,contract=None,**kwargs):
        events=[];test=self
        provider_failure=kwargs.pop('provider_failure',False)
        close_failure=kwargs.pop('close_failure',False)
        class Env:
            reference=test.ref
            closed=False;done=False
            @property
            def unwrapped(self):return self
            def reset(self,seed):
                events.append('reset')
                return {'goal':'Read','last_action_error':'','screenshot':np.zeros((2,2,3),dtype=np.uint8)},{}
            def step(self,action):
                events.append('step');self.done=action.startswith('send_msg_to_user')
                return self.reset(0)[0],0,False,False,{}
            def close(self):
                events.append('close');self.closed=True
                if close_failure:raise RuntimeError('mock cleanup failed')
        class Model:
            calls=0;messages=None
            def complete(self,messages):
                self.calls+=1;self.messages=messages;events.append('provider')
                if provider_failure:raise RuntimeError('mock transport failed')
                return Completion("send_msg_to_user('Done')",{'fixture':True})
        class Task:
            def prepare(self,trace):self.trace=trace;return {}
            def capture_initial(self,*args):return {}
            def evaluate(self,env,trace,outcome):
                events.append('browser-evaluation')
                from intent_browser.trace import write_json
                write_json(trace.directory/'native-state.json',{'done':env.done,'closed':env.closed})
                return Evaluation('browser-phase','1',trust='manual',task_completed=True)
        env=Env();model=Model();task=Task()
        original_grade=contract.grade if contract else None
        if contract:
            # Original callback executes against a retained snapshot at the declared phase.
            def track_grade(e,t,o):
                events.append('grade')
                record=json.loads((t.directory/'native-state.json').read_text());record['closed']=e.closed if e else env.closed
                (t.directory/'native-state.json').write_text(json.dumps(record))
                return original_grade(e,t,o)
            contract=replace(contract,grade=track_grade)
        with patch('intent_browser.runner.observation_text',return_value='page'):
            directory,summary=run_episode(lambda _:env,model,{},self.root/'runs',max_steps=1,
                episode_task=task,automatic_grading=contract,**kwargs)
        return directory,summary,events,model,env,contract

    def test_missing_or_implicit_grader_blocks_before_environment_and_provider(self):
        for options in ({},{'allow_ungraded':True},{'ungraded_reason':'manual'},
                        {'allow_ungraded':'yes'},{'automatic_grading':object()}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                run_episode(lambda _:self.fail('created environment'),object(),{},**options)

    def test_before_and_after_close_grade_once_actual_viewer_and_no_policy_leak(self):
        for phase in ('before_close','after_close'):
            with self.subTest(phase=phase):
                p,s,events,m,e,_=self.episode(replace(self.contract,phase=phase))
                self.assertIsNone(s['error']);self.assertTrue(s['success']);self.assertTrue(s['infrastructure_completed'])
                self.assertEqual(events.count('grade'),1)
                self.assertLess(events.index('grade'),events.index('close')) if phase=='before_close' else self.assertGreater(events.index('grade'),events.index('close'))
                self.assertEqual(json.loads((p/'automatic-grade.json').read_text())['raw_grade']['closed'],phase=='after_close')
                self.assertTrue(json.loads((p/'automatic-grade-projection.json').read_text())['verified'])
                self.assertNotIn('synthetic-native',json.dumps(m.messages));self.assertNotIn(str(self.ref),json.dumps(m.messages))
                self.assertEqual(json.loads((p/'episode.json').read_text())['evaluation'],s['evaluation'])
                self.assertEqual(json.loads((p/'evaluation-before-close.json').read_text())['verifier'],'browser-phase')

    def test_explicit_diagnostic_is_recorded_and_never_graded(self):
        p,s,*_=self.episode(allow_ungraded=True,ungraded_reason='Inspect browser capture')
        self.assertEqual(s['grading']['status'],'explicitly_ungraded');self.assertEqual(s['grading']['reason'],'Inspect browser capture')
        self.assertIsNone(s['success']);self.assertFalse(s['infrastructure_completed']);self.assertFalse((p/'automatic-grade.json').exists())

    def test_missing_projection_manual_verdict_and_tampered_native_are_system_failures(self):
        for contract in (replace(self.contract,viewer_check=bad_viewer),replace(self.contract,project=manual_project),
                         replace(self.contract,viewer_check=tamper_viewer),replace(self.contract,project=manual_trust_project)):
            with self.subTest(contract=contract):
                p,s,events,m,*_=self.episode(contract)
                self.assertEqual(m.calls,1);self.assertIsNotNone(s['grading_error'])
                self.assertEqual(s['evaluation']['trust'],'infrastructure_failure');self.assertIsNone(s['evaluation']['task_completed'])
                self.assertIsNone(s['success']);self.assertFalse(s['infrastructure_completed'])
                self.assertTrue((p/'evaluation-before-close.json').exists())

    def test_external_native_grade_pending_until_explicit_finalization(self):
        p,s,events,m,e,c=self.episode(replace(self.contract,phase='external'))
        self.assertEqual(s['grading']['status'],'pending_external');self.assertIsNone(s['success']);self.assertFalse(s['infrastructure_completed'])
        self.assertNotIn('grade',events);self.assertTrue(e.closed)
        after=finalize_external(p,c)
        self.assertTrue(after['success']);self.assertTrue(after['infrastructure_completed']);self.assertEqual(events.count('grade'),1)
        with self.assertRaises(ValueError):finalize_external(p,c)

    def test_external_changed_reference_fails_without_native_call(self):
        p,s,events,m,e,c=self.episode(replace(self.contract,phase='external'))
        self.ref.write_text('changed')
        after=finalize_external(p,c)
        self.assertNotIn('grade',events);self.assertIsNone(after['success']);self.assertEqual(after['grading']['status'],'failed')
        self.assertIn('binding differs',after['grading_error'])

    def test_actual_goal_and_callback_source_binding_required_before_first_request(self):
        for mode in ('goal','source'):
            def bad_binding(env,trace,obs):
                result=binding(env,trace,obs)
                if mode=='goal':result['goal_sha256']='0'*64
                else:result['source_files'].pop(str(Path(__file__).resolve()))
                return result
            p,s,events,m,*_=self.episode(replace(self.contract,bind=bad_binding))
            self.assertEqual(m.calls,0);self.assertIn('binding',s['error']);self.assertFalse(s['infrastructure_completed'])

    def test_reference_change_after_capture_blocks_dispatch(self):
        def mutate():self.ref.write_text('changed')
        with patch('intent_browser.runner.refresh_observation',side_effect=lambda env:env.reset(0)[0]):
            p,s,events,m,*_=self.episode(self.contract,before_observation=mutate)
        self.assertEqual(m.calls,0);self.assertIn('binding changed',s['error']);self.assertIsNone(s['success'])

    def test_provider_error_keeps_native_grade_but_no_false_success(self):
        p,s,*_=self.episode(self.contract,provider_failure=True)
        self.assertIn('mock transport failed',s['error']);self.assertIsNone(s['success'])
        self.assertIsNone(s['evaluation']['safe_success']);self.assertTrue((p/'automatic-grade.json').exists())
        self.assertFalse(s['infrastructure_completed']);self.assertEqual(s['grading']['status'],'graded')

    def test_cleanup_error_is_distinct_from_task_verdict_and_never_success(self):
        p,s,events,m,*_=self.episode(self.contract,close_failure=True)
        self.assertTrue(s['evaluation']['task_completed']);self.assertIsNone(s['evaluation']['safe_success'])
        self.assertIsNone(s['grading_error']);self.assertFalse(s['infrastructure_completed'])
        self.assertIsNone(s['execution_error']);self.assertEqual(s['cleanup_errors'][0]['phase'],'browsergym_close')
        self.assertEqual(events.count('grade'),1);self.assertTrue((p/'automatic-grade.json').exists())

    def test_auxiliary_episode_has_explicit_root_scope_without_fabricated_task_grade(self):
        import re
        from intent_browser.harness import native_tools_profile,with_subagents,SemanticFeedback
        from intent_browser.delegation import NoBrowserEnv,AgentLimits
        profile=with_subagents(replace(native_tools_profile(),feedback_factory=SemanticFeedback),AgentLimits(child_steps=2,total_model_calls=5))
        class Model:
            requires_browser_thread=True
            def __init__(self):self.request_options={};self.root_calls=0
            def configure_tools(self,options):self.request_options=options
            def complete(self,messages):
                tools=self.request_options['tools']
                root=any(t['function']['name']=='spawn_agent' for t in tools)
                if root:
                    self.root_calls+=1
                    if self.root_calls==1:name,args='spawn_agent',{'task':'Reason about public evidence','browser':'none'}
                    elif self.root_calls==2:
                        target=re.findall(r'"agent_id":\s*"([^" ]+)"',json.dumps(messages).replace('\\"','"'))[-1]
                        name,args='wait_agent',{'agent_id':target,'timeout_seconds':1}
                    else:name,args='send_msg_to_user',{'text':'Done'}
                else:name,args='send_msg_to_user',{'text':'Public result'}
                raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
                    'tool_calls':[{'id':f'call-{root}-{self.root_calls}','type':'function',
                    'function':{'name':name,'arguments':json.dumps(args)}}]}}]}
                return Completion('',raw)
        p,s=run_episode(lambda _:NoBrowserEnv('Read'),Model(),{},self.root/'helpers',max_steps=4,
            harness_profile=profile,allow_ungraded=True,ungraded_reason='Offline auxiliary scope diagnostic')
        self.assertIsNone(s['error'])
        children=list((p/'children').glob('*/episode.json'));self.assertEqual(len(children),1)
        child=json.loads(children[0].read_text())
        self.assertIsNone(child['error']);self.assertEqual(child['grading']['status'],'auxiliary')
        self.assertEqual(child['grading']['auxiliary_parent']['root_episode_id'],p.name)
        self.assertIsNone(child['evaluation']['task_completed']);self.assertFalse(child['infrastructure_completed'])

    def test_native_grader_exception_is_system_failure_once(self):
        original_grade=grade
        def fail_close_native(env,trace,outcome):
            native=original_grade(env,trace,outcome)
            raise RuntimeError('native grader crashed')
        p,s,events,m,*_=self.episode(replace(self.contract,grade=fail_close_native))
        self.assertIn('native grader crashed',s['grading_error']);self.assertIsNone(s['evaluation']['task_completed'])
        self.assertEqual(events.count('grade'),1);self.assertEqual(m.calls,1)

    def test_interrupted_native_grading_closes_and_records_failure_without_regrading(self):
        def interrupted_grade(env,trace,outcome):
            raise KeyboardInterrupt('native grading interrupted')
        for phase in ('before_close','after_close','external'):
            with self.subTest(phase=phase):
                p,s,events,m,e,c=self.episode(replace(self.contract,grade=interrupted_grade,phase=phase))
                if phase=='external':s=finalize_external(p,c)
                self.assertTrue(e.closed);self.assertEqual(events.count('close'),1)
                self.assertEqual(events.count('grade'),1);self.assertEqual(m.calls,1)
                self.assertIn('KeyboardInterrupt',s['grading_error'])
                self.assertEqual(s['grading']['status'],'failed');self.assertIsNone(s['success'])
                self.assertFalse(s['infrastructure_completed'])
                self.assertEqual(json.loads((p/'episode.json').read_text())['evaluation'],s['evaluation'])

    def test_automatic_projection_requires_nonempty_string_declarations(self):
        for name in ('verifier','verifier_version','trust'):
            for invalid in (None,'','   ',42,[]):
                def invalid_project(raw,bound):
                    result=project(raw,bound);setattr(result,name,invalid);return result
                with self.subTest(field=name,value=invalid):
                    p,s,*_=self.episode(replace(self.contract,project=invalid_project))
                    self.assertIn(name+' declaration',s['grading_error'])
                    self.assertIsNone(s['success']);self.assertFalse(s['infrastructure_completed'])
                    self.assertTrue((p/'automatic-grade.json').is_file())

    def test_whitespace_and_case_do_not_disguise_manual_projection(self):
        for name,invalid in (('trust','  Manual_browser_phase  '),('verifier',' Manual-Review ')):
            def invalid_project(raw,bound):
                result=project(raw,bound);setattr(result,name,invalid);return result
            with self.subTest(field=name):
                _,s,*_=self.episode(replace(self.contract,project=invalid_project))
                self.assertIn('Manual/ungraded',s['grading_error']);self.assertIsNone(s['success'])

    def test_external_native_technical_error_reaches_summary_without_losing_original_grade(self):
        def error_project(raw,bound):
            value=project(raw,bound);value.technical_error='native grading database unavailable';return value
        for provider_failure in (False,True):
            with self.subTest(provider_failure=provider_failure):
                p,s,events,m,e,c=self.episode(replace(self.contract,project=error_project,phase='external'),
                    provider_failure=provider_failure)
                after=finalize_external(p,c)
                self.assertEqual(after['error'],s['error'] or 'native grading database unavailable')
                self.assertEqual(after['evaluation']['technical_error'],after['error'])
                self.assertEqual(after['execution_error'],s['execution_error'])
                self.assertIsNone(after['grading_error']);self.assertIsNone(after['success'])
                self.assertFalse(after['infrastructure_completed']);self.assertEqual(events.count('grade'),1)
                self.assertEqual(json.loads((p/'automatic-grade.json').read_text())['raw_grade']['done'],
                    not provider_failure)
                self.assertEqual(json.loads((p/'episode.json').read_text())['error'],after['error'])

    def test_recording_failure_cannot_publish_success_even_if_grader_passes(self):
        from intent_browser.trace import Trace
        original=Trace.finish
        def failed_finish(trace,summary):
            original(trace,summary)
            raise RuntimeError('recording incomplete')
        with patch('intent_browser.runner.Trace.finish',failed_finish):
            p,s,*_=self.episode(self.contract)
        self.assertFalse(s['infrastructure_completed']);self.assertIsNone(s['success'])
        self.assertEqual(s['grading']['status'],'failed')
        self.assertFalse(json.loads((p/'episode.json').read_text())['trace_complete'])
        self.assertIsNone(json.loads((p/'evaluation.json').read_text())['safe_success'])

    def test_early_trace_finish_failure_still_saves_a_discoverable_episode(self):
        from intent_browser.trace import Trace
        original_event=Trace.event
        traces=[]
        def failed_event(trace,kind,**data):
            if kind=='episode_finished':
                traces.append(trace)
                raise RuntimeError('lifecycle finalization failed')
            return original_event(trace,kind,**data)
        with patch.object(Trace,'event',failed_event):
            p,s,*_=self.episode(self.contract)
        saved=json.loads((p/'episode.json').read_text())
        self.assertIn('lifecycle finalization failed',s['grading_error'])
        self.assertFalse(saved['trace_complete']);self.assertIsNone(saved['success'])
        self.assertFalse(saved['infrastructure_completed']);self.assertEqual(saved['episode_id'],p.name)
        self.assertEqual(saved['steps_file'],'steps.jsonl');self.assertEqual(saved['events_file'],'events.jsonl')
        self.assertEqual(saved['evaluation'],json.loads((p/'evaluation.json').read_text()))
        self.assertEqual(saved['grading']['status'],'failed');self.assertTrue((p/'automatic-grade.json').is_file())
        self.assertTrue(traces[0].events.closed);self.assertTrue(traces[0].lifecycle.closed)

    def test_interrupted_trace_finish_closes_writer_and_preserves_failure(self):
        from intent_browser.observation_writer import ObservationWriter
        original_close=ObservationWriter.close
        writers=[]
        def interrupted_close(writer):
            if not writers:
                writers.append(writer)
                raise KeyboardInterrupt('recording close interrupted')
            return original_close(writer)
        with patch.object(ObservationWriter,'close',interrupted_close):
            p,s,*_=self.episode(self.contract)
        saved=json.loads((p/'episode.json').read_text())
        self.assertTrue(writers[0].closed);self.assertFalse(writers[0].pending)
        self.assertIn('KeyboardInterrupt: recording close interrupted',saved['grading_error'])
        self.assertFalse(saved['trace_complete']);self.assertIsNone(saved['success'])
        self.assertEqual(saved['evaluation'],s['evaluation'])

    def test_concurrent_external_claim_rejects_second_without_regrading(self):
        p,s,events,m,e,c=self.episode(replace(self.contract,phase='external'))
        (p/'automatic-grading-finalization.lock').write_text('other finalizer')
        with self.assertRaises(FileExistsError):finalize_external(p,c)
        self.assertNotIn('grade',events)
        self.assertEqual(json.loads((p/'automatic-grading.json').read_text())['status'],'pending_external')

    def test_changed_external_callback_cannot_take_over_same_contract_id(self):
        p,s,events,m,e,c=self.episode(replace(self.contract,phase='external'))
        with self.assertRaisesRegex(ValueError,'matching pending'):
            finalize_external(p,replace(c,project=manual_project))
        self.assertNotIn('grade',events)
        self.assertFalse((p/'automatic-grading-finalization.lock').exists())

    def test_absent_pre_dispatch_viewer_callable_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'viewer_check'):
            validate_options(replace(self.contract,viewer_check=None),False,None)

if __name__=='__main__':unittest.main()
