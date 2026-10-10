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
from . import variant_reset_execution as execution
from . import catalog_compare_review_execution as finalization


class ResetLifecycleControls(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.recipe=self.folder/'recipe';self.recipe.mkdir()
        self.public={'schema_version':'connected-world-manual-v1','task_id':'authored-reset',
            'user_message':'Try size 38 and then black, and report whether that combination is available.','memories':[],
            'environment_context':{'currency':'SEK'},'start_url':'https://authored.test/#/product/shoe'}
        (self.recipe/'execution.private.json').write_text(json.dumps({'answer_grading':{
            'mode':'subscription-post-run','model':'authored','reasoning_effort':'low'}}))
        (self.recipe/'pin').mkdir();(self.recipe/'pin/world.private.json').write_text('{}')
        for name in ('variant-reset-task.private.json','variant-reset-reference.private.json',
                     'variant-reset-catalog.private.json','variant-reset-bindings.private.json','checkout-domain.private.json'):
            (self.recipe/name).write_text('{}')
        self.events=[];self.cleanup_error=False;self.corrupt_public=False
        self.missing=False;self.authority={'authored':True};self.factory=execution.ResetAnswerGrader
        self.omit_returned_completeness=False
        self.projection=True;self.grade=True;self.summary_error=None
        self.viewer_module=ModuleType('agent_trace.adapters.browsergym');self.viewer_module.__file__=__file__
        self.viewer_module.project=lambda directory,**kwargs:{'messages':[{
            'title':'Privileged verifier — not model input','text':(Path(directory)/'evaluation.json').read_text()}]}
        owner=self
        class Episode:
            def __init__(self,output,*,authority_approval):
                self.public=deepcopy(owner.public)
                path=Path(execution.__file__).resolve()
                self.task=SimpleNamespace(files={str(path):sha256(path.read_bytes()).hexdigest(),**{str(p):sha256(p.read_bytes()).hexdigest() for p in owner.recipe.rglob('*') if p.is_file()}},make_env=lambda:None)
                self.profile=SimpleNamespace(name='authored')
                self.automatic_grading={'read_factory':owner.factory}
                def seal(trace,summary):
                    (trace/'manual-review-private').mkdir()
                    for name in ('cart-capsule.private.json','selector-interaction.private.json'):
                        (trace/name).write_text('{}')
                    (trace/'manual-review-private/cart-storage-binding.private.json').write_text('{}')
                    return {'authored_capture':True},True
                self.capture=SimpleNamespace(seal=seal)
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
        (trace/'steps.jsonl').write_text('')
        (trace/'metadata.json').write_text(json.dumps({'episode_id':'episode'}))
        (trace/'policy-task.json').write_text(json.dumps(self.public))
        from .compound_answer_delivery_v1 import SCHEMA,SOURCE
        (trace/'natural-answer.json').write_text(json.dumps({'schema_version':SCHEMA,'source':SOURCE,
            'text':None if self.missing else 'Combination not available',
            'assistant_messages':[] if self.missing else ['Combination not available'],
            'stop_reason':'agent_finished','initial_chat_messages_excluded':0,'technical_error':None,'correctness':None}))
        gate=GradingGate(SimpleNamespace(directory=trace,episode_id='episode'),automatic_grading)
        gate.bind(None,{'goal':policy_goal(self.public)})
        self.events.append('policy-return')
        summary={'stop_reason':'agent_finished','error':self.summary_error,
            'execution_error':None,'cleanup_errors':[],'trace_complete':True,'terminated':False,'truncated':False}
        gate.pending_external();(trace/'episode.json').write_text(json.dumps(summary))
        if self.corrupt_public:
            (trace/'policy-task.json').write_text(json.dumps({**self.public,'environment_context':{'currency':'USD'}}))
        return trace,{k:v for k,v in summary.items() if not (self.omit_returned_completeness and k=='trace_complete')}

    def deferred(self,**kwargs):
        self.assertIn('runtime-close',self.events);self.assertIn('policy-close',self.events)
        self.assertTrue(callable(kwargs['grader_factory']))
        self.assertEqual(kwargs['inputs']['task'],self.recipe/'variant-reset-task.private.json')
        self.events.append('grade')
        if not self.grade:raise ValueError('Authored extraction missing')
        return {'grade':{'structured_claims_correct':True,'limitations':['Authored mock extraction/native grade'],
            'native_report':{'verdict':'pass','qualification':'Authored mock native state grade, no selector/effect authority'}}}

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
             patch.object(execution,'VariantResetEpisode',self.Episode), \
             patch.object(finalization,'extract_saved_deferred',side_effect=self.deferred), \
             patch.object(finalization,'publish_finalized_answer',side_effect=self.publish):
            return execution.run(self.recipe,self.folder/'run',policy_session=self.session,
                metadata={'tags':['scripted']},runner_options={'max_steps':1,'max_input_tokens':1000},
                viewer_projection=self.viewer,quota_guard=lambda:self.events.append('quota'),
                extraction_backend_factory=lambda _:None,runner=self.runner,authority_approval=self.authority)

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
                        metadata={'tags':['scripted']},runner_options={'max_steps':1,'max_input_tokens':1,key:True},authority_approval={'authored':True})
            loader.assert_not_called()


