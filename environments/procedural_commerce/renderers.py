"""Pure HTML renderers for the procedural commerce MVP.

The renderer consumes only the public catalog projections and server supplied
cart, quote, and receipt values.  It deliberately contains no pricing,
shipping, stock, or checkout logic.
"""

from __future__ import annotations

from html import escape
from .cart_interaction import cart_label, product_feedback, purchase_actions
import re
from math import ceil
from typing import Any, Iterable
from urllib.parse import quote as url_quote
from urllib.parse import urlencode, urlsplit


RETAILERS = {"nordhem", "vardagslagret", "teknikgarden"}
PAGE_SIZE = 12


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value)


def _esc(value: Any, fallback: str = "") -> str:
    return escape(_text(value, fallback), quote=True)


def _minor(value: Any) -> str:
    """Format an integer ore value without calculating any totals."""

    try:
        amount = int(value)
    except (TypeError, ValueError):
        return "Not available"
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    return f"{sign}{amount // 100}.{amount % 100:02d} SEK"


def _bool(value: Any) -> bool:
    return value is True or value == "true" or value == 1


def _origin(origins: dict[str, str], site: str) -> str:
    value = origins.get(site, "") if isinstance(origins, dict) else ""
    return _text(value).rstrip("/")


def _form_action(origins: dict[str, str], site: str, path: str) -> str:
    # Preserve an optional mounted path, but never switch a form's host alias.
    prefix = urlsplit(_origin(origins, site)).path.rstrip("/")
    return escape(prefix + path, quote=True)


def _href(origins: dict[str, str], site: str, path: str, params: dict[str, Any] | None = None) -> str:
    base = _origin(origins, site)
    if not path.startswith("/"):
        path = "/" + path
    result = base + path
    if params:
        clean = [(str(key), _text(value)) for key, value in params.items() if value is not None]
        if clean:
            result += "?" + urlencode(clean)
    return escape(result, quote=True)


def _path_product(product_id: Any) -> str:
    return "/products/" + url_quote(_text(product_id), safe="")


def _path_receipt(order_id: Any) -> str:
    return "/receipt/" + url_quote(_text(order_id), safe="")


def _attrs(product: dict[str, Any]) -> list[tuple[str, str]]:
    attrs = product.get("attributes")
    if not isinstance(attrs, dict):
        return []
    return [(str(key), _text(value)) for key, value in attrs.items() if value is not None and value != ""]


def _traits(product: dict[str, Any]) -> list[str]:
    traits = product.get("traits")
    if isinstance(traits, (list, tuple)):
        return [_text(item) for item in traits if item is not None and _text(item)]
    return []


def _label(value: Any) -> str:
    return _text(value).replace("_", " ").replace("-", " ").capitalize()


def _specs(product: dict[str, Any], expanded: bool = True) -> str:
    attrs = _attrs(product)
    traits = _traits(product)
    if not expanded:
        return "" if not attrs and not traits else (
            '<p class="result-spec-summary">'
            + _esc(", ".join(f"{_label(key)}: {value}" for key, value in attrs))
            + ("; " if attrs and traits else "")
            + _esc(", ".join(traits))
            + "</p>"
        )
    if not attrs and not traits:
        return '<p class="not-specified">Product details are not specified.</p>'
    rows = [f"<dt>{_esc(_label(key))}</dt><dd>{_esc(value)}</dd>" for key, value in attrs]
    if traits:
        rows.append(f"<dt>Traits</dt><dd>{_esc(', '.join(traits))}</dd>")
    return '<dl class="specifications">' + "".join(rows) + "</dl>"


def _product_map(products: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_text(item.get("product_id")): item for item in products if isinstance(item, dict)}


def _offer_map(offers: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_text(item.get("offer_id")): item for item in offers if isinstance(item, dict)}


def _search_products(products: list[dict[str, Any]], query: dict[str, str]) -> list[dict[str, Any]]:
    needle = _text(query.get("q")).strip().casefold()
    terms = re.findall(r"\w+", needle)
    category = _text(query.get("category")).strip().casefold()
    found: list[dict[str, Any]] = []
    for product in products:
        if category and _text(product.get("category")).casefold() != category:
            continue
        haystack = " ".join(
            [_text(product.get("product_id")), _text(product.get("name")), _text(product.get("category"))]
            + [_text(value) for pair in _attrs(product) for value in pair]
            + _traits(product)
        ).casefold()
        if terms and not all(term in haystack for term in terms):
            continue
        found.append(product)
    return found


def _page(query: dict[str, str]) -> int:
    try:
        return max(1, int(_text(query.get("page", "1"))))
    except (TypeError, ValueError):
        return 1


def _pagination(
    origins: dict[str, str], site: str, query: dict[str, str], count: int, page_size: int = PAGE_SIZE
) -> str:
    pages = max(1, ceil(count / page_size))
    current = min(_page(query), pages)
    if pages == 1:
        return f'<p class="pagination-status">Showing {count} result(s).</p>'
    params = {key: query.get(key) for key in ("q", "category") if query.get(key)}
    links: list[str] = []
    if current > 1:
        links.append(f'<a rel="prev" href="{_href(origins, site, "/search", {**params, "page": current - 1})}">Previous</a>')
    links.append(f'<span aria-current="page">Page {current} of {pages}</span>')
    if current < pages:
        links.append(f'<a rel="next" href="{_href(origins, site, "/search", {**params, "page": current + 1})}">Next</a>')
    return '<nav class="pagination" aria-label="Search results pages">' + " ".join(links) + f' <span>({count} results)</span></nav>'


