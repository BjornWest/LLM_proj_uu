import copy
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import pytest

from environments.shopping_intent.world import QUERIES, resolve_world, predicate
from environments.shopping_intent.oracle import analyze, grade_answer, objective_value
from .scenario import generate_scenario, sample_task
from .outcomes import candidates_for, evaluate


def fixture(query='cheapest_pickup', family='footwear', stockout=0, branch_stockout=0, reviews=None):
    s=generate_scenario({'seed':3,'family':family,'query':query,'destination_city':'uppsala',
                        'hidden':'none','memory':'none','world_preferences':'none'},
        {'seed':42,'store_count':2,'models_per_store':1,'store_config':{'stockout_probability':stockout}},
        {'profile_weights':{'local_shop':1,'regional_chain':0,'major_retailer':0,'online_specialist':0},
         'config':{'home_city_probability':1,'home_country_probability':0,'branch_carry_probability':1,
                   'branch_stockout_probability':branch_stockout,'display_probability':1,'transfer_probability':1}},reviews)
    # Explicit small oracle fixture: remove product constraints to isolate world facts.
    task=s['task']['resolved_task'];task['lines'][0]['requirements']=[];task['constraints']={}
    task['world_requirements']=[]
    if query in QUERIES and QUERIES[query][1]!='delivery':
        task['world_requirements']=[predicate('travel_mode','eq','driving','mode')]
    return s


def test_world_task_memory_matrix_is_consistent_and_not_hidden():
    def check(case):
        query,mode,seed=case;family='beer' if query=='unit_price' else 'footwear'
        t=sample_task(seed=seed,family=family,query=query,destination_city='malmo',memory=mode,world_preferences='reputation_domestic')
        assert t['resolved_task']['world_requirements']==resolve_world(t['request']['explicit_world_requirements'],t['world_memory_facts'],t['request']['query']['activity'])
        assert all(h['predicate']['field'] not in ('travel_mode','travel_minutes','merchant_mean_stars') for h in t['hidden_user_specifications'])
        assert '\n' not in t['public']['user_message']
        assert ''.join(p['text'] for p in t['authoring']['message_segments'])==t['public']['user_message']
        visible={x['id'] for channel in t['public']['memories'].values() for x in channel}
        assert {m['id'] for m in t['world_memory_facts']}<=visible
        if mode=='none':assert not t['world_memory_facts']
        if query!='unit_price':assert 'shipping' not in t['public']['user_message'] and 'home delivery' not in t['public']['user_message'].lower()
        other=sample_task(seed=seed,family=family,query=query,destination_city='malmo',memory=mode,world_preferences='reputation_domestic',prose_seed=900)
        assert other['semantic_sha256']==t['semantic_sha256']
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(check,[(q,m,s) for q in QUERIES for m in ('none','profile','episodic','mixed','override') for s in range(8)]))


def test_world_memory_scope_and_explicit_override():
    p=predicate('travel_mode','eq','cycling','mode')
    memories=[{'id':'m','scope':'pickup','channel':'episodic','predicate':p}]
    assert resolve_world([],memories,'delivery')==[]
    assert resolve_world([],memories,'pickup')[0]['value']=='cycling'
    explicit=[{**p,'value':'walking'}]
    assert resolve_world(explicit,memories,'pickup')[0]['source']=={'kind':'request'}
    assert memories[0]['predicate']['value']=='cycling'


def test_world_and_review_changes_never_rewrite_task():
    options={'seed':3,'family':'footwear','query':'nearest_pickup','destination_city':'malmo','memory':'mixed','world_preferences':'reputation'}
    a=generate_scenario(options,{'seed':2,'models_per_store':1},{})
    b=generate_scenario(options,{'seed':4,'models_per_store':1},{}, {'reviews_per_store':0})
    assert a['task']==b['task']==sample_task(**options)
    assert all(c['statistics']['review_count']==0 for c in b['merchant_reviews']['public']['companies'])


@pytest.mark.parametrize('options',[
    {'family':'beer','query':'nearest_inspection','destination_city':'malmo'},
    {'family':'laptops','query':'unit_price'},
    {'family':'footwear','query':'nearest_pickup'},
    {'family':'footwear','query':'nearest_inspection','destination_city':'malmo','budget_sek':500},
    {'family':'footwear','world_preferences':'invalid'},
    {'family':'footwear,laptops,dog_food','query':'basket','world_preferences':'reputation'},
])
def test_unsupported_world_recipes_fail_explicitly(options):
    with pytest.raises(ValueError):sample_task(**options)