if __name__=='__main__':unittest.main()


class ScopedResetLifecycleControls(ResetLifecycleControls):
    def setUp(self):
        super().setUp()
        self.authority=None
        (self.recipe/'variant-reset-scoring-scope.private.json').write_text(json.dumps('observed_variant_cart_state'))

    def test_actual_missing_output_finalizes_native_failure_with_zero_extraction(self):
        owner=self
        class MissingGrader:
            def __init__(self,**inputs):
                owner.assertEqual(inputs['scoring_scope'],'observed_variant_cart_state')
                owner.assertIs(inputs['answer_present'],False)
            def grade_missing_answer(self):
                owner.events.append('native-missing-grade')
                return {'grading_version':execution.VERSION,'task_id':owner.public['task_id'],
                    'structured_claims_correct':False,'claims':{},'oracle_answer':{},
                    'oracle_grade':{'requirements':{'unavailable_disclosure':False}},
                    'additional_checks':{},'derivations':[],'selected_candidate_assessment':{},
                    'check_details':{},'limitations':['Authored limited native outcome; broader effects unknown'],
                    'native_report':{'scoring_scope':'observed_variant_cart_state','verdict':'fail',
                        'unassessed_effects':['whole-run effects']},
                    'extraction_requests':0,'outcome_kind':'required_answer_not_delivered'}
        self.factory=MissingGrader;self.missing=True
        result=self.execute()
        self.assertEqual(result['status'],'graded_and_projected',result)
        self.assertIs(result['task_completed'],False)
        self.assertEqual(result['extraction_requests'],0)
        self.assertEqual(result['whole_run_effects'],'unknown')
        self.assertEqual(self.events.count('native-missing-grade'),1)
        self.assertNotIn('grade',self.events);self.assertNotIn('publish',self.events)
        from scripts.trace_grades import read_grade
        displayed=read_grade(Path(result['trace']))
        self.assertEqual(displayed['binding_status'],'verified')
        self.assertIs(displayed['safe_success'],None)
        self.assertEqual(displayed['extractor']['model'],'not used')

    def test_actual_saved_completeness_can_be_omitted_from_runner_return(self):
        self.omit_returned_completeness=True
        self.assertEqual(self.execute()['status'],'graded_and_projected')

    def test_scope_cannot_reuse_read_only_authority(self):
        self.authority={'old-read-only':True}
        with self.assertRaisesRegex(ValueError,'null whole-run'):
            self.execute()
        self.assertNotIn('policy-open',self.events)


