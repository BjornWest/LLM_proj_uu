from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
import json
import pytest
from .scenario import generate_scenario
from .accounts import iso
from .generator import digest
from .storefront_content import generate_storefront_content,validate_storefront_content,attach_storefront_content,KINDS
from .episode import Episode
from .outcomes import evaluate


@pytest.fixture(scope='module')
def sample():
    return generate_scenario({'seed':0,'family':'footwear','destination_city':'malmo','requirements':1,
        'hidden':'none','world_preferences':'none'},
        {'seed':42,'store_count':6,'models_per_store':1,'footwear_depth':{}},{},
        account_options={'seed':42,'as_of':'2026-09-27'})


@pytest.fixture(scope='module')
def content(sample):return generate_storefront_content(sample['bundle'],seed=42,accounts=sample['accounts'])


def test_repeatable_complete_typed_collections_and_no_model_count_inflation(sample,content):
    assert content==generate_storefront_content(sample['bundle'],seed=42,accounts=sample['accounts'])
    w=sample['bundle'];products={p['product_id']:p for p in w['public']['products']}
    models={v['product_id']:g['group_id'] for g in w['public']['product_groups'] for v in g['variants']}
    for row in content['retailers']:
        carried={o['product_id'] for o in w['public']['offers'] if o['retailer_id']==row['retailer_id']}
        if {products[p]['category'] for p in carried}=={'footwear'}:
            assert all(c['rule']['field']!='category' for c in row['collections'])
            assert all(c['title'] in ('Walking shoes','Running shoes','Hiking shoes','Dress shoes','Flip-flops') for c in row['collections'])
        for c in row['collections']:
            rule=c['rule'];expected={p for p in carried if products[p]['category']==rule['family'] and
                (rule['field']=='category' or products[p]['attributes'][rule['field']]==rule['value'])}
            assert set(c['product_ids'])==expected
        assert {m['model_id'] for m in row['merchandising']}=={models[p] for p in carried}
        for section in row['sections']:
            assert len({models[p] for p in section['product_ids']})==len(section['product_ids'])
            assert set(section['product_ids'])<=carried
    assert validate_storefront_content(w,content,accounts=sample['accounts'])['valid']


def test_introduction_dates_and_order_counts_respect_historical_accounts(sample,content):
    model_for={v['product_id']:g['group_id'] for g in sample['bundle']['public']['product_groups'] for v in g['variants']}
    rows={r['retailer_id']:{m['model_id']:m for m in r['merchandising']} for r in content['retailers']}
    window_start=iso(content['as_of'])-timedelta(days=29);known={}
    for a in sample['accounts']['accounts']:
        for o in a['orders']:
            for line in o['lines']:
                key=a['retailer_id'],model_for[line['product_id']];m=rows[key[0]][key[1]]
                assert m['introduced_on']<=o['placed_date']
                if iso(o['placed_date'])>=window_start and o['status']!='cancelled':known[key]=known.get(key,0)+line['quantity']
    assert all(rows[sid][mid]['units_ordered_30d']>=qty for (sid,mid),qty in known.items())
    for row in content['retailers']:
        for m in row['merchandising']:
            assert m['sales_rank_30d']==1+sum(other['units_ordered_30d']>m['units_ordered_30d'] for other in row['merchandising'])
    public=json.dumps(content)
    for a in sample['accounts']['accounts']:
        for order in a['orders']:assert order['order_id'] not in public
        for coupon in a['coupons']:assert coupon['code'] not in public


@pytest.mark.parametrize('mutation',['world','accounts','snapshot','collection','price_claim','future_date','rank','negative_sales','duplicate_model','unknown_product','newness','bestseller_order'])
def test_claim_or_binding_tampering_is_rejected(sample,content,mutation):
    a=deepcopy(content);row=a['retailers'][0]
    if mutation=='world':a['source_world_sha256']='wrong'
    elif mutation=='accounts':a['source_accounts_sha256']='wrong'
    elif mutation=='snapshot':a['sales_window']['start_date']='1900-01-01'
    elif mutation=='collection':row['collections'][0]['product_ids'].pop()
    elif mutation=='price_claim':row['sections'][0]['body']='Everything is half price with free delivery.'
    elif mutation=='future_date':row['merchandising'][0]['introduced_on']='2099-01-01'
    elif mutation=='rank':row['merchandising'][0]['sales_rank_30d']=9999
    elif mutation=='negative_sales':row['merchandising'][0]['units_ordered_30d']=-1
    elif mutation=='duplicate_model':row['sections'][0]['product_ids'].append(row['sections'][0]['product_ids'][0])
    elif mutation=='unknown_product':row['sections'][0]['product_ids'][0]='missing'
    elif mutation=='newness':
        for r in a['retailers']:
            for m in r['merchandising']:m['introduced_on']='2000-01-01'
        assert any(s['kind']=='new_arrivals' for r in a['retailers'] for s in r['sections'])
    elif mutation=='bestseller_order':
        section=next(s for r in a['retailers'] for s in r['sections'] if s['kind']=='bestsellers' and len(s['product_ids'])>1)
        section['product_ids'].reverse()
    with pytest.raises(ValueError):validate_storefront_content(sample['bundle'],a,accounts=sample['accounts'])


