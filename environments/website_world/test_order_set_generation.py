"""Fresh opt-in multi-item integration, with original producer pins preserved."""
from copy import deepcopy
import json
import pytest

from environments.website_world import generation as g
from experiments.footwear_world_pilot import order_set_task as tasks, order_set_grader as grader


def request():
    return {'schema':g.VERSION,'seed':2,'world':{'controls':{'world_size':1}},
        'basket_shipping':{'enabled':True},'checkout_domain':{},
        'difficulty':{'reset_weights':{'preserve':0,'services':1,'delivery':0,'checkout':0}},
        'order_set_task':{'schema_version':tasks.VERSION,'objective':tasks.OBJECTIVE,
            'requirements':[
                {'requirement_id':'sandals','quantity':1,'concept_id':'footwear.walking_sandals','size_eu':42},
                {'requirement_id':'shoes','quantity':1,'concept_id':'footwear.walking_shoes','size_eu':44}],
            'domain':{'destination':'user_home','allowed_destination_types':['home']}},
        'requirements':[{'id':'reset','target':{'kind':'all_retailers'},'conditions':{'site.resetPolicy':['services']}}]}


def answer(ref,bindings):
    result=ref['result'];orders=[]
    for o in result['solutions'][0]['orders']:
        orders.append({'retailer_id':o['retailer_id'],'lines':[{'offer_id':l['offer_id'],'quantity':l['quantity'],
            'url':bindings['retailer_offers'][l['offer_id']]['url'],
            'selection':bindings['retailer_offers'][l['offer_id']]['required_selection']} for l in o['lines']],
            'selections':o['quote']['selection'],'split':o['quote']['split'],'coupon_code':o['coupon_code'],'total_minor':o['cost']})
    return {'schema_version':grader.VERSION,'status':'plan','orders':orders,'total_minor':result['total_minor']}


def test_new_generated_task_and_exact_requotes_preserve_original_world(tmp_path):
    spec=request();out=tmp_path/'world';manifest=g.prepare(spec,out)
    assert manifest['task_kind']=='native_order_set' and manifest['structured_order_set_grader_supported']
    assert manifest['automatic_grader_supported'] is False
    w=json.loads((out/'pin/world.json').read_text());audit=json.loads((out/'sampling-audit.private.json').read_text())
    assert g.digest(w)==g.digest(g.producer.generate(audit['selected_seed'],controls={'world_size':1}))
    ref=json.loads((out/'order-set-reference.private.json').read_text())
    assert ref['result']['complete'] and ref['result']['status']=='optimal'
    assert json.loads((out/'reference.private.json').read_text())==w['reference']
    assert all(c['config']['resetPolicy']=='services' for c in json.loads((out/'compositions.private.json').read_text()).values())
    with g.GeneratedEpisode(out) as episode:
        assert 'walking sandals, EU 42' in episode.public['user_message'] and 'walking shoes, EU 44' in episode.public['user_message']
        result=episode.grade_structured(answer(ref,episode.runtime.bindings))
        assert result['verdict']=='pass'
        assert len(result['components']['outcome']['quotes'])>=1
        assert len(episode.public['memories'])==1 and episode.public['memories'][0].startswith('My home address')
        runtime_packet=tmp_path/'runtime';episode.export_private_runtime(runtime_packet)
        from scripts.grade_website_order_set import grade
        structured=answer(ref,episode.runtime.bindings)
        assert grade(out,structured,runtime_packet)['verdict']=='pass'
        assert grade(out,structured)['verdict']=='inconclusive'
        (runtime_packet/'bindings.private.json').write_text('{}')
        assert grade(out,structured,runtime_packet)['verdict']=='inconclusive'
        assert episode.runtime.snapshot()['orders']==[]
        assert episode.runtime.snapshot()['commerce_mutations']==[]
    assert spec==request()


@pytest.mark.parametrize('kind',['best_matching_retailers','world_reference'])
def test_legacy_winner_selector_cannot_silently_target_new_basket_objective(kind):
    spec=request();spec['requirements']=[{'id':'wrong','target':{'kind':kind},
        **({'status':['match']} if kind=='world_reference' else {'conditions':{'site.url':['none']}})}]
    with pytest.raises(ValueError,match='Single-offer winner'):g.compile_request(spec)


def test_search_exhaustion_returns_unknown_without_resampling_a_different_world():
    spec=request();spec['requirements']=[];spec['order_set_search']={'max_work':1}
    with pytest.raises(g.SamplingBudgetExceeded) as exc:g.generate(spec)
    assert exc.value.audit['status']=='order_set_search_exhausted'
    assert exc.value.audit['feasibility']=='unknown'
    assert len(exc.value.audit['proposals'])==1
    assert not exc.value.audit['order_set_reference']['result']['complete']


def test_request_is_supplied_before_sampling_and_unsupported_range_is_rejected():
    spec=request();spec['order_set_task']['requirements'][0]['facts']={'market_range':'women'}
    with pytest.raises(tasks.UnsupportedTask):g.compile_request(spec)