def test_inspection_display_unit_is_not_a_purchase_and_branch_is_graded():
    s=fixture('nearest_inspection',stockout=1,branch_stockout=1)
    candidates=candidates_for(s);task=s['task']['resolved_task']
    assert candidates and all(c['inspectable'] and c['purchasable'] is None and c['total_minor'] is None for c in candidates)
    result=analyze(task,candidates,coverage_complete=True)
    winner=next(c for c in candidates if c['candidate_id'] in result['best_candidate_ids'])
    answer={'status':'selection','candidate_id':winner['candidate_id'],'branch_id':winner['branch_id'],
            'travel_mode':'driving','travel_minutes':winner['travel_minutes']}
    assert grade_answer(task,candidates,answer,coverage_complete=True,effects=[])['structured_claims_correct']
    answer['branch_id']='wrong-branch'
    assert not grade_answer(task,candidates,answer,coverage_complete=True,effects=[])['structured_claims_correct']


def test_transfer_constraint_and_readiness_ranking():
    s=fixture('fastest_pickup',branch_stockout=1);task=s['task']['resolved_task']
    candidates=candidates_for(s)
    assert all(c['world_facts']['requires_stock_transfer'] and c['ready_days']>0 for c in candidates)
    best=min((c['ready_days'],c['total_minor']) for c in candidates)
    result=analyze(task,candidates,coverage_complete=True)
    assert all((c['ready_days'],c['total_minor'])==best for c in candidates if c['candidate_id'] in result['best_candidate_ids'])
    task['world_requirements'].append(predicate('requires_stock_transfer','eq',False,'transfer'))
    assert analyze(task,candidates,coverage_complete=True)['status']=='no_match'


def test_unmodelled_cycling_is_unknown_not_zero_or_no_match():
    s=fixture('nearest_pickup');task=s['task']['resolved_task'];candidates=candidates_for(s)
    # A trusted adapter's unmodelled travel record carries null metrics.
    for c in candidates:c['travel_minutes']=None;c['world_facts'].update(travel_mode='cycling',travel_minutes=None,travel_km=None)
    task['world_requirements']=[predicate('travel_mode','eq','cycling','mode')]
    assert analyze(task,candidates,coverage_complete=True)['status']=='uncertain'


def test_review_thresholds_empty_and_missing_evidence():
    s=fixture('cheapest',reviews={'config':{'star_weights':{str(n):int(n==5) for n in range(1,6)}}})
    task=s['task']['resolved_task']
    task['world_requirements']=[predicate('merchant_mean_stars','ge',4,'rating'),predicate('merchant_review_count','ge',20,'count')]
    assert evaluate(s)['outcome']['status']=='determined'
    task['world_requirements'][1]['value']=40
    assert evaluate(s)['outcome']['status']=='no_match'
    missing=copy.deepcopy(s);missing.pop('merchant_reviews')
    assert evaluate(missing)['outcome']['status']=='uncertain'
    empty=fixture('cheapest',reviews={'reviews_per_store':0});empty['task']['resolved_task']['world_requirements']=task['world_requirements']
    assert evaluate(empty)['outcome']['status']=='no_match'
    s['merchant_reviews']['private_provenance']['source_world_sha256']='other-world'
    with pytest.raises(ValueError,match='another world'):evaluate(s)


def test_domestic_filter_compares_merchant_home_not_delivery_destination():
    s=fixture();task=s['task']['resolved_task'];candidates=candidates_for(s)
    task['world_requirements'].append(predicate('merchant_country','eq','SE','country'))
    for c in candidates:c['world_facts']['merchant_country']='DK'
    assert all(c['destination']=='SE' for c in candidates)
    assert analyze(task,candidates,coverage_complete=True)['status']=='no_match'


def test_unit_price_uses_all_units_and_exact_ratio_not_pack_price():
    s=fixture('unit_price','beer');task=s['task']['resolved_task'];candidates=candidates_for(s)
    for c in candidates:
        attrs=c['lines'][0]['facts']
        assert c['unit_price']['quantity_milliunits']==attrs['pack_count']*attrs['volume_ml']
    a,b=copy.deepcopy(candidates[0]),copy.deepcopy(candidates[1]);a['candidate_id']='small';b['candidate_id']='large'
    a['total_minor']=10000;a['unit_price']={'cost_minor':10000,'quantity_milliunits':1000}
    b['total_minor']=15000;b['unit_price']={'cost_minor':15000,'quantity_milliunits':2000}
    assert objective_value(b,'unit_price')==Fraction(7500)
    assert analyze(task,[a,b],coverage_complete=True)['best_candidate_ids']==['large']
    a['unit_price']={'cost_minor':7500,'quantity_milliunits':1000}
    assert set(analyze(task,[a,b],coverage_complete=True)['best_candidate_ids'])=={'small','large'}
