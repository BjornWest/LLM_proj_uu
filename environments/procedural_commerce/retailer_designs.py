"""Structurally distinct, accessibility-first retailer page families.

This module renders only catalog-facing routes.  Transactional and policy routes
return ``None`` so the established renderer can remain their single owner.
"""

from __future__ import annotations

from html import escape
from . import department_variations as variants
from .cart_interaction import cart_label, product_feedback, purchase_actions
from math import ceil
from typing import Any, Iterable
from urllib.parse import quote as url_quote


DESIGNS = frozenset(
    {"department-market", "editorial-boutique", "technical-catalog", "dense-storefront"}
)
_PAGE_SIZE = 12
_DETAILS_BY_DESIGN = {
    "dense-storefront": frozenset({"disclosure"}),
    "department-market": frozenset({"inline", "disclosure"}),
    "editorial-boutique": frozenset({"linked"}),
    "technical-catalog": frozenset({"disclosure"}),
}
_DEFAULTS = {
    "dense-storefront": {"nav_expanded": False, "details_presentation": "disclosure", "image_count": 2, "title_style": "descriptive"},
    "department-market": {
        "nav_expanded": True,
        "details_presentation": "inline",
        "image_count": 2,
        "title_style": "descriptive",
    },
    "editorial-boutique": {
        "nav_expanded": False,
        "details_presentation": "linked",
        "image_count": 2,
        "title_style": "short",
    },
    "technical-catalog": {
        "nav_expanded": True,
        "details_presentation": "disclosure",
        "image_count": 1,
        "title_style": "descriptive",
    },
}


def _legacy() -> Any:
    """Import shared, fact-preserving helpers only after render dispatch begins."""

    from . import renderers

    return renderers


def _text(value: Any, fallback: str = "") -> str:
    return fallback if value is None else str(value)


def _esc(value: Any, fallback: str = "") -> str:
    return escape(_text(value, fallback), quote=True)


def _label(value: Any) -> str:
    return _text(value).replace("_", " ").replace("-", " ").capitalize()


def _attrs(product: dict[str, Any]) -> list[tuple[str, str]]:
    attributes = product.get("attributes")
    if not isinstance(attributes, dict):
        return []
    return [
        (_text(key), _text(value))
        for key, value in attributes.items()
        if value is not None and _text(value)
    ]


def _traits(product: dict[str, Any]) -> list[str]:
    traits = product.get("traits")
    if not isinstance(traits, (list, tuple)):
        return []
    return [_text(value) for value in traits if value is not None and _text(value)]


def _products(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in catalog.get("products", []) if isinstance(row, dict)]


def _offers(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _text(row.get("product_id")): row
        for row in catalog.get("offers", [])
        if isinstance(row, dict)
    }


def _product(catalog: dict[str, Any], product_id: str) -> dict[str, Any] | None:
    return next(
        (row for row in _products(catalog) if _text(row.get("product_id")) == product_id),
        None,
    )


def _categories(products: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({_text(row.get("category")) for row in products if row.get("category")})


def _options(design: str, supplied: dict[str, Any] | None) -> dict[str, Any]:
    if design not in DESIGNS:
        raise ValueError(f"unknown retailer design: {design}")
    if supplied is None:
        supplied = {}
    if not isinstance(supplied, dict):
        raise TypeError("retailer design options must be a dict or None")
    # ``legacy_style`` belongs to the sibling legacy renderer.  The runtime keeps
    # it in every resolved option map so a site can switch design families without
    # changing the public configuration shape.
    allowed = {
        "nav_expanded",
        "details_presentation",
        "image_count",
        "title_style",
        "legacy_style",
    }
    allowed |= set(variants.CHOICES)
    variants.validate(design,supplied)
    unknown = set(supplied) - allowed
    if unknown:
        raise ValueError(f"unknown retailer design options: {sorted(unknown)}")
    resolved = {
        **_DEFAULTS[design],
        **(variants.DEFAULTS if design=="department-market" else {}),
        **{key: value for key, value in supplied.items() if key != "legacy_style"},
    }
    if not isinstance(resolved["nav_expanded"], bool):
        raise TypeError("nav_expanded must be a bool")
    if resolved["details_presentation"] not in _DETAILS_BY_DESIGN[design]:
        choices = ", ".join(sorted(_DETAILS_BY_DESIGN[design]))
        raise ValueError(f"details_presentation for {design} must be {choices}")
    if resolved["image_count"] not in {1, 2}:
        raise ValueError("image_count must be 1 or 2")
    if resolved["title_style"] not in {"short", "descriptive"}:
        raise ValueError("title_style must be short or descriptive")
    return resolved


def _href(origins: dict[str, str], site: str, path: str, params: dict[str, Any] | None = None) -> str:
    return _legacy()._href(origins, site, path, params)


def _product_path(product_id: Any) -> str:
    return "/products/" + url_quote(_text(product_id), safe="")


def _title(product: dict[str, Any], style: str) -> str:
    name = _text(product.get("name"), _text(product.get("product_id"), "Product"))
    if style == "short":
        return name
    facts = [_label(product.get("category"))]
    facts.extend(value for _key, value in _attrs(product))
    return " — ".join([name, *[fact for fact in facts if fact]])


def _svg_src(view: int) -> str:
    # Symbolic catalog drawing only: it deliberately contains no product depiction.
    accent = "264653" if view == 1 else "9c6644"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="320" '
        'viewBox="0 0 480 320"><rect width="480" height="320" fill="#f4f1ea"/>'
        f'<path d="M80 235L180 95l88 105 55-63 77 98z" fill="none" stroke="#{accent}" '
        'stroke-width="13"/><circle cx="365" cy="82" r="29" fill="none" '
        f'stroke="#{accent}" stroke-width="10"/></svg>'
    )
    return "data:image/svg+xml," + url_quote(svg, safe="")


