"""Exact, additive navigation projection over already composed copied assets."""
from hashlib import sha256
import json
from pathlib import Path

VERSION = 'website-explicit-url-selection-priority-v1'
HELPER_SHA256 = '318ae458a59eb0305c675bd690b619d22ab3b9d901c5b8124f607c6b68f7777d'
ANCHOR = '  const {variant:v}=resolveProduct(id,selection); state.selection[id]={...v.selection}; save();'
REPLACEMENT = '  const {variant:v}=resolveNavigation(p,params,state.selection[id]||{},conf.url,resolveProduct); state.selection[id]={...v.selection}; save();'
IMPORT = '\nimport {resolveNavigation} from "./resolve-navigation.js";\n'


def project_assets(assets, *, expected_source_sha256):
    """Retain basket/review extensions and every other asset byte exactly."""
    source = assets.get('shop.js')
    if type(source) is not bytes or sha256(source).hexdigest() != expected_source_sha256:
        raise ValueError('Complete composed renderer differs from its source pin')
    text = source.decode()
    if text.count(ANCHOR) != 1 or 'resolveNavigation' in text or 'resolve-navigation.js' in assets:
        raise ValueError('Copied navigation seam is absent, ambiguous or already changed')
    helper = Path(__file__).with_name('resolve_navigation.js').read_bytes()
    if sha256(helper).hexdigest() != HELPER_SHA256:
        raise ValueError('Recipient-navigation helper differs from accepted source candidate')
    changed = (text.replace(ANCHOR, REPLACEMENT) + IMPORT).encode()
    if restore_source(changed) != source:
        raise ValueError('Navigation projection has no complete byte-exact inverse')
    result = {**assets, 'shop.js': changed, 'resolve-navigation.js': helper}
    return result, {'schema': VERSION, 'before_source_sha256': expected_source_sha256,
                    'after_source_sha256': sha256(changed).hexdigest(),
                    'helper_source_sha256': HELPER_SHA256,
                    'changed_assets': ['shop.js', 'resolve-navigation.js'],
                    'exact_inverse': True, 'catalog_menus': {},
                    'scope': 'Valid jointly satisfiable explicit URL fields precede remembered/default selections; ordinary control resolution unchanged.'}


def restore_source(source):
    text = source.decode()
    if text.count(REPLACEMENT) != 1 or not text.endswith(IMPORT):
        raise ValueError('Copied navigation projection no longer matches its inverse')
    return text[:-len(IMPORT)].replace(REPLACEMENT, ANCHOR).encode()


def menu_binding(catalog):
    """Private native menu/URL binding; this is not browser certification."""
    payload = {'url_mode': catalog['configuration']['url'], 'products': [
        {'id': p['id'], 'options': p['options'], 'variants': [
            {'selection': v['selection'], 'skuId': v['skuId'], 'offerId': v['offerId']}
            for v in p['variants']]} for p in catalog['products']]}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return {'menu_sha256': sha256(raw).hexdigest(), 'url_mode': payload['url_mode'],
            'product_count': len(payload['products']),
            'variant_count': sum(len(p['variants']) for p in payload['products'])}
