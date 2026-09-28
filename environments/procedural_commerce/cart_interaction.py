"""Independent post-add navigation and factual basket feedback."""
from html import escape
import hashlib

MODES=('redirect','inline','menu')
SHOWCASE={'nordhem':'inline','vardagslagret':'menu','teknikgarden':'inline'}


def resolve(seed, sites, supplied=None):
    if supplied=='sampled':
        return {site:('inline','menu')[hashlib.sha256(f'cart-navigation-v1/{seed}/{site}'.encode()).digest()[0]%2] for site in sites}
    supplied={} if supplied is None else dict(supplied)
    if set(supplied)-set(sites):raise ValueError('Unknown cart-navigation retailer')
    result={site:supplied.get(site,'redirect') for site in sites}
    if any(v not in MODES for v in result.values()):raise ValueError('Unknown cart navigation')
    return result


def cart_label(catalog,label='Cart'):
    count=catalog.get('cart_quantity')
    return escape(f'{label} ({count})' if type(count) is int else label)


def product_feedback(catalog,cart,error=None):
    text=f'<p role="alert">{escape(str(error))}</p>' if error else ''
    if not cart:return text
    offer=next((o for o in catalog.get('offers',[]) if o['offer_id']==cart['offer_id']),{})
    product=next((p for p in catalog.get('products',[]) if p['product_id']==offer.get('product_id')),{})
    text+=f'<p role="status">Your cart contains {escape(str(cart["quantity"]))} × {escape(str(product.get("name","item")))}.</p>'
    if catalog.get('cart_navigation')=='menu':
        text+='<p>Use the cart option in the store menu to review your basket.</p>'
    return '<section aria-label="Basket status">'+text+'</section>'


def purchase_actions(catalog, cart=None, error=None):
    link=''
    if cart and catalog.get('cart_navigation')=='inline':
        link='<a class="go-to-cart" href="/cart" style="display:inline-block;background:#237443;color:white;padding:.5rem .8rem;font:inherit;text-decoration:none;border-radius:3px">Go to cart</a>'
    actions='<div class="purchase-actions" style="display:flex;gap:.65rem;align-items:center;flex-wrap:wrap"><button type="submit">Add to cart</button>'+link+'</div>'
    if catalog.get('cart_navigation') in ('inline','menu'):
        actions+='<div style="flex-basis:100%">'+product_feedback(catalog,cart,error)+'</div>'
    return actions


def resolve_addition(seed, sites, supplied=None):
    if supplied=='sampled':
        return {site:('set','increment')[hashlib.sha256(f'cart-addition-v1/{seed}/{site}'.encode()).digest()[0]%2] for site in sites}
    supplied={} if supplied is None else dict(supplied)
    if set(supplied)-set(sites):raise ValueError('Unknown cart-addition retailer')
    result={site:supplied.get(site,'set') for site in sites}
    if any(v not in ('set','increment') for v in result.values()):raise ValueError('Unknown cart addition')
    return result