def _figure(product: dict[str, Any], view: int) -> str:
    name = _text(product.get("name"), _text(product.get("product_id"), "Product"))
    return (
        f'<figure><img src="{_svg_src(view)}" alt="{_esc(name)}, catalog illustration/view {view}" '
        'width="480" height="320">'
        f'<figcaption>Catalog view {view}</figcaption></figure>'
    )


def _fact_table(product: dict[str, Any], *, caption: str = "Product specifications") -> str:
    rows = [
        ("Product ID", product.get("product_id")),
        ("Category", _label(product.get("category"))),
        *[(_label(key), value) for key, value in _attrs(product)],
    ]
    traits = _traits(product)
    if traits:
        rows.append(("Traits", ", ".join(traits)))
    if not rows:
        return '<p class="not-specified">Product details are not specified.</p>'
    return (
        f'<table class="fact-table"><caption>{_esc(caption)}</caption><tbody>'
        + "".join(
            f'<tr><th scope="row">{_esc(label)}</th><td>{_esc(value)}</td></tr>'
            for label, value in rows
        )
        + "</tbody></table>"
    )


def _search_form(
    site: str,
    origins: dict[str, str],
    products: list[dict[str, Any]],
    query: dict[str, str],
    *,
    label: str,
) -> str:
    categories = _categories(products)
    selected = _text(query.get("category"))
    choices = '<option value="">All categories</option>' + "".join(
        f'<option value="{_esc(category)}"{" selected" if category == selected else ""}>{_esc(_label(category))}</option>'
        for category in categories
    )
    return (
        f'<form class="search-form" method="get" action="{_legacy()._form_action(origins, site, "/search")}">'
        f'<label>{_esc(label)}<input type="search" name="q" value="{_esc(query.get("q"))}"></label>'
        f'<label>Category<select name="category">{choices}</select></label>'
        '<button type="submit">Search</button></form>'
    )


def _purchase_form(site: str, origins: dict[str, str], offer: dict[str, Any], *, grouped: bool, catalog=None, context=None, delivery_control="select") -> str:
    legacy = _legacy()
    selection = (context or {}).get('product_selection')
    prefix = ''
    if selection:
        from .product_controls import purchase_prefix
        available = bool(offer.get('offer_id')) and offer.get('stock_quantity', 0) > 0
        prefix = purchase_prefix(site, origins, context, available)
        if not available:
            return (f'<form method="get" action="{legacy._form_action(origins, site, _product_path(selection["source_product_id"]))}">' + prefix + '</form>'
                    + product_feedback(catalog or {}, context.get('cart'), context.get('error')))
    controls = (
        '<label>Quantity<input type="number" name="quantity" min="1" value="1" required></label>'
        + legacy._destination_control("SE")
        + legacy._method_control("standard", radio=delivery_control=="radio")
        + legacy._offer_extra_control(
            offer, checked=legacy._bool(offer.get("extra_preselected"))
        )
    )
    if grouped:
        controls = f'<fieldset><legend>Configure this offer</legend>{controls}</fieldset>'
    return (
        f'<form class="purchase-form" method="post" action="{_legacy()._form_action(origins, site, "/cart/set")}">'
        f'<input type="hidden" name="offer_id" value="{_esc(offer.get("offer_id"))}">'
        f"{prefix}{controls}<p>Stock available: {_esc(offer.get('stock_quantity'))}</p>"
        + purchase_actions(catalog or {},(context or {}).get("cart"),(context or {}).get("error")) + "</form>"
    )


