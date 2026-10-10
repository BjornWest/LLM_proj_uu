"""Additive hidden recipes using the accepted feature freeze, with a private reply contract."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from . import feature_offer_publication as feature, hidden_offer_generation as native
from . import hidden_offer_execution  # include the complete execution closure
from . import catalog_clarification

VERSION = 'website-hidden-offer-publication-v1'
compile_request = _bind(feature.compile_request, native=native)


def generate(request, *, world_factory=None):
    config = compile_request(request)  # validate hidden/visible predicates before any draw
    result = _bind(native.generate, compile_request=lambda _: config)(request, world_factory=world_factory)
    if config['requested_start'] is not None:
        result['resolved_configuration']['proxy_episode'] = deepcopy(result['resolved_configuration']['episode'])
        result['episode']['start'] = deepcopy(config['requested_start'])
        result['resolved_configuration']['episode']['start'] = deepcopy(config['requested_start'])
    task = result['hidden_offer_task']
    scope = task['selection_task'].get('comparison_scope')
    if scope:
        result['episode']['shopping_scope'] = 'Products and retailer listings shown on ' + scope['site_name']
    result['resolved_configuration']['hidden_offer_selection'] = deepcopy(config['spec'])
    result['hidden_field_inventory'] = {k: deepcopy(getattr(config['inventory'], k))
        for k in ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}
    result['hidden_reply_binding'] = {
        'schema': catalog_clarification.VERSION, 'task_id': task['task_id'],
        'audit_id': catalog_clarification.Responder(task).audit_id,
        'hidden_requirement': deepcopy(task['hidden_requirement'])}
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """Reuse the accepted new-output freeze; rename its fresh private task attachments.

    The feature generator's underlying task stays private implementation data.
    Only the native hidden message/memories are authoritative for the episode.
    No historical files or module globals are modified.
    """
    sampled = []
    def feature_shape(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return {**result, 'feature_offer_task': result['hidden_offer_task'],
            'feature_offer_reference': result['hidden_offer_reference'],
            'feature_field_inventory': result['hidden_field_inventory']}
    freeze = _bind(feature.prepare, __file__=__file__, VERSION=VERSION,
                   compile_request=compile_request, generate=feature_shape)
    manifest = freeze(request, output, validation=validation,
        answer_grading=answer_grading, lazy_publication=lazy_publication)
    output = Path(output).resolve()
    for old, new in (
            ('feature-offer-task.private.json', 'hidden-offer-task.private.json'),
            ('feature-offer-reference.private.json', 'hidden-offer-reference.private.json'),
            ('feature-field-inventory.private.json', 'hidden-field-inventory.private.json')):
        if (output/new).exists():
            raise FileExistsError(output/new)
        (output/old).rename(output/new)
        expected = manifest['files'].pop(old)
        actual = sha256((output/new).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError('Hidden attachment bytes changed during freeze: '+new)
        manifest['files'][new] = actual
    for name, key in (('hidden-offer-binding.private.json', 'hidden_offer_binding'),
                      ('hidden-reply-binding.private.json', 'hidden_reply_binding')):
        feature.unified.shared.save(output/name, sampled[0][key])
        manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    manifest['hidden_binding_status'] = sampled[0]['hidden_offer_binding']['status']
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
