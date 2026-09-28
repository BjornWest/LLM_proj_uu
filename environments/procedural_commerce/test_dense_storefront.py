"""Public-data and routing invariants for the dense renderer."""
from copy import deepcopy
from html.parser import HTMLParser
from urllib.parse import urlsplit,unquote
import pytest
from .dense_preview import fixture,make_runtime
from .generator import retailer_view
from .retailer_designs import render_retailer
from .presentation import resolve_presentations


class Links(HTMLParser):
    def __init__(self,text):
        super().__init__();self.links=[];self.ids=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a':self.links.append(a.get('href',''))
        if 'id' in a:self.ids.append(a['id'])


def context(scale='large'):
    world,groups=fixture(scale)
    catalog=retailer_view(world,'nordhem');catalog['product_groups']=groups
    return {'catalog':catalog,'cart':None}


def render(ctx,path='/products/shoe-42-black',query=None):
    return render_retailer('nordhem',path,query or {},ctx,{'nordhem':'http://store.test'},'dense-storefront')


@pytest.mark.parametrize('scale',['small','large'])
@pytest.mark.parametrize('path',['/','/search','/products/shoe-42-black','/products/shoe-42-black/details'])
def test_links_resolve_only_to_listed_products_and_public_routes(scale,path):
    ctx=context(scale);before=deepcopy(ctx)
    # Simulate a sparse merchant assortment, without changing other world products.
    ctx['catalog']['offers']=ctx['catalog']['offers'][1:]
    html=render(ctx,path);parsed=Links(html)
    allowed={o['product_id'] for o in ctx['catalog']['offers']}
    for link in parsed.links:
        url=urlsplit(link)
        assert url.netloc in ('','store.test')
        if url.path.startswith('/products/'):
            assert unquote(url.path.split('/')[2]) in allowed
        if link.startswith('#'):assert link[1:] in parsed.ids
    assert len(parsed.ids)==len(set(parsed.ids))
    assert ctx['catalog']['products']==before['catalog']['products']


def test_unlisted_and_soldout_selections_do_not_keep_previous_price_or_buy_button():
    ctx=context()
    missing=render(ctx,query={'option_size_eu':'eu475','option_colour':'blue'})
    soldout=render(ctx,query={'option_size_eu':'eu42','option_colour':'blue'})
    for page in (missing,soldout):assert '>Add to cart<' not in page
    assert 'Choose an available combination' in missing
    assert 'This combination is not listed' in missing
    assert 'out of stock' in soldout


def test_escaping_private_context_and_generic_soldout():
    ctx=context();p=ctx['catalog']['products'][0];p['name']='<script>ATTACK</script>'
    ctx['private_provenance']='PRIVATE_SENTINEL'
    offer=next(o for o in ctx['catalog']['offers'] if o['product_id']==p['product_id']);offer['stock_quantity']=0
    page=render(ctx,'/products/'+p['product_id'])
    assert '<script>ATTACK' not in page and '&lt;script&gt;ATTACK' in page
    assert 'PRIVATE_SENTINEL' not in page and '>Add to cart<' not in page


@pytest.mark.parametrize('flow',['express','accordion','wizard'])
def test_all_checkout_shells_accept_new_design(flow):
    from urllib.request import urlopen
    with make_runtime('small',flow) as runtime:
        with urlopen(runtime.origins['nordhem']+'/cart') as response:page=response.read().decode()
        assert 'Shop by department' in page
        assert 'Shopping bag' in page
        assert page.count('<main ')==1
    assert resolve_presentations(7,['nordhem'],{'nordhem':'dense-storefront'})[0]['nordhem']=='dense-storefront'