def _quote_link(site: str, origins: dict[str, str], offer: dict[str, Any]) -> str:
    if not offer.get("offer_id"):
        return ""
    checked = _legacy()._bool(offer.get("extra_preselected"))
    params = {
        "offer_id": _text(offer.get("offer_id")),
        "quantity": "1",
        "destination": "SE",
        "method": "standard",
        "extra": "true" if checked else "false",
    }
    return (
        f'<p><a href="{_href(origins, site, "/quote", params)}">'
        "Preview a complete delivery quote</a></p>"
    )


def _style(design: str) -> str:
    common = """
*{box-sizing:border-box}body{margin:0;color:#202124;background:#faf9f6;font:16px/1.55 system-ui,sans-serif}a{color:#174b6e}header,main,footer{padding:1rem clamp(1rem,4vw,3rem)}header{border-bottom:1px solid #bbb;background:#fff}header h1{margin:.15rem 0}nav ul{padding-left:1.25rem}.search-form,.purchase-form{display:flex;gap:.8rem;align-items:end;flex-wrap:wrap;padding:1rem;border:1px solid #aaa;background:#fff}.search-form label,.purchase-form label{display:grid;gap:.2rem}.purchase-form fieldset{display:flex;gap:.8rem;flex-wrap:wrap;border:1px solid #777}input,select,button{font:inherit;padding:.45rem}button{background:#173f5f;color:white;border:0}.price{font-weight:700}.fact-table,.result-table{width:100%;border-collapse:collapse}.fact-table th,.fact-table td,.result-table th,.result-table td{text-align:left;vertical-align:top;border:1px solid #aaa;padding:.55rem}figure{margin:.5rem}img{display:block;max-width:100%;height:auto}.site-footer{border-top:1px solid #aaa;margin-top:2rem}.skip-link{position:absolute;left:-9999px}.skip-link:focus{left:1rem;background:#fff;padding:.5rem;z-index:2}.notice{border-left:4px solid #8a5a00;padding:.7rem}.pagination{margin:1rem 0}
"""
    layouts = {
        "department-market": """
.department-header .utility-nav ul{display:flex;gap:1rem;list-style:none;padding:0}.department-shell{display:grid;grid-template-columns:minmax(13rem,22%) 1fr;gap:2rem}.department-sidebar{border-right:1px solid #aaa;padding-right:1rem}.result-list{display:grid;gap:1rem}.market-result{display:grid;grid-template-columns:150px 1fr auto;gap:1rem;border-bottom:1px solid #aaa;padding:1rem 0}.product-market{display:grid;grid-template-columns:minmax(0,1fr) minmax(17rem,32%);gap:2rem}.product-gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.market-bottom{grid-column:1/-1}.department-detail-first{max-width:72rem}.department-detail-first article>header{padding:0;background:none;border:0}.product-facts{display:grid;grid-template-columns:12rem 1fr}.product-facts dt{font-weight:bold}.product-facts dd{margin:0}.department-detail-first details{border:1px solid #aaa;padding:1rem;margin:1rem 0}.department-detail-first .product-gallery img{max-height:240px}.department-sidebar details{margin:.6rem 0}.department-sidebar summary{cursor:pointer;font-weight:bold}
""",
        "editorial-boutique": """
.boutique-header{display:flex;align-items:baseline;justify-content:space-between}.boutique-header nav ul{display:flex;gap:1rem;list-style:none}.boutique-story{max-width:64rem;margin:auto;padding-block:4rem}.boutique-results,.boutique-product{max-width:58rem;margin:auto}.boutique-results li{padding:1rem 0;border-bottom:1px solid #bbb}.editorial-figures{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.inline-purchase{margin:2rem 0}.shipping-copy{font-family:Georgia,serif}
""",
        "technical-catalog": """
.technical-frame{display:grid;grid-template-columns:17rem minmax(0,1fr);min-height:85vh}.technical-sidebar{grid-column:1;grid-row:1/3;border-right:2px solid #273746;background:#edf1f3}.technical-sidebar header,.technical-sidebar nav{padding:1rem}.technical-main{grid-column:2}.section-nav ul{display:flex;gap:1rem;flex-wrap:wrap}.technical-product details{border:1px solid #777;padding:1rem;margin:1rem 0}.technical-product summary{font-weight:700;cursor:pointer}.status{white-space:nowrap}
""",
    }
    return f"<style>{common}{layouts[design]}@media(max-width:720px){{.department-shell,.product-market,.technical-frame{{display:block}}.market-result{{grid-template-columns:1fr}}}}</style>"


