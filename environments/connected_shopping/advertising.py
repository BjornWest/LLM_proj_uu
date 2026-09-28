"""Render a validated frozen ad sidecar without changing organic catalogs/evidence."""
from copy import deepcopy
from decimal import Decimal
from html import escape
import re
from urllib.parse import quote
from environments.product_world.advertising import validate_advertising

STYLE='''<style id="shopping-advertising-style">
.shopping-ad{border:1px solid #b5bec5;background:#f4f6f7;padding:16px;margin:16px 0;color:#253744;box-sizing:border-box;overflow-wrap:anywhere}
.shopping-ad .ad-label{font-size:12px;text-transform:uppercase;letter-spacing:.08em;font-weight:bold}
.shopping-ad h2{font-size:19px;margin:8px 0}.shopping-ad a{display:inline-block;color:#164d75;text-decoration:underline}
.ad-layout{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:20px;max-width:1540px;margin:auto;padding:0 16px}.ad-layout>main{min-width:0;width:100%;box-sizing:border-box}.ad-sidebar{padding-top:20px;min-width:0}
@media(max-width:850px){.ad-layout{display:block}.ad-sidebar{padding-top:0}}
</style>'''


class Advertising:
    def __init__(self,world,data,specs,origins):
        validate_advertising(world,data)
        known={s['site_id']:s for s in specs}
        for s in data['sites']:
            expected=known.get(s['site_id'])
            if expected is None or s['kind']!=expected['kind'] or sorted(s['families'])!=sorted(expected['families']):
                raise ValueError('Advertising site differs from the published site contract: '+s['site_id'])
        self.public=deepcopy(data);self.by_site={s['site_id']:s['ads'] for s in self.public['sites']}
        self.stores={s['retailer_id']:s for s in world['public']['retailers']}
        self.origins=origins  # Filled with bound retailer origins before any ad page is served.

    def card(self,ad):
        e=escape;store=self.stores[ad['retailer_id']]['name']
        href=self.origins[ad['retailer_id']]+'/products/'+quote(ad['product_id'],safe='')
        return ('<section class="shopping-ad" data-ad-id="'+e(ad['ad_id'])+'" data-placement="'+e(ad['placement'])+'" aria-label="Advertisement from '+e(store)+'">'
          '<p class="ad-label">'+e(ad['label'])+'</p><p>Advertiser: '+e(store)+'</p><h2>'+e(ad['headline'])+'</h2>'
          '<p>'+e(ad['body'])+'</p><p class="ad-price">Item price: '+format(Decimal(ad['price_minor'])/100,'.2f')+' '+e(ad['currency'])+'</p>'
          '<p>Shipping and availability: check the retailer.</p><a rel="sponsored" href="'+e(href)+'">'+e(ad['cta'])+' at '+e(store)+'</a></section>')

    def decorate(self,site_id,body):
        ads=self.by_site.get(site_id,[])
        if not ads:return body
        main=re.search(r'<main\b[^>]*>',body)
        end=body.find('</main>',main.end() if main else 0)
        if main is None or end<0:raise ValueError('Advertisement page requires a main landmark')
        parts={a['placement']:self.card(a) for a in ads}
        inner=parts.get('banner','')+body[main.end():end]+parts.get('inline','')
        content=main.group()+inner+'</main>'
        if 'sidebar' in parts:
            content='<div class="ad-layout">'+content+'<aside class="ad-sidebar" aria-label="Advertisements">'+parts['sidebar']+'</aside></div>'
        return (body[:main.start()]+content+body[end+len('</main>'):]).replace('</head>',STYLE+'</head>',1)
