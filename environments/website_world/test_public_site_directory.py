"""Public directory completeness and explicit episode-mode compatibility."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from environments.website_world.site_discovery import DiscoverSites, scope_description
from environments.website_world.discovery import Index, retailer_records, directory_page
from environments.website_world import unified_generation
from intent_browser.site_discovery import validate_response


def records():
    return [{'site_id': sid, 'kind': kind, 'name': name, 'origin': f'http://localhost:{8000+i}',
             'families': ['footwear'], 'types': ['walking shoes'], 'description': 'Walking shoes and sandals.',
             'private_price': 100-i, 'winner': i == 1}
            for i, (sid, kind, name) in enumerate([
                ('z', 'retailer', 'Zephyr'), ('a', 'retailer', 'Aster'),
                ('c', 'aggregator', 'Compare'), ('r', 'product_reviews', 'Readers')])]


def test_public_pagination_all_kinds_scope_and_private_field_exclusion():
    source = records(); saved = deepcopy(source); directory = DiscoverSites(source)
    source[0]['name'] = 'Changed'
    first = directory.search('walking-shoes', limit=2)
    validate_response(first, {'kind': None, 'limit': 2, 'offset': 0})
    second = directory.search('walking_shoes', limit=2, offset=first['next_offset'])
    validate_response(second, {'kind': None, 'limit': 2, 'offset': 2})
    assert first['total'] == 4 and second['next_offset'] is None
    rows = first['sites'] + second['sites']
    assert len({row['site_id'] for row in rows}) == 4
    assert {row['kind'] for row in rows} == {'retailer', 'comparison', 'review'}
    assert all(set(row) == {'site_id','kind','name','url','description'} for row in rows)
    assert [row['name'] for row in directory.search(kind='retailer')['sites']] == ['Aster','Zephyr']
    assert directory.search('winner')['total'] == 0
    first['sites'][0]['name'] = 'Mutated response'
    assert directory.search('walking shoes', limit=2)['sites'][0]['name'] != 'Mutated response'
    assert directory.search('no match')['total'] == 0
    assert directory.search(offset=100)['sites'] == []
    assert saved[0]['name'] == 'Zephyr'


@pytest.mark.parametrize('arguments', [ {'query':None}, {'query':'x'*301}, {'kind':'aggregator'},
    {'kind':[]}, {'limit':True}, {'limit':0}, {'limit':21}, {'offset':True}, {'offset':-1} ])
def test_invalid_queries_reject(arguments):
    with pytest.raises(ValueError):DiscoverSites(records()).search(**arguments)


def test_inventory_scope_and_legacy_index_compatibility():
    catalogs = {'shop':{'siteName':'Shop','products':[]}}
    sites, docs = retailer_records(catalogs, {'shop':'http://localhost:8000'})
    assert sites[0]['description'] == 'No products are currently listed.'
    assert sites[0]['types'] == []
    assert Index(sites,docs).page('/',{})[0] == 200
    assert scope_description(['Tablets','Tablets','T-shirts']) == 'Sells T-shirts, Tablets.'
    assert 'No models' in scope_description([],kind='aggregator')
    assert 'No products' in scope_description([],kind='product_reviews')
    sites[0]['unexpected'] = 'must still reject'
    with pytest.raises(ValueError):Index(sites,docs)


def test_human_directory_lists_every_tool_record_including_later_pages():
    source = [dict(records()[0], site_id=f'site-{n}', name=f'Shop {n}',
                   origin=f'http://localhost:{8000+n}') for n in range(45)]
    source[0]['description'] = '<script>untrusted</script>'
    directory = DiscoverSites(source)
    html = directory_page(directory)
    assert html.count('<li>') == 45
    assert 'Search products and pages' in html and '<script>' not in html
    assert '&lt;script&gt;untrusted&lt;/script&gt;' in html
    for row in source:
        assert f'href="{row["origin"]}/"' in html
        assert f'>{row["name"]}</a>' in html


def test_tool_episode_compiles_and_binds_only_matching_runtime():
    request={'schema':unified_generation.VERSION,'seed':57,'task':{'kind':'cheapest_available'},
             'episode':{'start':{'kind':'tool_discovery'}}}
    before=deepcopy(request)
    config=unified_generation.compile_request(request)
    assert config['episode']==request['episode'] and request==before
    runtime=SimpleNamespace(discovery_mode='tool',research_origin='http://localhost:9000',
                            world={'world_id':'a'*64,'quote_as_of':'2026-10-06'})
    task=unified_generation.bind_task(runtime, {**config['episode'],
             'manual_task':{'user_message':'Find shoes','memories':[]}})
    assert task['start_url']=='http://localhost:9000/'
    runtime.discovery_mode='index'
    with pytest.raises(ValueError):unified_generation.bind_task(runtime, {**config['episode'],
             'manual_task':{'user_message':'Find shoes','memories':[]}})
    request['episode']['start']['retailer_id']='hidden'
    with pytest.raises(ValueError):unified_generation.compile_request(request)
