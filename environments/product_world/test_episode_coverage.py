from copy import deepcopy
from types import SimpleNamespace

import pytest

from .test_episode import scenario,winning_answer
from .comparison_coverage import generate_coverage,identities
from .episode import Episode
from .generator import digest


def runtime_for(scenario,omitted=False):
    world=scenario['bundle']
    coverage=generate_coverage(world,[{'site_id':'a','families':['footwear']},{'site_id':'b','families':['footwear']}],
        config={'retailer_only_probability':1 if omitted else 0,'shared_core_probability':1})
    sites=[{'site_id':s['retailer_id'],'kind':'retailer','origin':'http://localhost:'+str(6000+i)}
           for i,s in enumerate(world['public']['retailers'])]
    sites.extend({'site_id':sid,'kind':'aggregator','origin':'http://localhost:'+str(7000+i)} for i,sid in enumerate(('a','b')))
    origins={s['site_id']:s['origin'] for s in sites}
    families,_,_=identities(world)
    bindings={'comparison_products':{cid:[origins[s['site_id']]+('/models/' if f=='footwear' else '/products/')+cid
        for s in coverage['sites'] if cid in s['comparison_ids']] for cid,f in families.items()}}
    return SimpleNamespace(public_manifest={'index_url':'http://localhost:5555','sites':sites},index_origin='http://localhost:5555',
        comparison_coverage=coverage,bindings=bindings,provenance={'world_sha256':world['world_sha256'],
            'locations_sha256':scenario['locations']['locations_sha256'],
            'merchant_reviews_public_sha256':digest(scenario['merchant_reviews']['public']),
            'comparison_coverage_sha256':digest(coverage),'bindings_sha256':digest(bindings)})


def test_omission_changes_links_not_global_candidates_or_grading(scenario):
    full=Episode.from_runtime(scenario,runtime_for(scenario))
    omitted=Episode.from_runtime(scenario,runtime_for(scenario,omitted=True))
    assert full.reference()==omitted.reference()
    assert full._candidates==omitted._candidates
    assert all(not links for links in omitted._comparison_urls.values())
    assert omitted.grade(winning_answer(scenario,omitted),effects=[])['structured_claims_correct']


def test_comparison_exception_accepts_each_covered_site_only(scenario):
    from environments.shopping_intent.answer_contract import extend
    scenario=deepcopy(scenario);scenario['task']=extend(scenario['task'],'comparison')
    runtime=runtime_for(scenario);episode=Episode.from_runtime(scenario,runtime)
    answer=winning_answer(scenario,episode);answer.pop('offer_url')
    for url in episode._comparison_urls[answer['sku_id']]:
        assert episode.grade({**answer,'comparison_url':url},effects=[])['structured_claims_correct']
    assert len(episode._comparison_urls[answer['sku_id']])==2
    assert not episode.grade({**answer,'comparison_url':'http://localhost:9999/models/missing'},effects=[])['structured_claims_correct']
    omitted=Episode.from_runtime(scenario,runtime_for(scenario,omitted=True))
    assert not omitted.grade({**answer,'comparison_url':url},effects=[])['structured_claims_correct']
    with pytest.raises(ValueError,match='outside coverage'):
        Episode.from_runtime(scenario,runtime_for(scenario,omitted=True),comparison_urls={answer['sku_id']:url})


@pytest.mark.parametrize('failure',['missing','coverage_hash','bindings_hash','invented_url','missing_site'])
def test_stale_or_invented_coverage_binding_rejected(scenario,failure):
    runtime=runtime_for(scenario)
    if failure=='missing':del runtime.comparison_coverage
    if failure=='coverage_hash':runtime.provenance['comparison_coverage_sha256']='wrong'
    if failure=='bindings_hash':runtime.provenance['bindings_sha256']='wrong'
    if failure=='invented_url':
        cid=next(iter(runtime.bindings['comparison_products']))
        runtime.bindings['comparison_products'][cid].append('http://localhost:9999/products/made-up')
        runtime.provenance['bindings_sha256']=digest(runtime.bindings)
    if failure=='missing_site':runtime.public_manifest['sites'].pop()
    with pytest.raises(ValueError):Episode.from_runtime(scenario,runtime)