def _storefront_navigation(catalog: dict[str, Any]) -> str:
    """Optional public collection links; standalone commerce defaults stay intact."""
    rows = catalog.get('storefront_links', [])
    if not rows:
        return ''
    return '<nav aria-label="Shop by category"><ul>' + ''.join(
        '<li><a href="' + _esc(row['href']) + '">' + _esc(row['title']) + '</a></li>'
        for row in rows
    ) + '</ul></nav>'


def _service_links(catalog: dict[str, Any]) -> str:
    rows = catalog.get('customer_service_links', [])
    if not rows:
        return ''
    return '<nav aria-label="Customer service">' + ' · '.join(
        '<a href="' + _esc(row['href']) + '">' + _esc(row['title']) + '</a>'
        for row in rows
    ) + '</nav>'


def _footer(catalog: dict[str, Any], design: str) -> str:
    retailer = catalog.get("retailer") if isinstance(catalog.get("retailer"), dict) else {}
    if design == "editorial-boutique":
        shipping = retailer.get("shipping_methods") if isinstance(retailer.get("shipping_methods"), dict) else {}
        standard = shipping.get("standard") if isinstance(shipping.get("standard"), dict) else {}
        shipping_text = (
            f"Standard delivery has a base price of {_legacy()._minor(standard.get('base_price_minor'))} "
            f"and { _esc(standard.get('transit_days'), 'not specified') } transit day(s)."
        )
        extra = f'<p class="shipping-copy">{shipping_text}</p>'
    else:
        extra = ""
    return (
        f'<footer class="site-footer">{_service_links(catalog)}{extra}<p>Prices shown in {_esc(catalog.get("currency"), "SEK")}. '
        f'Scenario date: {_esc(catalog.get("scenario_date"))}.</p></footer>'
    )


def _department_nav(site: str, origins: dict[str, str], products: list[dict[str, Any]], expanded: bool) -> str:
    groups = []
    for category in _categories(products):
        children = ""
        if expanded:
            names = [row for row in products if _text(row.get("category")) == category][:3]
            children = "<ul>" + "".join(
                f'<li><a href="{_href(origins, site, _product_path(row.get("product_id")))}">{_esc(row.get("name"))}</a></li>'
                for row in names
            ) + "</ul>"
        groups.append(
            f'<li><a href="{_href(origins, site, "/search", {"category": category})}">{_esc(_label(category))}</a>{children}</li>'
        )
    return '<nav aria-label="Departments"><h2>Departments</h2><ul>' + "".join(groups) + "</ul></nav>"


def _technical_nav(site: str, origins: dict[str, str], products: list[dict[str, Any]], expanded: bool, catalog=None) -> str:
    category_items = ""
    if expanded:
        category_items = "<ul>" + "".join(
            f'<li><a href="{_href(origins, site, "/search", {"category": category})}">{_esc(_label(category))}</a></li>'
            for category in _categories(products)
        ) + "</ul>"
    return (
        '<nav aria-label="Catalog navigation"><ul>'
        f'<li><a href="{_href(origins, site, "/")}">Catalog start</a></li>'
        f'<li><a href="{_href(origins, site, "/search")}">All specifications</a>{category_items}</li>'
        f'<li><a href="{_href(origins, site, "/policy")}">Delivery and returns</a></li>'
        f'<li><a href="{_href(origins, site, "/cart")}">{cart_label(catalog or {}, "Current order")}</a></li>'
        "</ul></nav>"
    )


