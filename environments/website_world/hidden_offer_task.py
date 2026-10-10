"""Personal preference omitted from initial prose and supplied through ask_user."""
from copy import deepcopy

from . import feature_offer_task, catalog_clarification
from .catalog_predicates import PredicateSet
from .adapter import digest

VERSION = 'website-hidden-feature-task-v1'
KIND = 'cheapest_matching_after_clarification'


def resolve(value, *, inventory, concept_ids):
    allowed = {'kind','concept_id','predicates','hidden_requirement','availability','max_price_minor','comparison_site_id'}
    if (type(value) is not dict or set(value)-allowed or not {'kind','concept_id','hidden_requirement'} <= set(value) or
            value['kind'] != KIND or value['concept_id'] != inventory.concept_id):
        raise ValueError('Declare a feature task with one hidden personal requirement')
    visible = PredicateSet(inventory.fields,value.get('predicates',[]),known_paths=inventory.known_paths).predicates
    slot = catalog_clarification.compile_slot(value['hidden_requirement'],inventory)
    if any(p['field'] == slot['predicate']['field'] for p in visible):
        raise ValueError('A hidden personal field cannot also be a visible current requirement')
    selection = feature_offer_task.resolve({'kind':feature_offer_task.KIND,'concept_id':value['concept_id'],
        'predicates':[slot['predicate'],*visible], **{k:value[k] for k in
        ('availability','max_price_minor','comparison_site_id') if k in value}},inventory=inventory,concept_ids=concept_ids)
    spec = {'kind':KIND,'concept_id':value['concept_id'],'predicates':visible,'hidden_requirement':slot,
            **{k:selection[k] for k in ('availability','max_price_minor','comparison_site_id') if k in selection}}
    return spec,selection


def make(world,value,*,inventory,surrounding=None):
    spec,selection = resolve(value,inventory=inventory,concept_ids=world['config']['concept_ids'])
    native = feature_offer_task.make(world,selection,inventory=inventory,surrounding=surrounding)
    all_words = '; '.join(feature_offer_task._wording(p,inventory.fields[p['field']]) for p in selection['predicates'])
    visible_words = '; '.join(feature_offer_task._wording(p,inventory.fields[p['field']]) for p in spec['predicates'])
    phrase = 'Requirements: '+all_words+'. Any model or variant satisfying all these requirements is acceptable.'
    if phrase not in native['user_message']: raise ValueError('Feature task prose contract changed')
    public = native['user_message'].replace(phrase, ('Requirements: '+visible_words+'. ' if visible_words else '')+
        'I do not have a specific model in mind; choose an appropriate personal variant.')
    subject = spec['hidden_requirement']['subject']
    public = ('This is for me. ' if subject == 'self' else 'This is for '+subject+'. ')+public
    task = {**deepcopy(spec),'schema_version':VERSION,'world_id':world['world_id'],
        'world_sha256':native['world_sha256'],'quantity':1,'price_basis':native['price_basis'],
        'user_message':public,'memories':[],'selection_task':native,
        'reply_contract_version':catalog_clarification.VERSION,
        'evidence_coverage':'Answer outcome and actual clarification delivery/ordering are separate.'}
    task['task_id'] = 'hidden-offer-'+digest(task)[:24]
    return task


def reference(world,task,*,inventory,surrounding=None):
    spec = {k:task[k] for k in ('kind','concept_id','predicates','hidden_requirement','availability',
                               'max_price_minor','comparison_site_id') if k in task}
    if task != make(world,spec,inventory=inventory,surrounding=surrounding):
        raise ValueError('Hidden task/world/source/prose/reply binding changed')
    native = feature_offer_task.reference(world,task['selection_task'],inventory=inventory,surrounding=surrounding)
    original = {r['offer_id'] for r in native['candidates']}; contrasts = []
    for value in task['hidden_requirement']['contrast_values']:
        selection = deepcopy(task['selection_task'])
        alternative = {**task['hidden_requirement']['predicate'],'value':value}
        alt = feature_offer_task.make(world,{'kind':feature_offer_task.KIND,'concept_id':task['concept_id'],
            'predicates':[alternative,*task['predicates']], **{k:selection[k] for k in
            ('availability','max_price_minor','comparison_site_id') if k in selection}},inventory=inventory,surrounding=surrounding)
        ref = feature_offer_task.reference(world,alt,inventory=inventory,surrounding=surrounding)
        ids = sorted(r['offer_id'] for r in ref['candidates'])
        contrasts.append({'value':deepcopy(value),'eligible_offer_ids':ids,'status':ref['status'],
                          'eligibility_differs':set(ids) != original})
    return {'schema_version':VERSION,'task_id':task['task_id'],'world_id':task['world_id'],
        'world_sha256':task['world_sha256'],'selection_reference':native,
        'status':native['status'],'contrast_evaluations':contrasts,
        'clarification_affects_eligibility':any(c['eligibility_differs'] for c in contrasts),
        'evidence_coverage':task['evidence_coverage']}
