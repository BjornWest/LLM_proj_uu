"""Ad publication boundaries: truthful destinations, visible labels, unchanged organic facts."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.request import urlopen
import pytest
from .advertising import Advertising
from .conformance import Document,review_check
from .runtime import Runtime
from environments.product_world.generator import digest

PIN=Path('.local/coordination/footwear-depth/pin-v1')
AD_PIN=Path('.local/coordination/shopping-ads/pin-v1')

@pytest.fixture(scope='module')
def inputs():
    return (json.loads((PIN/'scenario.private.json').read_text()),
            json.loads((PIN/'coverage.public.json').read_text()),
            json.loads((AD_PIN/'advertising.public.json').read_text()))

@pytest.fixture(scope='module')
def rt(inputs):
    scenario,coverage,ads=inputs
    with Runtime(scenario,comparison_coverage=coverage,advertising=ads,consent=False) as r:yield r


def test_binding_provenance_and_input_immutability(rt,inputs):
    scenario,coverage,ads=inputs
    assert rt.advertising.public==ads
    assert rt.provenance['advertising_sha256']==digest(ads)
    assert rt.world==scenario['bundle'] and rt.comparison_coverage==coverage
    assert rt.product_review_evidence==scenario['product_review_evidence']
    assert rt.merchant_reviews==scenario['merchant_reviews']
    for member in coverage['sites']:
        assert set(rt.comparison_designs[member['site_id']].by_id)==set(member['comparison_ids'])
    forbidden=('focus_families','contextual_probability','winner','resolved_task')
    assert not any(k in json.dumps(rt.advertising.public) for k in forbidden)


def test_all_ad_labels_prices_links_and_review_exclusion(rt,inputs):
    ads=inputs[2];count=0
    for s in ads['sites']:
        root=Document(urlopen(rt.origins[s['site_id']]).read().decode()).root
        actual=root.find(**{'class':'shopping-ad'})
        assert len(actual)==len(s['ads'])
        for ad in s['ads']:
            card=root.one('section',**{'data-ad-id':ad['ad_id']})
            assert card.attrs['aria-label'].startswith('Advertisement from ')
            assert card.one('p',**{'class':'ad-label'}).text()=='Advertisement'
            assert rt.stores[ad['retailer_id']]['name'] in card.text()
            assert card.one('p',**{'class':'ad-price'}).text()==f"Item price: {ad['price_minor']/100:.2f} SEK"
            target=card.one('a').attrs['href']
            assert target==rt.origins[ad['retailer_id']]+'/products/'+ad['product_id']
            assert urlopen(target).status==200
            count+=1
        if s['kind']=='aggregator':
            d=rt.comparison_designs[s['site_id']]
            for path in ('/search','/compare'):
                _,organic=d.render(path,{})
                served=urlopen(rt.origins[s['site_id']]+path).read().decode()
                # Every original tag/text survives as one contiguous main-content block.
                inner=organic.split('<main id="main">',1)[1].split('</main>',1)[0]
                assert inner in served
        elif s['ads']:
            row=next(r for r in rt.product_review_evidence['public']['reviews'] if rt.products[r['subject']['id']]['category'] in s['families'])
            rows=[r for r in rt.product_review_evidence['public']['reviews'] if r['article_id']==row['article_id']]
            page=Document(urlopen(rt.origins[s['site_id']]+'/reviews/'+row['article_id']).read().decode()).root
            review_check(page,rows)
            assert not page.one(id='reader-panel').find(**{'class':'shopping-ad'})
    assert count==18


@pytest.mark.parametrize('mutation',['world','site','kind','families','price','private'])
def test_invalid_ads_fail_before_publishing(inputs,mutation):
    scenario,coverage,ads=inputs;ads=deepcopy(ads)
    if mutation=='world':ads['source_world_sha256']='0'*64
    elif mutation=='site':ads['sites'][0]['site_id']='not-published'
    elif mutation=='kind':ads['sites'][0]['kind']='product_review'
    elif mutation=='families':ads['sites'][0]['families']=['wine']
    elif mutation=='price':ads['sites'][0]['ads'][0]['price_minor']+=1
    elif mutation=='private':ads['winner']='secret'
    with pytest.raises(ValueError):Runtime(scenario,comparison_coverage=coverage,advertising=ads,consent=False)


def test_absent_ads_leave_page_bytes_unchanged(inputs):
    scenario,coverage,ads=inputs;ads=deepcopy(ads)
    for site in ads['sites']:site['ads']=[]
    specs=[{k:s[k] for k in ('site_id','kind','families')} for s in ads['sites']]
    renderer=Advertising(scenario['bundle'],ads,specs,{})
    body='<html><head></head><body><main id="main"><p>Original</p></main></body></html>'
    assert renderer.decorate(ads['sites'][0]['site_id'],body)==body
    assert renderer.decorate('retailer',body)==body
