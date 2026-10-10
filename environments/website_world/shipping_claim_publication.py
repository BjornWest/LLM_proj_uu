"""Additive shipping-audit recipes; preserve native selection and complete menus."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, catalog_shipping_claim_generation as native
from . import shipping_claim_execution  # retain the complete execution source closure

VERSION = 'website-shipping-claim-publication-v1'


def compile_request(request):
    config = native.compile_request(request)
    sources = {str(Path(m.__file__).resolve().relative_to(feature.unified.ROOT)):
        sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (native, native.native)}
    return {**config, 'publication_inventory': {
        'kind': native.native.KIND, 'quantity_basis': 'retail_sale_units',
        'policy_basis': 'retailer-wide threshold plus complete admitted basket fees',
        'source_hashes': sources}, 'inventory': SimpleNamespace(source_hashes=sources)}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    result['shipping_claim_inventory'] = deepcopy(config['publication_inventory'])
    result['resolved_configuration']['shipping_claim_selection'] = deepcopy(config['selection'])
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Freeze a new packet, retaining null tasks for naturally missing identities."""
    sampled = []
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result,
            'feature_offer_task': result['shipping_claim_task'] or {'kind': native.native.KIND},
            'feature_offer_reference': {**(result['shipping_claim_reference'] or {}),
                'status': result['shipping_claim_binding']['status']},
            'feature_field_inventory': result['shipping_claim_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=compile_request, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading=answer_grading, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new, key in (
            ('feature-offer-task.private.json', 'shipping-claim-task.private.json', 'shipping_claim_task'),
            ('feature-offer-reference.private.json', 'shipping-claim-reference.private.json', 'shipping_claim_reference'),
            ('feature-field-inventory.private.json', 'shipping-claim-inventory.private.json', 'shipping_claim_inventory')):
        if (output/new).exists(): raise FileExistsError(output/new)
        (output/old).rename(output/new)
        (output/new).write_text(json.dumps(sampled[0][key], indent=2, ensure_ascii=False)+'\n')
        manifest['files'].pop(old)
        manifest['files'][new] = sha256((output/new).read_bytes()).hexdigest()
    name = 'shipping-claim-binding.private.json'
    feature.unified.shared.save(output/name, sampled[0]['shipping_claim_binding'])
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['shipping_claim_binding_status'] = sampled[0]['shipping_claim_binding']['status']
    manifest['automatic_grader_supported'] = sampled[0]['shipping_claim_task'] is not None
    manifest['evidence_coverage'] = 'Native audit truth does not establish public disclosure, visits or cart effects'
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
