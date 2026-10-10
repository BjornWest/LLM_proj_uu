"""Authored real-gate lifecycle controls; no actual Runtime, browser or model."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from intent_browser.automatic_grading import GradingGate
from intent_browser.connected_world_task import policy_goal
from . import variant_link_execution as execution
from . import saved_answer_lifecycle as lifecycle


class LinkLifecycleControls(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.recipe=self.folder/'recipe';self.recipe.mkdir()
        self.public={'schema_version':'connected-world-manual-v1','task_id':'authored-link',
            'user_message':'Send the selected product link.','memories':[],
            'environment_context':{'currency':'SEK'},'start_url':'https://authored.test/#/product/shoe'}
        (self.recipe/'execution.private.json').write_text(json.dumps({'answer_grading':{
            'mode':'subscription-post-run','model':'authored','reasoning_effort':'low'}}))
        (self.recipe/'pin').mkdir();(self.recipe/'pin/world.private.json').write_text('{}')
        for name in ('variant-link-task.private.json','variant-link-reference.private.json'):
            (self.recipe/name).write_text('{}')
        self.events=[];self.cleanup_error=False;self.corrupt_public=False;self.corrupt_start=False
        self.projection=True;self.grade=True;self.summary_error=None
        self.missing=False;self.omit_returned_completeness=False
        self.run_options={'max_steps':1,'max_input_tokens':1000}
        (self.recipe/'variant-link-task.private.json').write_text(json.dumps(
            {k:self.public[k] for k in ('task_id','memories','user_message')}))
        self.viewer_module=ModuleType('agent_trace.adapters.browsergym');self.viewer_module.__file__=__file__
        self.viewer_module.project=lambda directory,**kwargs:{'messages':[{
            'title':'Privileged verifier — not model input','text':(Path(directory)/'evaluation.json').read_text()}]}
        owner=self
        class Episode:
            def __init__(self,output):
                self.public=deepcopy(owner.public)
                self.answer_grading=json.loads((Path(output)/'execution.private.json').read_bytes())['answer_grading']
                path=Path(execution.__file__).resolve()
                self.site_discovery=None
                self.task=SimpleNamespace(files={str(path):sha256(path.read_bytes()).hexdigest(),
                    str(Path(__file__).resolve()):sha256(Path(__file__).read_bytes()).hexdigest(),
                    **{str(p):sha256(p.read_bytes()).hexdigest() for p in owner.recipe.rglob('*') if p.is_file()}},make_env=lambda:None)
                self.profile=SimpleNamespace(name='authored')
            def export_private_runtime(self,output):
                output.mkdir()
                for name in ('catalog.private.json','bindings.private.json','navigation-capability.private.json'):
                    (output/name).write_text('{}')
                manifest={'files':{str(p.relative_to(output)):sha256(p.read_bytes()).hexdigest()
                                   for p in output.rglob('*') if p.is_file()}}
                (output/'manifest.json').write_text(json.dumps(manifest))
                return manifest
            def __enter__(self):return self
            def __exit__(self,*args):
                owner.events.append('runtime-close')
                if owner.cleanup_error:raise ValueError('Authored Runtime cleanup error')
        self.Episode=Episode

    @contextmanager
    def session(self,**kwargs):
        self.events.append('policy-open')
        try:yield object()
        finally:self.events.append('policy-close')

    def runner(self,*args,output,automatic_grading,**kwargs):
        self.assertEqual(automatic_grading.phase,'external')
        trace=output/'episode';trace.mkdir(parents=True)
        (trace/'steps.jsonl').write_text('')
        (trace/'metadata.json').write_text(json.dumps({'episode_id':'episode','tags':['scripted']}))
        (trace/'policy-task.json').write_text(json.dumps(self.public))
        from .compound_answer_delivery_v1 import SCHEMA,SOURCE
        (trace/'natural-answer.json').write_text(json.dumps({'schema_version':SCHEMA,'source':SOURCE,
            'text':None if self.missing else 'Authored completed link answer',
            'assistant_messages':[] if self.missing else ['Authored completed link answer'],
            'stop_reason':'agent_finished','initial_chat_messages_excluded':0,'technical_error':None,'correctness':None}))
        gate=GradingGate(SimpleNamespace(directory=trace,episode_id='episode'),automatic_grading)
        gate.bind(None,{'goal':policy_goal(self.public)})
        self.events.append('policy-return')
        summary={'stop_reason':'agent_finished','error':self.summary_error,
            'execution_error':None,'cleanup_errors':[],'trace_complete':True,'terminated':False,'truncated':False}
        gate.pending_external();(trace/'episode.json').write_text(json.dumps(summary))
        if self.corrupt_public:
            (trace/'policy-task.json').write_text(json.dumps({**self.public,'environment_context':{'currency':'USD'}}))
        if self.corrupt_start:
            (trace/'policy-task.json').write_text(json.dumps({**self.public,'start_url':'https://different.test/#/product/other'}))
        return trace,{k:v for k,v in summary.items() if not (self.omit_returned_completeness and k=='trace_complete')}

    def deferred(self,**kwargs):
        self.assertIn('runtime-close',self.events);self.assertIn('policy-close',self.events)
        self.assertTrue(callable(kwargs['grader_factory']))
        self.assertEqual(kwargs['inputs']['task'],self.recipe/'variant-link-task.private.json')
        self.events.append('grade')
        if not self.grade:raise ValueError('Authored extraction missing')
        return {'grade':{'structured_claims_correct':True,'limitations':['Authored mock extraction/native grade']}}

    def publish(self,deferred,*,contract_id):
        self.events.append('publish')
        trace=self.folder/'run/runs/episode'
        record=json.loads((trace/'automatic-grading.json').read_text())
        self.assertEqual(record['status'],'graded');self.assertEqual(record['contract_id'],contract_id)
        return deferred['grade']

    def viewer(self,*,trace,grade):
        self.events.append('viewer')
        summary=json.loads((trace/'episode.json').read_text())
        self.assertTrue(summary['infrastructure_completed'])
        return {'status':'verified' if self.projection else 'missing','qualification':'Authored offline projection, no HTTP'}

    def execute(self, *, extraction_backend_factory=lambda _:None):
        with patch.dict('sys.modules',{'agent_trace.adapters.browsergym':self.viewer_module}), \
             patch.object(execution.shared,'load',return_value={}), \
             patch.object(execution,'VariantLinkEpisode',self.Episode), \
             patch.object(lifecycle,'extract_saved_deferred',side_effect=self.deferred), \
             patch.object(lifecycle,'publish_finalized_answer',side_effect=self.publish):
            return execution.run(self.recipe,self.folder/'run',policy_session=self.session,
                metadata={'tags':['scripted']},runner_options=self.run_options,
                viewer_projection=self.viewer,quota_guard=lambda:self.events.append('quota'),
                extraction_backend_factory=extraction_backend_factory,runner=self.runner)

    def test_prospective_real_gate_finalizes_after_closes_before_first_publication(self):
        result=self.execute();self.assertEqual(result['status'],'graded_and_projected')
        self.assertTrue(result['native_grade']['structured_claims_correct'])
        self.assertEqual(self.events,['quota','policy-open','policy-return','policy-close',
            'runtime-close','grade','publish','viewer'])
        evaluation=json.loads((Path(result['trace'])/'evaluation.json').read_text())
        self.assertIsNone(evaluation['authorization_satisfied'])

    def test_omitted_returned_completeness_uses_actual_saved_record(self):
        self.omit_returned_completeness=True
        result=self.execute();self.assertEqual(result['status'],'graded_and_projected')
        self.assertEqual(self.events.count('grade'),1)

    def test_clean_missing_answer_is_published_with_zero_extraction(self):
        self.missing=True
        result=self.execute();self.assertEqual(result['status'],'graded_and_projected')
        self.assertFalse(result['native_grade']['structured_claims_correct'])
        self.assertEqual(result['extraction_requests'],0)
        self.assertNotIn('grade',self.events)
        self.assertEqual(self.events.count('viewer'),1)
        from scripts.trace_grades import read_grade
        displayed=read_grade(result['trace'])
        self.assertEqual(displayed['binding_status'],'verified')
        self.assertFalse(displayed['structured_claims_correct'])

    def test_explicit_unlimited_turns_pass_through_without_a_large_integer(self):
        self.run_options['max_steps']=None
        original=self.runner
        def runner(*args,**kwargs):
            self.assertIsNone(kwargs['max_steps'])
            return original(*args,**kwargs)
        self.runner=runner
        result=self.execute();self.assertEqual(result['status'],'graded_and_projected')

    def test_cleanup_failure_skips_extraction_and_success(self):
        self.cleanup_error=True;result=self.execute()
        self.assertEqual(result['status'],'system_failure');self.assertNotIn('grade',self.events)

    def test_context_drift_skips_extraction(self):
        self.corrupt_public=True;result=self.execute()
        self.assertEqual(result['status'],'system_failure');self.assertNotIn('grade',self.events)

    def test_start_only_drift_rejects_before_answer_or_missing_output_grading(self):
        self.corrupt_start=True
        for missing in (False, True):
            with self.subTest(missing=missing):
                self.missing=missing
                result=self.execute()
                self.assertEqual(result['status'],'system_failure')
                self.assertNotIn('grade',self.events);self.assertNotIn('publish',self.events)
                self.assertNotIn('viewer',self.events)
                self.assertFalse((self.folder/'run/missing-answer-native-grade.json').exists())
                # Each run has independent output and gate state.
                if not missing:
                    import shutil
                    shutil.rmtree(self.folder/'run')

    def test_default_extractor_retains_authenticated_recipe_settings_after_cleanup(self):
        from experiments.answer_grading import task_answer
        configured={'mode':'subscription-post-run','model':'gpt-6-sol','reasoning_effort':'high'}
        (self.recipe/'execution.private.json').write_text(json.dumps({'answer_grading':configured}))
        deferred=self.deferred
        transport=object()
        def extracting(**kwargs):
            self.assertIn('runtime-close',self.events);self.assertIn('policy-close',self.events)
            self.assertIs(kwargs['backend_factory'](self.folder/'transport'),transport)
            return deferred(**kwargs)
        self.deferred=extracting
        with patch.object(task_answer,'SubscriptionTaskExtractor') as constructor:
            constructor.return_value.backend.return_value=transport
            result=self.execute(extraction_backend_factory=None)
            self.assertEqual(result['status'],'graded_and_projected')
            constructor.assert_called_once()
            self.assertEqual(constructor.call_args.kwargs['model'],'gpt-6-sol')
            self.assertEqual(constructor.call_args.kwargs['reasoning_effort'],'high')
            self.assertTrue(callable(constructor.call_args.kwargs['quota_guard']))
            constructor.return_value.backend.assert_called_once_with(self.folder/'transport')

    def test_explicit_extractor_override_is_retained(self):
        from experiments.answer_grading import task_answer
        backend=lambda _:None
        deferred=self.deferred
        def extracting(**kwargs):
            self.assertIs(kwargs['backend_factory'],backend)
            return deferred(**kwargs)
        self.deferred=extracting
        with patch.object(task_answer,'SubscriptionTaskExtractor') as constructor:
            result=self.execute(extraction_backend_factory=backend)
            self.assertEqual(result['status'],'graded_and_projected')
            constructor.assert_not_called()

    def test_missing_output_does_not_construct_configured_extractor(self):
        from experiments.answer_grading import task_answer
        self.missing=True
        with patch.object(task_answer,'SubscriptionTaskExtractor') as constructor:
            result=self.execute(extraction_backend_factory=None)
            self.assertEqual(result['extraction_requests'],0)
            constructor.assert_not_called()

    def test_setup_failure_does_not_dispatch_extraction(self):
        self.summary_error='Authored setup failure';result=self.execute()
        self.assertEqual(result['status'],'system_failure');self.assertNotIn('grade',self.events)

    def test_missing_grade_or_projection_is_system_failure(self):
        self.grade=False;result=self.execute();self.assertEqual(result['status'],'system_failure')
        self.assertEqual(self.events.count('grade'),1);self.assertNotIn('publish',self.events)

    def test_missing_final_projection_is_system_failure(self):
        self.projection=False;result=self.execute();self.assertEqual(result['status'],'system_failure')
        self.assertEqual(self.events.count('grade'),1);self.assertEqual(self.events.count('viewer'),1)

    def test_caller_cannot_replace_contract_or_escape_grading(self):
        with patch.object(execution.shared,'load') as loader:
            for key in ('automatic_grading','allow_ungraded','agent_runtime','episode_task'):
                with self.subTest(key=key),self.assertRaises(ValueError):
                    execution.run('unused','unused',policy_session=lambda:None,viewer_projection=lambda **_:None,
                        metadata={'tags':['scripted']},runner_options={'max_steps':1,'max_input_tokens':1,key:True})
            loader.assert_not_called()


class LinkConstructorControls(unittest.TestCase):
    def test_unlisted_or_changed_grading_input_rejects_before_Runtime(self):
        from . import runtime
        for declared in (False, True):
            with self.subTest(declared=declared), TemporaryDirectory() as folder:
                root=Path(folder)
                original=b'{"answer_grading":{"mode":"subscription-post-run"}}'
                (root/'execution.private.json').write_bytes(original+b' ')
                manifest={'recipe':execution.publication.VERSION,'files':{
                    'execution.private.json':sha256(original).hexdigest()} if declared else {}}
                with patch.object(execution.shared,'load',return_value=manifest), \
                     patch.object(runtime,'Runtime') as constructor, \
                     self.assertRaisesRegex(ValueError,'frozen manifest'):
                    execution.VariantLinkEpisode(root)
                constructor.assert_not_called()

    def test_disabled_grading_rejects_before_capability_or_Runtime(self):
        from . import runtime
        with TemporaryDirectory() as folder:
            root=Path(folder);payload=b'{"answer_grading":{"mode":"off"}}'
            (root/'execution.private.json').write_bytes(payload)
            manifest={'recipe':execution.publication.VERSION,'files':{
                'execution.private.json':sha256(payload).hexdigest()}}
            with patch.object(execution.shared,'load',return_value=manifest), \
                 patch.object(runtime,'Runtime') as constructor, \
                 patch.object(execution.publication,'compile_packet') as compile_packet, \
                 self.assertRaisesRegex(ValueError,'before dispatch'):
                execution.VariantLinkEpisode(root)
            constructor.assert_not_called();compile_packet.assert_not_called()

    def test_export_binds_all_actual_runtime_records(self):
        episode=execution.VariantLinkEpisode.__new__(execution.VariantLinkEpisode)
        episode.runtime=SimpleNamespace(manifest={'world_id':'authored'},bindings={'complete':'bindings'})
        episode.catalog={'siteId':'authored'};episode.capability={'synthetic_control':True}
        episode.public={'task_id':'authored'}
        with TemporaryDirectory() as folder:
            destination=Path(folder)/'runtime'
            manifest=episode.export_private_runtime(destination)
            self.assertEqual(set(manifest['files']),{'runtime.private.json','bindings.private.json',
                'catalog.private.json','navigation-capability.private.json','task.public.json'})
            self.assertEqual(json.loads((destination/'manifest.json').read_bytes()),manifest)
            for name,digest in manifest['files'].items():
                self.assertEqual(sha256((destination/name).read_bytes()).hexdigest(),digest)


if __name__=='__main__':unittest.main()
