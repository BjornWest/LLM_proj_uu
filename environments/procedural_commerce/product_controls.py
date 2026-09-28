"""Versioned, public variant selection semantics; no task or layout dependencies."""
from copy import deepcopy
from math import isfinite
import re

VERSION = 'commerce-product-controls-v1'
KEY = re.compile(r'[a-z][a-z0-9_]*\Z')


def validate_groups(groups, world):
    """Strict development boundary: all listed combinations bind existing SKUs."""
    if groups is None:
        return []
    if not isinstance(groups, list):
        raise ValueError('product_groups must be a list')
    products = {p['product_id']: p for p in world['products']}
    used_skus, used_groups = set(), set()
    for group in groups:
        if set(group) != {'schema_version', 'group_id', 'family', 'name', 'axes', 'variants'}:
            raise ValueError('Unexpected group fields')
        if group['schema_version'] != VERSION:
            raise ValueError('Unsupported product-controls version')
        for key in ('group_id', 'family', 'name'):
            if not isinstance(group[key], str) or not group[key]:
                raise ValueError('Group identity must be nonempty text')
        if group['group_id'] in used_groups:
            raise ValueError('Duplicate group')
        used_groups.add(group['group_id'])
        domains = {}
        if not isinstance(group['axes'], list) or not group['axes']:
            raise ValueError('Axes required')
        for axis in group['axes']:
            if set(axis) != {'field', 'label', 'value_type', 'unit', 'options'}:
                raise ValueError('Unexpected axis fields')
            field = axis['field']
            if not isinstance(field, str) or not KEY.fullmatch(field) or field in domains:
                raise ValueError('Invalid or duplicate field')
            if not isinstance(axis['label'], str) or not axis['label']:
                raise ValueError('Axis label required')
            if axis['unit'] is not None and not isinstance(axis['unit'], str):
                raise ValueError('Invalid unit')
            if axis['value_type'] not in ('number', 'string'):
                raise ValueError('Unsupported option type')
            domains[field] = {}
            values = []
            if not isinstance(axis['options'], list) or not axis['options']:
                raise ValueError('Options required')
            for option in axis['options']:
                if set(option) != {'id', 'label', 'value'}:
                    raise ValueError('Unexpected option fields')
                if not isinstance(option['id'], str) or not KEY.fullmatch(option['id']) or option['id'] in domains[field]:
                    raise ValueError('Invalid or duplicate option id')
                if not isinstance(option['label'], str) or not option['label']:
                    raise ValueError('Option label required')
                value = option['value']
                valid = (type(value) in (int, float) and isfinite(value)) if axis['value_type'] == 'number' else isinstance(value, str)
                if not valid or value in values:
                    raise ValueError('Invalid or duplicate canonical option value')
                values.append(value)
                domains[field][option['id']] = value
        seen = set()
        if not isinstance(group['variants'], list) or not group['variants']:
            raise ValueError('Variants required')
        for variant in group['variants']:
            if set(variant) != {'product_id', 'selection'}:
                raise ValueError('Unexpected variant fields')
            sku, selection = variant['product_id'], variant['selection']
            if sku not in products or sku in used_skus or set(selection) != set(domains):
                raise ValueError('Missing/reused SKU or incomplete selection')
            pair = tuple(sorted(selection.items()))
            if pair in seen:
                raise ValueError('Ambiguous variant tuple')
            seen.add(pair); used_skus.add(sku)
            for field, option_id in selection.items():
                if option_id not in domains[field]:
                    raise ValueError('Unknown option id')
                value = products[sku].get('attributes', {}).get(field)
                expected = domains[field][option_id]
                if isinstance(value, bool) or value != expected:
                    raise ValueError('SKU attributes disagree with canonical selection')
    return deepcopy(groups)


def group_for(groups, product_id):
    return next((g for g in groups if any(v['product_id'] == product_id for v in g['variants'])), None)


def resolve(group, product_id, submitted=None):
    """None means direct canonical SKU URL; a supplied partial tuple stays partial."""
    if submitted is None:
        selection = dict(next(v['selection'] for v in group['variants'] if v['product_id'] == product_id))
    else:
        if set(submitted) - {a['field'] for a in group['axes']}:
            raise ValueError('Unknown selection field')
        selection = {a['field']: submitted.get(a['field'], '') for a in group['axes']}
    for axis in group['axes']:
        if selection[axis['field']] not in ['', *[o['id'] for o in axis['options']]]:
            raise ValueError('Unknown option')
    match = next((v for v in group['variants'] if v['selection'] == selection), None)
    status = 'incomplete' if '' in selection.values() else 'resolved' if match else 'unlisted'
    return {'status': status, 'selection': selection,
            'product_id': match['product_id'] if match else None}


def render_controls(group, state, styles):
    """Layout-independent native controls; the parent design chooses placement."""
    from html import escape as e
    parts = []
    for axis in group['axes']:
        field = axis['field']; selected = state['selection'][field]
        name = 'option_' + field
        if styles.get(field, 'select') == 'select':
            opts = '<option value="">Choose an option</option>'
            for o in axis['options']:
                opts += f'<option value="{e(o["id"])}"'+(' selected' if o['id'] == selected else '')+f'>{e(o["label"])}</option>'
            parts.append(f'<label>{e(axis["label"])}<select name="{e(name)}">{opts}</select></label>')
        else:
            opts = ''
            for o in [{'id':'', 'label':'Not selected'}, *axis['options']]:
                opts += f'<label><input type="radio" name="{e(name)}" value="{e(o["id"])}"'+(' checked' if o['id'] == selected else '')+f'>{e(o["label"])}</label> '
            parts.append(f'<fieldset><legend>{e(axis["label"])}</legend>{opts}</fieldset>')
    return '<section aria-label="Product options">'+''.join(parts)+'</section>'


def page_selection(catalog, product_id, submitted):
    """Resolve public model data without changing the cart or falling back to a SKU."""
    group = group_for(catalog.get('product_groups', []), product_id)
    if group is None:
        return None
    state = resolve(group, product_id, submitted)
    state.update(group=group, source_product_id=product_id)
    return state


def purchase_prefix(site, origins, context, available):
    from html import escape as e
    from .renderers import _form_action, _path_product
    state = context['product_selection']
    group = state['group']
    style = context['catalog'].get('product_control_styles', {})
    action = _form_action(origins, site, _path_product(state['source_product_id']))
    controls = render_controls(group, state, style)
    button = f'<button type="submit" formmethod="get" formaction="{action}" formnovalidate>Update selection</button>'
    messages = {'incomplete':'Choose all product options to see a specific offer.',
                'unlisted':'This combination is not listed. Your other selections have been kept.'}
    message = messages.get(state['status'], 'This selected variant is out of stock.' if not available else 'Selected variant shown below. Update changed options to refresh price and stock.')
    return controls + button + f'<p role="status">{e(message)}</p>'
