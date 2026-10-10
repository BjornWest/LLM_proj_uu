"""Frozen quote-offer recipes over the released native pre-sampling binder.

This additive caller does not change pages, native quote semantics or existing recipes.
Native matching and public fact disclosure remain separate acceptance boundaries.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from . import quote_offer_generation as native
from . import quote_offer_execution  # retain the complete execution source closure
from . import execution_generation, unified_generation as unified, generation_configs

VERSION = 'website-quote-offer-publication-v1'


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
            raise ValueError('Comparison-home start must match the task scope')
        proxy['episode']['start'] = {'kind': 'directory'}
    config = native.compile_request(proxy)
    config['requested_start'] = deepcopy(start) if comparison_home else None
    return config


def generate(request, *, world_factory=None):
    config = compile_request(request)  # validates field/type/unit before any draw
    factory = _bind(native.generate, compile_request=lambda _: config)
    result = factory(request, world_factory=world_factory)
    if config['requested_start'] is not None:
        result['resolved_configuration']['proxy_episode'] = deepcopy(result['resolved_configuration']['episode'])
        result['episode']['start'] = config['requested_start']
        result['resolved_configuration']['episode']['start'] = deepcopy(config['requested_start'])
    task = result['quote_offer_task']
    if 'comparison_scope' in task:
        result['episode']['shopping_scope'] = 'Products and retailer listings shown on ' + task['comparison_scope']['site_name']
    result['resolved_configuration']['quote_offer_selection'] = deepcopy(config['selection'])
    result['quote_field_inventory'] = {k: deepcopy(getattr(config['inventory'], k))
        for k in ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}
    return result


def prepare(request, output, *, validation='off', answer_grading=None, lazy_publication=True):
    """New output only; keep original request, defaults and exact declaration bytes."""
    config = compile_request(request)
    options = generation_configs.execution_options({'validation': validation,
        'answer_grading': answer_grading, 'lazy_publication': lazy_publication})
    sources = _bind(unified.shared.source_files, __file__=__file__)()
    sources.update(unified.shared.source_files())
    sources.update(config['inventory'].source_hashes)
    from scripts import trace_grades, product_width_watch
    for module in (trace_grades, product_width_watch):
        path = Path(module.__file__).resolve()
        sources[str(path.relative_to(unified.ROOT))] = sha256(path.read_bytes()).hexdigest()
    for path in (unified.ROOT/'experiments/external_agent').glob('*.mjs'):
        sources[str(path.relative_to(unified.ROOT))] = sha256(path.read_bytes()).hexdigest()
    sampled = []
    def generate_once(request, *, world_factory=None):
        result = generate(request, world_factory=world_factory)
        sampled.append(result)
        return result
    shim = SimpleNamespace(**vars(unified))
    shim.generate = generate_once
    manifest = _bind(execution_generation.prepare, unified=shim)(request, output,
        validation=validation, lazy_publication=lazy_publication)
    result = sampled[0]
    output = Path(output).resolve()
    for name, key in (('quote-offer-task.private.json', 'quote_offer_task'),
                      ('quote-offer-reference.private.json', 'quote_offer_reference'),
                      ('quote-field-inventory.private.json', 'quote_field_inventory')):
        unified.shared.save(output/name, result[key])
    record = json.loads((output/'execution.private.json').read_text())
    record['answer_grading'] = options['answer_grading']
    record['source_sha256'].update(sources)
    capture = json.loads((output/'generation-config.private.json').read_text())
    capture.update(execution=options, task_source='structured_template', recipe=VERSION,
        config_sha256=generation_configs.digest({'request': request, 'execution': options}))
    # These files were created within this new preparation call. Historical
    # packets and existing producer pin manifests are never modified.
    for name, value in (('execution.private.json', record), ('generation-config.private.json', capture)):
        (output/name).write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')
    for name, expected in sources.items():
        source = unified.ROOT/name
        if sha256(source.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Quote recipe source changed during freeze: '+name)
        archive = output/'pin/source-snapshot'/name
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, archive)
    manifest['source_sha256'].update(sources)
    manifest.update(recipe=VERSION, task_kind=result['quote_offer_task']['kind'],
                    automatic_grader_supported=True, execution_policy=record,
                    native_match_status=result['quote_offer_reference']['status'],
                    evidence_coverage='not_inferred_from_native_truth')
    for name in ('execution.private.json', 'generation-config.private.json',
                 'quote-offer-task.private.json', 'quote-offer-reference.private.json',
                 'quote-field-inventory.private.json'):
        manifest['files'][name] = sha256((output/name).read_bytes()).hexdigest()
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
    return manifest
