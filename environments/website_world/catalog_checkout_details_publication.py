"""Additive checkout-detail recipes; native memories and sampled pages retained."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import catalog_basket_publication as basket
from . import catalog_cart_publication as cart
from . import catalog_checkout_details_generation as native
from . import catalog_checkout_details_execution  # include the capture source closure

VERSION = 'website-catalog-checkout-details-publication-v1'


def compile_request(request):
    return _bind(basket.compile_request, native=native)(request)


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(
        request, world_factory=world_factory)
    result['checkout_details_field_inventory'] = deepcopy(config['publication_inventory'])
    return result


def prepare(request, output, *, validation='off', answer_grading=None,
            lazy_publication=True):
    """Freeze a new state-task container; never use natural-answer extraction.

    The cart container identity permits unchanged raw capture/authority tooling.
    Its explicit checkout identity and task files distinguish the new semantics.
    No existing cart recipe's release guard is changed.
    """
    if answer_grading not in (None, {'mode': 'off'}):
        raise ValueError('Checkout details require actual storage, not answer extraction')
    sampled = []

    def cart_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result, 'catalog_cart_task': result['checkout_details_task'],
                'catalog_cart_reference': result['checkout_details_reference'],
                'catalog_cart_binding': result['checkout_details_binding'],
                'cart_field_inventory': result['checkout_details_field_inventory']}

    freeze = _bind(cart.prepare, __file__=__file__, require_release=lambda: None,
                   compile_request=compile_request, generate=cart_shape)
    manifest = freeze(request, output, validation=validation,
                      answer_grading={'mode': 'off'}, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    result = sampled[0]
    for name, key in (
            ('checkout-details-task.private.json', 'checkout_details_task'),
            ('checkout-details-reference.private.json', 'checkout_details_reference'),
            ('checkout-details-binding.private.json', 'checkout_details_binding'),
            ('original-cart-task.private.json', 'catalog_cart_task'),
            ('original-cart-reference.private.json', 'catalog_cart_reference')):
        cart.feature.unified.shared.save(output/name, result[key])
        manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest.update(checkout_details_recipe=VERSION,
                    task_kind=result['checkout_details_task']['kind'],
                    automatic_grader_supported=False,
                    state_grader='actual_capture_after_policy_close',
                    effect_authority='exact_independent_source_union_acceptance_required')
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
