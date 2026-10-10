"""Explicit fresh cart recipes using the accepted native task/capture boundary.

The historical container identity is retained for the unchanged authority helper.
The additional cart_live_recipe identity opts into this caller; historical guards
and authority approvals remain unchanged.
"""
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import catalog_cart_publication as cart
from . import catalog_cart_live_execution  # retain the new execution source union

VERSION = 'website-catalog-cart-live-publication-v1'


def compile_request(request):
    return cart.compile_request(request)


def generate(request, *, world_factory=None):
    return _bind(cart.generate, require_release=lambda: None,
                 compile_request=compile_request)(request, world_factory=world_factory)


def prepare(request, output, *, validation='off', answer_grading=None,
            lazy_publication=True):
    """Freeze complete native inputs under a separate, explicit opt-in identity."""
    if answer_grading not in (None, {'mode': 'off'}):
        raise ValueError('Cart state grading does not use answer extraction')
    freeze = _bind(cart.prepare, __file__=__file__, require_release=lambda: None,
                   compile_request=compile_request, generate=generate)
    manifest = freeze(request, output, validation=validation,
                      answer_grading={'mode': 'off'}, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    # Both files were created by this invocation, never an existing recipe.
    config_path = output/'generation-config.private.json'
    config = json.loads(config_path.read_text())
    config['cart_live_recipe'] = VERSION
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False)+'\n')
    manifest['files'][config_path.name] = sha256(config_path.read_bytes()).hexdigest()
    manifest.update(cart_live_recipe=VERSION, automatic_grader_supported=False,
        state_grader='actual_capture_after_policy_close',
        effect_authority='exact_independent_source_union_acceptance_required')
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