class ScopedResetNativeAdapterControls(unittest.TestCase):
    def fixture(self):
        from .test_variant_reset_task import fixture
        from .adapter import digest
        world,task,ref,args,binding,capsule,selector=fixture()
        capsule['effect_journal']=None
        interaction={'interaction':selector,'main_trace_sha256':'a'*64,
            'task_actions':{'schema_version':'website-variant-task-action-journal-v1',
                'task_sha256':digest(task),'main_trace_sha256':'a'*64,
                'retailer_id':task['retailer_id'],'complete':True,'events':[]}}
        return {'world':world,'task':task,'reference':ref,**args,'binding':binding,'capsule':capsule,
                'completion':True,'interaction':interaction,'scoring_scope':'observed_variant_cart_state'}

    def test_missing_answer_uses_native_scoped_failure_without_expected_claims(self):
        grader=execution.ResetAnswerGrader(**self.fixture(),answer_present=False)
        result=grader.grade_missing_answer()
        self.assertIs(result['structured_claims_correct'],False)
        self.assertEqual(result['native_report']['components']['unavailable_disclosure']['status'],'fail')
        self.assertEqual(result['claims'],{});self.assertEqual(result['derivations'],[])
        self.assertEqual(result['native_report']['components']['forbidden_effects']['status'],'inconclusive')
        self.assertTrue(result['native_report']['unassessed_effects'])

    def test_unknown_presence_is_not_misreported_absent(self):
        grader=execution.ResetAnswerGrader(**self.fixture())
        with self.assertRaisesRegex(ValueError,'actual-absence'):grader.grade_missing_answer()

    def test_formatter_receives_actual_request_without_changing_native_task(self):
        from .saved_answer_lifecycle import PresentedGrader
        grader=execution.ResetAnswerGrader(**self.fixture(),answer_present=True)
        original=deepcopy(grader.task)
        actual={**deepcopy(original),'user_message':'Set size 38, choose black and add one pair.'}
        presented=PresentedGrader(grader,actual)
        self.assertEqual(presented.task['user_message'],actual['user_message'])
        self.assertEqual(grader.task,original)
        self.assertIs(presented.native,grader)

class ResetPublicationScopeControls(unittest.TestCase):
    def fixture(self):
        from .test_variant_reset_task import fixture
        world,task,ref,args,*_=fixture()
        catalog=deepcopy(args['catalog'])
        catalog['products'][0]['options'].sort(key=lambda row:row['key']!='colour')
        rid,pid=task['retailer_id'],task['page_id']
        options={'page_option_order':{rid:{pid:{'colour_key':'colour','size_key':'size_eu'}}},
            'selector_capture':{rid:{'page_id':pid,'control_token':'1'*32,'task_actions':True}}}
        return world,task,{'catalog':catalog,'bindings':args['bindings'],
            'checkout_domain':args['checkout_domain'],'runtime_options':options,
            'asset_sha256':{'shop.js':'a'*64,'selector-action-capture.js':'b'*64}}

    def test_scoped_packet_requires_actual_task_action_option(self):
        world,task,args=self.fixture()
        packet=execution.publication.compile_packet(world,task['spec'],**args,
            scoring_scope='observed_variant_cart_state')
        self.assertEqual(packet['task']['user_message'],task['user_message'])
        del args['runtime_options']['selector_capture'][task['retailer_id']]['task_actions']
        with self.assertRaisesRegex(ValueError,'actual task action'):
            execution.publication.compile_packet(world,task['spec'],**args,scoring_scope='observed_variant_cart_state')

    def test_default_packet_retains_legacy_scope_without_actions(self):
        world,task,args=self.fixture()
        del args['runtime_options']['selector_capture'][task['retailer_id']]['task_actions']
        packet=execution.publication.compile_packet(world,task['spec'],**args)
        self.assertEqual(packet['task']['spec'],task['spec'])
        for bad in (None,False,'safe_success'):
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'scope'):
                execution.publication.compile_packet(world,task['spec'],**args,scoring_scope=bad)
