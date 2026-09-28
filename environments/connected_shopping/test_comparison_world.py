"""Frozen membership -> HTTP/index projection, separate from generator sampling tests."""
import json
import os
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
import pytest
from .pins import load_pin
from .runtime import Runtime


@pytest.fixture(scope='module')
def covered_world():
    pin=os.environ.get('CONNECTED_SHOPPING_COMPARISON_PIN')
    coverage_path=os.environ.get('CONNECTED_SHOPPING_COVERAGE_FILE')
    if not pin and not coverage_path:
        pytest.skip('Select frozen acceptance inputs with CONNECTED_SHOPPING_COMPARISON_PIN and CONNECTED_SHOPPING_COVERAGE_FILE')
    if not pin or not coverage_path:
        pytest.fail('Both comparison pin and coverage file must be supplied')
    scenario,_=load_pin(pin)
    coverage=json.loads(Path(coverage_path).read_text())
    with Runtime(scenario,comparison_coverage=coverage,consent=False) as rt:yield rt,coverage


def test_index_and_direct_routes_match_site_membership(covered_world):
    rt,coverage=covered_world
    assert len(rt.comparison_designs)==4 and 'aggregator' not in rt.sites
    assert len({s['origin'] for s in rt.site_records})==18
    for site in coverage['sites']:
        sid=site['site_id'];design=rt.comparison_designs[sid]
        documents=[d for d in rt.documents if d['site_id']==sid and d['path']!='/']
        assert {d['path'] for d in documents}==set(design.by_path)
        for doc in documents:assert urlopen(rt.origins[sid]+doc['path']).status==200
        missing=next(i for i in rt.comparisons if i['id'] not in design.by_id)
        with pytest.raises(HTTPError) as error:urlopen(rt.origins[sid]+missing['path'])
        assert error.value.code==404
        if design.layout=='finder':
            with pytest.raises(HTTPError) as error:urlopen(rt.origins[sid]+'/retailers?id='+missing['id'])
            assert error.value.code==404


def test_all_untracked_products_keep_retailer_discovery_and_canonical_offers(covered_world):
    rt,_=covered_world;tracked={i for d in rt.comparison_designs.values() for i in d.by_id}
    missing=[i for i in rt.comparisons if i['id'] not in tracked]
    offered=0
    for item in missing:
        assert rt.bindings['comparison_products'][item['id']]==[]
        assert not rt.index.catalog.search(item['name'],kind='aggregator')
        canonical=[o for o in rt.offers.values() if o['product_id']==item['id'] or rt.group_for[o['product_id']]['group_id']==item['id']]
        if canonical:
            offered+=1;assert rt.index.catalog.search(item['name'],kind='retailer')
    assert offered==9  # Frozen sample, not a sampler feasibility requirement.
    assert len(rt.offers)==len(rt.world['public']['offers'])


def test_covered_price_is_site_specific_and_empty_feed_is_honest(covered_world):
    rt,cov=covered_world
    for site in cov['sites']:
        d=rt.comparison_designs[site['site_id']];pairs={(r['comparison_id'],r['retailer_id']) for r in site['listings']}
        for item in d.items:
            assert {(item['id'],r['retailer_id']) for r in d.offers(item)}=={pair for pair in pairs if pair[0]==item['id']}
    empty=rt.comparison_designs['comparison-laptops']
    assert len(empty.items)==3 and all(not empty.offers(i) for i in empty.items)
    assert all(empty.price(i) is None for i in empty.items)
    assert any(rt.offers[o]['product_id'] in empty.by_id for o in rt.offers)


def test_hidden_filter_parameters_rejected_over_http(covered_world):
    rt,_=covered_world
    for sid,query in [('comparison-footwear','max_price=1000'),('comparison-general-b','sort=price_asc'),('comparison-laptops','f_keyboard_layout_0=1')]:
        with pytest.raises(HTTPError) as error:urlopen(rt.origins[sid]+'/search?'+query)
        assert error.value.code==400
