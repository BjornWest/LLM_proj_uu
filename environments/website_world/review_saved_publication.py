"""Freeze an exact saved review draft through ordinary producer publication.

No world generation, corpus edits, sidecar repair or new native task is performed.
The producer validates the native task/reference before exposing authored prose.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

from experiments.accepted_catalog_commerce.execution import Execution, _bind
from . import generation as shared, catalog_review_task as native
from . import review_saved_execution, review_saved_runner  # retain the complete execution source closure
from .adapter import ROOT, digest
from .review_saved_inputs import read_saved, sha, target_setup

VERSION = 'website-saved-review-publication-v1'
RECIPE = 'website-catalog-review-publication-v1'


def source_files():
    sources = _bind(shared.source_files, __file__=__file__)()
    # The ordinary AST collector excludes scripts, although final grading uses
    # its reader. Freeze it into the recipe archive and episode file bindings.
    sources['scripts/trace_grades.py'] = sha(ROOT/'scripts/trace_grades.py')
    package = ROOT/'scripts/__init__.py'
    if package.is_file():
        sources['scripts/__init__.py'] = sha(package)
    return sources


def prepare_saved(saved, output, *, expected_manifest_sha256, review_site_id):
    """A new immutable container around one manifest-pinned, unchanged draft."""
    saved, output = Path(saved).resolve(), Path(output).resolve()
    draft, payloads, message = read_saved(saved, expected_manifest_sha256=expected_manifest_sha256)
    read = lambda name: json.loads(payloads[name])
    world, task, reference = (read(name) for name in
        ('world.private.json', 'task.private.json', 'reference.private.json'))
    if world.get('schema_version') != 'accepted-catalog-commerce-world-v1':
        raise ValueError('Saved review publication requires native accepted catalog commerce')
    inventory = native.ReviewInventory(task['concept_id'])
    if inventory.source_hashes != draft['source_hashes'] or task['source_sha256'] != draft['source_hashes']:
        raise ValueError('Saved review native inventory/source contract changed')
    if native.reference(world, task, inventory=inventory) != reference:
        raise ValueError('Saved review native task/reference changed')
    original = read('native-episode-control.json')
    if (original['task_id'] != task['task_id'] or original['manual_task'] != {
            'user_message': task['user_message'], 'memories': task['memories']}):
        raise ValueError('Original saved public/native identity or memories changed')
    surrounding = read('surrounding.private.json')
    declared_start = read('diagnostic-start.private.json') if 'diagnostic-start.private.json' in payloads else None
    if 'diagnostic-start.private.json' in payloads:
        selected = next((site for site in surrounding['sites'] if site['site_id'] == review_site_id), None)
        if (type(declared_start) is not dict or selected is None
                or declared_start.get('site_id') != review_site_id
                or declared_start.get('product_id') != task['subject']['product_id']
                or declared_start.get('layout') != selected['layout']
                or type(declared_start.get('query')) is not dict):
            raise ValueError('Declared saved review start identity changed')
    setup = target_setup(world, task, surrounding,
        read('review-binding.private.json'), review_site_id=review_site_id,
        start_query=declared_start['query'] if declared_start is not None else None)
    episode = {'start': {'kind': 'directory'}, 'readable_origins': True,
        'task_id': task['task_id'], 'manual_task': {
            'user_message': message, 'memories': deepcopy(task['memories'])},
        'shopping_scope': 'Reviews on '+setup['site_name']}
    # AST-based closure starts at this module and includes the saved episode;
    # sources are checked again before publishing the manifest.
    sources = source_files()
    for name, expected in inventory.source_hashes.items():
        if name in sources and sources[name] != expected:
            raise ValueError('Native/Website review source conflict: '+name)
        sources[name] = expected
    execution = Execution(validation='off')
    output.mkdir(parents=True, exist_ok=False)
    producer = execution.freeze(world, output/'pin')
    # Preserve actual saved world bytes, not a reserialized equivalent.
    (output/'pin/world.private.json').write_bytes(payloads['world.private.json'])
    producer['files']['world.private.json'] = draft['files']['world.private.json']
    (output/'pin/manifest.json').write_text(json.dumps(producer, indent=2, ensure_ascii=False)+'\n')
    for name, expected in producer['source_sha256'].items():
        if name in sources and sources[name] != expected:
            raise ValueError('Producer/Website review source conflict: '+name)
        sources[name] = expected
    for name, expected in sources.items():
        source = (ROOT/name).resolve()
        if not source.is_relative_to(ROOT) or sha(source) != expected:
            raise ValueError('Review publication source changed: '+name)
        archive = output/'pin/source-snapshot'/name
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, archive)
    aliases = {'presentation.private.json': 'presentation.json',
        'task.private.json': 'catalog-review-task.private.json',
        'reference.private.json': 'catalog-review-reference.private.json',
        'review-binding.private.json': 'catalog-review-binding.private.json',
        **{name: name for name in ('compositions.private.json', 'surrounding.private.json',
                                  'basket-plan.private.json', 'checkout-domain.private.json')}}
    if 'delivery-plan.private.json' in payloads:
        aliases['delivery-plan.private.json'] = 'delivery-plan.private.json'
    for old, new in aliases.items():
        with (output/new).open('xb') as stream:
            stream.write(payloads[old])
    original_inputs = output/'original-inputs'
    original_inputs.mkdir()
    for name, payload in payloads.items():
        with (original_inputs/name).open('xb') as stream:
            stream.write(payload)
    topic_inventory = {'concept_id': inventory.concept_id, 'topics': deepcopy(inventory.topics),
        'legacy': inventory.legacy, 'source_hashes': deepcopy(inventory.source_hashes),
        'field_inventory': {k: deepcopy(getattr(inventory.fields, k)) for k in
            ('concept_id', 'fields', 'publication', 'known_paths', 'source_hashes')}}
    request = {'schema': VERSION, 'operation': 'saved_world_publication',
        'draft_manifest_sha256': expected_manifest_sha256, 'saved_directory': str(saved),
        'review_site_id': review_site_id, 'world_draws': 0}
    execution_record = {**execution.record(), 'source_sha256': sources,
        'runtime_options': {'lazy_publication': True},
        'answer_grading': {'mode': 'external_required', 'native_kind': task['kind'],
            'before_dispatch': 'Evaluation_attaches_automatic_grader'}, 'world_draws': 0}
    for name, value in {'request.json': request, 'episode.json': episode,
        'saved-review-setup.private.json': setup, 'review-topic-inventory.private.json': topic_inventory,
        'execution.private.json': execution_record,
        'generation-config.private.json': {'request': request, 'recipe': VERSION,
            'config_sha256': digest(request), 'task_source': 'saved_native_task_with_authored_public_prose'},
        'sampling-audit.private.json': {'operation': 'saved_world_publication', 'world_draws': 0,
            'native_world_unmodified': True, 'source_world_sha256': draft['files']['world.private.json']}}.items():
        shared.save(output/name, value)
    # Verify archived sources and original inputs against the live/saved sources.
    read_saved(saved, expected_manifest_sha256=expected_manifest_sha256)
    for name, expected in sources.items():
        if sha(ROOT/name) != expected or sha(output/'pin/source-snapshot'/name) != expected:
            raise ValueError('Source changed before saved review publication: '+name)
    manifest = {'schema': 'website-world-generation-v2', 'recipe': RECIPE,
        'saved_review_recipe': VERSION, 'world_id': world['world_id'], 'task_kind': task['kind'],
        'source_sha256': sources, 'files': {str(p.relative_to(output)): sha(p)
            for p in output.rglob('*') if p.is_file() and 'source-snapshot' not in p.relative_to(output).parts},
        'automatic_grader_supported': True, 'automatic_grading_attached': False,
        'review_binding_status': 'bound', 'world_draws': 0, 'model_runs': 0,
        'execution_policy': execution_record, 'evidence_coverage': 'not_inferred_from_native_truth',
        'effects': 'unknown', 'source_world_sha256': draft['files']['world.private.json']}
    shared.save(output/'manifest.json', manifest)
    return manifest
