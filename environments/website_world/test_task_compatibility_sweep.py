from itertools import product
import pytest

from .task_compatibility_sweep import interactions, select_cases


def candidates():
    result=[]
    for i,(scope,operation,grain) in enumerate(product(['shop','comparison'],['count','mean'],['model','listing'])):
        factors={'scope':scope,'operation':operation,'grain':grain}
        result.append({'id':str(i),'factors':factors,'instance':{'parameters':factors,'user_message':'Calculate it.'}})
    return result


def test_pairwise_selection_reports_real_pool_coverage_and_is_replayable():
    source=candidates();report=select_cases(source,limit=4,seed=9)
    assert len(report['selected'])==4
    assert report['coverage']['covered_pairs']==report['coverage']['applicable_pairs']==12
    assert not report['coverage']['uncovered_pairs']
    assert report==select_cases(source,limit=4,seed=9)
    assert len(source)==8


def test_budget_cannot_be_reported_as_complete_coverage():
    report=select_cases(candidates(),limit=1)
    assert report['coverage']['covered_pairs']==3
    assert report['coverage']['applicable_pairs']==12
    assert len(report['coverage']['uncovered_pairs'])==9


def test_targeted_triples_require_the_actual_compatible_combination():
    report=select_cases(candidates(),limit=8,triples=[['scope','operation','grain']])
    assert report['coverage']['covered_triples']==report['coverage']['targeted_triples']==8


def test_conditional_axes_do_not_invent_cross_family_combinations():
    pool=[{'id':'review','factors':{'family':'review','topic':'grip'},'instance':{'family':'review'}},
          {'id':'cart','factors':{'family':'cart','quantity':2},'instance':{'family':'cart'}}]
    report=select_cases(pool,limit=10,triples=[['family','topic','quantity']])
    assert report['coverage']['applicable_pairs']==2
    assert report['coverage']['targeted_triples']==0


def test_rewording_cannot_inflate_native_configuration_count():
    pool=candidates();copy={**pool[0],'id':'new','instance':{**pool[0]['instance'],'user_message':'Different words'}}
    with pytest.raises(ValueError,match='Duplicate semantic'):select_cases(pool+[copy])


@pytest.mark.parametrize('limit',[0,-1,True,1.5])
def test_bad_bounds_reject(limit):
    with pytest.raises(ValueError):select_cases(candidates(),limit=limit)


def test_factor_tokens_keep_type_and_structured_scope():
    assert interactions({'value':True,'scope':{'kind':'sku'}},1)!=interactions({'value':1,'scope':{'kind':'sku'}},1)


def test_compaction_preserves_bytes_modes_and_independent_paths(tmp_path):
    import os
    from .task_compatibility_sweep import compact_prepared
    folders=[]
    for label in ['one','two']:
        directory=tmp_path/label;directory.mkdir();folders.append(directory)
        (directory/'prepared-instance.json').write_text('{}')
        (directory/'same').write_bytes(b'immutable')
        (directory/'executable').write_bytes(b'immutable');os.chmod(directory/'executable',0o755)
    compact_prepared(folders[0],tmp_path/'store')
    result=compact_prepared(folders[1],tmp_path/'store')
    assert result['reused_duplicate_bytes']>0
    assert (folders[0]/'same').stat().st_ino==(folders[1]/'same').stat().st_ino
    assert (folders[0]/'same').stat().st_ino!=(folders[0]/'executable').stat().st_ino
    for directory in folders:
        assert (directory/'same').read_bytes()==b'immutable'
        assert (directory/'executable').stat().st_mode&0o777==0o755


def test_compaction_rejects_unfinished_preparation_and_corrupted_store(tmp_path):
    from .task_compatibility_sweep import compact_prepared
    from hashlib import sha256
    directory=tmp_path/'prepared';directory.mkdir();store=tmp_path/'store';store.mkdir()
    with pytest.raises(ValueError,match='completed'):compact_prepared(directory,store)
    (directory/'prepared-instance.json').write_text('{}')
    target=store/(sha256(b'{}').hexdigest()+'-644');target.write_text('changed')
    with pytest.raises(ValueError,match='changed'):compact_prepared(directory,store)


def _fake_inspection(instance):
    return {'task':{'task_id':str(instance['value'])},'reference':{},'setup':{},'metrics':{'status':'ready','population':1}}


def _selection(*values):
    rows=[{'id':str(i),'factors':{'family':'fixture','axis':'same'},'instance':{'value':v}} for i,v in enumerate(values)]
    return select_cases(rows,limit=len(rows))


