"""Place transactional content in the existing storefront's main-content slot.

Only the content fragment is styled here. Brand, navigation, background and footer
are rendered by the same document builder as the store's product pages.
"""
from . import retailer_designs, renderers

CONTENT_STYLE='''<style>
.commerce-content{min-width:0}.commerce-content input[type=text],.commerce-content input[type=email],.commerce-content input[type=tel]{display:block;width:100%;max-width:34rem;margin:.3rem 0 1rem}.commerce-content details{border:1px solid #aaa;padding:1rem;margin:1rem 0}.commerce-content summary{cursor:pointer;font-weight:700}.commerce-content fieldset{margin:1rem 0}.commerce-content fieldset label{display:block}.commerce-content .review{display:grid;grid-template-columns:max-content 1fr;gap:.4rem 1rem}.commerce-content dd{margin:0}.commerce-content dt{font-weight:700}.commerce-content .summary-card{border:1px solid #aaa;padding:1rem;margin:1rem 0}.commerce-content .actions{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin-top:1rem}.commerce-content .error-summary,.commerce-content .field-error,.commerce-content [role=alert]{color:#991b1b}.commerce-content .basket-table{border-collapse:collapse;width:100%}.commerce-content .basket-table th,.commerce-content .basket-table td{border-bottom:1px solid #aaa;padding:.6rem;text-align:left}.commerce-content input[type=number]{width:5rem}.commerce-content .basket-columns,.commerce-content .express-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(14rem,32%);gap:1rem}.commerce-content .progress ol{display:flex;gap:1.5rem;flex-wrap:wrap}.commerce-content .continue{display:inline-block;padding:.7rem;border:1px solid currentColor}@media(max-width:800px){.commerce-content .basket-columns,.commerce-content .express-grid{display:block}}
</style>'''


def render_in_storefront(site, origins, catalog, design, options, title, main):
    if not main.startswith('<main class="') or main.count('<main ')!=1:
        raise ValueError('Checkout content must contain one main element')
    layout_class={'department-market':'','editorial-boutique':'boutique-product ','technical-catalog':'technical-main '}.get(design,'')
    main=main.replace('<main class="',f'<main id="main-content" class="commerce-content {layout_class}',1)
    if design in retailer_designs.DESIGNS:
        document=retailer_designs._design_document(site,origins,catalog,design,title,main,retailer_designs._options(design,options))
    elif design=='legacy-catalog':
        document=renderers._document(site,origins,catalog,title,main,'Commerce')
    else:
        raise ValueError('Unsupported storefront shell')
    return document.replace('</head>',CONTENT_STYLE+'</head>',1)
