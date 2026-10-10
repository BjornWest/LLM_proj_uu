"""Scoped native and real automatic-gate controls; synthetic, zero providers."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from . import atomic_product_execution_consumer as consumer
from . import catalog_compare_review_execution as finalization
from .test_atomic_product_tasks import fixture
from .test_variant_reset_execution import ResetLifecycleControls as _ResetControls
from .adapter import digest


def inputs(kind='read_listed_price'):
    world, task, ref, args, binding, capsule = fixture(kind)
    capsule['effect_journal'] = None
    actions = {'schema_version':'website-atomic-task-action-journal-v1',
        'task_sha256':digest(task),'main_trace_sha256':capsule['main_trace_sha256'],
        'retailer_id':task['retailer_id'],'complete':True,'events':[]}
    if kind == 'add_exact_quantity':
        actions['events'] = [{'kind':'cart_add','offer_id':task['offer_id'],'quantity':2}]
    return dict(world=world, task=task, reference=ref, **args, binding=binding,
        capsule=capsule, completion=True, scoring_scope='observed_atomic_state',
        interaction={'main_trace_sha256':capsule['main_trace_sha256'],'task_actions':actions})


@pytest.mark.parametrize('kind',['select_exact_variant','add_exact_quantity'])
def test_action_consumer_uses_actual_native_journal_without_formatter(kind):
    result=consumer.AtomicOutcomeGrader(**inputs(kind)).grade_outcome()
    assert result['native_report']['verdict']=='pass'
    assert result['extraction_requests']==0
    assert result['native_report']['unassessed_effects']
    assert result['native_report']['components']['forbidden_effects']['status']=='inconclusive'


@pytest.mark.parametrize('kind',['select_exact_variant','add_exact_quantity'])
def test_transient_remove_is_not_hidden_by_correct_terminal_cart(kind):
    values=inputs(kind)
    values['interaction']['task_actions']['events'].append(
        {'kind':'cart_remove','offer_id':'shop/black39','quantity':1})
    values['interaction']['task_actions']['complete']=False
    assert consumer.AtomicOutcomeGrader(**values).grade_outcome()['native_report']['verdict']=='fail'


@pytest.mark.parametrize('kind',['read_listed_price','read_public_fact'])
def test_clean_missing_read_is_native_failure_without_claims_or_extraction(kind):
    result=consumer.AtomicReadGrader(**inputs(kind),answer_present=False).grade_missing_answer()
    assert result['native_report']['verdict']=='fail'
    assert result['extraction_requests']==0
    assert result['claims']=={} and result['derivations']==[]


def test_unknown_read_presence_cannot_be_relabelled_missing():
    with pytest.raises(ValueError,match='actual-absence'):
        consumer.AtomicReadGrader(**inputs()).grade_missing_answer()


def test_outer_trace_mismatch_does_not_borrow_complete_journal():
    values=inputs('select_exact_variant')
    values['interaction']['main_trace_sha256']='b'*64
    assert consumer.AtomicOutcomeGrader(**values).grade_outcome()['native_report']['verdict']=='inconclusive'


def test_scoped_packet_keeps_native_task_and_requires_actual_target_assets():
    values=inputs('select_exact_variant')
    task=values['task']
    args={k:values[k] for k in ('catalog','bindings','checkout_domain','scoring_scope')}
    args['runtime_options']={'selector_capture':{task['retailer_id']:{
        'page_id':task['page_id'],'control_token':'1'*32,'task_actions':True}}}
    args['asset_sha256']={'shop.js':'a'*64,'selector-action-capture.js':'b'*64}
    assert consumer.publication.compile_packet(values['world'],task['spec'],**args)['task']==task
    bad=deepcopy(args);del bad['runtime_options']['selector_capture']['shop']['task_actions']
    with pytest.raises(ValueError,match='exact native page'):
        consumer.publication.compile_packet(values['world'],task['spec'],**bad)
    bad=deepcopy(args);del bad['asset_sha256']['selector-action-capture.js']
    with pytest.raises(ValueError,match='assets'):
        consumer.publication.compile_packet(values['world'],task['spec'],**bad)


class AtomicLifecycleControls(_ResetControls):
    """Reuse the reviewed real gate/terminal fixtures with atomic consumers."""
    def setUp(self):
        super().setUp()
        self.authority=None
        self.public['task_id']='authored-atomic'
        self.public['user_message']='Read the listed price for this selected product.'
        for suffix in ('task','reference','catalog','bindings'):
            (self.recipe/f'atomic-product-{suffix}.private.json').write_text(
                json.dumps({'kind':'read_listed_price'}) if suffix=='task' else '{}')
        (self.recipe/'atomic-product-scoring-scope.private.json').write_text(json.dumps('observed_atomic_state'))
        for filename in ('atomic-product-runtime-options.private.json','atomic-product-assets.private.json'):
            (self.recipe/filename).write_text('{}')
        owner=self
        class Episode:
            def __init__(self,*args,**kwargs):
                self.public=deepcopy(owner.public)
                path=Path(consumer.__file__).resolve()
                self.task=SimpleNamespace(files={str(path):sha256(path.read_bytes()).hexdigest(),
                    **{str(p):sha256(p.read_bytes()).hexdigest() for p in owner.recipe.rglob('*') if p.is_file()}},
                    make_env=lambda:None)
                self.profile=SimpleNamespace(name='synthetic')
                self.automatic_grading={'read_factory':owner.factory,'outcome_factory':owner.factory}
                def seal(trace,summary):
                    (trace/'manual-review-private').mkdir()
                    for name in ('cart-capsule.private.json','selector-interaction.private.json'):
                        (trace/name).write_text('{}')
                    (trace/'manual-review-private/cart-storage-binding.private.json').write_text('{}')
                    return {'synthetic':True},True
                self.capture=SimpleNamespace(seal=seal,selector_artifacts={})
            def __enter__(self):return self
            def __exit__(self,*args):
                owner.events.append('runtime-close')
                if owner.cleanup_error:raise ValueError('Authored Runtime cleanup error')
        self.Episode=Episode

    def deferred(self,**kwargs):
        self.assertIn('runtime-close',self.events);self.assertIn('policy-close',self.events)
        self.assertEqual(kwargs['inputs']['task'],self.recipe/'atomic-product-task.private.json')
        self.events.append('grade')
        if not self.grade:raise ValueError('Authored extraction missing')
        return {'grade':{'structured_claims_correct':True,'limitations':['Synthetic gate/native fixture'],
            'native_report':{'verdict':'pass','scoring_scope':'observed_atomic_state'}}}

    def execute(self):
        with patch.dict('sys.modules',{'agent_trace.adapters.browsergym':self.viewer_module}), \
             patch.object(consumer.shared,'load',return_value={'files':{
                 str(p.relative_to(self.recipe)):sha256(p.read_bytes()).hexdigest()
                 for p in self.recipe.rglob('*') if p.is_file()}}), \
             patch.object(consumer,'AtomicProductEpisode',self.Episode), \
             patch.object(finalization,'extract_saved_deferred',side_effect=self.deferred), \
             patch.object(finalization,'publish_finalized_answer',side_effect=self.publish):
            return consumer.run(self.recipe,self.folder/'run',policy_session=self.session,
                metadata={'tags':['scripted']},runner_options={'max_steps':1,'max_input_tokens':1000},
                viewer_projection=self.viewer,quota_guard=lambda:self.events.append('quota'),
                extraction_backend_factory=lambda _:None,runner=self.runner,authority_approval=self.authority)

    def test_no_whole_run_authority_reuse(self):
        self.authority={'old':True}
        with self.assertRaisesRegex(ValueError,'null whole-run'):self.execute()
        self.assertNotIn('policy-open',self.events)

    def _native_result(self,verdict):
        return {'grading_version':consumer.VERSION,'task_id':self.public['task_id'],
            'structured_claims_correct':verdict=='pass','claims':{},'oracle_answer':{},
            'oracle_grade':{'requirements':{}},'additional_checks':{},'derivations':[],
            'selected_candidate_assessment':{},'check_details':{},'limitations':['Synthetic native outcome'],
            'native_report':{'verdict':verdict,'scoring_scope':'observed_atomic_state',
                'unassessed_effects':['whole-run effects']},'extraction_requests':0}

    def test_missing_read_publishes_once_with_zero_extraction(self):
        self.missing=True;owner=self
        class Missing:
            def __init__(self,**values):
                owner.assertIs(values['answer_present'],False)
                owner.assertEqual(values['scoring_scope'],'observed_atomic_state')
            def grade_missing_answer(self):
                owner.events.append('native-missing-grade');return owner._native_result('fail')
        self.factory=Missing
        result=self.execute();self.assertEqual(result['status'],'graded_and_projected',result)
        self.assertIs(result['task_completed'],False);self.assertEqual(result['extraction_requests'],0)
        self.assertNotIn('grade',self.events);self.assertEqual(self.events.count('native-missing-grade'),1)
        from scripts.trace_grades import read_grade
        displayed=read_grade(Path(result['trace']))
        self.assertEqual(displayed['binding_status'],'verified');self.assertIsNone(displayed['safe_success'])

    def test_action_publishes_once_without_answer_formatter(self):
        (self.recipe/'atomic-product-task.private.json').write_text(json.dumps({'kind':'add_exact_quantity'}))
        owner=self
        class Outcome:
            def __init__(self,**values):owner.assertEqual(values['scoring_scope'],'observed_atomic_state')
            def grade_outcome(self):
                owner.events.append('native-action-grade');return owner._native_result('pass')
        self.factory=Outcome
        result=self.execute();self.assertEqual(result['status'],'graded_and_projected',result)
        self.assertIs(result['task_completed'],True);self.assertEqual(result['extraction_requests'],0)
        self.assertNotIn('grade',self.events);self.assertEqual(self.events.count('native-action-grade'),1)


@pytest.mark.parametrize('name',['atomic-product-scoring-scope.private.json',
    'atomic-product-runtime-options.private.json','atomic-product-assets.private.json'])
def test_unlisted_or_changed_scope_sidecars_are_rejected_before_runtime(tmp_path,name):
    records={'atomic-product-scoring-scope.private.json':'observed_atomic_state',
        'atomic-product-runtime-options.private.json':{},'atomic-product-assets.private.json':{}}
    for n,value in records.items():(tmp_path/n).write_text(json.dumps(value))
    files={n:sha256((tmp_path/n).read_bytes()).hexdigest() for n in records}
    assert consumer.publication.recipe_scope(tmp_path,{'files':files})=='observed_atomic_state'
    missing=dict(files);missing.pop(name)
    with pytest.raises(ValueError,match='manifest-bound'):
        consumer.publication.recipe_scope(tmp_path,{'files':missing})
    (tmp_path/name).write_text('null')
    with pytest.raises(ValueError,match='manifest-bound'):
        consumer.publication.recipe_scope(tmp_path,{'files':files})


def test_old_recipe_keeps_strict_scope_but_cannot_admit_orphan_recorder(tmp_path):
    assert consumer.publication.recipe_scope(tmp_path,{'files':{}})=='whole_run'
    path=tmp_path/'atomic-product-runtime-options.private.json';path.write_text('{}')
    with pytest.raises(ValueError,match='manifest-bound'):
        consumer.publication.recipe_scope(tmp_path,{'files':{}})
    with pytest.raises(ValueError,match='Whole-run recipe'):
        consumer.publication.recipe_scope(tmp_path,{'files':{path.name:sha256(path.read_bytes()).hexdigest()}})


def test_scoped_recipe_cannot_omit_required_sidecar(tmp_path):
    path=tmp_path/'atomic-product-scoring-scope.private.json';path.write_text(json.dumps('observed_atomic_state'))
    with pytest.raises(ValueError,match='all three'):
        consumer.publication.recipe_scope(tmp_path,{'files':{path.name:sha256(path.read_bytes()).hexdigest()}})
