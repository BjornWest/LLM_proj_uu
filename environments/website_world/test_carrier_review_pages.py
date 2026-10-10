from copy import deepcopy
import json

import pytest

from environments.website_world.carrier_review_pages import CarrierReviewPages
from environments.website_world.carrier_review_runtime import CarrierDirectory
from environments.website_world.test_carrier_review_task import fixture


def view():return CarrierReviewPages(fixture()[3])


def test_public_profile_scope_dates_silent_ratings_and_html_escape():
    pages=view();config,rows=pages.scope('carrier-01',{'shipping_class':'regular'})
    assert len(rows)==6 and len([r for r in rows if r['text']])==5
    code,body,_=pages.page('/carriers/carrier-01',{'shipping_class':'regular'})
    assert code==200 and all('data-review-id="'+r['review_id']+'"' in body for r in rows)
    assert 'Rating only — no written comment' in body and '3.17' in body and '2026-08-01' in body
    assert 'r7' not in body and 'hidden_success' not in body and 'shipments' not in body
    assert pages.page('/api/publication',{})[1]==json.dumps(pages.publication,ensure_ascii=False)
    changed=deepcopy(pages.publication);changed['profiles'][0]['reviews'][0]['text']='<script>bad()</script>'
    body=CarrierReviewPages(changed).page('/carriers/carrier-01',{})[1]
    assert '&lt;script&gt;bad()&lt;/script&gt;' in body and '<script>bad()' not in body


def test_inclusive_dates_empty_mean_and_class_filter():
    pages=view();_,rows=pages.scope('carrier-01',{'shipping_class':'bulky','date_from':'2026-08-02','date_to':'2026-08-02'})
    assert [r['review_id'] for r in rows]==['r7']
    body=pages.page('/carriers/carrier-01',{'date_to':'1900-01-01'})[1]
    assert 'Undefined — no ratings' in body and 'data-review-id=' not in body
    assert 'Collection locations' not in body


def test_pagination_retains_every_rating_once():
    publication=fixture()[3];original=deepcopy(publication['profiles'][0]['reviews'][0])
    publication['profiles'][0]['reviews']=[{**original,'review_id':'rating-'+str(i),'reviewer_id':'person-'+str(i)} for i in range(26)]
    pages=CarrierReviewPages(publication);ids=[]
    for n,expected in [(1,12),(2,12),(3,2)]:
        body=pages.page('/carriers/carrier-01',{'page':str(n)})[1]
        import re
        batch=re.findall('data-review-id="([^"]+)"',body);assert len(batch)==expected;ids+=batch
    assert len(set(ids))==26 and set(ids)=={r['review_id'] for r in publication['profiles'][0]['reviews']}


@pytest.mark.parametrize('query',[{'shipping_class':'home'},{'page':'0'},{'page':'4'},{'date_to':'1900-01-01','date_from':'2026-09-01'},{'private_quality':'high'}])
def test_bad_filters_do_not_widen_or_silently_repair_scope(query):
    with pytest.raises(ValueError):view().page('/carriers/carrier-01',query)


def test_carrier_discovery_extension_is_private_and_uses_existing_review_kind():
    from environments.website_world.site_discovery import PUBLIC_KINDS,DiscoverSites
    row={'site_id':'carrier-reviews-01','kind':'carrier_reviews','name':'Parcelvoices','origin':'https://parcelvoices.test','description':'Delivery companies and customer opinions.'}
    before=deepcopy(PUBLIC_KINDS);d=CarrierDirectory([row]);result=d.search('delivery',kind='review')
    assert result['total']==1 and result['sites'][0]['kind']=='review' and PUBLIC_KINDS==before
    with pytest.raises(ValueError):DiscoverSites([row])