def _department_document(
    site: str,
    origins: dict[str, str],
    catalog: dict[str, Any],
    title: str,
    main: str,
    options: dict[str, Any],
) -> str:
    retailer = catalog.get("retailer") if isinstance(catalog.get("retailer"), dict) else {}
    name = _text(retailer.get("name"), site.title())
    products = _products(catalog)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{_esc(title)}</title>{_style("department-market")}</head><body class="department-market">'
        '<a class="skip-link" href="#main-content">Skip to content</a>'
        f'<header class="department-header"><p>Customer service and delivery information</p><h1><a href="{_href(origins, site, "/")}">{_esc(name)}</a></h1>'
        '<nav class="utility-nav" aria-label="Utility navigation"><ul>'
        f'<li><a href="{_href(origins, site, "/search")}">Search</a></li>'
        f'<li><a href="{_href(origins, site, "/policy")}">Delivery &amp; policy</a></li>'
        f'<li><a href="{_href(origins, site, "/cart")}">{cart_label(catalog, "Cart")}</a></li></ul></nav></header>'
        '<div class="department-shell"><aside class="department-sidebar">'
        + (_storefront_navigation(catalog) or (_department_nav(site, origins, products, options["nav_expanded"]) if options["navigation_structure"]=="standard" else variants.navigation(site,origins,products,options["navigation_structure"])))
        + f'</aside>{main}</div>{_footer(catalog, "department-market")}</body></html>'
    )


def _editorial_document(
    site: str,
    origins: dict[str, str],
    catalog: dict[str, Any],
    title: str,
    main: str,
    options: dict[str, Any],
) -> str:
    retailer = catalog.get("retailer") if isinstance(catalog.get("retailer"), dict) else {}
    name = _text(retailer.get("name"), site.title())
    extra = (
        f'<li><a href="{_href(origins, site, "/")}">Home</a></li>'
        if options["nav_expanded"]
        else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{_esc(title)}</title>{_style("editorial-boutique")}</head><body class="editorial-boutique">'
        '<a class="skip-link" href="#main-content">Skip to content</a>'
        f'<header class="boutique-header"><h1><a href="{_href(origins, site, "/")}">{_esc(name)}</a></h1>'
        '<nav aria-label="Primary navigation"><ul>'
        f'<li><a href="{_href(origins, site, "/search")}">Collection</a></li>'
        f'<li><a href="{_href(origins, site, "/policy")}">Shipping</a></li>'
        f'<li><a href="{_href(origins, site, "/cart")}">{cart_label(catalog, "Bag")}</a></li>{extra}</ul></nav>{_storefront_navigation(catalog)}</header>'
        f'{main}{_footer(catalog, "editorial-boutique")}</body></html>'
    )


def _technical_document(
    site: str,
    origins: dict[str, str],
    catalog: dict[str, Any],
    title: str,
    main: str,
    options: dict[str, Any],
) -> str:
    retailer = catalog.get("retailer") if isinstance(catalog.get("retailer"), dict) else {}
    name = _text(retailer.get("name"), site.title())
    products = _products(catalog)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{_esc(title)}</title>{_style("technical-catalog")}</head><body class="technical-catalog">'
        '<a class="skip-link" href="#main-content">Skip to content</a><div class="technical-frame">'
        '<aside class="technical-sidebar">'
        f'<header><h1><a href="{_href(origins, site, "/")}">{_esc(name)}</a></h1><p>Technical product catalog</p></header>'
        + _technical_nav(site, origins, products, options["nav_expanded"] and not catalog.get('storefront_links'),catalog)
        + _storefront_navigation(catalog)
        + f'</aside>{main}{_footer(catalog, "technical-catalog")}</div></body></html>'
    )


def _design_document(
    site: str,
    origins: dict[str, str],
    catalog: dict[str, Any],
    design: str,
    title: str,
    main: str,
    options: dict[str, Any],
) -> str:
    if design == "dense-storefront":
        from .dense_storefront import document
        return document(site, origins, catalog, title, main, options)
    if design == "department-market":
        return _department_document(site, origins, catalog, title, main, options)
    if design == "editorial-boutique":
        return _editorial_document(site, origins, catalog, title, main, options)
    return _technical_document(site, origins, catalog, title, main, options)


def _not_found(site: str, origins: dict[str, str], catalog: dict[str, Any], design: str, options: dict[str, Any]) -> str:
    main = '<main id="main-content"><h2>Product not found</h2><p>The requested catalog entry is not available.</p></main>'
    return _design_document(site, origins, catalog, design, "Product not found", main, options)


