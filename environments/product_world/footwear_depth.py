"""Explicit model-density recipe, planned before offers, stock or review opinions.

These are authored assortment controls, not measured prevalence or an outcome quota.
No public flag identifies which models an author considers plausible for a task.
"""
from copy import deepcopy

from environments.shopping_intent.catalog import attribute_for

TYPE_ACTIVITY = {'walking shoes': 'walking', 'running shoes': 'running',
                 'hiking shoes': 'hiking', 'dress shoes': 'formal', 'flip-flops': 'beach'}


def validate_footwear_facts(facts):
    kind = facts.get('shoe_type')
    if kind not in TYPE_ACTIVITY or facts.get('activity') != TYPE_ACTIVITY[kind]:
        raise ValueError('Footwear type contradicts intended activity')
    if kind in ('dress shoes', 'flip-flops') and facts.get('waterproof') is not False:
        raise ValueError('This footwear blueprint does not claim waterproof dress shoes/flip-flops')


def validate_blueprint(family, blueprint):
    if family != 'footwear' or not isinstance(blueprint, dict) or set(blueprint) != {
            'shared_attributes', 'axis_values', 'anchor_attributes', 'reference_range_sek'}:
        raise ValueError('Only explicit footwear blueprints are supported')
    shared = blueprint['shared_attributes']
    if set(shared) != {'shoe_type', 'activity', 'waterproof'} or type(shared['waterproof']) is not bool:
        raise ValueError('Invalid footwear shared attributes')
    validate_footwear_facts(shared)
    axes = blueprint['axis_values']
    if set(axes) != {'size_eu', 'colour', 'width'}:
        raise ValueError('Footwear blueprint must retain all existing controls')
    for field, values in axes.items():
        domain = attribute_for('footwear', field).values
        if not isinstance(values, list) or not values or len(values) != len(set(values)) or any(
                not any(type(v) is type(d) and v == d for d in domain) for v in values):
            raise ValueError('Invalid typed footwear option')
    anchor = blueprint['anchor_attributes']
    if not isinstance(anchor, dict) or not anchor or set(anchor) - set(axes) or any(
            type(value) is not type(axes[field][0]) or value not in axes[field] for field,value in anchor.items()):
        raise ValueError('Invalid footwear anchor')
    prices = blueprint['reference_range_sek']
    if not isinstance(prices, list) or len(prices) != 2 or any(type(v) is not int for v in prices) or not 1 <= prices[0] <= prices[1] <= 10000:
        raise ValueError('Invalid footwear reference price range')


def resolve_depth(config):
    defaults = {'plausible_models': 10, 'dress_models': 2, 'flip_flop_models': 2, 'size_eu': 40}
    if not isinstance(config, dict) or set(config) - set(defaults):
        raise ValueError('Unknown footwear depth field')
    result = {**defaults, **config}
    for key in ('plausible_models', 'dress_models', 'flip_flop_models'):
        if type(result[key]) is not int or not 1 <= result[key] <= 20:
            raise ValueError('Footwear model counts must be 1..20')
    if type(result['size_eu']) is not int or result['size_eu'] not in attribute_for('footwear', 'size_eu').values:
        raise ValueError('Unsupported focus size')
    return result


def plan_depth(seed, config, stores, families, assignments, anchors, model_counts):
    """Replace the footwear portion of a store-first plan before materializing SKUs."""
    from .generator import rng
    cfg = resolve_depth(config)
    carriers = [s['retailer_id'] for s in stores if 'footwear' in s['families']]
    if len(carriers) < 2 or 'footwear' not in anchors:
        raise ValueError('Footwear depth requires a focused family and two carrying stores')
    count = sum(cfg[k] for k in ('plausible_models', 'dress_models', 'flip_flop_models'))
    nonfoot = [i for i,f in enumerate(families) if f != 'footwear']
    remap = {i:count+j for j,i in enumerate(nonfoot)}
    result_assignments = {sid:[remap[i] for i in values if i in remap] for sid,values in assignments.items()}
    # Cover every model without checking whether stock, price or opinions qualify.
    for i in range(count):
        first = i % len(carriers)
        result_assignments[carriers[first]].append(i)
        if i % 2 == 0:
            result_assignments[carriers[(first+1) % len(carriers)]].append(i)
    # Keep the original named/shared anchor present in its specialist stores.
    for sid in anchors['footwear']['stores']:
        if 0 not in result_assignments[sid]:result_assignments[sid].append(0)
    for sid in carriers:
        old_count = sum(families[i] == 'footwear' for i in assignments[sid])
        wanted = min(count, max(6, old_count * 2))
        pool = [i for i in range(count) if i not in result_assignments[sid]]
        rng(seed, sid+'/footwear-depth/assortment').shuffle(pool)
        for i in pool[:max(0, wanted-sum(i<count for i in result_assignments[sid]))]:
            result_assignments[sid].append(i)
    new_anchors = deepcopy(anchors)
    for family,anchor in new_anchors.items():
        anchor['model_index'] = 0 if family == 'footwear' else remap[anchor['model_index']]
    kinds = ['walking shoes' if i % 5 < 3 else 'running shoes' if i % 5 == 3 else 'hiking shoes'
             for i in range(cfg['plausible_models'])]
    kinds += ['dress shoes'] * cfg['dress_models'] + ['flip-flops'] * cfg['flip_flop_models']
    names = ('Promenade', 'Harbour', 'Riverside', 'Pace', 'Ridge', 'Daytrip', 'Metro', 'Park', 'Tempo', 'Trail')
    brands = ('Aster', 'Boreal', 'Cedar', 'Solvik')
    blueprints=[];identities=[]
    for i,kind in enumerate(kinds):
        style_name = names[i % len(names)] if i < cfg['plausible_models'] else ('Civic' if kind=='dress shoes' else 'Coast')
        name = f'{brands[i % len(brands)]} {style_name} {kind.title()} {i+1:02d}'
        identities.append({'id':f'footwear-depth-model-{i+1:04d}', 'name':name})
        waterproof = kind == 'hiking shoes' and rng(seed,f'footwear-depth/{i}/waterproof').random()<.65
        blueprints.append({'shared_attributes':{'shoe_type':kind,'activity':TYPE_ACTIVITY[kind],'waterproof':waterproof},
            'axis_values':{'size_eu':list(attribute_for('footwear','size_eu').values),'colour':['black','blue'],'width':['standard','wide']},
            'anchor_attributes':{'size_eu':cfg['size_eu'],'colour':'black','width':'standard'},
            'reference_range_sek':{'walking shoes':[650,1100],'running shoes':[700,1200],
                'hiking shoes':[850,1350],'dress shoes':[800,1600],'flip-flops':[150,400]}[kind]})
    plan = ['footwear']*count + [families[i] for i in nonfoot]
    details={'recipe':cfg,'type_counts':{k:kinds.count(k) for k in TYPE_ACTIVITY},
             'coverage_rule':'Distinct models and focus-size listing anchors only; no stock, price or opinion guarantee.'}
    return plan,result_assignments,new_anchors,identities+[None]*len(nonfoot),blueprints+[None]*len(nonfoot),details
