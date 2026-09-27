"""Audit generated catalog identities, types, domain coherence and group binding."""
from environments.procedural_commerce.product_controls import validate_groups
from environments.shopping_intent.catalog import FAMILIES, OPTIONAL_ATTRIBUTES
from environments.shopping_intent.semantics import conflicts
from .config import AXES, FAMILY_IDS, domains, wine_colours


def validate_catalog(bundle):
    from .generator import VERSION, digest
    if bundle.get('schema_version') != VERSION: raise ValueError('Unsupported catalog schema')
    public = bundle['public']
    if set(public) != {'products', 'product_groups'}: raise ValueError('Unexpected public catalog fields')
    products, groups = public['products'], public['product_groups']
    ids = [p['product_id'] for p in products]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate SKU identity')
    validate_groups(groups, {'products': products})
    bound = [v['product_id'] for g in groups for v in g['variants']]
    if set(bound) != set(ids): raise ValueError('Unbound product')
    if len(groups) != bundle['model_count']: raise ValueError('Incorrect model count')
    by_id = {p['product_id']: p for p in products}
    known = domains()
    for group in groups:
        family = group['family']
        if family not in FAMILY_IDS: raise ValueError('Unsupported family')
        if set(a['field'] for a in group['axes']) != set(AXES[family]): raise ValueError('Wrong axes')
        shared_reference = None
        recipe_reference = {}
        for variant in group['variants']:
            p = by_id[variant['product_id']]
            if set(p) != {'product_id', 'name', 'category', 'reference_price_minor', 'attributes', 'traits'}:
                raise ValueError('Unexpected product fields')
            if p['category'] != family: raise ValueError('Family mismatch')
            if type(p['reference_price_minor']) is not int or p['reference_price_minor'] <= 0: raise ValueError('Invalid reference price')
            attrs = {a.key: a for a in FAMILIES[family].attributes}
            optional = {a.key: a for a in OPTIONAL_ATTRIBUTES.get(family, ())}
            if not set(attrs) <= set(p['attributes']) or set(p['attributes']) - set(attrs) - set(optional):
                raise ValueError('Missing/extra product fact')
            attrs.update({k:a for k,a in optional.items() if k in p['attributes']})
            if set(p['attributes']) != set(attrs): raise ValueError('Missing/extra product fact')
            predicates = []
            for field, value in p['attributes'].items():
                attr = attrs[field]
                if attr.value_type == 'string_set':
                    if not isinstance(value, list) or not value or any(type(v) is not str for v in value) or len(value) != len(set(value)):
                        raise ValueError('Expected complete, nonempty canonical set')
                    if field != 'ingredients' and set(value) - set(known[family + '.' + field]):
                        raise ValueError('Unknown canonical set member')
                    predicates.extend({'field': field, 'operator': 'contains', 'value': v} for v in value)
                else:
                    domain = known.get(family + '.' + field, attr.values)
                    if not any(type(value) is type(v) and value == v for v in domain): raise ValueError('Invalid typed canonical fact')
                    predicates.append({'field': field, 'operator': 'eq', 'value': value})
            if conflicts(family, predicates): raise ValueError('Contradictory product facts')
            if family == 'footwear' and 'shoe_type' in p['attributes']:
                from .footwear_depth import validate_footwear_facts
                validate_footwear_facts(p['attributes'])
            if family == 'wine' and p['attributes']['wine_colour'] not in wine_colours(p['attributes']['grapes']):
                raise ValueError('Wine colour contradicts complete grape composition')
            if family in ('dog_food', 'cat_food') and p['attributes']['recipe'] not in p['attributes']['ingredients']:
                raise ValueError('Recipe protein missing from complete ingredients')
            shared = {k: v for k, v in p['attributes'].items() if k not in AXES[family] and k != 'ingredients'}
            if shared_reference is not None and shared != shared_reference: raise ValueError('Inconsistent model-level facts')
            shared_reference = shared
            if family in ('dog_food', 'cat_food'):
                recipe = p['attributes']['recipe']
                if recipe in recipe_reference and p['attributes']['ingredients'] != recipe_reference[recipe]:
                    raise ValueError('Recipe changes across pack-size siblings')
                recipe_reference[recipe] = p['attributes']['ingredients']
    if bundle['catalog_sha256'] != digest(public): raise ValueError('Catalog digest mismatch')
    return {'valid': True, 'models': len(groups), 'skus': len(products)}