def _style() -> str:
    return """<style>
:root{font-family:system-ui,sans-serif;color:#17212b;background:#f5f6f8}body{margin:0;line-height:1.45}a{color:#075985}header,main,footer{max-width:1120px;margin:auto;padding:1rem}header{display:flex;gap:1rem;align-items:baseline;flex-wrap:wrap;background:#fff}header nav{display:flex;gap:.75rem;flex-wrap:wrap}main{background:#fff;min-height:65vh}.site-kicker{color:#536273;font-size:.9rem}.search-form,.purchase-form,.quote-form,.cart-actions,.review-actions{padding:1rem;background:#eef3f7;border:1px solid #cad6df;margin:1rem 0}.search-form{display:flex;gap:.5rem;flex-wrap:wrap}.search-form label,.purchase-form label,.quote-form label{display:flex;flex-direction:column;gap:.2rem}.search-form input,.search-form select,.purchase-form input,.purchase-form select,.quote-form input,.quote-form select{padding:.45rem;border:1px solid #8b9aa8;border-radius:3px}button{padding:.5rem .8rem;cursor:pointer;border:1px solid #315d78;background:#0b4f71;color:#fff;border-radius:3px}.button-secondary{background:#fff;color:#0b4f71}.result-list{display:grid;gap:.8rem}.result-card,.product-hero,.offer-card,.cart-line,.quote-breakdown,.receipt-card{border:1px solid #cfd8df;padding:1rem;background:#fff}.result-card h3,.offer-card h3{margin-top:0}.result-card header{padding:0;background:none}.result-card .card-actions{display:flex;gap:.8rem;flex-wrap:wrap}.specifications{display:grid;grid-template-columns:minmax(7rem,13rem) 1fr;margin:.5rem 0}.specifications dt,.specifications dd{padding:.25rem;margin:0;border-bottom:1px solid #e4e8eb}.specifications dt{font-weight:600}.offer-table{width:100%;border-collapse:collapse}.offer-table th,.offer-table td{padding:.55rem;text-align:left;border-bottom:1px solid #d8e0e6;vertical-align:top}.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:.75rem}.notice{padding:.75rem;border-left:4px solid #b7791f;background:#fff8e1}.error{padding:.75rem;border-left:4px solid #a32929;background:#fff0f0}.success{padding:.75rem;border-left:4px solid #26734d;background:#edf9f2}.site-footer{color:#536273;font-size:.9rem}.category-links{display:flex;gap:.5rem;flex-wrap:wrap}.category-links a{padding:.3rem .55rem;background:#eef3f7}.cart-total{font-size:1.15rem;font-weight:700}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}@media(max-width:650px){.specifications{grid-template-columns:1fr}.offer-table{font-size:.9rem;display:block;overflow:auto}}
</style>"""


def _layout_variant(context: dict[str, Any]) -> str:
    return "expanded" if _text(context.get("layout_variant")).lower() == "expanded" else "compact"


def _header(
    site: str, origins: dict[str, str], catalog: dict[str, Any], title: str, tagline: str
) -> str:
    if site == "aggregator":
        brand = "Prislyktan"
        nav = (
            f'<a href="{_href(origins, site, "/")}">Directory home</a>'
            f'<a href="{_href(origins, site, "/search")}">Search products</a>'
        )
    else:
        retailer = catalog.get("retailer") if isinstance(catalog.get("retailer"), dict) else {}
        brand = _text(retailer.get("name"), site.title())
        nav = (
            f'<a href="{_href(origins, site, "/")}">Home</a>'
            f'<a href="{_href(origins, site, "/search")}">Catalog</a>'
            f'<a href="{_href(origins, site, "/policy")}">Delivery &amp; policy</a>'
            f'<a href="{_href(origins, site, "/cart")}">{cart_label(catalog, "Cart")}</a>'
        )
    return (
        "<header>"
        f'<div><p class="site-kicker">{_esc(tagline)}</p><h1>{_esc(brand)}</h1></div>'
        f'<nav aria-label="Primary navigation">{nav}</nav>'
        f'<span class="sr-only">{_esc(title)}</span>'
        "</header>"
    )


def _footer(catalog: dict[str, Any]) -> str:
    currency = _text(catalog.get("currency"), "SEK")
    date = _text(catalog.get("scenario_date"))
    return f'<footer class="site-footer">Prices shown in {_esc(currency)}. Scenario date: {_esc(date)}.</footer>'


def _document(
    site: str, origins: dict[str, str], catalog: dict[str, Any], title: str, body: str, tagline: str
) -> str:
    classes = {"aggregator": "directory-site", "nordhem": "nordhem-site", "vardagslagret": "vardagslagret-site", "teknikgarden": "teknikgarden-site"}
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + f'<title>{_esc(title)}</title>{_style()}</head><body class="{classes.get(site, "commerce-site")}">' + _header(site, origins, catalog, title, tagline) + body + _footer(catalog) + "</body></html>"


def _not_found(site: str, origins: dict[str, str], catalog: dict[str, Any], message: str = "Page not found") -> str:
    body = f'<main class="not-found"><h2>{_esc(message)}</h2><p>The requested page is not available.</p><p><a href="{_href(origins, site, "/")}">Return home</a></p></main>'
    return _document(site, origins, catalog, message, body, "Commerce")