def _home(site: str, origins: dict[str, str], catalog: dict[str, Any], design: str, options: dict[str, Any]) -> str:
    products = _products(catalog)
    retailer = catalog.get("retailer") if isinstance(catalog.get("retailer"), dict) else {}
    name = _text(retailer.get("name"), site.title())
    if design == "department-market":
        links = "".join(
            f'<li><a href="{_href(origins, site, _product_path(row.get("product_id")))}">{_esc(_title(row, options["title_style"]))}</a></li>'
            for row in products[:4]
        )
        main = (
            '<main id="main-content"><h2>Shop the complete department catalog</h2>'
            + _search_form(site, origins, products, {}, label="Search products and attributes")
            + f'<section><h2>Current catalog highlights</h2><ul>{links}</ul></section></main>'
        )
    elif design == "editorial-boutique":
        main = (
            '<main id="main-content" class="boutique-story"><article><p>Seasonal collection</p>'
            f'<h2>The catalog at {_esc(name)}</h2><p>Browse a considered selection organized by product story and catalog details.</p>'
            f'<p><a href="{_href(origins, site, "/search")}">Read the collection</a></p></article></main>'
        )
    else:
        main = (
            '<main id="main-content" class="technical-main"><h2>Specification index</h2>'
            + _search_form(site, origins, products, {}, label="Filter by name or specification")
            + '<p>Use the catalog table to compare listed attributes, stock status, and current item price.</p></main>'
        )
    return _design_document(site, origins, catalog, design, f"{name} catalog", main, options)


def _matching(products: list[dict[str, Any]], query: dict[str, str]) -> list[dict[str, Any]]:
    return _legacy()._search_products(products, query)


def _pagination(site: str, origins: dict[str, str], query: dict[str, str], count: int) -> str:
    return _legacy()._pagination(origins, site, query, count, _PAGE_SIZE)


def _search(site: str, origins: dict[str, str], catalog: dict[str, Any], query: dict[str, str], design: str, options: dict[str, Any]) -> str:
    products = _products(catalog)
    matches = _matching(products, query)
    page = min(_legacy()._page(query), max(1, ceil(len(matches) / _PAGE_SIZE)))
    shown = matches[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]
    offers = _offers(catalog)
    if design == "department-market":
        rows = []
        for product in shown:
            offer = offers.get(_text(product.get("product_id")), {})
            rows.append(
                '<article class="market-result">'
                + _figure(product, 1)
                + f'<div><p>{_esc(_label(product.get("category")))}</p><h3><a href="{_href(origins, site, _product_path(product.get("product_id")))}">{_esc(_title(product, options["title_style"]))}</a></h3></div>'
                + f'<p class="price">{_esc(_legacy()._minor(offer.get("price_minor")))}</p></article>'
            )
        result = '<div class="result-list">' + "".join(rows) + "</div>"
        if options["result_structure"]=="table":
            result=variants.result_table(site,origins,shown,offers,options)
        label = "Search the market"
        heading = "Department results"
    elif design == "editorial-boutique":
        entries = "".join(
            '<li><article>'
            f'<p>{_esc(_label(product.get("category")))}</p><h3><a href="{_href(origins, site, _product_path(product.get("product_id")))}">{_esc(_title(product, options["title_style"]))}</a></h3>'
            f'<p>{_esc(_legacy()._minor(offers.get(_text(product.get("product_id")), {}).get("price_minor")))}</p>'
            f'<p><a href="{_href(origins, site, _product_path(product.get("product_id")) + "/details")}">Read full catalog details</a></p>'
            "</article></li>"
            for product in shown
        )
        result = f'<ol class="editorial-results">{entries}</ol>'
        label = "Find in the collection"
        heading = "The collection, in order"
    else:
        rows = []
        for product in shown:
            offer = offers.get(_text(product.get("product_id")), {})
            specs = "; ".join(f"{_label(key)}: {value}" for key, value in _attrs(product)) or "Not specified"
            stock = offer.get("stock_quantity")
            status = "In stock" if isinstance(stock, int) and stock > 0 else "Out of stock"
            rows.append(
                f'<tr><th scope="row"><a href="{_href(origins, site, _product_path(product.get("product_id")))}">{_esc(_title(product, options["title_style"]))}</a></th>'
                f'<td>{_esc(_label(product.get("category")))}</td><td>{_esc(specs)}</td><td class="status">{status} ({_esc(stock)})</td>'
                f'<td>{_esc(_legacy()._minor(offer.get("price_minor")))}</td></tr>'
            )
        result = (
            '<table class="result-table"><caption>Products matching the current catalog filters</caption>'
            '<thead><tr><th>Product</th><th>Category</th><th>Attributes</th><th>Status</th><th>Price</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
        )
        label = "Filter specifications"
        heading = "Technical results"
    if not shown:
        result = '<p class="notice">No products matched this search.</p>'
    main_class = "technical-main" if design == "technical-catalog" else ("boutique-results" if design == "editorial-boutique" else "department-results")
    main = (
        f'<main id="main-content" class="{main_class}"><h2>{heading}</h2>'
        + _search_form(site, origins, products, query, label=label)
        + f'<p>{len(matches)} matching product(s).</p>{result}'
        + _pagination(site, origins, query, len(matches))
        + "</main>"
    )
    return _design_document(site, origins, catalog, design, heading, main, options)


