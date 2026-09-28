from copy import deepcopy
from html.parser import HTMLParser
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from urllib.parse import urlencode
import pytest
from environments.product_world.generator import generate_catalog
from .generate import generate_reviews,FAMILIES,stats
from .data import Catalog,LAYOUTS
from .runtime import Runtime
from . import render


@pytest.fixture(scope='module')
def world():
    return generate_catalog(seed=42,model_count=18,model_families=list(FAMILIES)*3)


@pytest.fixture(scope='module')
def bundle(world):return generate_reviews(world,seed=11)


class Structure(HTMLParser):
    def __init__(self,html):super().__init__();self.ids=[];self.links=[];self.feed(html)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])
        if tag=='a':self.links.append(a.get('href',''))


def test_generation_canonical_facts_and_independent_names(world,bundle):
    before=deepcopy(world);assert generate_reviews(world,seed=11)==bundle
    source={p['product_id']:p for p in world['public']['products']}
    db=Catalog(bundle['public'])
    assert set(a['family'] for a in db.articles)==set(FAMILIES)
    for sku,v in db.variants.items():assert v['facts']==source[sku]['attributes']
    assert 'reference_price_minor' not in str(bundle['public']) and 'private_provenance' not in str(bundle['public'])
    longer=generate_reviews(world,seed=11,opinions_per_review=40)
    for a,b in zip(bundle['public']['articles'],longer['public']['articles']):
        assert a['reviewed_sku']==b['reviewed_sku'] and a['reader_opinions']==b['reader_opinions'][:24]
        assert a['reader_statistics']==stats(a['reader_opinions'])
    assert world==before


def test_reordering_does_not_change_export(world,bundle):
    w=deepcopy(world);w['public']['products'].reverse();w['public']['product_groups'].reverse()
    for g in w['public']['product_groups']:g['variants'].reverse()
    assert generate_reviews(w,seed=11)['public']==bundle['public']


@pytest.mark.parametrize('mutation',['wrong_sku','count','float_count','mean','histogram','rating_bool','date','duplicate','private','nan','orphan'])
def test_bad_export_rejected(bundle,mutation):
    p=deepcopy(bundle['public']);a=p['articles'][0]
    if mutation=='wrong_sku':a['reviewed_sku']=p['articles'][1]['reviewed_sku']
    elif mutation=='count':a['reader_statistics']['count']+=1
    elif mutation=='float_count':a['reader_statistics']['count']=24.0
    elif mutation=='mean':a['reader_statistics']['mean']=5
    elif mutation=='histogram':a['reader_statistics']['histogram']['1']+=1
    elif mutation=='rating_bool':a['reader_opinions'][0]['stars']=True
    elif mutation=='date':a['reader_opinions'][0]['date']='2999-01-01'
    elif mutation=='duplicate':p['variants'].append(p['variants'][0])
    elif mutation=='private':p['private_provenance']={'answer':'SECRET'}
    elif mutation=='nan':p['variants'][0]['facts']['weight_kg']=float('nan')
    elif mutation=='orphan':p['variants'][0]['model_id']='not-a-model'
    with pytest.raises(ValueError):Catalog(p)


def test_empty_opinions_and_exact_sku_filter(world):
    public=generate_reviews(world,opinions_per_review=0,as_of='0001-01-01')['public'];db=Catalog(public)
    for a in db.articles:assert a['reader_statistics']=={'count':0,'mean':None,'histogram':{str(i):0 for i in range(1,6)}}
    a=db.articles[0];assert db.find({'q':a['reviewed_sku']})==[a]
    with Runtime(public,families=[a['family']],layout='community-feed') as rt:
        html=urlopen(rt.origin+render.review_url(a)).read().decode();assert 'Not rated' in html and 'No reader notes match.' in html


