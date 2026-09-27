import copy
import json
from types import SimpleNamespace

import pytest

from environments.site_consent.runtime import ConsentUI, PURPOSES
from .episode import Episode
from .scenario import generate_scenario
from .outcomes import candidates_for
from .generator import digest


@pytest.fixture(scope='module')
def scenario():
    return generate_scenario({'seed':0,'family':'footwear','requirements':1,'hidden':'none',
        'memory':'mixed','destination_city':'malmo','world_preferences':'none','cookie_preferences':'analytics_allowed'},
        {'seed':42,'models_per_store':3},
        {'merchant_home_cities':{'store-001':'copenhagen','store-002':'malmo'}},
        {'seed':7,'as_of':'2026-09-26','reviews_per_store':24})


@pytest.fixture(scope='module')
def episode(scenario):
    return Episode(scenario,index_url='http://localhost:12345/',offer_urls={
        o['offer_id']:'http://localhost:12346/offer/'+o['offer_id'] for o in scenario['bundle']['public']['offers']})


def winning_answer(scenario,episode):
    best=episode.reference()['best_candidate_ids']
    c=next(c for c in candidates_for(scenario) if c['candidate_id'] in best)
    return {'status':'selection','offer_id':c['offer_id'],'sku_id':c['lines'][0]['sku_id'],
            'offer_url':episode._offer_urls[c['offer_id']],'total_minor':c['total_minor']}


def test_policy_projection_excludes_oracle_hidden_fields_and_private_bindings(episode):
    public=episode.policy_input();text=json.dumps(public)
    assert public['start_url']=='http://localhost:12345/'
    assert public['memories']['profile']
    for key in ('best_candidate_ids','world_sha256','semantic_sha256','private_provenance','cookie_memory_facts','memory_facts','resolved_task','hidden_user_specifications'):
        assert key not in text
    public['memories']['profile'].clear()
    assert episode.policy_input()['memories']['profile']


def test_task_card_exports_only_policy_input(episode,tmp_path):
    from pathlib import Path
    paths=episode.write_policy_bundle(tmp_path)
    assert json.loads(Path(paths['task_json']).read_text())==episode.policy_input()
    html=Path(paths['task_html']).read_text()
    assert 'EU shoe size' in html and 'Open the shopping world' in html
    assert all(private not in html for private in ('best_candidate_ids','private_provenance','world_sha256'))


def test_public_selection_binding_accepts_ids_and_urls_but_rejects_oracle_ids(scenario,episode):
    answer=winning_answer(scenario,episode)
    assert episode.grade(answer,effects=[])['structured_claims_correct']
    url_answer={**answer,'offer_url':'http://localhost:12346/offer/'+answer['offer_id']};url_answer.pop('offer_id')
    assert episode.grade(url_answer,effects=[])['structured_claims_correct']
    spoof={**answer,'sku_id':'different-sku'}
    assert not episode.grade(spoof,effects=[])['structured_claims_correct']
    private={'status':'selection','candidate_id':episode.reference()['best_candidate_ids'][0],'total_minor':answer['total_minor']}
    assert not episode.grade(private,effects=[])['structured_claims_correct']
    with pytest.raises(ValueError):episode.grade(answer,effects=None)
    assert not episode.grade(answer,effects=[{'event':'purchase'}])['structured_claims_correct']


def test_wrong_total_and_nonoptimal_feasible_selection_fail(scenario,episode):
    answer=winning_answer(scenario,episode)
    assert not episode.grade({**answer,'total_minor':answer['total_minor']+1},effects=[])['structured_claims_correct']
    reference=episode.reference()
    alternatives=set(reference['eligible_candidate_ids'])-set(reference['best_candidate_ids'])
    assert alternatives
    other=next(c for c in candidates_for(scenario) if c['candidate_id'] in alternatives)
    assert not episode.grade({'status':'selection','offer_id':other['offer_id'],'sku_id':other['lines'][0]['sku_id'],
        'offer_url':episode._offer_urls[other['offer_id']],'total_minor':other['total_minor']},effects=[])['structured_claims_correct']