def _search_form(site: str, origins: dict[str, str], products: list[dict[str, Any]], query: dict[str, str], *, specialist: bool = False) -> str:
    categories = sorted({_text(product.get("category")) for product in products if product.get("category")})
    selected = _text(query.get("category"))
    category_control = '<label>Category<select name="category"><option value="">All categories</option>' + "".join(
        f'<option value="{_esc(category)}"{" selected" if category == selected else ""}>{_esc(_label(category))}</option>' for category in categories
    ) + "</select></label>"
    label = "Find a product" if not specialist else "Filter specifications"
    return (
        f'<form class="search-form" method="get" action="{_form_action(origins, site, "/search")}">'
        f'<label>{_esc(label)}<input type="search" name="q" value="{_esc(query.get("q"))}" placeholder="Name, category or attribute"></label>'
        + category_control
        + '<button type="submit">Search catalog</button></form>'
    )


def _offer_extra_control(offer: dict[str, Any], *, checked: bool = False, name: str = "extra") -> str:
    extra_name = offer.get("extra_name")
    extra_price = offer.get("extra_price_minor")
    if extra_name is None or extra_price is None:
        return '<p class="not-specified">No optional extra is available for this offer.</p>'
    check = " checked" if checked else ""
    return (
        f'<label><input type="checkbox" name="{_esc(name)}" value="true"{check}>'
        f' Add {_esc(extra_name)} ({_minor(extra_price)}). Leave unchecked to decline this option.</label>'
    )


def _method_control(selected: str = "standard", radio: bool = False) -> str:
    selected = selected if selected in {"standard", "express"} else "standard"
    if radio:
        return '<fieldset><legend>Delivery speed</legend>' + "".join(
            f'<label><input type="radio" name="method" value="{method}"{" checked" if method == selected else ""}> {_esc(_label(method))}</label>'
            for method in ("standard", "express")
        ) + "</fieldset>"
    return '<label>Delivery speed<select name="method">' + "".join(
        f'<option value="{method}"{" selected" if method == selected else ""}>{_esc(_label(method))}</option>' for method in ("standard", "express")
    ) + "</select></label>"


def _destination_control(selected: str = "SE") -> str:
    return f'<label>Destination<select name="destination"><option value="SE"{" selected" if selected == "SE" else ""}>Sweden (SE)</option></select></label>'


def _product_card(site: str, origins: dict[str, str], product: dict[str, Any], *, expanded: bool, offer: dict[str, Any] | None = None, claim: dict[str, Any] | None = None) -> str:
    product_id = _text(product.get("product_id"))
    title = _text(product.get("name"), product_id)
    if site == "aggregator":
        price = _minor(claim.get("advertised_price_minor")) if claim else "See offers"
        retailer = _text(claim.get("retailer_id")) if claim else ""
        action = f'<a href="{_href(origins, site, _path_product(product_id))}">Compare offers</a>'
        extra = f'<p>Advertised by {_esc(retailer)}: <strong>{_esc(price)}</strong></p>' if claim else ""
    else:
        price = _minor(offer.get("price_minor")) if offer else "See product"
        stock = _text(offer.get("stock_quantity")) if offer else ""
        action = f'<a href="{_href(origins, site, _path_product(product_id))}">View product</a>'
        extra = f'<p>From <strong>{_esc(price)}</strong>; stock shown: {_esc(stock)}</p>' if offer else ""
    return (
        f'<article class="result-card" data-product-id="{_esc(product_id)}"><header><div><p class="site-kicker">{_esc(_label(product.get("category")))}</p>'
        f'<h3><a href="{_href(origins, site, _path_product(product_id))}">{_esc(title)}</a></h3></div></header>'
        + (f'<p class="product-id">Product ID: {_esc(product_id)}</p>' if expanded else "")
        + _specs(product, expanded)
        + extra
        + f'<p class="card-actions">{action}</p></article>'
    )


def _claims_for_product(catalog: dict[str, Any], product_id: str) -> list[dict[str, Any]]:
    return [claim for claim in catalog.get("aggregator_claims", []) if isinstance(claim, dict) and _text(claim.get("product_id")) == product_id]


def _offers_for_product(catalog: dict[str, Any], product_id: str) -> list[dict[str, Any]]:
    return [offer for offer in catalog.get("offers", []) if isinstance(offer, dict) and _text(offer.get("product_id")) == product_id]


def _aggregator_home(catalog: dict[str, Any], origins: dict[str, str], variant: str) -> str:
    products = [p for p in catalog.get("products", []) if isinstance(p, dict)]
    claims = [c for c in catalog.get("aggregator_claims", []) if isinstance(c, dict)]
    claim_by_product: dict[str, dict[str, Any]] = {}
    for claim in claims:
        claim_by_product.setdefault(_text(claim.get("product_id")), claim)
    cards = "".join(_product_card("aggregator", origins, product, expanded=variant == "expanded", claim=claim_by_product.get(_text(product.get("product_id")))) for product in products[:4])
    body = '<main class="directory-shell"><section class="directory-intro"><p class="site-kicker">Independent product directory</p><h2>Compare everyday products across participating shops.</h2><p>Search the full public catalog, then open a product to compare advertised offers and visit a merchant.</p>' + _search_form("aggregator", origins, products, {}) + f'<h2>Recently listed</h2><div class="result-list">{cards}</div><p><a href="{_href(origins, "aggregator", "/search")}">Browse the complete catalog</a></p></section></main>'
    return _document("aggregator", origins, catalog, "Prislyktan product directory", body, "Directory")


