from collections import Counter
from copy import deepcopy

import pytest

from .stores import generate_store_world, validate_store_world
from .generator import digest, generate_catalog
from .footwear_depth import TYPE_ACTIVITY, validate_blueprint
from .validation import validate_catalog
from environments.product_review_sites.evidence import generate_evidence, validate_evidence


@pytest.mark.parametrize('seed',[0,7,42,101])
def test_distinct_model_density_coherent_styles_overlap_and_size_listing(seed):
    world=generate_store_world(seed,models_per_store=3,footwear_depth={})
    assert validate_store_world(world)['valid']
    products={p['product_id']:p for p in world['public']['products']}
    groups={g['group_id']:g for g in world['public']['product_groups']}
    shoes=[g for g in groups.values() if g['family']=='footwear']
    kinds=Counter(products[g['variants'][0]['product_id']]['attributes']['shoe_type'] for g in shoes)
    assert kinds=={'walking shoes':6,'running shoes':2,'hiking shoes':2,'dress shoes':2,'flip-flops':2}
    assert len(shoes)==14 and len({g['name'] for g in shoes})==14
    carriers={g['group_id']:set() for g in shoes}
    for a in world['public']['assortments']:
        if groups[a['model_id']]['family']!='footwear':continue
        listed=[products[sku]['attributes'] for sku in a['product_ids']]
        assert any(p['size_eu']==40 and p['colour']=='black' and p['width']=='standard' for p in listed)
        carriers[a['model_id']].add(a['retailer_id'])
    assert all(carriers.values()) and sum(len(v)>1 for v in carriers.values())>=7
    for p in products.values():
        if p['category']=='footwear':
            attrs=p['attributes'];assert attrs['activity']==TYPE_ACTIVITY[attrs['shoe_type']]
            if attrs['shoe_type']=='flip-flops':assert attrs['waterproof'] is False
    assert all(set(g['axes'][0])=={'field','label','value_type','unit','options'} for g in shoes)


def test_stock_and_price_priors_do_not_change_type_plan_or_coverage():
    first=generate_store_world(42,models_per_store=3,footwear_depth={})
    changed=generate_store_world(42,models_per_store=3,footwear_depth={},
        config={'reference_price_multiplier':2},store_config={'stockout_probability':1})
    assert first['public']['product_groups']==changed['public']['product_groups']
    assert first['public']['assortments']==changed['public']['assortments']
    assert first['private_provenance']['footwear_depth']==changed['private_provenance']['footwear_depth']
    assert all(o['stock_quantity']==0 for o in changed['public']['offers'])
    assert first['public']==generate_store_world(42,models_per_store=3,footwear_depth={})['public']


def test_legacy_catalogs_without_optional_type_still_validate():
    w=generate_catalog(seed=42,model_count=10,model_families=['footwear']*10)
    assert validate_catalog(w)['valid']
    assert all('shoe_type' not in p['attributes'] and p['attributes']['activity'] in ('running','walking','hiking') for p in w['public']['products'])


def test_invalid_type_activity_even_with_rehashed_catalog_is_rejected():
    w=generate_store_world(42,models_per_store=3,footwear_depth={})['catalog']
    p=next(p for p in w['public']['products'] if p['attributes'].get('shoe_type')=='flip-flops')
    p['attributes']['activity']='hiking'
    w['catalog_sha256']=digest(w['public'])
    with pytest.raises(ValueError,match='Contradictory product facts'):validate_catalog(w)


def test_flip_flops_do_not_get_closed_heel_narratives_and_missing_claims_remain_missing():
    w=generate_store_world(42,models_per_store=3,footwear_depth={})
    e=generate_evidence(w,seed=42)
    products={p['product_id']:p for p in w['public']['products']}
    flip=[r for r in e['public']['reviews'] if products[r['subject']['id']]['attributes'].get('shoe_type')=='flip-flops']
    assert flip and all(not any(a['aspect_id']=='heel_rubbing' for a in r['assessments']) for r in flip)
    assert all('heel' not in r['body'].casefold() for r in flip)
    assert validate_evidence(w,e)['valid']
    r=flip[0];r['assessments'].append({'aspect_id':'heel_rubbing','context_id':'long_walks','stance':'positive'})
    e['private_provenance']['public_sha256']=digest(e['public'])
    with pytest.raises(ValueError,match='flip-flops'):validate_evidence(w,e)


def test_unknown_and_nonfootwear_blueprints_rejected():
    w=generate_store_world(42,models_per_store=3,footwear_depth={})
    b=deepcopy(w['catalog']['private_provenance']['model_blueprints'][0])
    with pytest.raises(ValueError):validate_blueprint('laptops',b)
    b['axis_values']['size_eu']=[True]
    with pytest.raises(ValueError):validate_blueprint('footwear',b)


def test_explicit_style_predicates_participate_in_intent_coherence():
    from environments.shopping_intent.semantics import conflicts, entails
    flip={'field':'shoe_type','operator':'eq','value':'flip-flops'}
    hike={'field':'activity','operator':'eq','value':'hiking'}
    beach={'field':'activity','operator':'eq','value':'beach'}
    assert conflicts('footwear',[flip,hike])
    assert not conflicts('footwear',[flip,beach])
    assert entails('footwear',[flip],beach)
