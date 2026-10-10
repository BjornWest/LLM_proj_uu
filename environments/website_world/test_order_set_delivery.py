"""Fresh native order-set artifacts, live quote and grading share admitted menus."""
from copy import deepcopy
import json
from urllib.request import Request,urlopen
import pytest
from environments.website_world import generation as g
from environments.website_world.adapter import browser_address
from environments.website_world.test_order_set_generation import request,answer
from experiments.footwear_world_pilot import model,order_set_grader
from experiments.accepted_catalog_commerce import delivery_admission


def test_fresh_native_menu_artifacts_runtime_cli_and_requotes_agree(tmp_path):
    spec=request();spec['realism']={'delivery_options':{'enabled':True,'count_weights':{'1':1}},'page_variations':{'enabled':True}}
    spec['requirements']=[]
    before=deepcopy(spec);out=tmp_path/'fresh';manifest=g.prepare(spec,out)
    admission=json.loads((out/'delivery-plan.private.json').read_text());ref=json.loads((out/'order-set-reference.private.json').read_text())
    assert ref['result']['complete'] and ref['result']['admission_plan_sha256']==model.digest(admission)
    assert spec==before
    with g.GeneratedEpisode(out) as episode:
        runtime=episode.runtime
        assert runtime.delivery_plan==admission and runtime.manifest['delivery_options']
        if ref['result']['status']=='infeasible':
            assert episode.grade_structured({'schema_version':order_set_grader.VERSION,'status':'no_match'})['verdict']=='pass'
        else:
            submitted=answer(ref,runtime.bindings);assert episode.grade_structured(submitted)['verdict']=='pass'
            for order in submitted['orders']:
                rid=order['retailer_id'];catalog=runtime.public_catalogs[rid]
                for line in order['lines']:
                    binding=runtime.bindings['retailer_offers'][line['offer_id']]
                    ids={o['id'] for o in catalog['fulfilment']['optionsBySku'][binding['sku_id']]}
                    assert order['selections'][line['offer_id']] in ids
                data={'revision':1,'world_id':runtime.world['world_id'],'plan_id':runtime.baskets.plan_id,
                    'domain_id':runtime.baskets.domain_id,'lines':[{'line_id':l['offer_id'],'offer_id':l['offer_id'],'quantity':l['quantity']} for l in order['lines']],
                    'address':browser_address(next(a for a in runtime.world['address_context']['addresses'] if a['address_id']=='user-home')),
                    'selections':order['selections'],'split':order['split'],'coupon_code':order['coupon_code']}
                response=json.load(urlopen(Request(runtime.origins[rid]+'/api/basket-quote',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})))
                assert response['selected']['totalMinor']==order['total_minor']
                assert response['selected']['selection']==order['selections']
            packet=tmp_path/'bindings';episode.export_private_runtime(packet)
            from scripts.grade_website_order_set import grade
            assert grade(out,submitted,packet)['verdict']=='pass'
        assert runtime.snapshot()['orders']==[]


def test_single_offer_reference_still_rejects_menus_before_sampling():
    with pytest.raises(ValueError,match='native reference'):
        g.generate({'schema':g.VERSION,'seed':1,'realism':{'delivery_options':{'enabled':True}}},
            world_factory=lambda *a,**kw:pytest.fail('Unsupported reference must fail before generation'))
