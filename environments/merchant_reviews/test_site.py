from copy import deepcopy
from datetime import date
from html.parser import HTMLParser
from urllib.request import urlopen,Request
from urllib.error import HTTPError
import pytest
from environments.product_world.stores import generate_store_world
from environments.product_world.reviews import generate_reviews
from .data import ReviewCatalog,statistics
from .runtime import Runtime,query_for
from . import render


@pytest.fixture(scope='module')
def public():
    world=generate_store_world(seed=42,store_count=6,models_per_store=2)
    return generate_reviews(world,seed=11,reviews_per_store=25)['public']


class Structure(HTMLParser):
    def __init__(self,text):
        super().__init__();self.ids=[];self.links=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])
        if tag=='a':self.links.append(a.get('href'))


def test_corpus_statistics_preserved_when_filtered(public):
    db=ReviewCatalog(public);c=db.companies[0];before=deepcopy(c)
    rows=db.reviews(c['company_id'],{'stars':'1','topic':'delivery','sort':'oldest'})
    expected=[r for r in c['reviews'] if r['stars']==1 and r['topic']=='delivery']
    assert [r['review_id'] for r in rows]==[r['review_id'] for r in sorted(expected,key=lambda r:(r['published_date'],r['review_id']))]
    html=render.profile(db,c,{'stars':'1'})
    assert f'All reviews ({len(c["reviews"])})' in html and c==before
    assert c['statistics']==statistics(c['reviews'])


def test_keyword_date_and_sort(public):
    db=ReviewCatalog(public);c=db.companies[0]
    rows=db.reviews(c['company_id'],{'q':'order','period':'90','sort':'lowest'})
    for r in rows:
        assert 'order' in (r['title']+' '+r['body']).lower()
        assert (date.fromisoformat(db.as_of)-date.fromisoformat(r['published_date'])).days<=90
    assert [r['stars'] for r in rows]==sorted(r['stars'] for r in rows)
    assert db.search({'q':c['domain']})==[c]


def test_empty_reviews_and_early_date(public):
    p=deepcopy(public);p['as_of']='0002-02-01'
    for c in p['companies']:c['reviews']=[];c['statistics']=statistics([])
    db=ReviewCatalog(p);c=db.companies[0]
    assert db.reviews(c['company_id'],{})==[] and db.reviews(c['company_id'],{'period':'365'})==[]
    assert 'Not rated' in render.profile(db,c,{}) and 'No reviews match' in render.profile(db,c,{})


@pytest.mark.parametrize('mutation',['count','mean','histogram','stars','date','duplicate','private'])
def test_reject_inconsistent_or_private_payload(public,mutation):
    p=deepcopy(public);c=p['companies'][0]
    if mutation=='count':c['statistics']['review_count']+=1
    elif mutation=='mean':c['statistics']['mean_stars']=float('nan')
    elif mutation=='histogram':c['statistics']['star_counts']['1']+=1
    elif mutation=='stars':c['reviews'][0]['stars']=True
    elif mutation=='date':c['reviews'][0]['experience_date']='2099-01-01'
    elif mutation=='duplicate':c['reviews'][1]['review_id']=c['reviews'][0]['review_id']
    else:p['private_provenance']={'latent':'SECRET'}
    with pytest.raises(ValueError):ReviewCatalog(p)


def test_escaped_reviews_no_duplicate_dom_ids(public):
    p=deepcopy(public);p['companies'][0]['reviews'][0]['body']='<script>alert("bad")</script>'
    db=ReviewCatalog(p);page=render.profile(db,db.companies[0],{})
    assert '<script>' not in page
    detail=render.review_card(db.companies[0],db.companies[0]['reviews'][0]);assert '&lt;script&gt;' in detail
    ids=Structure(page).ids;assert len(ids)==len(set(ids))


@pytest.mark.parametrize('query',['page=0','page=-1','page=999999','stars=9','q=a&q=b','secret=1','sort=nonsense','topic=unknown','period=2'])
def test_bad_filters_rejected(query):
    with pytest.raises(ValueError):query_for('/review/store-001',query)


def test_http_routes_and_no_mutation_or_private_api(public):
    before=deepcopy(public)
    with Runtime(public) as rt:
        pages=['/','/categories','/search?q=nonexistent','/about']
        c=rt.catalog.companies[0];pages.extend([render.company_url(c),render.review_url(c['reviews'][0])])
        for path in pages:
            with urlopen(rt.origin+path) as response:assert response.status==200
        for path,expected in [('/api/state',404),('/review/unknown',404),('/search?page=0',400)]:
            with pytest.raises(HTTPError) as error:urlopen(rt.origin+path)
            assert error.value.code==expected
        with pytest.raises(HTTPError) as error:urlopen(Request(rt.origin+'/review/'+c['company_id'],data=b'stars=5'))
        assert error.value.code==405
    assert public==before


def test_website_bindings_are_explicit(public):
    c=public['companies'][0];db=ReviewCatalog(public)
    assert '>Visit website<' not in render.profile(db,db.companies[0],{})
    db=ReviewCatalog(public,{c['company_id']:'http://localhost:12345/'})
    assert 'href="http://localhost:12345/"' in render.profile(db,db.companies[0],{})
    with pytest.raises(ValueError):ReviewCatalog(public,{c['company_id']:'javascript:alert(1)'})


def test_identity_is_stable_separate_and_consistent_across_routes(public):
    from .identity import sample_identity, NAMES
    assert sample_identity(42)==sample_identity(42)
    assert {sample_identity(i)['name'] for i in range(200)}==set(NAMES)
    before=deepcopy(public)
    # Two simultaneous worlds must not mutate a module-global brand.
    with Runtime(public,site_name='Kundkompassen') as a, Runtime(public,site_name='Butikspanelen') as b:
        c=public['companies'][0]
        paths=['/','/search','/categories','/about',render.company_url(c),render.review_url(c['reviews'][0])]
        for rt,name,other in [(a,'Kundkompassen','Butikspanelen'),(b,'Butikspanelen','Kundkompassen')]:
            for path in paths:
                page=urlopen(rt.origin+path).read().decode()
                assert f'| {name}</title>' in page and f'href="/">{name}</a>' in page
                assert other not in page and 'Omdömeskollen' not in page
            with pytest.raises(HTTPError) as error:urlopen(rt.origin+'/missing')
            assert name in error.value.read().decode()
    assert public==before
