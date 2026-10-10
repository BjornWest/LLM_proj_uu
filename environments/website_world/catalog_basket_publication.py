"""Additive mixed-basket publication; preserve natural infeasibility and search limits."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, catalog_basket_generation as native
from . import catalog_basket_execution  # retain the complete execution source closure

VERSION = 'website-catalog-basket-publication-v1'


def compile_request(request):
    config = native.compile_request(request)
    records, sources = {}, {}
    for row in config['selection']['requirements']:
        concept = row['concept_id']
        fields = config['inventory'].fields(concept)
        records[concept] = {k: deepcopy(getattr(fields, k)) for k in
            ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}
        for path, value in fields.source_hashes.items():
            if path in sources and sources[path] != value:
                raise ValueError('Basket declaration source changed: ' + path)
            sources[path] = value
    config['publication_inventory'] = records
    config['publication_source_sha256'] = sources
    return config


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    result['basket_field_inventory'] = deepcopy(config['publication_inventory'])
    result['resolved_configuration']['basket_selection'] = deepcopy(config['selection'])
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Freeze new output only; no fallback, winner-selected reduction or repair."""
    sampled = []
    def feature_config(request):
        config = compile_request(request)
        return {**config, 'inventory': SimpleNamespace(source_hashes=config['publication_source_sha256'])}
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result, 'feature_offer_task': result['catalog_basket_task'],
            'feature_offer_reference': {**result['catalog_basket_reference'],
                'status': result['catalog_basket_reference']['result']['status']},
            'feature_field_inventory': result['basket_field_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=feature_config, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading=answer_grading, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new, key in (
            ('feature-offer-task.private.json', 'catalog-basket-task.private.json', 'catalog_basket_task'),
            ('feature-offer-reference.private.json', 'catalog-basket-reference.private.json', 'catalog_basket_reference'),
            ('feature-field-inventory.private.json', 'basket-field-inventory.private.json', 'basket_field_inventory')):
        if (output/new).exists(): raise FileExistsError(output/new)
        (output/old).rename(output/new)
        (output/new).write_text(json.dumps(sampled[0][key], indent=2, ensure_ascii=False)+'\n')
        manifest['files'].pop(old)
        manifest['files'][new] = sha256((output/new).read_bytes()).hexdigest()
    name = 'catalog-basket-binding.private.json'
    feature.unified.shared.save(output/name, sampled[0]['catalog_basket_binding'])
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['basket_binding_status'] = sampled[0]['catalog_basket_binding']['status']
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
