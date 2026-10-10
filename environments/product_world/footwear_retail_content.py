"""Fact-bound retail content for the isolated footwear authoring package.

Consumes public products only. Does not draw stock, invent seller claims or change
the proposed concept registry. Language assets require human semantic review.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from string import Formatter


RECIPE_PATH = Path(__file__).with_name('data')/'footwear_context_pilot'/'retail_content.json'


def load_recipe():
    recipe = json.loads(RECIPE_PATH.read_text())
    validate_recipe(recipe)
    return recipe


def validate_recipe(recipe):
    if recipe['schema_version'] != 'footwear-retail-recipe-v1':
        raise ValueError('Unsupported retail recipe')
    fields = recipe['fields']
    if len({f['id'] for f in fields}) != len(fields):
        raise ValueError('Duplicate retail field')
    for field in fields:
        if field['scope'] not in {'product','sku'} or not field['eligible_roles'] or set(field['eligible_roles'])-{'selector','page_partition','descriptive'}:
            raise ValueError('Invalid field scope or presentation roles')
        if field['scope']=='product' and not field['path'].startswith('facts.'):
            raise ValueError('Product fields must bind public facts')
        if field['scope']=='sku' and field['path'] not in {'size_eu','colour','width'}:
            raise ValueError('Unknown pilot SKU dimension')
    for concept in recipe['concepts'].values():
        blocks = concept['description_blocks']
        if len({b['id'] for b in blocks}) != len(blocks):
            raise ValueError('Duplicate description block')
        for field_id,roles in concept['role_overrides'].items():
            field = next((f for f in fields if f['id']==field_id),None)
            if field is None or not roles or not set(roles)<=set(field['eligible_roles']):
                raise ValueError('Invalid role override')
        for block in blocks:
            paths = list(block['slots'].values())+list(block['requires'])
            if any(p!='name' and not p.startswith('facts.') for p in paths):
                raise ValueError('Description must use public catalog facts')
            variants = block['variants']
            if not variants or len({v['id'] for v in variants}) != len(variants):
                raise ValueError('Missing or duplicate description variants')
            for variant in variants:
                parts = list(Formatter().parse(variant['text']))
                slots = {key for _,key,_,_ in parts if key is not None}
                if slots!=set(block['slots']) or any(fmt or conv for _,_,fmt,conv in parts):
                    raise ValueError('Description slots must exactly match the binding')


def fact_at(product, path):
    value = product
    try:
        for part in path.split('.'):
            value = value[part]
    except (KeyError, TypeError) as exc:
        raise ValueError(f'Missing public fact: {path}') from exc
    return deepcopy(value)


def render_retail_content(product, *, seed=0, recipe=None):
    recipe = load_recipe() if recipe is None else recipe
    validate_recipe(recipe)
    cfg = recipe['concepts'][product['concept']]
    if product['concept_id']!=cfg['concept_id']:
        raise ValueError('Concept identity mismatch')
    sentences=[]
    for block in cfg['description_blocks']:
        for path,expected in block['requires'].items():
            if fact_at(product,path)!=expected:
                raise ValueError(f'Description precondition failed: {path}')
        slots={key:fact_at(product,path) for key,path in block['slots'].items()}
        key=f"retail-description-v1/{seed}/{product['product_id']}/{block['id']}"
        index=int.from_bytes(hashlib.sha256(key.encode()).digest(),'big')%len(block['variants'])
        variant=block['variants'][index]
        sentences.append({'text':variant['text'].format(**slots), 'block_id':block['id'],
                          'realization_id':variant['id'],
                          'fact_paths':list(dict.fromkeys([*block['slots'].values(),*block['requires']]))})
    fields=[]
    for definition in recipe['fields']:
        if product['concept'] not in definition.get('concepts',[product['concept']]):
            continue
        field=deepcopy(definition)
        field['eligible_roles']=cfg['role_overrides'].get(field['id'],field['eligible_roles'])
        if field['scope']=='sku':
            field['values']=sorted({sku[field['path']] for sku in product['skus']})
            field['coverage_basis']='canonical SKUs; not retailer availability'
        else:
            field['value']=fact_at(product,field['path'])
            field['evidence_status']='unknown' if field['value'] in field.get('unknown_values',[]) else 'known'
            field['qualifiers']={p:fact_at(product,p) for p in field.get('qualifier_paths',[])}
        fields.append(field)
    return {'schema_version':'footwear-retail-content-v1','product_id':product['product_id'],
            'concept_id':product['concept_id'],'authority':'catalog_facts',
            'description':{'text':' '.join(s['text'] for s in sentences),'sentences':sentences},
            'fields':fields,'variants':deepcopy(product['skus'])}


def bind_page_content(content, page, policy):
    """Resolve eligible roles against a retailer's already-grouped listings."""
    variants=[f for f in content['fields'] if f['scope']=='sku']
    if set(policy)!={f['id'] for f in variants}:
        raise ValueError('Page policy must cover all variant dimensions')
    if not page['listings']:
        raise ValueError('Retail page needs at least one listing')
    canonical={sku['sku_id']:sku for sku in content['variants']}
    seen=set()
    for row in page['listings']:
        sku=canonical.get(row['sku_id'])
        if sku is None or any(row.get(k)!=v for k,v in sku.items()) or row['sku_id'] in seen:
            raise ValueError('Page references invalid or duplicate canonical SKU')
        seen.add(row['sku_id'])
    resolved=[]
    for field in variants:
        role=policy[field['id']]
        if role not in field['eligible_roles']:
            raise ValueError('Ineligible retailer presentation role')
        values=sorted({row[field['path']] for row in page['listings']})
        if not set(values)<=set(field['values']):
            raise ValueError('Page references unknown variant values')
        if role=='page_partition' and (len(values)!=1 or page['page_key'].get(field['id'])!=values[0]):
            raise ValueError('Page partition does not match its listings')
        if role=='selector' and page['selectors'].get(field['id'])!=values:
            raise ValueError('Selector values do not match listed SKUs')
        resolved.append({'id':field['id'],'label':field['label'],'role':role,'values':values,
                         'coverage_basis':'all listed SKUs, including sold-out listings'})
    return {'product_content_ref':content['product_id'],'variant_fields':resolved,
            'sku_ids':[row['sku_id'] for row in page['listings']]}


def authoring_packet(spec, registry, *, recipe=None):
    """Offline packet for bounded future authoring; never an agent observation."""
    recipe=load_recipe() if recipe is None else recipe
    coverage=[]
    for concept,cfg in recipe['concepts'].items():
        dimensions=registry.get(cfg['concept_id'])['dimensions']
        fields=[f for f in recipe['fields'] if concept in f.get('concepts',[concept])]
        for dimension in dimensions:
            bound=[f for f in fields if f['registry_dimension']==dimension['id']]
            status='bounded_pilot' if bound else 'not_implemented'
            if dimension['id']=='exposure_protection':status='unknown_only'
            if dimension['id']=='heel_geometry':status='partial_enclosure_or_retention_only'
            coverage.append({'concept_id':cfg['concept_id'],'dimension_id':dimension['id'],
                             'module_id':dimension['module_id'],'status':status,
                             'field_ids':[f['id'] for f in bound]})
    return {'schema_version':'footwear-authoring-packet-v1','audience':'offline_authors_not_shopping_agents',
            'recipe':deepcopy(recipe),'sampling_spec':deepcopy(spec),'registry_coverage':coverage,
            'completion_boundary':'Pilot bindings only; registry placeholders and live retailer renderers remain unchanged.'}