def test_zero_sales_do_not_produce_fake_bestsellers_and_ties_have_rank_one(sample):
    weights={k:int(k=='bestsellers') for k in KINDS}
    a=generate_storefront_content(sample['bundle'],config={'sales_multiplier':0,'section_kind_weights':weights})
    assert all(not row['sections'] for row in a['retailers'])
    assert all(m['units_ordered_30d']==0 and m['sales_rank_30d']==1 for row in a['retailers'] for m in row['merchandising'])


def test_historical_order_blocks_plausible_but_false_newness_and_sales_claims(sample,content):
    model_for={v['product_id']:g['group_id'] for g in sample['bundle']['public']['product_groups'] for v in g['variants']}
    account,order=next((a,o) for a in sample['accounts']['accounts'] for o in a['orders']
        if '2026-08-29'<=o['placed_date']<'2026-09-27' and o['status']!='cancelled')
    mid=model_for[order['lines'][0]['product_id']]
    for key,value,message in [('introduced_on','2026-09-27','historical orders'),('units_ordered_30d',0,'known history')]:
        bad=deepcopy(content)
        row=next(r for r in bad['retailers'] if r['retailer_id']==account['retailer_id'])
        next(m for m in row['merchandising'] if m['model_id']==mid)[key]=value
        with pytest.raises(ValueError,match=message):validate_storefront_content(sample['bundle'],bad,accounts=sample['accounts'])


def test_changed_account_snapshot_requires_new_bound_content(sample,content):
    with pytest.raises(ValueError,match='snapshot date'):
        generate_storefront_content(sample['bundle'],as_of='2026-09-28',accounts=sample['accounts'])
    different=deepcopy(sample['accounts']);different['accounts'][0]['signed_in']=not different['accounts'][0]['signed_in']
    with pytest.raises(ValueError,match='binding mismatch'):
        validate_storefront_content(sample['bundle'],content,accounts=different)


def test_small_catalog_and_legacy_activity_fallback():
    s=generate_scenario({'family':'footwear','hidden':'none'},{'store_count':2,'models_per_store':1})
    a=generate_storefront_content(s['bundle'],config={'section_count_weights':{'2':0,'3':1}})
    assert validate_storefront_content(s['bundle'],a)['valid']
    for row in a['retailers']:
        assert len(row['sections'])<=min(3,len(row['merchandising']))
        assert all(c['rule']['field'] in ('shoe_type','activity') for c in row['collections'] if c['rule']['family']=='footwear')


@pytest.mark.parametrize('patch',[{'unknown':1},{'new_arrival_probability':1.1},{'sales_multiplier':float('nan')},
 {'products_per_section':True},{'maximum_age_days':1},{'new_arrival_days':0},
 {'section_kind_weights':{k:0 for k in KINDS}}])
def test_invalid_priors_rejected(sample,patch):
    with pytest.raises(ValueError):generate_storefront_content(sample['bundle'],config=patch)


def test_attachment_preserves_every_business_fact_and_answer_and_binds_episode(sample):
    before=deepcopy(sample);new=attach_storefront_content(sample,seed=42)
    assert sample==before and {k:v for k,v in new.items() if k!='storefront_content'}==sample
    assert evaluate(new)==evaluate(sample)
    e=Episode(new,index_url='http://localhost:12345');old=Episode(sample,index_url='http://localhost:12345')
    assert e.reference()==old.reference() and e.episode_id!=old.episode_id
    a=e.policy_input();b=old.policy_input();a.pop('episode_id');b.pop('episode_id');assert a==b
    rt=SimpleNamespace(index_origin='http://localhost:12345',public_manifest={'index_url':'http://localhost:12345','sites':[
        {'site_id':st['retailer_id'],'kind':'retailer','origin':f'http://localhost:{13000+i}'} for i,st in enumerate(sample['bundle']['public']['retailers'])]},
        provenance={'world_sha256':sample['bundle']['world_sha256'],'locations_sha256':sample['locations']['locations_sha256'],
                    'merchant_reviews_public_sha256':digest(sample['merchant_reviews']['public']),
                    'accounts_sha256':digest(sample['accounts']),'storefront_content_sha256':digest(new['storefront_content'])},
        storefront_content=new['storefront_content'])
    assert Episode.from_runtime(new,rt).episode_id==e.episode_id
    with pytest.raises(ValueError,match='lacks runtime storefront'):Episode.from_runtime(sample,rt)
    rt.provenance['storefront_content_sha256']='wrong'
    with pytest.raises(ValueError,match='different storefront'):Episode.from_runtime(new,rt)
