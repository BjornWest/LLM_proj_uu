"""Saved caller boundary controls; reuse native listed-offer grading fixtures."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from . import basic_offer_saved_answer as consumer
from .test_listed_offer_grading import fixture, answer


def setup():
    task={'task_id':'t','memories':[{'text':'Original memory'}],'comparison_site_id':'comparison-01'}
    value={'schema':consumer.publication.VERSION,'task_id':'t','memories':deepcopy(task['memories']),
        'user_message':'Find the cheapest shoes on this comparison site.',
        'start':{'kind':'comparison_home','comparison_site_id':'comparison-01'}}
    return task,value


@pytest.mark.parametrize('change',[
    {'task_id':'other'}, {'memories':[]}, {'start':{'kind':'directory'}},
    {'start':{'kind':'comparison_home','comparison_site_id':'comparison-00'}},
    {'user_message':''}, {'schema':'other'}, {'extra':True}])
def test_public_setup_cannot_change_native_identity_memories_or_scope(change):
    task,value=setup()
    assert consumer.checked_setup(value,task)==value
    with pytest.raises(ValueError,match='identity/memories/scope'):
        consumer.checked_setup({**value,**change},task)


def test_unscoped_task_uses_directory_and_preserves_native_grader():
    world,task,reference,bindings=fixture()
    value={'schema':consumer.publication.VERSION,'task_id':task['task_id'],'memories':[],
        'user_message':'Find the cheapest shoes.','start':{'kind':'directory'}}
    assert consumer.checked_setup(value,task)==value
    grader=consumer.SavedListedOfferGrader(world,task,reference,bindings)
    assert grader.task==task and grader.extraction_instructions==consumer.SYSTEM
    for price,expected in [('740',True),('700',False)]:
        text,claims=answer(price=price)
        assert grader.grade(claims,text)['structured_claims_correct'] is expected


def test_genuine_no_match_uses_complete_formatter_schema_without_refill():
    from .adapter import digest
    world, _, _, bindings = fixture()
    for retailer in world['retailers']:
        for offer in retailer['offers']:
            offer['stock_by_source'] = {source: 0 for source in offer['stock_by_source']}
    task = consumer.native._make_bound(world,
        {'kind': consumer.native.KIND, 'concept_id': 'footwear.walking_shoes'}, digest(world))
    reference = consumer.native._reference_bound(world, task)
    grader = consumer.SavedListedOfferGrader(world, task, reference, bindings)
    text = 'No available walking shoes were found.'
    null = {'value': None, 'evidence': None}
    claims = {'interpretation': 'extracted', 'issues': [],
        'status': {'value': 'no_match', 'evidence': text},
        **{name: deepcopy(null) for name in ('product_name','retailer_name','offer_url','sku_id')},
        'variant': {}, 'total': None, 'source_urls': []}
    assert reference['status'] == 'no_match'
    assert grader.grade(claims,text)['structured_claims_correct'] is True


def test_run_reuses_prospective_shared_lifecycle_and_exact_native_inputs(monkeypatch,tmp_path):
    seen={}
    def run(*args,**kwargs):seen.update(args=args,kwargs=kwargs);return 'result'
    monkeypatch.setattr(consumer.lifecycle,'run',run)
    options={'runner_options':{'max_steps':None,'max_input_tokens':100},'metadata':{'tags':['scripted']}}
    assert consumer.run(tmp_path/'recipe',tmp_path/'run',**options)=='result'
    assert seen['kwargs']=={**options,'episode_factory':consumer.SavedBasicOfferEpisode,
        'inputs_factory':consumer.native_inputs,'grader_factory':consumer.SavedListedOfferGrader,
        'contract_id':consumer.VERSION,'verifier':'basic-listed-offer-native'}
    native=consumer.native_inputs(tmp_path/'recipe',tmp_path/'runtime')
    assert set(native)=={'world','task','reference','bindings','surrounding'}
    assert native['bindings']==tmp_path/'runtime/bindings.private.json'


def raw_inputs(tmp_path,delivery=False):
    saved=tmp_path/'saved';saved.mkdir()
    rows={'world.private.json':{'world_id':'world'},'presentation.private.json':{},
        'compositions.private.json':{},'surrounding.private.json':{},
        'basket-plan.private.json':{},'checkout-domain.private.json':{}}
    if delivery:rows['delivery-plan.private.json']={'menu':'retained'}
    for name,row in rows.items():(saved/name).write_text(json.dumps(row))
    task=tmp_path/'task.json';ref=tmp_path/'reference.json'
    task.write_text(json.dumps({'kind':consumer.native.KIND,'task_id':'t','memories':[],
        'user_message':'Native request','comparison_site_id':'comparison-01'}))
    ref.write_text(json.dumps({'status':'no_match'}))
    pin=lambda p:{'path':str(p),'sha256':sha256(p.read_bytes()).hexdigest()}
    return saved,{name:sha256((saved/name).read_bytes()).hexdigest() for name in rows},pin(task),pin(ref)


def test_saved_hashes_and_native_reference_fail_before_new_output(monkeypatch,tmp_path):
    saved,hashes,task,reference=raw_inputs(tmp_path)
    dest=tmp_path/'out'
    with pytest.raises(ValueError,match='complete saved'):
        consumer.prepare_saved(saved,dest,expected_input_sha256={},task_file=task,reference_file=reference)
    with pytest.raises(ValueError,match='file changed'):
        consumer.prepare_saved(saved,dest,expected_input_sha256={**hashes,'world.private.json':'0'*64},
            task_file=task,reference_file=reference)
    monkeypatch.setattr(consumer,'_reference',lambda *args:{'status':'match'})
    with pytest.raises(ValueError,match='native listed-offer reference changed'):
        consumer.prepare_saved(saved,dest,expected_input_sha256=hashes,task_file=task,reference_file=reference)
    assert not dest.exists()


@pytest.mark.parametrize('delivery',[False,True])
@pytest.mark.parametrize('archive_corruption',[False,True])
def test_saved_freeze_preserves_all_input_and_native_bytes(monkeypatch,tmp_path,delivery,archive_corruption):
    saved,hashes,task,reference=raw_inputs(tmp_path,delivery)
    dest=tmp_path/'out';root=tmp_path/'source';root.mkdir()
    script=root/'scripts/trace_grades.py';script.parent.mkdir();script.write_text('# pinned fixture\n')
    from scripts import trace_grades
    monkeypatch.setattr(trace_grades,'__file__',str(script))
    monkeypatch.setattr(consumer.shared,'ROOT',root)
    monkeypatch.setattr(consumer.shared,'source_files',lambda:{})
    monkeypatch.setattr(consumer,'_bind',lambda f,**kw:f)
    monkeypatch.setattr(consumer,'_reference',lambda *args:{'status':'no_match'})
    class Execution:
        def __init__(self,**options):assert options=={'validation':'off'}
        def freeze(self,world,out):
            out.mkdir();(out/'world.private.json').write_text('temporary')
            return {'files':{},'source_sha256':{}}
    monkeypatch.setattr(consumer,'Execution',Execution)
    if archive_corruption:
        real_save=consumer.shared.save
        def save(path,value):
            real_save(path,value)
            if path.name=='execution.private.json':
                (dest/'pin/source-snapshot/scripts/trace_grades.py').write_text('# changed archive\n')
        monkeypatch.setattr(consumer.shared,'save',save)
        with pytest.raises(ValueError,match='Source changed before publication'):
            consumer.prepare_saved(saved,dest,expected_input_sha256=hashes,task_file=task,
                reference_file=reference,user_message='Natural request')
        assert not (dest/'manifest.json').exists()
        return
    manifest=consumer.prepare_saved(saved,dest,expected_input_sha256=hashes,task_file=task,
        reference_file=reference,user_message='Natural request')
    assert manifest['world_draws']==manifest['model_runs']==0
    assert manifest['automatic_grading_attached'] is False
    for name in hashes:
        target=dest/('pin/world.private.json' if name=='world.private.json' else
                     'presentation.json' if name=='presentation.private.json' else name)
        assert target.read_bytes()==(saved/name).read_bytes()
        assert sha256((saved/name).read_bytes()).hexdigest()==hashes[name]
    assert (dest/'basic-offer-task.private.json').read_bytes()==Path(task['path']).read_bytes()
    assert (dest/'basic-offer-reference.private.json').read_bytes()==Path(reference['path']).read_bytes()
    assert json.loads((dest/'episode.json').read_bytes())['manual_task']['user_message']=='Native request'
    assert json.loads((dest/'saved-answer-setup.private.json').read_bytes())['user_message']=='Natural request'
    for name,h in manifest['files'].items():assert sha256((dest/name).read_bytes()).hexdigest()==h
