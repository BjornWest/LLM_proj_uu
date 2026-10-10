"""Known-recipient scoped memories composed with the unchanged feature task."""
from copy import deepcopy

from . import catalog_memory, feature_offer_task
from .adapter import digest

VERSION = 'website-memory-feature-task-v1'
KIND = 'cheapest_matching_with_memory'


def resolve(value, *, inventory, concept_ids):
    allowed = {'kind', 'concept_id', 'recipient', 'predicates', 'memory_records',
               'availability', 'max_price_minor', 'comparison_site_id'}
    required = {'kind', 'concept_id', 'recipient', 'memory_records'}
    if (type(value) is not dict or set(value)-allowed or not required <= set(value) or
            value['kind'] != KIND or type(value['memory_records']) is not list or not value['memory_records']):
        raise ValueError('Declare a known-recipient feature task with typed memory records')
    resolution = catalog_memory.resolve(recipient=value['recipient'], concept_id=value['concept_id'],
        explicit=value.get('predicates', []), records=value['memory_records'], inventory=inventory)
    selection = feature_offer_task.resolve({'kind': feature_offer_task.KIND, 'concept_id': value['concept_id'],
        'predicates': resolution['resolved_predicates'], **{k: value[k] for k in
            ('availability', 'max_price_minor', 'comparison_site_id') if k in value}},
        inventory=inventory, concept_ids=concept_ids)
    spec = {'kind': KIND, 'concept_id': value['concept_id'], 'recipient': value['recipient'],
        'predicates': resolution['explicit_predicates'], 'memory_records': resolution['records'],
        **{k: selection[k] for k in ('availability', 'max_price_minor', 'comparison_site_id') if k in selection}}
    return spec, selection, resolution


def make(world, value, *, inventory, surrounding=None):
    spec, selection, resolution = resolve(value, inventory=inventory, concept_ids=world['config']['concept_ids'])
    native = feature_offer_task.make(world, selection, inventory=inventory, surrounding=surrounding)
    all_words = '; '.join(feature_offer_task._wording(p, inventory.fields[p['field']])
                         for p in selection['predicates'])
    current_words = '; '.join(feature_offer_task._wording(p, inventory.fields[p['field']])
                             for p in spec['predicates'])
    # Memories retain the remembered requirements. They must not leak back into
    # the current request through the underlying native feature task wording.
    current = ('Requirements for this purchase: '+current_words if current_words else
               'Use the relevant remembered shopping defaults')
    message = native['user_message'].replace('Requirements: '+all_words, current)
    recipient = 'This is for me.' if spec['recipient'] == 'self' else 'This is for '+spec['recipient']+'.'
    message = recipient+' '+message+' My explicit requirements for this purchase override remembered defaults for those fields.'
    task = {**deepcopy(spec), 'schema_version': VERSION, 'world_id': world['world_id'],
        'world_sha256': native['world_sha256'], 'task_id': '', 'quantity': 1,
        'price_basis': native['price_basis'], 'user_message': message,
        'memories': [catalog_memory.prose(r, inventory) for r in spec['memory_records']],
        'memory_resolution': resolution, 'selection_task': native,
        'evidence_coverage': 'selection_correctness_does_not_prove_memory_read_or_maintenance'}
    task.pop('task_id')
    task['task_id'] = 'memory-offer-'+digest(task)[:24]
    return task


def reference(world, task, *, inventory, surrounding=None):
    spec = {k: task[k] for k in ('kind', 'concept_id', 'recipient', 'predicates', 'memory_records',
        'availability', 'max_price_minor', 'comparison_site_id') if k in task}
    if task != make(world, spec, inventory=inventory, surrounding=surrounding):
        raise ValueError('Memory task/world/source/prose/resolution binding changed')
    native = feature_offer_task.reference(world, task['selection_task'], inventory=inventory, surrounding=surrounding)
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_id': world['world_id'],
        'world_sha256': task['world_sha256'], 'status': native['status'], 'selection_reference': native,
        'memory_resolution_sha256': digest(task['memory_resolution']),
        'evidence_coverage': task['evidence_coverage']}
