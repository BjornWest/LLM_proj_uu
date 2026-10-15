"""Explicit ordered feature relaxations over unchanged manufactured offers."""
from copy import deepcopy

from . import feature_offer_task as feature
from .adapter import digest
from experiments import source_binding

VERSION = 'website-catalog-relaxation-task-v1'
KIND = 'cheapest_matching_with_permitted_relaxations'
ORIGINAL = 'Original requirements'


def _strict(spec):
    return {**{k: deepcopy(v) for k, v in spec.items() if k != 'relaxations'}, 'kind': feature.KIND}


def resolve(spec, *, inventory, concept_ids):
    if type(spec) is not dict or spec.get('kind') != KIND:
        raise ValueError('Declare an explicitly permitted feature-relaxation task')
    strict = feature.resolve(_strict(spec), inventory=inventory, concept_ids=concept_ids)
    original = {p['field']: p for p in strict['predicates']}
    if len(original) != len(strict['predicates']):
        raise ValueError('Relaxation tasks require one original predicate per field')
    changes = spec.get('relaxations')
    if type(changes) is not list or not 1 <= len(changes) <= 4:
        raise ValueError('Declare one to four ordered permitted relaxations')
    labels, normalized = {ORIGINAL}, []
    for row in changes:
        if type(row) is not dict or set(row)-{'label','drop_fields','replacements'} or 'label' not in row:
            raise ValueError('Each relaxation declares label and dropped/replaced fields only')
        label = row['label']
        if (type(label) is not str or not 1 <= len(label) <= 80 or label != label.strip()
                or not label.isprintable() or label in labels):
            raise ValueError('Criteria labels must be unique printable text of length1–80')
        labels.add(label)
        dropped, replacements = row.get('drop_fields', []), row.get('replacements', [])
        if (type(dropped) is not list or any(type(p) is not str or p not in original for p in dropped)
                or len(set(dropped)) != len(dropped) or type(replacements) is not list
                or not dropped and not replacements):
            raise ValueError('Name existing dropped fields or predicate replacements')
        used, predicates = set(dropped), deepcopy(original)
        for p in dropped: del predicates[p]
        for new in replacements:
            if type(new) is not dict or type(new.get('field')) is not str:
                raise ValueError('A replacement must be a declared predicate')
            field = new['field']
            if field not in original or field in used:
                raise ValueError('Replace each original field at most once, without also dropping it')
            # Validate type, unit, operator and sentinels before comparing bounds.
            feature.resolve({**strict, 'predicates': [new]}, inventory=inventory, concept_ids=concept_ids)
            old = original[field]
            op, value = new['operator'], new['value']
            weaker = ((op == old['operator'] and op in {'ge','gt'} and value < old['value'])
                      or (op == old['operator'] and op in {'le','lt'} and value > old['value'])
                      or (old['operator'] == 'eq' and op == 'in' and len(set(value)) > 1
                          and old['value'] in value)
                      or (old['operator'] == op == 'in' and set(old['value']) < set(value))
                      or (old['operator'] == op == 'not_in' and set(value) < set(old['value'])))
            if not weaker:
                raise ValueError('Replacement must demonstrably weaken the original requirement')
            used.add(field)
            predicates[field] = deepcopy(new)
        if not predicates:
            raise ValueError('At least one original feature must remain in every alternative')
        feature.resolve({**strict, 'predicates': list(predicates.values())}, inventory=inventory, concept_ids=concept_ids)
        normalized.append({'label': label, 'drop_fields': deepcopy(dropped), 'replacements': deepcopy(replacements)})
    return {**strict, 'kind': KIND, 'relaxations': normalized}


def _scenarios(selection):
    strict = _strict(selection)
    yield ORIGINAL, strict
    for alternative in selection['relaxations']:
        predicates = {p['field']: deepcopy(p) for p in strict['predicates']}
        for field in alternative['drop_fields']: del predicates[field]
        for p in alternative['replacements']: predicates[p['field']] = deepcopy(p)
        yield alternative['label'], {**strict, 'predicates': list(predicates.values())}


def make(world, spec, *, inventory, surrounding=None):
    selection = resolve(spec, inventory=inventory, concept_ids=world['config']['concept_ids'])
    scenarios = [{'label': label, 'feature_task': feature.make(world, inner, inventory=inventory, surrounding=surrounding)}
                 for label, inner in _scenarios(selection)]
    message = scenarios[0]['feature_task']['user_message'].replace(
        'If no available option has specifications establishing all requirements, say so; '
        'do not claim an unknown specification is physically false.',
        'Use the fallback rules below if the original requirements have no established match; '
        'do not claim an unknown specification is physically false.')
    message += (' Try criteria sets in the following priority order. Use the first set with an available '
                'option establishing its requirements, even if a later set has a cheaper option. '
                'Use the minimum listed price within that first matching set. Every alternative below '
                'starts from the original requirements; do not combine different alternatives. ')
    for scenario in scenarios[1:]:
        clauses = '; '.join(feature._wording(p, inventory.fields[p['field']]) for p in scenario['feature_task']['predicates'])
        message += scenario['label']+': '+clauses+'. '
    message += ('State exactly which criteria set you used: '+', '.join(s['label'] for s in scenarios)+'. '
                'Only use an alternative if all earlier sets have no established available match. '
                'If none of these permitted sets has a match, say so; do not invent another relaxation. '
                'Report the product, retailer, explicit variant, product link and listed SEK price. Do not place an order.')
    task = {'schema_version': VERSION, **selection, 'world_id': world['world_id'], 'world_sha256': digest(world),
            'scenarios': scenarios, 'priority': 'first_established_available_set_then_minimum_listed_price',
            'alternatives_basis': 'each_independently_replaces_original_predicates',
            'user_message': message, 'memories': []}
    task['task_id'] = 'catalog-relaxation-'+digest(task)[:24]
    return task


def reference(world, task, *, inventory, surrounding=None):
    spec = {k: deepcopy(task[k]) for k in ('kind','concept_id','predicates','availability',
            'max_price_minor','comparison_site_id','relaxations') if k in task}
    if not source_binding.compatible(task, make(world, spec, inventory=inventory, surrounding=surrounding)):
        raise ValueError('Relaxation task/world/declared criteria binding changed')
    refs = [feature.reference(world, s['feature_task'], inventory=inventory, surrounding=surrounding)
            for s in task['scenarios']]
    selected = next((i for i, ref in enumerate(refs) if ref['candidates']), None)
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_id': world['world_id'],
            'status': 'match' if selected is not None else 'no_match', 'selected_index': selected,
            'selected_label': task['scenarios'][selected]['label'] if selected is not None else None,
            'minimum_price_minor': refs[selected]['minimum_price_minor'] if selected is not None else None,
            'scenario_references': refs, 'priority': task['priority'],
            'evidence_coverage': 'not_inferred_from_native_truth'}