@pytest.mark.parametrize('layout',LAYOUTS)
def test_all_families_routes_links_and_no_private_api(bundle,layout):
    with Runtime(bundle['public'],layout=layout,name='Test Publication') as rt:
        paths=['/','/catalog','/methodology','/compare']
        for family in FAMILIES:
            a=next(a for a in rt.db.articles if a['family']==family)
            paths += [render.review_url(a)+suffix for suffix in ('','?part=specifications','?part=readers')]
            paths += [render.variant_url(rt.db.variants[a['reviewed_sku']]),render.review_url(a)+'/opinions/'+a['reader_opinions'][0]['id']]
        seen=set()
        for path in paths:
            html=urlopen(rt.origin+path).read().decode();structure=Structure(html)
            assert len(structure.ids)==len(set(structure.ids)),path
            assert 'Test Publication' in html and 'reference_price_minor' not in html
            for link in structure.links:
                if link.startswith('#'):
                    assert link[1:] in structure.ids
                elif link.startswith('/') and link not in seen:
                    assert urlopen(rt.origin+link).status==200,(path,link);seen.add(link)
        for path,status in [('/api/state',404),('/private_provenance',404),('/catalog?page=0',400),('/catalog?q=a&q=b',400),('/catalog?secret=1',400),('/compare?left=unknown',400),('/reviews/missing',404)]:
            with pytest.raises(HTTPError) as err:urlopen(rt.origin+path)
            assert err.value.code==status
        with pytest.raises(HTTPError) as err:urlopen(Request(rt.origin+'/',data=b'x'))
        assert err.value.code==405


def test_filter_comparison_and_other_configuration_scope(bundle):
    with Runtime(bundle['public'],families=['footwear']) as rt:
        a=rt.db.articles[0];v=rt.db.variants[a['reviewed_sku']]
        rows=rt.db.find({'family':'footwear','field':'width','value':v['facts']['width']})
        assert rows and all(rt.db.variants[x['reviewed_sku']]['facts']['width']==v['facts']['width'] for x in rows)
        assert not rt.db.find({'q':'no-such-model-xyz'})
        other=next(v for v in rt.db.variants.values() if v['model_id']==a['id'] and v['sku']!=a['reviewed_sku'])
        assert 'catalog facts only' in urlopen(rt.origin+render.variant_url(other)).read().decode()
        peer=rt.db.articles[1]
        html=urlopen(rt.origin+'/compare?'+urlencode({'left':a['id'],'right':peer['id']})).read().decode()
        assert a['reviewed_sku'] in html and peer['reviewed_sku'] in html
        excluded=next(a for a in bundle['public']['articles'] if a['family']=='beer')
        with pytest.raises(HTTPError) as err:urlopen(rt.origin+render.review_url(excluded))
        assert err.value.code==404


def test_escape_content_and_binding_scope(bundle):
    p=deepcopy(bundle['public']);a=p['articles'][0];a['model_name']='<script>bad()</script>'
    a['reader_opinions'][0]['body']='<img src=x onerror=bad()>'
    with Runtime(p,name='A < B',bindings={a['reviewed_sku']:'http://localhost:9876/exact-sku'}) as rt:
        html=render.review(rt,rt.db.by_id[a['id']],{})
        assert '<script>' not in html and '<img src=x' not in html and '&lt;script&gt;' in html
        assert 'href="http://localhost:9876/exact-sku"' in html
    for binding in ({'missing':'https://retailer.test/'},{a['reviewed_sku']:'javascript:alert(1)'},{a['reviewed_sku']:'https://user:secret@retailer.test/'}):
        with pytest.raises(ValueError):Catalog(p,bindings=binding)


def test_layout_changes_do_not_change_facts(bundle):
    a=bundle['public']['articles'][0];seen=[]
    for layout in LAYOUTS:
        with Runtime(bundle['public'],layout=layout,seed=3,page_size=4,related_count=1) as rt:
            seen.append((deepcopy(rt.db.by_id[a['id']]),deepcopy(rt.db.variants[a['reviewed_sku']])))
    assert seen[0]==seen[1]==seen[2]


def test_existing_store_world_contract_and_foreign_family_comparison():
    from environments.product_world.stores import generate_store_world
    world=generate_store_world(seed=42,store_count=6,models_per_store=2)
    export=generate_reviews(world,seed=7);db=Catalog(export['public'])
    assert {v['sku'] for v in db.variants.values()}=={p['product_id'] for p in world['public']['products']}
    with Runtime(export['public']) as rt:
        a=rt.db.articles[0];b=next(x for x in rt.db.articles if x['family']!=a['family'])
        with pytest.raises(HTTPError) as err:urlopen(rt.origin+'/compare?'+urlencode({'left':a['id'],'right':b['id']}))
        assert err.value.code==400
