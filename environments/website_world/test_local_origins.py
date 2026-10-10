"""URL projection is deterministic, detached, and strictly local/opt-in."""
from copy import deepcopy
import pytest
from environments.website_world.local_origins import OriginMap, LocalOriginBridge
from environments.website_world import generation, unified_generation


def records():
    return [{'site_id': 'a', 'kind': 'retailer', 'name': 'Åsen Handel', 'origin': 'http://localhost:8311'},
            {'site_id': 'b', 'kind': 'review', 'name': 'The Reader', 'origin': 'http://localhost:8312'}]


def test_stable_names_independent_of_order_ports_and_detached_sources():
    source = records(); first = OriginMap(source, world_id='world')
    assert first.to_public('http://localhost:8311/') == 'https://asen-handel.test/'
    other = deepcopy(source)
    other[0]['origin'] = 'http://localhost:9131'; other[1]['origin'] = 'http://localhost:9132'
    second = OriginMap(reversed(other), world_id='world')
    assert {r['site_id']: r['logical_origin'] for r in first.descriptor['sites']} == {
        r['site_id']: r['logical_origin'] for r in second.descriptor['sites']}
    source[0]['name'] = 'Mutation'
    first.descriptor['sites'][0]['name'] = 'Other mutation'
    assert first.descriptor['sites'][0]['name'] == 'Åsen Handel'


def test_name_collision_gets_stable_identity_suffix():
    source = records(); source[1]['name'] = 'Asen Handel'
    m = OriginMap(source, world_id='world')
    urls = [r['logical_origin'] for r in m.descriptor['sites']]
    assert len(set(urls)) == 2 and all(u.startswith('https://asen-handel-') for u in urls)


def test_reference_roundtrip_preserves_all_non_url_fields_and_exact_suffix():
    m = OriginMap(records(), world_id='world')
    url = 'http://localhost:8311/path%2Fitem?value=a%2Bb#/product/id?size=42&colour=blue'
    projected = m.project({'url': url, 'selection': {'size': '42'}, 'price_minor': 62400,
                           'offer_id': 'a/id', 'nested': [url]})
    assert projected['selection'] == {'size': '42'} and projected['price_minor'] == 62400
    assert projected['offer_id'] == 'a/id' and projected['nested'] == [projected['url']]
    assert m.to_transport(projected['url']) == url
    assert m.to_transport(projected['url'].replace('.test', '.TEST:443')) == url
    assert m.rewrite('http://localhost:83110/x') == 'http://localhost:83110/x'


@pytest.mark.parametrize('url', ['https://outside.test/', 'http://other.test/',
    'http://localhost:8311/', 'http://name:pass@asen-handel.test/', 'file:///tmp/a', 'https://asen-handel.test:81/'])
def test_undeclared_answer_destinations_reject(url):
    with pytest.raises(ValueError): OriginMap(records(), world_id='world').to_transport(url)


@pytest.mark.parametrize('url', ['http://example.com', 'http://127.0.0.2.evil.test',
    'https://localhost:8000', 'http://localhost:8000/path', 'http://name:pass@localhost:8000'])
def test_no_remote_or_ambiguous_transport(url):
    rows = records(); rows[0]['origin'] = url
    with pytest.raises(ValueError): OriginMap(rows, world_id='world')


def test_cookie_domain_rewriting_and_host_only_preservation():
    with_bridge = LocalOriginBridge(OriginMap(records(), world_id='world'))
    try:
        assert with_bridge._cookie('session=a; Domain=.localhost; Path=/; HttpOnly',
                    'https://asen-handel.test', 'http://localhost:8311') == 'session=a; Domain=asen-handel.test; Path=/; HttpOnly'
        assert with_bridge._cookie('session=a; Path=/', 'https://asen-handel.test', 'http://localhost:8311') == 'session=a; Path=/'
        assert with_bridge._cookie('session=a; Domain=outside.test', 'https://asen-handel.test', 'http://localhost:8311') == 'session=a; Domain=outside.test'
    finally: with_bridge.close()


@pytest.mark.parametrize('kind', ['directory', 'tool_discovery', 'retailer_home'])
def test_episode_opt_in_validation_and_old_shapes(kind):
    start = {'kind': kind, **({'retailer_id': 'retailer-1'} if kind == 'retailer_home' else {})}
    compiler = unified_generation.compile_request if kind == 'tool_discovery' else generation.compile_request
    schema = unified_generation.VERSION if kind == 'tool_discovery' else generation.VERSION
    request = {'schema': schema, 'seed': 1, 'episode': {'start': start}}
    assert compiler(request)['episode'] == {'start': start}
    request['episode']['readable_origins'] = True
    assert compiler(request)['episode'] == request['episode']
    for bad in ('true', 1, None):
        request['episode']['readable_origins'] = bad
        with pytest.raises(ValueError): compiler(request)