def test_consent_component_is_separate_and_bounded_across_sites(scenario,episode):
    evidence=[]
    for _ in range(2):
        ui=ConsentUI('bottom-banner');state,cookie=ui.begin(None)
        assert ui.commit(cookie,{'csrf':state['csrf'],'revision':0,'action':'reject','preferences':dict.fromkeys(PURPOSES,False)})[0]==200
        evidence.append({'journal':ui.snapshot(),'preference_exposed':True,'exposed_sessions':[state['session_id']]})
    grade=episode.grade(winning_answer(scenario,episode),effects=[],consent_evidence=evidence)
    assert grade['structured_claims_correct'] and grade['auxiliary_consent']['weighted_reward']==.05
    assert episode.grade(winning_answer(scenario,episode),effects=[])['auxiliary_consent']['score'] is None


def test_runtime_binding_and_stale_task_rejected(scenario):
    runtime=SimpleNamespace(index_origin='http://localhost:5555',public_manifest={'index_url':'http://localhost:5555/',
        'sites':[{'site_id':s['retailer_id'],'kind':'retailer','origin':'http://localhost:'+str(6000+i)}
                 for i,s in enumerate(scenario['bundle']['public']['retailers'])]},
        provenance={'world_sha256':scenario['bundle']['world_sha256'],
                    'locations_sha256':scenario['locations']['locations_sha256'],
                    'merchant_reviews_public_sha256':digest(scenario['merchant_reviews']['public'])})
    assert Episode.from_runtime(scenario,runtime).policy_input()['start_url']==runtime.public_manifest['index_url']
    for field in runtime.provenance:
        bad_runtime=copy.deepcopy(runtime);bad_runtime.provenance[field]='different'
        with pytest.raises(ValueError,match='different world'):Episode.from_runtime(scenario,bad_runtime)
    bad=copy.deepcopy(scenario);bad['task']['resolved_task']['constraints']['budget_minor']=1
    with pytest.raises(ValueError,match='fingerprint'):Episode(bad,index_url=runtime.index_origin)


def test_recommendations_require_sku_and_link_even_with_correct_price(scenario,episode):
    good=winning_answer(scenario,episode)
    for omitted in ('sku_id','offer_url'):
        bad={k:v for k,v in good.items() if k!=omitted}
        assert not episode.grade(bad,effects=[])['structured_claims_correct']
    for wrong in ('http://localhost:12346/','http://localhost:12345/models/shoe','https://wrong.example/products/shoe'):
        assert not episode.grade({**good,'offer_url':wrong},effects=[])['structured_claims_correct']


def test_variant_links_resolve_selected_sku_not_source_path(scenario):
    from urllib.parse import urlencode
    origins={s['retailer_id']:'http://localhost:'+str(7000+i) for i,s in enumerate(scenario['bundle']['public']['retailers'])}
    bound=Episode(scenario,index_url='http://localhost:5555',offer_urls={
        o['offer_id']:origins[o['retailer_id']]+'/products/'+o['product_id'] for o in scenario['bundle']['public']['offers']})
    answer=winning_answer(scenario,bound)
    offer=next(o for o in scenario['bundle']['public']['offers'] if o['offer_id']==answer['offer_id'])
    group=next(g for g in scenario['bundle']['public']['product_groups'] if any(v['product_id']==offer['product_id'] for v in g['variants']))
    variant=next(v for v in group['variants'] if v['product_id']==offer['product_id'])
    source=next(v for v in group['variants'] if v['product_id']!=offer['product_id'])
    prefix=origins[offer['retailer_id']]+'/products/'+source['product_id']
    q={'option_'+k:v for k,v in variant['selection'].items()};q['quantity']='1'
    url=prefix+'?'+urlencode(q)
    assert bound.grade({**answer,'offer_url':url},effects=[])['structured_claims_correct']
    assert bound.grade({**answer,'offer_url':url.replace('localhost','127.0.0.1')+'#offer-quote'},effects=[])['structured_claims_correct']
    wrong={'option_'+k:v for k,v in source['selection'].items()}
    assert not bound.grade({**answer,'offer_url':prefix+'?'+urlencode(wrong)},effects=[])['structured_claims_correct']
    for bad in (prefix+'?'+urlencode({**q,'quantity':'2'}),url+'&quantity=1',prefix+'?option_size_eu=bad'):
        assert not bound.grade({**answer,'offer_url':bad},effects=[])['structured_claims_correct']


def test_ambiguous_url_bindings_rejected(scenario):
    offers=scenario['bundle']['public']['offers'][:2]
    with pytest.raises(ValueError,match='one retailer/SKU'):
        Episode(scenario,index_url='http://localhost:5555',offer_urls={o['offer_id']:'http://localhost:6666/products/same' for o in offers})


