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
from . import catalog_compare_review_execution as finalization


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
        self.events=[];self.cleanup_error=False;self.corrupt_public=False
        self.projection=True;self.grade=True;self.summary_error=None
        self.viewer_module=ModuleType('agent_trace.adapters.browsergym');self.viewer_module.__file__=__file__
        self.viewer_module.project=lambda directory,**kwargs:{'messages':[{
            'title':'Privileged verifier — not model input','text':(Path(directory)/'evaluation.json').read_text()}]}
        owner=self
        class Episode:
            def __init__(self,output):
                self.public=deepcopy(owner.public)
                path=Path(execution.__file__).resolve()
                self.task=SimpleNamespace(files={str(path):sha256(path.read_bytes()).hexdigest()},make_env=lambda:None)
                self.profile=SimpleNamespace(name='authored')
            def export_private_runtime(self,output):
                output.mkdir()
                for name in ('catalog.private.json','bindings.private.json','navigation-capability.private.json'):
                    (output/name).write_text('{}')
                return output
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
        (trace/'metadata.json').write_text(json.dumps({'episode_id':'episode'}))
        (trace/'policy-task.json').write_text(json.dumps(self.public))
        gate=GradingGate(SimpleNamespace(directory=trace,episode_id='episode'),automatic_grading)
        gate.bind(None,{'goal':policy_goal(self.public)})
        self.events.append('policy-return')
        summary={'stop_reason':'agent_finished','error':self.summary_error,
            'execution_error':None,'cleanup_errors':[],'trace_complete':True}
        gate.pending_external();(trace/'episode.json').write_text(json.dumps(summary))
        if self.corrupt_public:
            (trace/'policy-task.json').write_text(json.dumps({**self.public,'environment_context':{'currency':'USD'}}))
        return trace,summary

    def deferred(self,**kwargs):
        self.assertIn('runtime-close',self.events);self.assertIn('policy-close',self.events)
        self.assertEqual(kwargs['grader_factory'],execution.VariantLinkGrader)
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

    def execute(self):
        with patch.dict('sys.modules',{'agent_trace.adapters.browsergym':self.viewer_module}), \
             patch.object(execution.shared,'load',return_value={}), \
             patch.object(execution,'VariantLinkEpisode',self.Episode), \
             patch.object(finalization,'extract_saved_deferred',side_effect=self.deferred), \
             patch.object(finalization,'publish_finalized_answer',side_effect=self.publish):
            return execution.run(self.recipe,self.folder/'run',policy_session=self.session,
                metadata={},runner_options={'max_steps':1,'max_input_tokens':1000},
                viewer_projection=self.viewer,quota_guard=lambda:self.events.append('quota'),
                extraction_backend_factory=lambda _:None,runner=self.runner)

    def test_prospective_real_gate_finalizes_after_closes_before_first_publication(self):
        result=self.execute();self.assertEqual(result['status'],'graded_and_projected')
        self.assertTrue(result['task_completed'])
        self.assertEqual(self.events,['quota','policy-open','policy-return','policy-close',
            'runtime-close','grade','publish','viewer'])
        evaluation=json.loads((Path(result['trace'])/'evaluation.json').read_text())
        self.assertIsNone(evaluation['authorization_satisfied'])

    def test_cleanup_failure_skips_extraction_and_success(self):
        self.cleanup_error=True;result=self.execute()
        self.assertEqual(result['status'],'system_failure');self.assertNotIn('grade',self.events)

    def test_context_drift_skips_extraction(self):
        self.corrupt_public=True;result=self.execute()
        self.assertEqual(result['status'],'system_failure');self.assertNotIn('grade',self.events)

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
                        metadata={},runner_options={'max_steps':1,'max_input_tokens':1,key:True})
            loader.assert_not_called()


if __name__=='__main__':unittest.main()
