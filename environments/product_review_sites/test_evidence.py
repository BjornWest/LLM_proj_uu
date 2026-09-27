from copy import deepcopy

import pytest

from environments.product_world.stores import generate_store_world
from .evidence import generate_evidence,validate_evidence,render_report,digest,ASPECTS


@pytest.fixture(scope='module')
def world():return generate_store_world(42,models_per_store=3)


@pytest.fixture(scope='module')
def evidence(world):return generate_evidence(world,seed=42)


def test_deterministic_all_family_templates_use_exact_catalog_slots(world,evidence):
    assert evidence==generate_evidence(world,seed=42)
    products={p['product_id']:p for p in world['public']['products']}
    assert {products[r['subject']['id']]['category'] for r in evidence['public']['reviews']}=={'footwear','laptops','dog_food','cat_food','beer','wine'}
    bodies=[]
    for r in evidence['public']['reviews']:
        p=products[r['subject']['id']]
        assert r['body']==render_report(r,p)
        assert all(k in p['attributes'] for k in r['mentioned_attributes'])
        for a in r['assessments']:assert p['category'] in ASPECTS[a['aspect_id']]['families']
        bodies.append(r['body'])
    assert len(set(bodies))>.9*len(bodies)
    assert {a['stance'] for r in evidence['public']['reviews'] for a in r['assessments']}=={'positive','negative','neutral','mixed'}
    assert all(r['assessments'] for r in evidence['public']['reviews'])
    assert any(len(r['assessments'])==1 for r in evidence['public']['reviews'])
    assert any(not r['mentioned_attributes'] for r in evidence['public']['reviews'])


def test_task_price_stock_and_model_order_do_not_affect_reports(world,evidence):
    changed=deepcopy(world)
    for o in changed['public']['offers']:o['price_minor']+=10000;o['stock_quantity']=0
    changed['public']['product_groups'].reverse()
    generated=generate_evidence(changed,seed=42)
    assert generated['public']['reviews']==evidence['public']['reviews']
    assert generated['public']['coverage']==evidence['public']['coverage']


def test_zero_reviews_is_complete_but_unreviewed_sibling_has_no_coverage(world):
    e=generate_evidence(world,reviews_per_sku=0)
    assert e['public']['reviews']==[] and e['public']['coverage']
    assert all(c['status']=='complete' for c in e['public']['coverage'])
    assert len({c['sku_id'] for c in e['public']['coverage']})<len(world['public']['products'])


def test_stars_follow_primary_experience_and_nonusers_do_not_claim_experience(world,evidence):
    from .evidence import PRIMARY
    products={p['product_id']:p for p in world['public']['products']}
    for r in evidence['public']['reviews']:
        if r['usage_reports'][0]['experience_kind']!='actual_use':
            assert 'how it worked out for me' not in r['body']
        else:
            primary=PRIMARY[products[r['subject']['id']]['category']]
            stance=next((a['stance'] for a in r['assessments'] if a['aspect_id']==primary),None)
            if stance=='positive' and r['stars'] is not None:assert r['stars']>=4
            if stance=='negative' and r['stars'] is not None:assert r['stars']<=2


def test_original_template_records_remain_valid(world,evidence):
    original=deepcopy(evidence);products={p['product_id']:p for p in world['public']['products']}
    for r in original['public']['reviews']:
        if r['usage_reports'][0]['experience_kind']!='actual_use':r['assessments']=[]
        r.pop('template_version');r['body']=render_report(r,products[r['subject']['id']])
    original['private_provenance']['public_sha256']=digest(original['public'])
    assert validate_evidence(world,original)['valid']


def test_natural_reviews_do_not_announce_the_grading_labels(evidence):
    rows=evidence['public']['reviews']
    assert {r['template_version'] for r in rows}=={3,4}
    assert all(r['usage_reports'][0]['experience_kind']!='intention' for r in rows)
    for r in rows:
        for shortcut in ('this is about','have experience of','first-hand experience','listed configuration',
                         'For reference, the listing','I am not giving a view','personal impression, not a specification'):
            assert shortcut not in r['body']
    heard=[r for r in rows if r['usage_reports'][0]['experience_kind']=='hearsay']
    assert heard and all(r['assessments'] and '“' in r['body'] for r in heard)
    assert any(r['stars'] is not None for r in heard)
    assert any(r['stars'] is None and r['usage_reports'][0]['experience_kind']=='actual_use' for r in rows)


def test_first_person_inside_second_hand_quote_is_not_a_first_hand_vote(world,evidence):
    from environments.shopping_intent.review_evidence import summarize
    row=next(r for r in evidence['public']['reviews'] if r['usage_reports'][0]['experience_kind']=='hearsay')
    a=row['assessments'][0]
    result=summarize([row],sku_id=row['subject']['id'],aspect_id=a['aspect_id'],context_id=a['context_id'],complete=True)
    assert result['contextual_reviewer_count']==0 and result['majority_positive'] is None


def test_natural_attribute_annotation_cannot_claim_unused_slots(world,evidence):
    e=deepcopy(evidence);products={p['product_id']:p for p in world['public']['products']}
    row=next(r for r in e['public']['reviews'] if not r['mentioned_attributes'])
    row['mentioned_attributes']=[next(iter(products[row['subject']['id']]['attributes']))]
    e['private_provenance']['public_sha256']=digest(e['public'])
    with pytest.raises(ValueError,match='prose slots'):validate_evidence(world,e)


@pytest.mark.parametrize('failure',['body','catalog','corpus','scope','duplicate','author','date','aspect','coverage'])
def test_tampered_corpus_is_rejected_even_with_recomputed_hash(world,evidence,failure):
    e=deepcopy(evidence);r=e['public']['reviews'][0]
    if failure=='body':r['body']='Guaranteed to be comfortable for everyone.'
    if failure=='catalog':e['public']['source_catalog_sha256']='wrong'
    if failure=='scope':r['subject']['scope']='model'
    if failure=='duplicate':e['public']['reviews'].append(deepcopy(r))
    if failure=='author':e['public']['reviews'][1]['reviewer_id']=r['reviewer_id']
    if failure=='date':r['published_date']='2099-01-01'
    if failure=='aspect':r['assessments'].append({'aspect_id':'nonexistent','context_id':'tasting','stance':'positive'})
    if failure=='coverage':e['public']['coverage'].append(deepcopy(e['public']['coverage'][0]))
    e['private_provenance']['public_sha256']='wrong' if failure=='corpus' else digest(e['public'])
    with pytest.raises(ValueError):validate_evidence(world,e)