def _recommendations(site: str, origins: dict[str, str], catalog: dict[str, Any], product: dict[str, Any]) -> str:
    peers = [
        row for row in _products(catalog)
        if row.get("category") == product.get("category")
        and row.get("product_id") != product.get("product_id")
    ][:3]
    items = "".join(
        f'<li><a href="{_href(origins, site, _product_path(row.get("product_id")))}">{_esc(row.get("name"))}</a></li>'
        for row in peers
    )
    return f'<section aria-labelledby="more-category"><h2 id="more-category">More in {_esc(_label(product.get("category")))}</h2><ul>{items}</ul></section>'


def _cart_notice(site: str, origins: dict[str, str], catalog: dict[str, Any], context: dict[str, Any], product_id: str) -> str:
    cart = context.get("cart") if isinstance(context.get("cart"), dict) else None
    if catalog.get("cart_navigation") in ("inline","menu"):
        return ""
    active = next(
        (row for row in catalog.get("offers", []) if isinstance(row, dict) and row.get("offer_id") == (cart or {}).get("offer_id")),
        None,
    )
    if active is None or _text(active.get("product_id")) == product_id:
        return ""
    return (
        '<aside class="notice"><strong>This store accepts one product line per basket.</strong> '
        f'<a href="{_href(origins, site, "/cart")}">Review your cart and remove the current line before adding another product.</a></aside>'
    )


def _product_page(site: str, origins: dict[str, str], catalog: dict[str, Any], context: dict[str, Any], product_id: str, design: str, options: dict[str, Any]) -> str:
    product = _product(catalog, product_id)
    offer = _offers(catalog).get(product_id)
    if product is None or offer is None:
        return _not_found(site, origins, catalog, design, options)
    selection = context.get('product_selection')
    if selection:
        if selection['product_id']:
            product_id = selection['product_id']
            product = _product(catalog, product_id)
            offer = _offers(catalog).get(product_id)
            if product is None or offer is None:
                return _not_found(site, origins, catalog, design, options)
        else:
            # Do not display a previous SKU's facts, price or buy controls for an
            # unresolved combination. Keep only the public model identity.
            product = {'product_id': selection['group']['group_id'], 'name': selection['group']['name'],
                       'category': selection['group']['family'], 'attributes': {}, 'traits': []}
            offer = {'price_minor': None, 'stock_quantity': 0}
    title = _title(product, options["title_style"])
    figures = "".join(_figure(product, view) for view in range(1, options["image_count"] + 1))
    notice = _cart_notice(site, origins, catalog, context, product_id)
    if design == "department-market":
        fact_content=variants.facts(product) if options["fact_structure"]=="definitions" else _fact_table(product)
        if options["details_presentation"] == "disclosure":
            facts = f'<details><summary>Product facts</summary>{fact_content}</details>'
        else:
            facts = fact_content
        description = (
            f'<section id="description" aria-labelledby="description-heading"><h2 id="description-heading">Catalog description</h2>'
            f'<p>{_esc(product.get("name"))} is listed in {_esc(_label(product.get("category")))}.</p>{facts}</section>'
        )
        if options["product_structure"]=="details-first":
            main=variants.product_page(site,origins,catalog,context,product,offer,options,figures,description,notice)
            return _design_document(site,origins,catalog,design,title,main,options)
        main = (
            f'<main id="main-content" class="product-market">{notice}<section><p>{_esc(_label(product.get("category")))}</p><h2>{_esc(title)}</h2>'
            f'<div class="product-gallery">{figures}</div></section><aside class="purchase-aside"><h2>Current offer</h2><p class="price">{_esc(_legacy()._minor(offer.get("price_minor")))}</p>'
            f'<p>Offer ID: {_esc(offer.get("offer_id"))}</p><p>Dispatch: {_esc(offer.get("dispatch_days"))} day(s).</p>'
            f'{_purchase_form(site, origins, offer, grouped=False,catalog=catalog,context=context,delivery_control=options.get("delivery_control","select"))}{_quote_link(site, origins, offer)}</aside>'
            f'<div class="market-bottom">{_recommendations(site, origins, catalog, product)}{description}</div></main>'
        )
    elif design == "editorial-boutique":
        details_href = _href(origins, site, _product_path(product_id) + "/details")
        details_link = f'<p><a href="{details_href}">Read full product attributes</a></p>' if not selection or selection["product_id"] else ""
        main = (
            f'<main id="main-content" class="boutique-product">{notice}<article><p>{_esc(_label(product.get("category")))}</p><h2>{_esc(title)}</h2>'
            f'<p>{_esc(product.get("name"))} is part of the {_esc(_label(product.get("category")))} collection.</p>'
            f'{details_link}<div class="editorial-figures">{figures}</div>'
            f'<section class="inline-purchase" aria-labelledby="offer-heading"><h3 id="offer-heading">Current offer</h3><p class="price">{_esc(_legacy()._minor(offer.get("price_minor")))}</p><p>Offer ID: {_esc(offer.get("offer_id"))}</p>'
            f'{_purchase_form(site, origins, offer, grouped=False,catalog=catalog,context=context,delivery_control=options.get("delivery_control","select"))}{_quote_link(site, origins, offer)}</section></article></main>'
        )
    else:
        specs = f'<details id="specifications"><summary>Specifications</summary>{_fact_table(product)}</details>'
        main = (
            f'<main id="main-content" class="technical-main technical-product">{notice}<nav class="section-nav" aria-label="Product sections"><ul>'
            '<li><a href="#overview">Overview</a></li><li><a href="#specifications">Specifications</a></li><li><a href="#ordering">Ordering</a></li></ul></nav>'
            f'<section id="overview"><p>{_esc(_label(product.get("category")))}</p><h2>{_esc(title)}</h2>{figures}<p>Offer ID: {_esc(offer.get("offer_id"))}</p></section>{specs}'
            f'<section id="ordering"><h2>Ordering</h2><p class="price">{_esc(_legacy()._minor(offer.get("price_minor")))}</p><p>Dispatch: {_esc(offer.get("dispatch_days"))} day(s).</p>'
            f'{_purchase_form(site, origins, offer, grouped=True,catalog=catalog,context=context)}{_quote_link(site, origins, offer)}</section></main>'
        )
    return _design_document(site, origins, catalog, design, title, main, options)


