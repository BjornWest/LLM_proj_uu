"""Typed role joins must not credit wrong family/model/unit/state or slot pieces."""
from copy import deepcopy

import pytest
from training.browser_training.fact_compare_review_features import compile_roles, project


def fixture():
    return {'schema_version':'website-catalog-compare-review-task-v1','kind':'compare_facts_and_reviews',
        'task_id':'test','comparison_task':{'models':[{'product_id':'p'},{'product_id':'q'}],
            'fields':['product.facts.cushioning','product.facts.reference_mass_g','product.facts.fastening']},
        'required_obligations':[
            {'role_id':'model_1.fact.product.facts.cushioning','product_id':'p','grain':'manufactured_product_model',
             'source_family':'retailer','field':'product.facts.cushioning','unit':None,'basis':None},
            {'role_id':'model_1.review.summary.mean_rounded','product_id':'p','grain':'canonical_review_corpus',
             'source_family':'product_reviews','operation':'rating_summary','field':'summary.mean_rounded'}]}


def features(records):
    return {'schema':'native-fact-delivery-features-v1','recipient':'main','prefix_step':0,'records':records}


def retailer(status='complete'):
    return {'id':'r','binding':{'source_family':'retailer','product_id':'p',
        'authority':'native_public_field','field':'product.facts.cushioning',
        'subject_type':'product','subject_id':'p','unit':None,'status':'known'},
        'effective_state':{'product_id':'p','sku_id':'s'},'status':status}


@pytest.mark.parametrize('mutation',['family','model','subject','field','unit','effective_model','basis'])
def test_wrong_scope_cannot_satisfy_native_scalar(mutation):
    task=fixture();row=retailer()
    changes={'family':('source_family','product_reviews'),'model':('product_id','q'),
             'subject':('subject_type','sku'),'field':('field','sku.facts.cushioning'),'unit':('unit','kg')}
    if mutation=='effective_model':row['effective_state']['product_id']='q'
    elif mutation=='basis':task['required_obligations'][0]['basis']='reference option'
    else:key,value=changes[mutation];row['binding'][key]=value
    assert project(task,features([row]))['roles'][0]['observation_status']=='unknown'


def test_partial_direct_scalar_is_partial_but_compound_slot_needs_every_part():
    assert project(fixture(),features([retailer('partial')]))['roles'][0]['observation_status']=='partial'
    row=retailer('partial');b=row['binding'];b['authority']='selected_slot'
    b['assertions']=[{'field':'product.facts.cushioning','subject':{'kind':'product','id':'p'},
                     'status':'known','unit':None,'qualifiers':{},
                     'mapping_status':'native_scalar_field_without_authored_meaning'}]
    assert project(fixture(),features([row]))['roles'][0]['observation_status']=='unknown'
    row['status']='complete'
    assert project(fixture(),features([row]))['roles'][0]['observation_status']=='complete'
    b['assertions'][0]['subject']['kind']='sku'
    assert project(fixture(),features([row]))['roles'][0]['observation_status']=='unknown'


def histograms():
    return [{'id':f'h{s}','binding':{'source_family':'product_reviews','product_id':'p',
             'authority':'renderer_native_review_aggregate','field':'star_counts','stars':s,
             'grain':'model','basis':'all_recorded_ratings_all_options_including_silent'},
             'effective_state':{'product_id':'p','rating_summary_sha256':'corpus-one'},'status':'complete'}
            for s in range(1,6)]


def test_exact_mean_requires_all_histogram_cells_from_same_corpus_state():
    rows=histograms();task=fixture()
    assert project(task,features(rows))['roles'][1]['observation_status']=='complete'
    assert project(task,features(rows[:-1]))['roles'][1]['observation_status']=='partial'
    rows[-1]['effective_state']['rating_summary_sha256']='corpus-two'
    assert project(task,features(rows))['roles'][1]['observation_status']=='partial'
    for row in rows:row['binding']['basis']='filtered_written_reviews'
    assert project(task,features(rows))['roles'][1]['observation_status']=='unknown'


def test_unsupported_topic_summary_remains_unknown_not_native_truth_credit():
    task=fixture();task['required_obligations'][1].update(operation='topic_counts',field='counts.positive')
    role=project(task,features(histograms()))['roles'][1]
    assert role['observation_status']=='unknown' and role['reason']=='public_dependency_adapter_unbound'
    assert not project(task,features([]))['producer_qualified']


def test_mean_dependencies_preserve_variable_required_evidence():
    role=compile_roles(fixture())[1]
    assert len(role['dependencies'][0])==5
    assert {r['stars'] for r in role['dependencies'][0]}=={1,2,3,4,5}


def test_exact_private_obligations_are_required_without_rewriting_order_or_scope():
    from training.browser_training.fact_compare_review_features import bind_obligations
    task=fixture();roles=deepcopy(task['required_obligations'])
    assert bind_obligations(task,roles)['required_role_count']==2
    with pytest.raises(ValueError,match='mismatch'):bind_obligations(task,list(reversed(roles)))
    roles[0]['product_id']='q'
    with pytest.raises(ValueError,match='mismatch'):bind_obligations(task,roles)