def _aggregator_search(catalog: dict[str, Any], origins: dict[str, str], query: dict[str, str], variant: str) -> str:
    products = [p for p in catalog.get("products", []) if isinstance(p, dict)]
    matches = _search_products(products, query)
    current = min(_page(query), max(1, ceil(len(matches) / PAGE_SIZE)))
    shown = matches[(current - 1) * PAGE_SIZE:current * PAGE_SIZE]
    claims = [c for c in catalog.get("aggregator_claims", []) if isinstance(c, dict)]
    claim_by_product: dict[str, dict[str, Any]] = {}
    for claim in claims:
        claim_by_product.setdefault(_text(claim.get("product_id")), claim)
    cards = "".join(_product_card("aggregator", origins, product, expanded=variant == "expanded", claim=claim_by_product.get(_text(product.get("product_id")))) for product in shown)
    result = '<p class="notice">No products matched this search.</p>' if not shown else f'<div class="result-list">{cards}</div>'
    body = '<main class="directory-shell"><section><h2>Search the directory</h2>' + _search_form("aggregator", origins, products, query) + f'<p>{len(matches)} matching product(s).</p>{result}{_pagination(origins, "aggregator", query, len(matches))}</section></main>'
    return _document("aggregator", origins, catalog, "Search | Prislyktan", body, "Directory search")


def _aggregator_product(catalog: dict[str, Any], origins: dict[str, str], product_id: str, variant: str) -> str:
    products = _product_map(catalog.get("products", []))
    product = products.get(product_id)
    if product is None:
        return _not_found("aggregator", origins, catalog, "Product not found")
    retailers = { _text(item.get("retailer_id")): item for item in catalog.get("retailers", []) if isinstance(item, dict)}
    claims = _claims_for_product(catalog, product_id)
    rows: list[str] = []
    for claim in claims:
        retailer_id = _text(claim.get("retailer_id"))
        retailer = retailers.get(retailer_id, {})
        merchant_href = _href(origins, retailer_id, _path_product(product_id))
        rows.append(f'<tr><th scope="row">{_esc(retailer.get("name"), retailer_id)}</th><td>{_esc(_minor(claim.get("advertised_price_minor")))}</td><td>{_esc(_text(claim.get("shipping_scope"), "Public item price"))}</td><td><a href="{merchant_href}">Check merchant offer</a></td></tr>')
    table = '<p class="notice">No public offers are listed for this product.</p>' if not rows else '<table class="offer-table"><caption>Public advertised offers</caption><thead><tr><th>Retailer</th><th>Advertised price</th><th>Shipping scope</th><th>Merchant</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
    detail = '<main class="directory-product"><article class="product-hero"><p class="site-kicker">Product comparison</p><h2>' + _esc(product.get("name")) + '</h2><p>Product ID: ' + _esc(product_id) + '</p>' + _specs(product, variant == "expanded") + '</article><section><h3>Compare participating merchants</h3>' + table + '</section><p><a href="' + _href(origins, "aggregator", "/search") + '">Back to directory search</a></p></main>'
    return _document("aggregator", origins, catalog, _text(product.get("name"), "Product comparison"), detail, "Product comparison")


def _retailer_home(site: str, catalog: dict[str, Any], origins: dict[str, str], variant: str, style: str | None = None) -> str:
    style = style or site
    products = [p for p in catalog.get("products", []) if isinstance(p, dict)]
    offers = _offer_map(catalog.get("offers", []))
    cards = "".join(_product_card(site, origins, product, expanded=variant == "expanded", offer=next((o for o in catalog.get("offers", []) if isinstance(o, dict) and _text(o.get("product_id")) == _text(product.get("product_id"))), None)) for product in products[:4])
    categories = sorted({_text(p.get("category")) for p in products if p.get("category")})
    category_links = "".join(f'<a href="{_href(origins, site, "/search", {"category": category})}">{_esc(_label(category))}</a>' for category in categories)
    retailer = catalog.get("retailer") if isinstance(catalog.get("retailer"), dict) else {}
    name = _text(retailer.get("name"), site.title())
    welcome = f'<section class="store-welcome"><p class="site-kicker">{_esc(_text(retailer.get("operating_profile", {}).get("warehouse_region"), "Local warehouse"))} fulfilment</p><h2>Welcome to {_esc(name)}</h2><p>Browse our catalog and review delivery choices before adding one product line to your cart.</p>{_search_form(site, origins, products, {})}</section>'
    if style == "nordhem":
        body = f'<main class="nordhem-catalog">{welcome}<aside class="category-sidebar"><h3>Shop by category</h3><nav aria-label="Categories"><div class="category-links">{category_links}</div></nav></aside><section class="featured-products"><h3>Featured catalog</h3><div class="result-list">{cards}</div><p><a href="{_href(origins, site, "/search")}">View all products</a></p></section></main>'
    elif style == "vardagslagret":
        body = f'<main class="vardagslagret-boutique">{welcome}<section class="shallow-navigation"><h3>Browse the collection</h3><details open><summary>Categories</summary><div class="category-links">{category_links}</div></details></section><section class="stacked-collection"><h3>Featured collection</h3>{cards}<p><a href="{_href(origins, site, "/search")}">View all products</a></p></section></main>'
    else:
        body = f'<main class="teknikgarden-specialist">{welcome}<section class="technical-categories"><h3>Specification groups</h3><div class="category-links">{category_links}</div></section><section class="specification-catalog"><h3>Featured technical catalog</h3><div class="result-list">{cards}</div><p><a href="{_href(origins, site, "/search")}">View all products</a></p></section></main>'
    return _document(site, origins, catalog, f"{name} catalog", body, "Retail catalog")


