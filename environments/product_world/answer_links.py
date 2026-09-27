"""Resolve citations against trusted live offer bindings without fetching URLs.

Connected retailer links may be canonical SKU URLs or form-generated variant URLs.
Their option selections must resolve to the cited SKU, not merely the same model.
"""
from urllib.parse import parse_qsl,unquote,urlsplit

from environments.procedural_commerce.product_controls import resolve


def url_key(value):
    if not isinstance(value,str):raise ValueError('URL must be text')
    p=urlsplit(value)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
        raise ValueError('Expected HTTP URL without credentials')
    pairs=parse_qsl(p.query,keep_blank_values=True,strict_parsing=True,max_num_fields=30)
    if len(dict(pairs))!=len(pairs):raise ValueError('Duplicate URL parameter')
    host='localhost' if p.hostname in ('localhost','127.0.0.1') else p.hostname
    return (p.scheme,host,p.port or (443 if p.scheme=='https' else 80),unquote(p.path),tuple(sorted(pairs)))


class OfferLinks:
    def __init__(self,world,bindings):
        public=world['public'];self.offers={o['offer_id']:o for o in public['offers']}
        self.groups={v['product_id']:g for g in public['product_groups'] for v in g['variants']}
        self.by_pair={(o['retailer_id'],o['product_id']):o['offer_id'] for o in self.offers.values()}
        self.exact={};self.origins={}
        for oid,url in bindings.items():
            key=url_key(url)
            if key in self.exact:raise ValueError('Offer URL must identify one retailer/SKU')
            self.exact[key]=oid
            offer=self.offers[oid]
            if key[3]=='/products/'+offer['product_id'] and not key[4]:
                old=self.origins.setdefault(key[:3],offer['retailer_id'])
                if old!=offer['retailer_id']:raise ValueError('Retailer product origin is ambiguous')

    def resolve(self,value):
        """Return (offer ID, explicitly selected quantity), or no recognized link."""
        try:key=url_key(value)
        except (ValueError,TypeError):return None
        if key in self.exact:return self.exact[key],None
        retailer=self.origins.get(key[:3]);parts=key[3].strip('/').split('/')
        if not retailer or not key[3].startswith('/products/') or len(parts) not in (2,3) or parts[0]!='products' or (len(parts)==3 and parts[2]!='details'):
            return None
        group=self.groups.get(parts[1])
        if group is None:return None
        q=dict(key[4]);axes={'option_'+a['field'] for a in group['axes']}
        if set(q)-axes-{'quantity'}:return None
        quantity=None
        if 'quantity' in q:
            if not q['quantity'].isascii() or not q['quantity'].isdigit() or not 1<=int(q['quantity'])<=100:return None
            quantity=int(q['quantity'])
        selection={a['field']:q.get('option_'+a['field'],'') for a in group['axes']} if axes.intersection(q) else None
        try:sku=resolve(group,parts[1],selection)['product_id']
        except ValueError:return None
        oid=self.by_pair.get((retailer,sku))
        return (oid,quantity) if oid else None
