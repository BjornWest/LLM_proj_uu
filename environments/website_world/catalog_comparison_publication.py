"""Additive comparison recipes over the unchanged sampled retailer population."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, catalog_comparison_generation as native
from . import catalog_comparison_execution  # retain the complete execution source closure

VERSION = 'website-catalog-comparison-publication-v1'


compile_request = native.compile_request

def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    result['comparison_field_inventory'] = {k: deepcopy(getattr(config['inventory'], k))
        for k in ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}
    result['comparison_binding'] = {'status': 'bound', 'world_repaired': False}
    result['resolved_configuration']['comparison_selection'] = deepcopy(config['selection'])
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Freeze native fields, measurement scopes and results without changing pages."""
    sampled = []
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result, 'feature_offer_task': result['catalog_comparison_task'],
            'feature_offer_reference': result['catalog_comparison_reference'],
            'feature_field_inventory': result['comparison_field_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=compile_request, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading=answer_grading, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new, key in (
            ('feature-offer-task.private.json', 'catalog-comparison-task.private.json', 'catalog_comparison_task'),
            ('feature-offer-reference.private.json', 'catalog-comparison-reference.private.json', 'catalog_comparison_reference'),
            ('feature-field-inventory.private.json', 'comparison-field-inventory.private.json', 'comparison_field_inventory')):
        if (output/new).exists(): raise FileExistsError(output/new)
        (output/old).rename(output/new)
        (output/new).write_text(json.dumps(sampled[0][key], indent=2, ensure_ascii=False)+'\n')
        manifest['files'].pop(old)
        manifest['files'][new] = sha256((output/new).read_bytes()).hexdigest()
    name = 'catalog-comparison-binding.private.json'
    feature.unified.shared.save(output/name, sampled[0]['comparison_binding'])
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['comparison_binding_status'] = sampled[0]['comparison_binding']['status']
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
