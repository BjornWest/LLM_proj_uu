"""Served-asset projection for the scenario retailer, with an exact inverse.

The composed `shop.js` and `quote.js` of the target retailer are patched at
unique seams and the page helper is added. Nothing in `website_drafts` or
`website_world` is edited, and other retailers keep the native assets.
"""
from hashlib import sha256
from pathlib import Path
import re

VERSION = 'website-commerce-scenario-assets-v1'
HERE = Path(__file__).parent
SCRIPT, STYLE = 'commerce-scenario.js', 'commerce-scenario.css'
PIECE_NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,48}\.(js|css)')
IMPORT = '\nimport {commerceScenario} from "./commerce-scenario.js";\n'
STATE = "let feedback = '', previousRoute = '', lastCheckoutStep = null;"
SAVE = 'function save() {if(!applyingStoredState)localStorage.setItem(stateKey,JSON.stringify(state));'
CHOSEN = 'if(worldBinding.selectDelivery(state,input.value))revise("Delivery service selected. Totals recalculated.");return;}'
REVIEW = '<section aria-label="Checkout review"><h2>Review before payment</h2>'
TOTALS_START = '<dl><dt>Products</dt><dd>${money(result.subtotal)}</dd>'
TOTALS_END = '<dd><strong>${money(result.total)}</strong></dd></dl>'
SHIPPING = "<p>Delivery charge: ${money(s.fee)}${s.qualified?' · Free-delivery minimum reached':''}</p>"
COUPON = 'function couponForm() {if(worldBinding)return'
ORDER = 'if(worldBinding?.simulatedOrders){await completeSimulatedOrder('
RENDERED = '  save();\n  if(focusId)document.querySelector('
REFRESHED = '  if(worldBinding)worldBinding.decorate(app);\n  scheduleNativeQuote();\n}'
START = "\nif(worldBinding&&validateAddress(state.address).length)try{await worldBinding.refresh(state.address);}"
HOOKS = {
    # Create the helper before any listener, save or render runs.
    STATE: 'const __scenario=commerceScenario({site,conf,state:()=>state,route:()=>route(),'
           'render:()=>render(),revise:message=>revise(message),'
           'notify:message=>{feedback=message;render();},'
           'quote:()=>quote(state.cart,state,conf,state.revision),byVariant,'
           'money:value=>money(value),e:value=>e(value)});\n' + STATE,
    # The one place the shop saves state reports basket, delivery and location.
    SAVE: SAVE + '__scenario.sync();',
    CHOSEN: 'if(worldBinding.selectDelivery(state,input.value)){__scenario.chose(state);'
            'revise("Delivery service selected. Totals recalculated.");}return;}',
    REVIEW: REVIEW + '${__scenario.checkoutControls()}',
    # Family decorators can replace native shipment charges from a host quote.
    SHIPPING: SHIPPING.replace('<p>', '<p data-scenario-shipping-charge>'),
    # Every total of this retailer comes from the session quote.
    TOTALS_START: '${__scenario.totals(result)??`' + TOTALS_START,
    TOTALS_END: TOTALS_END + '`}',
    COUPON: 'function couponForm() {if(__scenario.promotionField)return __scenario.promotionForm();if(worldBinding)return',
    # The displayed grand total is armed before the unchanged native order request.
    ORDER: 'if(worldBinding?.simulatedOrders){if(!await __scenario.armOrder())return;await completeSimulatedOrder(',
    RENDERED: '  __scenario.decorate(app);\n' + RENDERED,
    REFRESHED: '  if(worldBinding)worldBinding.decorate(app);\n  __scenario.decorate(app);\n  scheduleNativeQuote();\n}',
    START: '\nawait __scenario.ready;' + START,
}
QUOTE_SEAM = 'shipping:selected.shippingMinor/100,total:selected.totalMinor/100,quoteId:value.quoteId,'
QUOTE_HOOKS = {QUOTE_SEAM: QUOTE_SEAM + 'optionId:selected.id,'}