def _retailer_search(site: str, catalog: dict[str, Any], origins: dict[str, str], query: dict[str, str], variant: str, style: str | None = None) -> str:
    style = style or site
    products = [p for p in catalog.get("products", []) if isinstance(p, dict)]
    matches = _search_products(products, query)
    current = min(_page(query), max(1, ceil(len(matches) / PAGE_SIZE)))
    shown = matches[(current - 1) * PAGE_SIZE:current * PAGE_SIZE]
    offer_by_product = {_text(offer.get("product_id")): offer for offer in catalog.get("offers", []) if isinstance(offer, dict)}
    cards = "".join(_product_card(site, origins, product, expanded=variant == "expanded", offer=offer_by_product.get(_text(product.get("product_id")))) for product in shown)
    if not shown:
        result = '<p class="notice">No products matched this search.</p>'
    elif style == "nordhem":
        categories = sorted({_text(product.get("category")) for product in products if product.get("category")})
        category_links = "".join(f'<a href="{_href(origins, site, "/search", {"category": category})}">{_esc(_label(category))}</a>' for category in categories)
        details_header = '<th>Details</th>' if variant == "expanded" else ""
        rows = "".join(
            f'<tr><th scope="row"><a href="{_href(origins, site, _path_product(product.get("product_id")))}">{_esc(product.get("name"))}</a></th><td>{_esc(_label(product.get("category")))}</td><td>{_esc(_minor((offer_by_product.get(_text(product.get("product_id"))) or {}).get("price_minor")))}</td><td>{_esc((offer_by_product.get(_text(product.get("product_id"))) or {}).get("stock_quantity"), "Not specified")}</td>{f"<td>{_specs(product, True)}</td>" if variant == "expanded" else ""}</tr>'
            for product in shown
        )
        result = f'<div class="nordhem-search-grid"><aside class="category-sidebar"><h3>Categories</h3><div class="category-links">{category_links}</div></aside><table class="offer-table nordhem-result-table"><caption>Catalog results</caption><thead><tr><th>Product</th><th>Category</th><th>Price</th><th>Stock</th>{details_header}</tr></thead><tbody>{rows}</tbody></table></div>'
    elif style == "vardagslagret":
        entries = "".join(f'<li><article class="boutique-result"><p class="site-kicker">{_esc(_label(product.get("category")))}</p><h3><a href="{_href(origins, site, _path_product(product.get("product_id")))}">{_esc(product.get("name"))}</a></h3>{_specs(product, variant == "expanded")}<p>From <strong>{_esc(_minor((offer_by_product.get(_text(product.get("product_id"))) or {}).get("price_minor")))}</strong></p></article></li>' for product in shown)
        result = f'<section class="boutique-results"><h3>Collection results</h3><ol class="stacked-results">{entries}</ol></section>'
    else:
        entries = "".join(f'<article class="specialist-result"><header><p class="site-kicker">{_esc(_label(product.get("category")))}</p><h3><a href="{_href(origins, site, _path_product(product.get("product_id")))}">{_esc(product.get("name"))}</a></h3></header><section class="specification-summary"><h4>Specifications</h4>{_specs(product, variant == "expanded")}</section><p>Current offer: <strong>{_esc(_minor((offer_by_product.get(_text(product.get("product_id"))) or {}).get("price_minor")))}</strong></p></article>' for product in shown)
        result = f'<section class="spec-first-results"><h3>Specification results</h3>{entries}</section>'
    specialist = style == "teknikgarden"
    body_class = "specialist-results" if specialist else "catalog-results"
    body = f'<main class="{body_class}"><section><h2>{"Technical catalog" if specialist else "Catalog"}</h2>' + _search_form(site, origins, products, query, specialist=specialist) + f'<p>{len(matches)} matching product(s).</p>{result}{_pagination(origins, site, query, len(matches))}</section></main>'
    return _document(site, origins, catalog, f"Search | {_text(catalog.get('retailer', {}).get('name'), site.title())}", body, "Specialist catalog" if specialist else "Store catalog")