def _details_page(site: str, origins: dict[str, str], catalog: dict[str, Any], product_id: str, design: str, options: dict[str, Any]) -> str:
    product = _product(catalog, product_id)
    if product is None:
        return _not_found(site, origins, catalog, design, options)
    title = f"Details for {_text(product.get('name'), product_id)}"
    main_class = "technical-main" if design == "technical-catalog" else "boutique-product"
    main = (
        f'<main id="main-content" class="{main_class}"><article><p>{_esc(_label(product.get("category")))}</p><h2>{_esc(title)}</h2>'
        f'{_fact_table(product, caption="Full catalog attributes")}<p><a href="{_href(origins, site, _product_path(product_id))}">Back to product offer</a></p></article></main>'
    )
    return _design_document(site, origins, catalog, design, title, main, options)


def render_retailer(
    site: str,
    path: str,
    query: dict[str, str],
    context: dict[str, Any],
    origins: dict[str, str],
    design: str,
    options: dict[str, Any] | None = None,
) -> str | None:
    """Render a retailer catalog page, or return ``None`` for legacy-owned routes."""

    resolved = _options(design, options)
    if not isinstance(context, dict):
        context = {}
    catalog = context.get("catalog") if isinstance(context.get("catalog"), dict) else {}
    query = query if isinstance(query, dict) else {}
    if design == "dense-storefront":
        from .dense_storefront import render
        return render(site, path, query, context, origins, resolved)
    parts = [part for part in _text(path).split("/") if part]
    if not parts:
        return _home(site, origins, catalog, design, resolved)
    if parts == ["search"]:
        return _search(site, origins, catalog, query, design, resolved)
    if len(parts) == 2 and parts[0] == "products":
        from .product_controls import page_selection
        submitted = {k[7:]: v for k,v in query.items() if k.startswith('option_')}
        state = page_selection(catalog, parts[1], submitted if submitted else None)
        if state:
            context = {**context, 'product_selection': state}
        return _product_page(site, origins, catalog, context, parts[1], design, resolved)
    if len(parts) == 3 and parts[0] == "products" and parts[2] == "details":
        return _details_page(site, origins, catalog, parts[1], design, resolved)
    return None


__all__ = ["DESIGNS", "render_retailer"]
