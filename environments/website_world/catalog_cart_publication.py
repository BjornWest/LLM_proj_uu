"""Prospective cart-state recipe. Source preparation only; native released; capture/authority validation pending."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, catalog_basket_publication as basket
from . import catalog_cart_generation as native
from . import catalog_cart_execution  # prospective complete source closure

VERSION = 'website-catalog-cart-publication-v1'
RUNTIME_RELEASED = False


def require_release():
    if not RUNTIME_RELEASED:
        raise RuntimeError('Cart consumer is source-only: native/capture/effect acceptance pending')


def compile_request(request):
    # Reuse field/source enumeration, with the cart notation's native compiler.
    return _bind(basket.compile_request, native=native)(request)


def generate(request, *, world_factory=None):
    require_release()
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    result['cart_field_inventory'] = deepcopy(config['publication_inventory'])
    result['resolved_configuration']['cart_selection'] = deepcopy(config['selection'])
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Freeze native draft-state semantics, without a natural-answer formatter."""
    require_release()
    if answer_grading not in (None, {'mode': 'off'}):
        raise ValueError('Cart state grading does not use answer extraction')
    sampled = []
    def feature_config(request):
        config = compile_request(request)
        return {**config, 'inventory': SimpleNamespace(source_hashes=config['publication_source_sha256'])}
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result, 'feature_offer_task': result['catalog_cart_task'],
            'feature_offer_reference': {**result['catalog_cart_reference'],
                'status': result['catalog_cart_binding']['status']},
            'feature_field_inventory': result['cart_field_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=feature_config, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading={'mode': 'off'}, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new, key in (
            ('feature-offer-task.private.json', 'catalog-cart-task.private.json', 'catalog_cart_task'),
            ('feature-offer-reference.private.json', 'catalog-cart-reference.private.json', 'catalog_cart_reference'),
            ('feature-field-inventory.private.json', 'cart-field-inventory.private.json', 'cart_field_inventory')):
        if (output/new).exists(): raise FileExistsError(output/new)
        (output/old).rename(output/new)
        (output/new).write_text(json.dumps(sampled[0][key], indent=2, ensure_ascii=False)+'\n')
        manifest['files'].pop(old)
        manifest['files'][new] = sha256((output/new).read_bytes()).hexdigest()
    name = 'catalog-cart-binding.private.json'
    feature.unified.shared.save(output/name, sampled[0]['catalog_cart_binding'])
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['cart_binding_status'] = sampled[0]['catalog_cart_binding']['status']
    manifest['cart_capture_adoption'] = 'Actual before/after bytes and independent whole-run effect authority required'
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