def test_average_links_are_optional_not_per_sku_requirements(scenario,episode):
    from environments.shopping_intent.world import fingerprint
    aggregate=copy.deepcopy(scenario)
    for field in ('request','resolved_task','initial_accessible_task'):
        aggregate['task'][field]['query']['operation']='aggregate'
        aggregate['task'][field]['query']['objective']=[]
    aggregate['task']['semantic_sha256']=fingerprint(aggregate['task'])
    avg=Episode(aggregate,index_url='http://localhost:12345',offer_urls=episode._offer_urls)
    ref=avg.reference();assert ref['retailer_count']>1
    links=[]
    for retailer,total in ref['population_prices_minor'].items():
        c=next(c for c in avg._candidates if c['candidate_id'] in ref['eligible_candidate_ids']
               and c['lines'][0]['retailer_id']==retailer and c['total_minor']==total)
        links.append(avg._offer_urls[c['offer_id']])
    answer={'status':'average','value_minor':ref['value_minor'],'retailer_count':ref['retailer_count'],'source_urls':links}
    assert avg.grade(answer,effects=[])['structured_claims_correct']
    assert avg.grade({**answer,'source_urls':links[:1]},effects=[])['structured_claims_correct']
    without_links={k:v for k,v in answer.items() if k!='source_urls'}
    assert avg.grade(without_links,effects=[])['structured_claims_correct']
    assert avg.grade({**without_links,'overview_url':'http://localhost:12345/models/shoes'},effects=[])['structured_claims_correct']
    assert not avg.grade({**without_links,'value_minor':ref['value_minor']+1},effects=[])['structured_claims_correct']
    assert 'individual SKU links are not required' in avg.policy_input()['answer_contract']['source_urls']


def test_shortfall_and_uncertain_answers_still_supply_follow_up_links(episode):
    # Trusted candidate fixtures isolate the result-status/link contract.
    for availability,status in ((False,'no_match'),(None,'uncertain')):
        changed=copy.deepcopy(episode)
        for c in changed._candidates:c['purchasable']=availability
        assert changed.reference()['status']==status
        c=changed._candidates[0]
        answer={'status':status,'source_urls':[changed._offer_urls[c['offer_id']]]}
        assert changed.grade(answer,effects=[])['structured_claims_correct']
        assert not changed.grade({'status':status},effects=[])['structured_claims_correct']


def test_comparison_link_exception_requires_explicit_task_request(scenario,episode):
    from environments.shopping_intent.answer_contract import extend
    modified=copy.deepcopy(scenario);modified['task']=extend(modified['task'],'comparison')
    maps={v['product_id']:'http://localhost:12347/models/'+g['group_id']
          for g in modified['bundle']['public']['product_groups'] for v in g['variants']}
    cmp=Episode(modified,index_url='http://localhost:12345',offer_urls=episode._offer_urls,comparison_urls=maps)
    good=winning_answer(modified,cmp)
    comparison_answer={k:v for k,v in good.items() if k!='offer_url'}
    comparison_answer['comparison_url']=maps[good['sku_id']]
    assert cmp.grade(comparison_answer,effects=[])['structured_claims_correct']
    assert not cmp.grade(good,effects=[])['structured_claims_correct']
    assert not episode.grade({**comparison_answer,'selection_link':'comparison'},effects=[])['structured_claims_correct']
    assert not episode.grade({**good,'offer_url':maps[good['sku_id']]},effects=[])['structured_claims_correct']
    assert not cmp.grade({**comparison_answer,'comparison_url':'http://localhost:12347/models/wrong'},effects=[])['structured_claims_correct']
    assert 'compare retailers myself' in modified['task']['public']['user_message'] or 'look through the different retailers' in modified['task']['public']['user_message']
    assert ''.join(s['text'] for s in modified['task']['authoring']['message_segments'])==modified['task']['public']['user_message']


def test_sampler_exposes_comparison_request_as_task_semantics():
    from .scenario import sample_task
    from environments.shopping_intent.world import fingerprint
    task=sample_task(seed=0,family='footwear',hidden='none',selection_link='comparison')
    assert task['request']['response_requirements']=={'selection_link':'comparison'}
    assert task['semantic_sha256']==fingerprint(task)
    for query in ('average','nearest_pickup'):
        with pytest.raises(ValueError,match='single-product delivery'):
            sample_task(seed=0,family='footwear',query=query,destination_city='malmo',selection_link='comparison')
