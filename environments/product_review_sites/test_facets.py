from copy import deepcopy
from urllib.parse import urlencode
import pytest
from environments.product_world.generator import generate_catalog
from .generate import generate_reviews,FAMILIES
from .data import Catalog
from .facets import token,matches,describe
from .runtime import query,Runtime
from .presentation import vocabulary,common_vocabulary,FAMILY_PROFILES
from . import render


@pytest.fixture(scope='module')
def db():
    world=generate_catalog(seed=42,model_count=36,model_families=list(FAMILIES)*6)
    return Catalog(generate_reviews(world,seed=42)['public'])


def test_multiselect_or_and_other_facets(db):
    colours=db.facets()['wine_colour']['values'][:2]
    q={'family':'wine','f.wine_colour':[token(v) for v in colours],'max.alcohol_abv':'13'}
    actual=db.find(q)
    expected=[a for a in db.articles if a['family']=='wine' and db.variants[a['reviewed_sku']]['facts']['wine_colour'] in colours and db.variants[a['reviewed_sku']]['facts']['alcohol_abv']<=13]
    assert {a['id'] for a in actual}=={a['id'] for a in expected}
    # Repeated choice fields survive HTTP decoding and pagination URLs.
    parsed=query('/catalog',urlencode(q,doseq=True));assert parsed==q
    link=render.u('/catalog',{**q,'page':'2'})
    assert query('/catalog',link.split('?',1)[1])=={**q,'page':'2'}


def test_include_and_exclude_ingredients_no_absence_from_missing(db):
    q={'family':'cat_food','f.ingredients':[token('chicken'),token('salmon')],'x.ingredients':[token('wheat')]}
    expected=[]
    for a in db.articles:
        v=db.variants[a['reviewed_sku']];ingredients=v['facts'].get('ingredients',[])
        if a['family']=='cat_food' and set(ingredients)&{'chicken','salmon'} and 'wheat' not in ingredients:expected.append(a)
    assert {a['id'] for a in db.find(q)}=={a['id'] for a in expected}
    assert not matches({},[('x','ingredients',{token('wheat')})])
    assert matches({'ingredients':[]},[('x','ingredients',{token('wheat')})])


@pytest.mark.parametrize('q',[
    {'f.nonexistent':['"x"']},{'f.wine_colour':['"purple"']},
    {'f.wine_colour':['"red"','"red"']},{'min.alcohol_abv':'NaN'},
    {'min.alcohol_abv':'Infinity'},{'min.alcohol_abv':'15','max.alcohol_abv':'8'},
    {'min.size_eu':'40'},{'f.alcohol_abv':['13']},{'x.wine_colour':['"red"']},
])
def test_invalid_filters_fail_explicitly(db,q):
    with pytest.raises(ValueError):db.find(q)


def test_range_not_size_inequality_and_displayed_choices(db):
    facets=db.facets()
    assert facets['size_eu']['kind']=='choice'
    assert facets['alcohol_abv']['kind']=='range' and facets['ram_gb']['kind']=='range'
    assert facets['waterproof']['kind']=='boolean'
    assert facets['ingredients']['exclude']
    with Runtime(db.public,families=['wine']) as site:
        page=render.listing(site,{})
        assert 'Exact value' not in page and 'e.g. wide' not in page
        assert 'type="checkbox" name="f.wine_colour"' in page
        assert 'name="max.alcohol_abv"' in page
        assert 'configuration' not in page.casefold()


@pytest.mark.parametrize('family',FAMILIES)
def test_vocabulary_across_all_layouts_and_families(db,family):
    words=vocabulary(family)
    for layout in ('lab-directory','editorial-magazine','community-feed'):
        with Runtime(db.public,families=[family],layout=layout) as site:
            a=site.db.articles[0]
            pages=[render.home(site),render.listing(site,{}),render.review(site,a,{}),render.review(site,a,{'part':'specifications'}),render.comparison(site,{})]
            assert words.covered in pages[2]
            if family!='laptops':assert all('configuration' not in page.casefold() for page in pages)
    assert vocabulary('dog_food')==vocabulary('cat_food')


def test_vocabulary_extension_groups():
    from environments.shopping_intent.catalog import FAMILIES as registry
    assert set(registry)<=set(FAMILY_PROFILES)
    assert vocabulary('phones')==vocabulary('laptops')
    assert vocabulary('trousers').item=='size and style'
    assert vocabulary('moisturizers').item=='formula and size'
    assert vocabulary('books').item=='edition'
    assert vocabulary('printer_ink').item=='compatible version'
    assert vocabulary('future_new_family').item=='version'
    assert common_vocabulary(['cat_food','dog_food'])==vocabulary('cat_food')
    assert common_vocabulary(['wine','laptops']).item=='version'
