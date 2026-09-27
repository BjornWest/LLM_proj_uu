from copy import deepcopy
import pytest
from .scenario import sample_task,generate_scenario
from .outcomes import candidates_for,evaluate
from .episode import Episode
from environments.shopping_intent.oracle import analyze,grade_answer
from environments.shopping_intent.world import fingerprint


def task():
    t=sample_task(seed=0,family='footwear',query='widest_assortment',destination_city='malmo',
                  requirements=1,hidden='none',memory='none',world_preferences='none')['resolved_task']
    t['world_requirements']=[]
    return t


def candidate(t,id,branch='a',model='m1',price=150000,stock=1,**changes):
    line=t['lines'][0]
    facts={p['field']:p['value'] for p in line['requirements']}
    row={'candidate_id':id,'activity':'inspect','branch_id':branch,'total_minor':price,
         'arrival_days':None,'inspectable':True,'currency':'SEK','destination':t['context']['destination'],
         'world_facts':{'branch_stock_quantity':stock},
         'lines':[{'line_id':line['id'],'family_id':'footwear','quantity':1,'sku_id':id,
                   'model_id':model,'retailer_id':'one-chain','facts':facts}]}
    return {**row,**changes}


def test_count_models_not_variants_units_or_chain_totals_and_price_endpoints():
    t=task();rows=[candidate(t,'a1',price=100000,stock=20),candidate(t,'a2',price=200000),
        candidate(t,'a3',model='m2'),candidate(t,'b1',branch='b',model='m3'),
        candidate(t,'b2',branch='b',model='m4'),candidate(t,'c1',branch='c',model='m5'),
        candidate(t,'cheap',model='m6',price=99999),candidate(t,'costly',model='m7',price=200001),
        candidate(t,'display',model='m8',stock=0),candidate(t,'no-try',model='m9',inspectable=False)]
    wrong=candidate(t,'wrong-size',model='m10');wrong['lines'][0]['facts']['size_eu']=99;rows.append(wrong)
    r=analyze(t,rows,coverage_complete=True)
    assert r['status']=='determined' and r['max_model_count']==2 and set(r['best_branch_ids'])=={'a','b'}
    a=next(b for b in r['branches'] if b['branch_id']=='a')
    assert a['matching_candidates_by_model']['m1']==['a1','a2']
    assert set(a['matching_model_ids'])=={'m1','m2'}


def test_no_match_and_unknown_do_not_become_false_zero_or_double_count():
    t=task();zero=analyze(t,[candidate(t,'none',stock=0)],coverage_complete=True)
    assert zero['status']=='no_match' and zero['best_branch_ids']==[]
    known=candidate(t,'known');unknown=candidate(t,'unknown',inspectable=None)
    # Unknown alternative of an already qualifying model cannot change its count.
    assert analyze(t,[known,unknown],coverage_complete=True)['status']=='determined'
    unknown['lines'][0]['model_id']='another'
    r=analyze(t,[known,unknown],coverage_complete=True)
    assert r['status']=='uncertain' and r['branches'][0]['model_count_max']==2 and r['max_model_count'] is None
    assert analyze(t,[known],coverage_complete=False)['status']=='uncertain'


@pytest.mark.parametrize('memory',['none','profile','episodic','mixed','override'])
def test_structured_range_purpose_memories_and_hidden_size_without_prose_drift(memory):
    args={'seed':3,'family':'footwear','query':'widest_assortment','destination_city':'malmo',
          'requirements':1,'memory':memory,'hidden':'blocker','price_range_sek':[1000,2000]}
    a=sample_task(**args);b=sample_task(**args,prose_seed=98)
    assert a['semantic_sha256']==b['semantic_sha256']==fingerprint(a)
    assert a['resolved_task']['constraints']=={'price_min_minor':100000,'budget_minor':200000}
    assert {p['field'] for p in a['resolved_task']['lines'][0]['requirements']}=={'size_eu','activity'}
    assert 'size_eu' not in {p['field'] for p in a['initial_accessible_task']['lines'][0]['requirements']}
    assert '1000' in a['public']['user_message'] and '2000' in a['public']['user_message']
    assert '\n' not in a['public']['user_message']
    assert ''.join(x['text'] for x in a['authoring']['message_segments'])==a['public']['user_message']


@pytest.mark.parametrize('bounds',[[-1,1000],[2000,1000],[True,2000],[1000.5,2000],[1000],[0,0]])
def test_invalid_range_rejected(bounds):
    with pytest.raises(ValueError,match='price_range_sek'):
        sample_task(family='footwear',query='widest_assortment',destination_city='malmo',price_range_sek=bounds)


def test_world_adapter_uses_local_stock_and_inspection_not_pickup_or_coupons():
    s=generate_scenario({'seed':0,'family':'footwear','query':'widest_assortment','destination_city':'malmo',
        'requirements':1,'hidden':'none','memory':'none','world_preferences':'none'},
        {'seed':42,'store_count':2,'models_per_store':1},
        {'profile_weights':{'local_shop':1,'regional_chain':0,'major_retailer':0,'online_specialist':0},
         'config':{'home_city_probability':1,'home_country_probability':0,'branch_carry_probability':1,'branch_stockout_probability':0}},
        account_options={'seed':42,'config':{'signed_in_probability':1,'coupon_probability':1}})
    offers={o['offer_id']:o for o in s['bundle']['public']['offers']}
    inventory={(i['branch_id'],i['product_id']):i for i in s['locations']['public']['branch_inventory']}
    candidates=candidates_for(s);assert candidates
    for c in candidates:
        assert c['total_minor']==offers[c['offer_id']]['price_minor']
        assert c['world_facts']['branch_stock_quantity']==inventory[(c['branch_id'],c['lines'][0]['sku_id'])]['stock_quantity']
        assert 'coupon_code' not in c
    without=deepcopy(s);without.pop('accounts');assert evaluate(s)==evaluate(without)
    e=Episode(s,index_url='http://localhost:12345')
    assert e.reference()==evaluate(s)['outcome']
    assert 'matching_model_count' in e.policy_input()['answer_contract']
    assert 'total_minor' not in e.policy_input()['answer_contract']
    with pytest.raises(NotImplementedError,match='manual review'):e.grade({'status':'branch_assortment'},effects=[])