def test_compaction_failure_does_not_erase_preparation_success(tmp_path,monkeypatch):
    from . import task_compatibility_sweep as sweep,task_instances
    monkeypatch.setattr(task_instances,'inspect',_fake_inspection)
    def prepare(instance,path):path.mkdir();return {'recipe':'recipe'}
    monkeypatch.setattr(task_instances,'prepare',prepare)
    monkeypatch.setattr(sweep.shutil,'disk_usage',lambda _:type('Disk',(),{'free':2*1024**3})())
    def broken(*args):raise OSError('EMLINK')
    monkeypatch.setattr(sweep,'compact_prepared',broken)
    report=sweep.run_native(_selection('one'),tmp_path/'out',prepare=True,share_assets=True)
    row=report['results'][0];assert row['stages']['unmocked_preparation']['status']=='passed'
    assert row['stages']['unmocked_preparation']['receipt']=={'recipe':'recipe'}
    assert row['stages']['immutable_compaction']['status']=='error'
    assert report['observed_stage_pair_coverage']['unmocked_preparation']['passed_pairs']==1


def test_disk_preflight_is_held_not_an_attempted_freeze(tmp_path,monkeypatch):
    from . import task_compatibility_sweep as sweep,task_instances
    monkeypatch.setattr(task_instances,'inspect',_fake_inspection)
    monkeypatch.setattr(sweep.shutil,'disk_usage',lambda _:type('Disk',(),{'free':0})())
    def forbidden(*args):raise AssertionError('Freeze must not be called')
    monkeypatch.setattr(task_instances,'prepare',forbidden)
    report=sweep.run_native(_selection('one'),tmp_path/'out',prepare=True)
    assert report['held']==1;assert report['results'][0]['stages']['preparation_preflight']['reason_code']=='insufficient_disk_space'
    assert report['observed_stage_pair_coverage']['unmocked_preparation']['attempted_pairs']==0


def test_mixed_outcome_pairs_and_invalid_input_are_visible(tmp_path,monkeypatch):
    from . import task_compatibility_sweep as sweep,task_instances
    def inspect(instance):
        if instance['value']=='bad':raise ValueError('Fixture failure')
        return _fake_inspection(instance)
    monkeypatch.setattr(task_instances,'inspect',inspect)
    report=sweep.run_native(_selection('good','bad'),tmp_path/'out')
    coverage=report['observed_stage_pair_coverage']['native_inspection'];assert coverage['passed_pairs']==coverage['mixed_outcome_pairs']==coverage['pairs_with_failure']==1
    with pytest.raises(ValueError,match='Malformed'):sweep.run_native({'schema':sweep.VERSION,'selected':[{'id':'bad'}]},tmp_path/'invalid')
    assert not (tmp_path/'invalid').exists()


def test_non_object_instances_fail_before_selection():
    with pytest.raises(ValueError,match='object'):select_cases([{'id':'x','factors':{},'instance':[]}])


def test_missing_coverage_and_nonserializable_receipt_fail_closed(tmp_path,monkeypatch):
    from . import task_compatibility_sweep as sweep,task_instances
    with pytest.raises(ValueError):sweep.run_native([],tmp_path/'bad')
    bad=_selection('one');bad.pop('coverage')
    with pytest.raises(ValueError):sweep.run_native(bad,tmp_path/'missing')
    monkeypatch.setattr(task_instances,'inspect',_fake_inspection)
    monkeypatch.setattr(sweep.shutil,'disk_usage',lambda _:type('Disk',(),{'free':2*1024**3})())
    monkeypatch.setattr(task_instances,'prepare',lambda instance,path:{'bad':path})
    report=sweep.run_native(_selection('one'),tmp_path/'out',prepare=True)
    row=report['results'][0];assert row['status']=='requires_triage'
    assert row['stages']['unmocked_preparation']['status']=='passed'
    assert row['stages']['preparation_receipt']['status']=='error'
    assert (tmp_path/'out/report.json').is_file()


def test_artifact_failure_does_not_replace_native_inspection(tmp_path,monkeypatch):
    from . import task_compatibility_sweep as sweep,task_instances
    def inspect(instance):
        result=_fake_inspection(instance);result['reference']={'bad':float('nan')};return result
    monkeypatch.setattr(task_instances,'inspect',inspect)
    report=sweep.run_native(_selection('one'),tmp_path/'out');row=report['results'][0]
    assert row['stages']['native_inspection']['status']=='passed'
    assert row['stages']['native_artifacts']['status']=='error'