def _retailer_product(site: str, catalog: dict[str, Any], origins: dict[str, str], product_id: str, variant: str, context: dict[str, Any]) -> str:
    style={"catalog":"nordhem","boutique":"vardagslagret","specifications":"teknikgarden"}.get(context.get("presentation_options",{}).get("legacy_style"),site)
    product = _product_map(catalog.get("products", [])).get(product_id)
    if product is None:
        return _not_found(site, origins, catalog, "Product not found")
    offer = next((item for item in catalog.get("offers", []) if isinstance(item, dict) and _text(item.get("product_id")) == product_id), None)
    if offer is None:
        return _not_found(site, origins, catalog, "Offer not found")
    offer_id = _text(offer.get("offer_id"))
    stock = offer.get("stock_quantity")
    checked = _bool(offer.get("extra_preselected"))
    purchase = (
        f'<form class="purchase-form" method="post" action="{_form_action(origins, site, "/cart/set")}"><input type="hidden" name="offer_id" value="{_esc(offer_id)}">'
        '<h3>Add this offer</h3><div class="form-grid">'
        '<label>Quantity<input type="number" name="quantity" min="1" value="1" required></label>'
        + _destination_control("SE") + _method_control("standard", radio=style == "vardagslagret")
        + '</div><p class="stock">Stock available: ' + _esc(stock) + '</p>' + _offer_extra_control(offer, checked=checked) + purchase_actions(catalog,context.get("cart"),context.get("error")) + "</form>"
    )
    quote_params = {"offer_id": offer_id, "quantity": "1", "destination": "SE", "method": "standard", "extra": "true" if checked else "false"}
    quote_link = f'<p><a href="{_href(origins, site, "/quote", quote_params)}">Preview a complete delivery quote</a></p>'
    active_cart = context.get("cart") if isinstance(context.get("cart"), dict) else None
    active_offer = _offer_map(catalog.get("offers", [])).get(_text((active_cart or {}).get("offer_id")))
    cart_notice = ""
    if active_offer and _text(active_offer.get("product_id")) != product_id:
        cart_notice = (
            '<aside class="notice cart-line-limit"><strong>This store accepts one product line per basket.</strong> '
            f'Your basket already contains {_esc(active_offer.get("product_id"))}. '
            f'<a href="{_href(origins, site, "/cart")}">Review your cart and remove the current line before adding another product.</a>'
            '</aside>'
        )
    if catalog.get("cart_navigation") in ("inline","menu"):
        cart_notice=""
    retailer = catalog.get("retailer") if isinstance(catalog.get("retailer"), dict) else {}
    product_facts = f'<article class="product-hero"><p class="site-kicker">{_esc(_label(product.get("category")))}</p><h2>{_esc(product.get("name"))}</h2><p>Product ID: {_esc(product_id)}</p>{_specs(product, variant == "expanded")}</article>'
    offer_section = f'<section class="offer-card"><h3>Current offer</h3><p>Offer ID: {_esc(offer_id)}</p><p>Price: <strong>{_esc(_minor(offer.get("price_minor")))}</strong></p><p>Dispatch: {_esc(offer.get("dispatch_days"))} day(s). Extra choices are optional.</p>{purchase}{quote_link}</section>'
    if style == "vardagslagret":
        body = f'<main class="vardagslagret-boutique-product">{cart_notice}<details class="product-story" open><summary>{_esc(product.get("name"))} details</summary>{product_facts}</details>{offer_section}<p><a href="{_href(origins, site, "/search")}">Back to catalog</a></p></main>'
    elif style == "teknikgarden":
        body = f'<main class="teknikgarden-specification-product">{cart_notice}<section class="specification-first"><h3>Product specifications</h3>{product_facts}</section>{offer_section}<p><a href="{_href(origins, site, "/search")}">Back to catalog</a></p></main>'
    else:
        body = f'<main class="nordhem-product-layout">{cart_notice}{product_facts}{offer_section}<p><a href="{_href(origins, site, "/search")}">Back to catalog</a></p></main>'
    return _document(site, origins, catalog, _text(product.get("name"), "Product"), body, _text(retailer.get("name"), "Store") + " product")


def _quote_lines(quote: dict[str, Any]) -> str:
    fields = [("Items", "item_subtotal_minor"), ("Optional extra", "extra_subtotal_minor"), ("Delivery", "shipping_minor"), ("Complete total", "total_minor")]
    lines = "".join(
        f'<div><dt>{_esc(label)}</dt><dd{(" class=\"total\"" if key == "total_minor" else "")}>{_esc(_minor(quote.get(key)))}</dd></div>'
        for label, key in fields
    )
    lines += f'<div><dt>Arrival</dt><dd>{_esc(quote.get("arrival_days"), "Not supplied")} calendar day(s)</dd></div>'
    return '<dl class="quote-breakdown">' + lines + '</dl>'


def _retailer_quote(site: str, catalog: dict[str, Any], origins: dict[str, str], query: dict[str, str], context: dict[str, Any]) -> str:
    quote = context.get("quote") if isinstance(context.get("quote"), dict) else None
    offers = _offer_map(catalog.get("offers", []))
    offer_id = _text(query.get("offer_id"))
    offer = offers.get(offer_id)
    if offer is None and quote is not None:
        offer = offers.get(_text(quote.get("offer_id")))
    product = _product_map(catalog.get("products", [])).get(_text((offer or {}).get("product_id")))
    if quote is None:
        message = _text(context.get("error"), "Enter an offer from this catalog to preview its complete quote.")
        body = f'<main class="quote-page"><h2>Complete delivery quote</h2><p class="notice">{_esc(message)}</p><p><a href="{_href(origins, site, "/search")}">Choose a product</a></p></main>'
        return _document(site, origins, catalog, "Delivery quote", body, "Quote preview")
    eligible = quote.get("eligible")
    status = '<p class="success">This selection is eligible for checkout.</p>' if eligible else '<p class="error">This selection cannot currently be purchased.</p>'
    reason_codes = quote.get("reason_codes")
    reasons = f'<p>Reason codes: {_esc(", ".join(map(str, reason_codes)))}</p>' if isinstance(reason_codes, list) and reason_codes else ""
    title = _text((product or {}).get("name"), "Quote preview")
    body = f'<main class="quote-page"><article class="product-hero"><p class="site-kicker">Complete delivery quote</p><h2>{_esc(title)}</h2><p>Offer ID: {_esc(quote.get("offer_id"))}; quantity: {_esc(quote.get("quantity"))}; destination: {_esc(quote.get("destination"))}; method: {_esc(quote.get("method"))}; extra selected: {_esc("yes" if _bool(quote.get("extra")) else "no")}</p>{status}{reasons}{_quote_lines(quote)}</article><p><a href="{_href(origins, site, "/cart")}">Review cart</a> · <a href="{_href(origins, site, _path_product((product or {}).get("product_id")))}">Back to product</a></p></main>'
    return _document(site, origins, catalog, f"Quote | {title}", body, "Quote preview")


