"""Additive statistics recipes over unchanged named comparison publications."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, catalog_statistics_generation as native
from . import catalog_statistics_execution  # retain the complete execution closure

VERSION = 'website-catalog-statistics-publication-v1'
compile_request = native.compile_request


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    result['statistics_field_inventory'] = {k: deepcopy(getattr(config['inventory'], k))
        for k in ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}
    result['statistics_binding'] = {'status': 'bound', 'world_repaired': False,
        'comparison_site_id': result['catalog_statistics_task']['comparison_site_id']}
    result['resolved_configuration']['statistics_selection'] = deepcopy(config['selection'])
    result['episode']['shopping_scope'] = 'Comparison catalog shown on ' + result['catalog_statistics_task']['comparison_site_name']
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Reuse the accepted new-output freeze; preserve natural empty populations."""
    sampled = []
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result, 'feature_offer_task': result['catalog_statistics_task'],
            'feature_offer_reference': {**result['catalog_statistics_reference'],
                'status': 'summary' if result['catalog_statistics_reference']['statistic_defined'] else 'undefined'},
            'feature_field_inventory': result['statistics_field_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=compile_request, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading=answer_grading, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new, key in (
            ('feature-offer-task.private.json', 'catalog-statistics-task.private.json', 'catalog_statistics_task'),
            ('feature-offer-reference.private.json', 'catalog-statistics-reference.private.json', 'catalog_statistics_reference'),
            ('feature-field-inventory.private.json', 'statistics-field-inventory.private.json', 'statistics_field_inventory')):
        if (output/new).exists(): raise FileExistsError(output/new)
        (output/old).rename(output/new)
        (output/new).write_text(json.dumps(sampled[0][key], indent=2, ensure_ascii=False)+'\n')
        manifest['files'].pop(old)
        manifest['files'][new] = sha256((output/new).read_bytes()).hexdigest()
    name = 'catalog-statistics-binding.private.json'
    feature.unified.shared.save(output/name, sampled[0]['statistics_binding'])
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['statistics_binding_status'] = sampled[0]['statistics_binding']['status']
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
