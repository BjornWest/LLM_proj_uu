"""Cart architectures and optional store surround; independent of product designs.

All controls submit existing cart operations. This module only reads public
catalog facts and the caller's current basket, never recalculates a quote.
"""
from html import escape
from urllib.parse import quote, urlencode


def e(value):
    return escape(str(value), quote=True)


def surround(catalog, body, cart=None):
    """A browsable store around checkout, without depending on a storefront ID."""
    products=catalog.get('products',[])
    current=next((o.get('product_id') for o in catalog.get('offers',[]) if o.get('offer_id')==(cart or {}).get('offer_id')),None)
    categories=sorted({str(p['category']) for p in products if p.get('category')})
    navigation=''.join(f'<li><a href="/search?{e(urlencode({"category":c}))}">{e(c.replace("_"," ").title())}</a></li>' for c in categories)
    # A bounded sidebar avoids turning a large catalog into a giant checkout page.
    candidates=[p for p in products if p.get('product_id')!=current][:3]
    related=''.join(f'<article><h3><a href="/products/{quote(str(p["product_id"]),safe="")}">{e(p["name"])}</a></h3><p>{e(p.get("category",""))}</p></article>' for p in candidates)
    return f'''<div class="store-strip"><a href="/">Store home</a> · <a href="/search">All products</a> · <a href="/policy">Delivery and returns</a><p>Keep browsing while you prepare your order. Nothing is purchased until you confirm.</p></div>
<div class="store-surround"><nav aria-label="Shop departments"><h2>Shop by department</h2><ul>{navigation}</ul><p><a href="/cart">Your basket</a></p></nav>{body}<aside aria-label="More from this store"><h2>Explore the store</h2>{related}<p><a href="/search">Browse the full collection</a></p></aside></div>'''


STYLES='''
.store-strip{background:#e2e8f0;padding:1rem max(1rem,calc((100% - 1260px)/2))}.store-strip p{margin:.35rem 0 0}.store-surround{display:grid;grid-template-columns:190px minmax(0,1fr) 220px;gap:1rem;max-width:1300px;margin:auto;padding:1rem}.store-surround>nav,.store-surround>aside{padding:1rem;background:#e8eef0;align-self:start}.store-surround>main{width:100%;padding:0;margin:0;min-width:0}.store-surround nav a{margin:0}.store-surround li{margin:.7rem 0}.store-surround aside article{border-top:1px solid #b4c4ca;padding:.7rem 0}.store-surround h2{font-size:1.2rem}.store-surround h3{font-size:1rem}.basket-columns{display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:1rem}.basket-columns aside{align-self:start;background:#eef2f5;padding:1rem}.basket-table{border-collapse:collapse;width:100%}.basket-table th,.basket-table td{padding:.7rem;text-align:left;border-bottom:1px solid #cbd5e1}.cart-page input[type=number]{width:5rem;padding:.6rem}.cart-page select{padding:.6rem}.express-bag{max-width:680px}.express-bag article{border-bottom:1px solid #cbd5e1;padding-bottom:1rem}.cart-page .continue{display:inline-block;padding:.75rem;background:#155e75;color:white;border-radius:.3rem}.cart-page [role=alert]{padding:1rem;background:#fef2f2;color:#991b1b;border:2px solid #b91c1c}@media(max-width:950px){.store-surround{grid-template-columns:150px minmax(0,1fr)}.store-surround>aside{grid-column:1/-1}.basket-columns{grid-template-columns:1fr}}@media(max-width:650px){.store-surround{display:block}.store-surround>nav,.store-surround>aside{margin-bottom:1rem}.basket-table{font-size:.9rem}}
'''


def render_cart(flow, catalog, error=None):
    from .renderers import _offer_extra_control, _method_control, _destination_control
    cart=flow._cart()
    notice=f'<p role="alert">{e(error)}</p>' if error else ''
    title={'express':'Your shopping bag','accordion':'Your basket','wizard':'Review basket'}[flow.mode]
    if not cart:
        body=f'<main class="cart-page {flow.mode}"><h2>{title}</h2>{notice}<p>Your cart is empty.</p><a href="/search">Browse products</a></main>'
    else:
        offer=next(o for o in catalog['offers'] if o['offer_id']==cart['offer_id'])
        product=next(p for p in catalog['products'] if p['product_id']==offer['product_id'])
        link=f'<a href="/products/{quote(str(product["product_id"]),safe="")}">{e(product["name"])}</a>'
        quantity=f'<label for="basket-quantity">Quantity</label><input id="basket-quantity" type="number" name="quantity" min="1" value="{e(cart["quantity"])}" required>'
        options=_offer_extra_control(offer,checked=bool(cart.get('extra')))
        delivery=_destination_control(cart.get('destination','SE'))+_method_control(cart.get('method','standard'),radio=flow.mode=='accordion')
        remove='<form method="post" action="/cart/remove"><button class="secondary" type="submit">Remove item</button></form>'
        next_step='<a class="continue" href="/checkout">Continue to checkout</a>' if cart['quote'].get('eligible') else '<p role="alert">This selection is unavailable. Update or remove it before checkout.</p>'
        summary=flow._quote_summary(catalog,cart)
        one_line='<p>This demo basket supports one product line. Remove it before choosing a different product.</p>'
        if flow.mode=='accordion':
            body=f'''<main class="cart-page embedded-basket"><h2>{title}</h2>{notice}{one_line}<form action="/cart/update" method="post"><table class="basket-table"><caption>Items in your basket</caption><thead><tr><th>Product</th><th>Quantity</th><th>Options</th></tr></thead><tbody><tr><td>{link}<p>Offer: {e(cart['offer_id'])}</p></td><td>{quantity}</td><td>{options}</td></tr></tbody></table><details open><summary>Delivery estimate</summary>{delivery}</details><button type="submit">Update cart</button></form>{summary}<div class="actions">{remove}{next_step}</div></main>'''
        elif flow.mode=='wizard':
            body=f'''<main class="cart-page guided-basket"><nav aria-label="Order stages"><ol><li aria-current="step">Basket</li><li>Contact</li><li>Address</li><li>Delivery</li><li>Review</li></ol></nav><h2>{title}</h2>{notice}{one_line}<div class="basket-columns"><section aria-label="Basket item"><h3>{link}</h3><p>Offer: {e(cart['offer_id'])}</p><form action="/cart/update" method="post"><fieldset><legend>Item configuration</legend>{quantity}{options}</fieldset><fieldset><legend>Delivery estimate</legend>{delivery}</fieldset><button type="submit">Update cart</button></form>{remove}<p><a href="/search">Continue shopping</a></p></section><aside aria-label="Basket totals">{summary}{next_step}</aside></div></main>'''
        else:
            body=f'''<main class="cart-page express-bag"><h2>{title}</h2>{notice}{one_line}<article><h3>{link}</h3><p>Offer: {e(cart['offer_id'])}; quantity: {e(cart['quantity'])}</p><details><summary>Edit item, extras and delivery</summary><form action="/cart/update" method="post">{quantity}{options}{delivery}<button type="submit">Update cart</button></form></details>{remove}</article>{summary}<div class="actions">{next_step}<a href="/search">Keep shopping</a></div></main>'''
    return flow._document(catalog,title,body)
