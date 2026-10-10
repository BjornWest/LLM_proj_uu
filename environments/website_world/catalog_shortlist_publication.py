"""Additive model-shortlist recipes over the complete sampled retailer population."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, catalog_shortlist_generation as native
from . import catalog_shortlist_execution  # retain the complete execution source closure

VERSION = 'website-catalog-shortlist-publication-v1'


def compile_request(request):
    proxy = deepcopy(request)
    episode = proxy.get('episode', {})
    if type(episode) is not dict:
        raise ValueError('Episode options must be an object')
    start = episode.get('start', {})
    comparison_home = type(start) is dict and start.get('kind') == 'comparison_home'
    if comparison_home:
        site_id = request.get('task', {}).get('comparison_site_id')
        if site_id is None or start != {'kind': 'comparison_home', 'comparison_site_id': site_id}:
            raise ValueError('Comparison-home start must match the shortlist scope')
        proxy['episode']['start'] = {'kind': 'directory'}
    config = native.compile_request(proxy)
    config['requested_start'] = deepcopy(start) if comparison_home else None
    return config


def generate(request, *, world_factory=None):
    config = compile_request(request)
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    if config['requested_start'] is not None:
        result['episode']['start'] = deepcopy(config['requested_start'])
        result['resolved_configuration']['episode']['start'] = deepcopy(config['requested_start'])
    result['shortlist_field_inventory'] = {k: deepcopy(getattr(config['inventory'], k))
        for k in ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}
    result['shortlist_binding'] = {'status': 'bound', 'world_repaired': False}
    result['resolved_configuration']['shortlist_selection'] = deepcopy(config['selection'])
    scope = result['catalog_shortlist_task']['feature_task'].get('comparison_scope')
    if scope is not None:
        result['episode']['shopping_scope'] = 'Products and retailer listings shown on ' + scope['site_name']
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Freeze new output without truncating routes, inventing rows or repairing no-match."""
    sampled = []
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result, 'feature_offer_task': result['catalog_shortlist_task'],
            'feature_offer_reference': result['catalog_shortlist_reference'],
            'feature_field_inventory': result['shortlist_field_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=compile_request, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading=answer_grading, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new, key in (
            ('feature-offer-task.private.json', 'catalog-shortlist-task.private.json', 'catalog_shortlist_task'),
            ('feature-offer-reference.private.json', 'catalog-shortlist-reference.private.json', 'catalog_shortlist_reference'),
            ('feature-field-inventory.private.json', 'shortlist-field-inventory.private.json', 'shortlist_field_inventory')):
        if (output/new).exists(): raise FileExistsError(output/new)
        (output/old).rename(output/new)
        (output/new).write_text(json.dumps(sampled[0][key], indent=2, ensure_ascii=False)+'\n')
        manifest['files'].pop(old)
        manifest['files'][new] = sha256((output/new).read_bytes()).hexdigest()
    name = 'catalog-shortlist-binding.private.json'
    feature.unified.shared.save(output/name, sampled[0]['shortlist_binding'])
    manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['shortlist_binding_status'] = sampled[0]['shortlist_binding']['status']
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