def _apply(text, hooks, name):
    for old, new in hooks.items():
        if text.count(old) != 1:
            raise ValueError(f'Scenario {name} seam is absent or ambiguous: {old}')
        text = text.replace(old, new)
    return text


def _restore(text, hooks, name):
    for old, new in reversed(list(hooks.items())):
        if text.count(new) != 1:
            raise ValueError(f'Scenario {name} inverse seam is not unique: {old}')
        text = text.replace(new, old)
    return text


def project_assets(assets, *, expected_source_sha256, expected_quote_sha256, pieces=None):
    """Return the target retailer's assets and the evidence that inverts them.

    `pieces` maps a served name to the bytes of a family's own page module or
    stylesheet; the helper loads them and calls each module's `attach(api)`.
    """
    source, quote = assets.get('shop.js'), assets.get('quote.js')
    if type(source) is not bytes or sha256(source).hexdigest() != expected_source_sha256:
        raise ValueError('Scenario projection requires the exact composed shop renderer')
    if type(quote) is not bytes or sha256(quote).hexdigest() != expected_quote_sha256:
        raise ValueError('Scenario projection requires the exact composed quote binding')
    pieces = dict(pieces or {})
    for name, body in pieces.items():
        if (type(name) is not str or not PIECE_NAME.fullmatch(name) or type(body) is not bytes
                or name in assets or name in (SCRIPT, STYLE)):
            raise ValueError('Scenario page pieces need new lowercase .js/.css names and bytes')
    text = source.decode()
    if SCRIPT in assets or STYLE in assets or '__scenario' in text:
        raise ValueError('Scenario renderer has already been projected')
    changed = (_apply(text, HOOKS, 'renderer') + IMPORT).encode()
    changed_quote = _apply(quote.decode(), QUOTE_HOOKS, 'quote').encode()
    helper, style = (HERE/'scenario.js').read_bytes(), (HERE/'scenario.css').read_bytes()
    served = {'shop.js': changed, 'quote.js': changed_quote, SCRIPT: helper, STYLE: style, **pieces}
    evidence = {'schema': VERSION, 'before_sha256': expected_source_sha256,
                'after_sha256': sha256(changed).hexdigest(),
                'quote_before_sha256': expected_quote_sha256,
                'quote_after_sha256': sha256(changed_quote).hexdigest(),
                'served_asset_sha256': {name: sha256(body).hexdigest() for name, body in sorted(served.items())},
                'pieces': sorted(pieces),
                'qualification': 'Asset projection only; the session journal and browser acceptance are separate'}
    if restore_source(changed, evidence) != source or restore_quote(changed_quote, evidence) != quote:
        raise ValueError('Scenario projection has no exact inverse')
    return {**assets, **served}, evidence


def restore_source(source, evidence):
    """Recover the native composed renderer from the projected one."""
    if evidence.get('schema') != VERSION or sha256(source).hexdigest() != evidence['after_sha256']:
        raise ValueError('Scenario projection differs from pinned renderer')
    text = source.decode()
    if not text.endswith(IMPORT):
        raise ValueError('Scenario projection import changed')
    original = _restore(text[:-len(IMPORT)], HOOKS, 'renderer').encode()
    if sha256(original).hexdigest() != evidence['before_sha256']:
        raise ValueError('Scenario inverse differs from original renderer')
    return original


def restore_quote(source, evidence):
    """Recover the native composed quote binding from the projected one."""
    if evidence.get('schema') != VERSION or sha256(source).hexdigest() != evidence['quote_after_sha256']:
        raise ValueError('Scenario quote projection differs from pinned binding')
    original = _restore(source.decode(), QUOTE_HOOKS, 'quote').encode()
    if sha256(original).hexdigest() != evidence['quote_before_sha256']:
        raise ValueError('Scenario quote inverse differs from native binding')
    return original
