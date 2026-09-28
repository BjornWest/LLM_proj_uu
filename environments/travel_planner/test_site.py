import copy
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import urlopen
from urllib.parse import urlencode
import pytest

from environments.product_world.scenario import generate_scenario
from environments.product_world.travel import export_travel_planner
from .data import Catalog
from .runtime import Runtime, home, journey


@pytest.fixture(scope='module')
def scenario():
    return generate_scenario({'seed':2,'family':'footwear','destination_city':'uppsala'},
        {'seed':42,'models_per_store':2},{})


@pytest.fixture(scope='module')
def export(scenario):return export_travel_planner(scenario['bundle'],scenario['locations'])


def test_complete_deterministic_public_export_and_route_agreement(scenario,export):
    assert export==export_travel_planner(scenario['bundle'],scenario['locations'])
    c=Catalog(export['public']);loc=scenario['locations']['public']
    assert len(c.places)==1+sum(len(m['branches']) for m in loc['merchants'])
    assert len(c.trips)==3*len(c.places)**2
    for r in loc['routes'].values():
        if r['mode']=='freight':continue
        t=c.trip(r['origin_id'],r['destination_id'],r['mode'])
        assert (t['status'],t['duration_minutes'],t['distance_km'])==(r['status'],r['duration_minutes'],r['distance_km'])
    text=json.dumps(export['public'])
    for forbidden in ('memory_facts','explicit_requirements','stock_quantity','fulfilment_policy','warehouse','private_provenance'):
        assert forbidden not in text


def test_search_resolution_does_not_guess_ambiguous_or_unknown_places(export):
    c=Catalog(export['public'])
    assert c.resolve('  MY HOME  ')[0]['place_id']=='user-home'
    assert len(c.resolve('Uppsala'))>1
    assert c.resolve('Nonexistent Road 887, Atlantis')==[]
    place=next(p for p in c.places.values() if p['kind']=='branch')
    assert c.resolve(place['place_id'])==[place]
    assert c.resolve(place['label'])==[place]
    assert all(p['kind']=='branch' for p in c.search('',kind='branch'))


def test_all_origin_destination_modes_branch_to_branch_and_self(export):
    c=Catalog(export['public'])
    for p in c.places:
        assert c.trip(p,p,'driving')['duration_minutes']==0
    a,b=[p for p in c.places if p!='user-home'][:2]
    assert c.trip(a,b,'driving')['status']=='estimated'
    with pytest.raises(ValueError):c.trip('unknown',b,'driving')
    with pytest.raises(ValueError):c.trip(a,b,'bus')


def test_unknown_routes_are_not_zero_minutes(export):
    c=Catalog(export['public'])
    unknown=[t for t in c.trips.values() if t['status']=='not_modelled']
    assert unknown and all(t['distance_km'] is None and t['duration_minutes'] is None for t in unknown)
    t=unknown[0]
    text=journey(c,'/w/example',{'from':t['origin_id'],'to':t['destination_id'],'mode':t['mode']})
    assert 'Walking estimate unavailable' in text


def test_sorted_search_matches_public_trip_matrix(export):
    c=Catalog(export['public'])
    result=home(c,'/w/example',{'origin':'Home','sort':'duration','mode':'driving'})
    expected=sorted(c.search('',kind='branch'),key=lambda p:(c.trip('user-home',p['place_id'],'driving')['duration_minutes'] is None,c.trip('user-home',p['place_id'],'driving')['duration_minutes'] or 0,p['place_id']))[:12]
    positions=[result.index('data-place="'+p['place_id']+'"') for p in expected]
    assert positions==sorted(positions)
    assert 'Next' in result


def test_html_escapes_queries_and_requires_confirmation(export):
    c=Catalog(export['public'])
    html=journey(c,'/w/example',{'from':'Home','to':'<script>alert(1)</script>'})
    assert '<script>' not in html and 'Location not found' in html
    html=journey(c,'/w/example',{'from':'Home','to':'Uppsala'})
    assert 'Choose your places' in html and 'Confirm places' in html


@pytest.mark.parametrize('damage',['missing-trip','duplicate-place','negative-time','unknown-numeric'])
def test_invalid_export_rejected(export,damage):
    public=copy.deepcopy(export['public'])
    if damage=='missing-trip':public['trips'].pop()
    if damage=='duplicate-place':public['places'].append(public['places'][0])
    if damage=='negative-time':public['trips'][0]['duration_minutes']=-1
    if damage=='unknown-numeric':
        t=next(t for t in public['trips'] if t['status']=='not_modelled');t['duration_minutes']=0
    with pytest.raises(ValueError):Catalog(public)


def test_public_http_and_authoring_isolation(export):
    with Runtime() as server:
        url=server.register(export)
        def read(path):
            with urlopen(url+path) as r:return r.status,r.read().decode()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(read,['','/api/places?q=home','/api/journey?from=Home&to=Home&mode=walking','/journey?from=Home&to=Home']))
        assert all(status==200 for status,_ in results)
        assert json.loads(results[2][1])['duration_minutes']==0
        for path in ('/api/scenario','/api/defaults','/api/location-quotes'):
            with pytest.raises(HTTPError) as e:urlopen(server.origin+path)
            assert e.value.code==404
        with pytest.raises(HTTPError) as e:urlopen(url+'/api/journey?from=Home&to=nowhere')
        assert e.value.code==400
