"""Append-only name capacity without changing population or profile draws."""
from copy import deepcopy
import pytest
from environments.product_world import footwear_context_pilot as footwear
from . import model, package_export
from .execution import Execution
from .catalog_registry import FIRST_ADDITIONS

@pytest.mark.parametrize('seed',[1,62,63])
def test_all_legacy_draws_unchanged_and_full_candidate_scope_can_be_named(seed):
    spec=footwear.load_spec();old=deepcopy(spec);actual=[];legacy=[]
    count=len(spec['brand_sampling']['scopes']['footwear']['names'])
    for slot in range(24):
        selected=model._footwear_brand_spec(spec,actual)
        brand=footwear.sample_brand(seed,slot,selected,existing=actual)
        if slot<count:
            assert selected is spec
            baseline=footwear.sample_brand(seed,slot,spec,existing=legacy)
            assert brand==baseline
            legacy.append(baseline)
        else:assert brand['name'] in model.FOOTWEAR_OVERFLOW_NAMES
        actual.append(brand)
    assert len({b['name'].casefold() for b in actual})==24
    assert spec==old
    # New names never change positioning/emphasis/fit for a given prior profile.
    expanded=model._footwear_brand_spec(spec,actual[:count])
    for slot in range(count,24):
        alternative=deepcopy(expanded);alternative['brand_sampling']['scopes']['footwear']['names']=[n+'a' for n in expanded['brand_sampling']['scopes']['footwear']['names']]
        a=footwear.sample_brand(seed,slot,expanded,existing=actual[:slot])
        b=footwear.sample_brand(seed,slot,alternative,existing=actual[:slot])
        assert {k:v for k,v in a.items() if k!='name'}=={k:v for k,v in b.items() if k!='name'}

def test_failed_broad38_population_now_retains_its_full_draw():
    world=Execution().generate(62,concept_ids=(*package_export.CONCEPTS,*FIRST_ADDITIONS),
        tasks=['footwear.walking_shoes'],controls={'world_size':4,'product_concentration':1,
        'retailer_concentration':0,'within_store_task_concentration':1,
        'unrelated_store_assortment_weight':1,'brand_diversity':1},review_count=0)
    brands=[b for b in world['brands'] if b['scope_id']=='footwear']
    assert len(brands)>12 and len({b['name'].casefold() for b in brands})==len(brands)
    assert world['controls']['world_size']==4
    assert model.validate(world)['valid']
