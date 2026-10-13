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