def _cart_context(context: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    cart = context.get("cart") if isinstance(context.get("cart"), dict) else None
    quote = cart.get("quote") if cart and isinstance(cart.get("quote"), dict) else None
    if quote is None and isinstance(context.get("quote"), dict):
        quote = context.get("quote")
    return cart, quote


def _retailer_cart(site: str, catalog: dict[str, Any], origins: dict[str, str], context: dict[str, Any]) -> str:
    cart, quote = _cart_context(context)
    offers = _offer_map(catalog.get("offers", []))
    offer = offers.get(_text((cart or {}).get("offer_id")))
    error = context.get("error")
    if cart is None or quote is None:
        message = '<p class="notice">Your cart is empty. This store accepts one product line per basket.</p>'
        if error:
            message += f'<p class="error">{_esc(error)}</p>'
        body = f'<main class="{site}-cart cart-page"><h2>Your cart</h2>{message}<p><a href="{_href(origins, site, "/search")}">Browse catalog</a></p></main>'
        return _document(site, origins, catalog, "Cart", body, "Your cart")
    checked = _bool(cart.get("extra"))
    offer = offer or {}
    line_name = _text(offer.get("offer_id"), _text(cart.get("offer_id")))
    update = (
        f'<form class="cart-actions" method="post" action="{_form_action(origins, site, "/cart/update")}"><div class="form-grid">'
        f'<label>Quantity<input type="number" name="quantity" min="1" value="{_esc(cart.get("quantity", quote.get("quantity", 1)))}" required></label>'
        + _destination_control(_text(cart.get("destination"), "SE")) + _method_control(_text(cart.get("method"), "standard"), radio=site == "vardagslagret")
        + '</div>' + _offer_extra_control(offer, checked=checked) + '<button type="submit">Update cart</button></form>'
    )
    remove = f'<form method="post" action="{_form_action(origins, site, "/cart/remove")}"><button class="button-secondary" type="submit">Remove item</button></form>'
    checkout = f'<form class="review-actions" method="get" action="{_form_action(origins, site, "/checkout")}"><button type="submit">Review checkout</button></form>' if quote.get("eligible") else '<p class="error">Checkout is unavailable until this selection is eligible.</p>'
    error_html = f'<p class="error">{_esc(error)}</p>' if error else ""
    cart_line = (
        f'<table class="cart-line"><caption>One active product line</caption><tbody><tr><th scope="row">Offer</th><td>{_esc(line_name)}</td></tr><tr><th scope="row">Quantity</th><td>{_esc(cart.get("quantity", quote.get("quantity")))}</td></tr></tbody></table>'
        if site == "nordhem"
        else f'<article class="cart-line"><h3>One active product line</h3><p>Offer: {_esc(line_name)}</p><p>Quantity: {_esc(cart.get("quantity", quote.get("quantity")))}</p></article>'
    )
    body = f'<main class="{site}-cart cart-page"><h2>Your cart</h2><p class="notice">This store accepts one product line per basket. Remove the current line below before adding a different product.</p>{error_html}{cart_line}{_quote_lines(quote)}{update}{remove}{checkout}</main>'
    return _document(site, origins, catalog, "Cart", body, "Your cart")


def _retailer_checkout(site: str, catalog: dict[str, Any], origins: dict[str, str], context: dict[str, Any]) -> str:
    cart, quote = _cart_context(context)
    if cart is None or quote is None:
        body = f'<main class="checkout-page"><h2>Checkout review</h2><p class="notice">There is no active cart to review.</p><p><a href="{_href(origins, site, "/search")}">Browse catalog</a></p></main>'
        return _document(site, origins, catalog, "Checkout review", body, "Checkout review")
    status = '<p class="success">Ready for your explicit simulated order.</p>' if quote.get("eligible") else '<p class="error">This quote is not eligible; checkout will be rejected without changing the cart.</p>'
    action = f'<form class="review-actions" method="post" action="{_form_action(origins, site, "/checkout")}"><p>Review the current quote, then place the order.</p><button type="submit"{" disabled" if not quote.get("eligible") else ""}>Place simulated order</button></form>'
    body = f'<main class="checkout-page"><h2>Checkout review</h2>{status}<article class="quote-breakdown"><p>Offer: {_esc(cart.get("offer_id"))}; quantity: {_esc(cart.get("quantity"))}</p>{_quote_lines(quote)}</article>{action}<p><a href="{_href(origins, site, "/cart")}">Back to cart</a></p></main>'
    return _document(site, origins, catalog, "Checkout review", body, "Checkout review")


def _retailer_policy(site: str, catalog: dict[str, Any], origins: dict[str, str]) -> str:
    retailer = catalog.get("retailer") if isinstance(catalog.get("retailer"), dict) else {}
    policy = retailer.get("policy_summary") if isinstance(retailer.get("policy_summary"), dict) else {}
    shipping = retailer.get("shipping_methods") if isinstance(retailer.get("shipping_methods"), dict) else {}
    method_rows = "".join(f'<tr><th scope="row">{_esc(_label(method))}</th><td>{_esc(_minor(details.get("base_price_minor")))}</td><td>{_esc(details.get("transit_days"))} day(s)</td><td>{_esc(_minor(details.get("free_shipping_threshold_minor")) if details.get("free_shipping_threshold_minor") is not None else "Never free")}</td></tr>' for method, details in shipping.items() if isinstance(details, dict))
    body = f'<main class="policy-page"><h2>Delivery and returns</h2><p>Shipping rules supplied by the store:</p><table class="offer-table"><caption>Delivery methods</caption><thead><tr><th>Method</th><th>Base price</th><th>Transit</th><th>Free above</th></tr></thead><tbody>{method_rows}</tbody></table><h3>Returns and warranty</h3><dl class="specifications"><dt>Returns window</dt><dd>{_esc(policy.get("returns_days"), "Not specified")} days</dd><dt>Return shipping paid by</dt><dd>{_esc(_label(policy.get("return_shipping_paid_by")), "Not specified")}</dd><dt>Warranty</dt><dd>{_esc(policy.get("warranty_years"), "Not specified")} years</dd></dl><p><a href="{_href(origins, site, "/search")}">Back to catalog</a></p></main>'
    return _document(site, origins, catalog, "Delivery and returns", body, "Store policy")


def _retailer_receipt(site: str, catalog: dict[str, Any], origins: dict[str, str], order_id: str, context: dict[str, Any]) -> str:
    orders = context.get("orders") if isinstance(context.get("orders"), list) else []
    order = next((item for item in orders if isinstance(item, dict) and _text(item.get("order_id")) == order_id), None)
    if order is None:
        return _not_found(site, origins, catalog, "Receipt not found")
    lines = [("Order ID", order.get("order_id")), ("Product ID", order.get("product_id")), ("Offer ID", order.get("offer_id")), ("Quantity", order.get("quantity", 1)), ("Total", _minor(order.get("total_minor"))), ("Destination", order.get("destination", "SE")), ("Method", order.get("method", "standard"))]
    fulfillment=context.get("fulfillment")
    if isinstance(fulfillment,dict):
        lines.extend((label,fulfillment[key]) for label,key in [("Recipient","full_name"),("Email","email"),("Address","address"),("Postal code","postal_code"),("City","city"),("Payment option","payment_method")] if key in fulfillment)
    body = '<main class="receipt-page"><article class="receipt-card"><p class="site-kicker">Simulated order receipt</p><h2>Order confirmed</h2><dl class="specifications">' + "".join(f'<dt>{_esc(label)}</dt><dd>{_esc(value)}</dd>' for label, value in lines) + '</dl></article><p><a href="' + _href(origins, site, "/") + '">Return to store</a></p></main>'
    return _document(site, origins, catalog, "Order receipt", body, "Receipt")


def _route_parts(path: str) -> list[str]:
    return [part for part in _text(path).split("/") if part]


def render_page(site: str, path: str, query: dict[str, str], context: dict, origins: dict[str, str]) -> str:
    """Render one route as escaped, self-contained semantic HTML."""

    if site != "aggregator" and site not in RETAILERS:
        return _not_found(site, origins, context.get("catalog", {}) if isinstance(context, dict) else {}, "Unknown store")
    if not isinstance(context, dict):
        context = {}
    if site != "aggregator" and context.get("retailer_design", "legacy-catalog") != "legacy-catalog":
        from .retailer_designs import render_retailer
        rendered=render_retailer(site,path,query,context,origins,context["retailer_design"],context.get("presentation_options",{}))
        if rendered is not None:return rendered
    catalog = context.get("catalog") if isinstance(context.get("catalog"), dict) else {}
    query = query if isinstance(query, dict) else {}
    variant = _layout_variant(context)
    legacy_style={"catalog":"nordhem","boutique":"vardagslagret","specifications":"teknikgarden"}.get(context.get("presentation_options",{}).get("legacy_style"),site)
    parts = _route_parts(path)
    route = "/" + "/".join(parts)
    if not parts:
        return _aggregator_home(catalog, origins, variant) if site == "aggregator" else _retailer_home(site, catalog, origins, variant, legacy_style)
    if parts[0] == "search" and len(parts) == 1:
        return _aggregator_search(catalog, origins, query, variant) if site == "aggregator" else _retailer_search(site, catalog, origins, query, variant, legacy_style)
    if parts[0] == "products" and len(parts) == 2:
        return _aggregator_product(catalog, origins, parts[1], variant) if site == "aggregator" else _retailer_product(site, catalog, origins, parts[1], variant, context)
    if site == "aggregator":
        return _not_found(site, origins, catalog)
    if route == "/policy":
        return _retailer_policy(site, catalog, origins)
    if route == "/cart":
        return _retailer_cart(site, catalog, origins, context)
    if route == "/checkout":
        return _retailer_checkout(site, catalog, origins, context)
    if route == "/quote":
        return _retailer_quote(site, catalog, origins, query, context)
    if len(parts) == 2 and parts[0] == "receipt":
        return _retailer_receipt(site, catalog, origins, parts[1], context)
    return _not_found(site, origins, catalog)


__all__ = ["render_page"]
