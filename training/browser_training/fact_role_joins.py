"""Conjunctive selected-configuration and successful-quote public span joins."""
from collections import defaultdict
from copy import deepcopy
import json
import math

from .task_prefix_coverage import slice16, text_hash

def checked_occurrences(normalized):
    rows = normalized.get('occurrences', [])
    if not isinstance(rows, list):
        raise ValueError('Malformed public occurrence collection')
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not isinstance(row.get('binding'), dict)
                or not isinstance(row.get('effective_state'), dict)
                or not isinstance(row.get('parts'), list)):
            raise ValueError('Malformed public occurrence identity/state/parts')
        for part in row['parts']:
            if not isinstance(part,dict) or not isinstance(part.get('part'),str) or not isinstance(part.get('spans'),list):
                raise ValueError('Malformed public occurrence part/spans')
            for span in part['spans']:
                if (not isinstance(span,dict) or not isinstance(span.get('source_id'),str)
                        or type(span.get('start')) is not int or type(span.get('end')) is not int):
                    raise ValueError('Malformed public occurrence source interval')
    return rows


def public_part_texts(row, sources):
    """Validate the recorded UTF-16 parts against exact original AX text."""
    result = {}
    for part in row['parts']:
        if not part['spans'] or part['part'] in result:
            return None
        text = ''
        for span in part['spans']:
            source = sources.get(span['source_id'])
            if source is None:
                return None
            if source.get('sha256') != text_hash(source['text']):
                raise ValueError('Changed public part source text')
            text += slice16(source['text'], span['start'], span['end'])
        result[part['part']] = text
    return result


def typed_slot_assertions(normalized, sources):
    """Expand declared product assertions, requiring the entire public slot.

    No scalar substring matching: each assertion retains every original part,
    including the reference-configuration wording in a multi-fact value.
    The displayed SKU identifies the page, not the assertion's product subject.
    """
    result = []
    for row in checked_occurrences(normalized):
        b = row['binding']
        if (b.get('authority') != 'native_existing_public_dom'
                or b.get('source_family') != 'retailer' or b.get('field') is not None
                or not isinstance(b.get('slot_id'), str) or not b['slot_id']
                or b.get('status') != 'known' or not isinstance(b.get('displayed_value'), str)):
            continue
        assertions = b.get('assertions', [])
        if not isinstance(assertions, list) or not all(isinstance(a, dict) for a in assertions):
            raise ValueError('Malformed typed slot assertions')
        parts = public_part_texts(row, sources)
        if not parts or not parts.get('label') or parts.get('value') != b['displayed_value']:
            continue
        label = next(p for p in row['parts'] if p['part'] == 'label')['spans']
        # The native probe adopts a full label element. A suffix registration
        # could otherwise silently drop reference/maximum/basis qualifiers.
        if (len(label) != 1 or label[0]['start'] != 0
                or label[0]['end'] != len(sources[label[0]['source_id']]['text'].encode('utf-16-le')) // 2):
            continue
        for assertion in assertions:
            value = assertion.get('value')
            if (not isinstance(assertion.get('semantic_id'), str) or not assertion['semantic_id']
                    or not isinstance(assertion.get('field'), str) or not assertion['field']
                    or assertion.get('authority') != 'catalog_fact' or assertion.get('status') != 'known'
                    or not b.get('product_id')
                    or row['effective_state'].get('product_id') != b['product_id']
                    or assertion.get('subject') != {'kind': 'product', 'id': b['product_id']}
                    or type(value) not in (str, bool, int, float)
                    or type(value) is float and not math.isfinite(value)
                    or assertion.get('unit') is not None and not isinstance(assertion['unit'], str)
                    or not isinstance(assertion.get('qualifiers', {}), dict)):
                continue
            expanded = deepcopy(row)
            expanded['id'] += '/assertion/' + assertion['semantic_id']
            expanded['binding'].update(field=assertion['field'],
                unit=assertion.get('unit'), typed_assertion=deepcopy(assertion),
                authority='native_complete_public_slot_assertion')
            result.append(expanded)
    return result


def page_title_axes(normalized, sources):
    """The native catalog title grammar binds a single page-key axis.

    catalog_adapter builds name + ' — ' + page-key values. Restrict this
    bridge to one string axis: exported object ordering cannot qualify a
    multi-axis suffix. The recorded title must match in full; state alone
    cannot earn exposure. No page/probe modification or new capture is needed.
    """
    groups = defaultdict(list)
    for row in checked_occurrences(normalized):
        b, state = row['binding'], row['effective_state']
        if (b.get('field') == 'product_name' and b.get('authority') == 'native_existing_public_dom'
                and b.get('source_family') == 'retailer'):
            groups[json.dumps(state, sort_keys=True)].append(row)
    result = []
    for rows in groups.values():
        if len(rows) != 1:
            continue
        row = rows[0]; b, state = row['binding'], row['effective_state']
        axes = state.get('page_configuration')
        if not isinstance(axes, dict) or len(axes) != 1:
            continue
        axis, value = next(iter(axes.items()))
        title = b.get('displayed_value')
        if (not isinstance(axis, str) or not axis or not isinstance(value, str) or not value
                or not isinstance(title, str) or not title.endswith(' — ' + value)
                or len(title) <= len(' — ' + value)
                or any(not b.get(k) or b.get(k) != state.get(k)
                       for k in ('product_id', 'page_id', 'sku_id', 'offer_id'))
                or b.get('site_id') != state.get('site')):
            continue
        texts = public_part_texts(row, sources)
        if texts != {'value': title} or len(row['parts'][0]['spans']) != 1:
            continue
        span = row['parts'][0]['spans'][0]
        start = span['end'] - len(value.encode('utf-16-le')) // 2
        expanded = deepcopy(row)
        expanded['id'] += '/page-axis/' + axis
        expanded['binding'].update(field='sku.' + axis, displayed_value=value, status='known',
            authority='native_single_page_axis_title', title_grammar='catalog-page-name-v1')
        # The whole title is the identifying context; the suffix is its value.
        expanded['parts'] = [dict(part='label', spans=[deepcopy(span)]),
            dict(part='value', spans=[dict(span, start=start)])]
        result.append(expanded)
    return result

def selected_configurations(normalized, sources=None):
    groups=defaultdict(list)
    for o in checked_occurrences(normalized):
        s=o['effective_state']
        if 'page_configuration' in s and 'selection' in s:
            if (not all(isinstance(s.get(k),dict) for k in ('page_configuration','selection'))
                    or any(k not in s for k in ('product_id','sku_id','site'))):
                raise ValueError('Malformed selected-configuration identity/state')
            groups[json.dumps(s,sort_keys=True)].append(o)
    result=[]
    for rows in groups.values():
        state=rows[0]['effective_state'];wanted={**state['page_configuration'],**state['selection']}
        parts=[];missing_axes=[]
        for axis,value in wanted.items():
            choices=[o for o in rows if o['binding'].get('field')=='sku.'+axis
                and o['binding'].get('status') not in ('unknown','not_applicable')
                and (type(o['binding'].get('displayed_value')) is type(value)
                    and o['binding']['displayed_value']==value
                    or type(value) is int and o['binding'].get('displayed_value')==str(value))
                and {p['part'] for p in o['parts'] if p['part'] in ('label','value')}=={'label','value'}]
            if sources is not None:
                choices=[o for o in choices if resolved_parts(o,sources)[0]]
            if not choices:
                missing_axes.append(axis);continue
            parts.extend({**deepcopy(p),'part':axis+'.'+p['part']} for p in choices[0]['parts']
                if p['part'] in ('label','value'))
        if wanted:
            result.append(dict(id='configuration-'+rows[0]['id'],binding=dict(
                authority='native_visible_configuration_join',field='selected_configuration',
                product_id=state['product_id'],sku_id=state['sku_id'],site_id=state['site'],
                displayed_value=wanted),effective_state=deepcopy(state),
                parts=[] if missing_axes else parts,unresolved_axes=missing_axes,
                resolved_axis_parts=parts if missing_axes else []))
    return result

def resolved_parts(occurrence,sources):
    parts=[];missing=[]
    for part in occurrence['parts']:
        spans=[]
        if not part['spans']:missing.append('empty-part:'+part['part'])
        for span in part['spans']:
            source=sources.get(span['source_id'])
            if source is None:missing.append(span['source_id']);continue
            spans.append({'source_id':source['id'],'start':span['start'],'end':span['end']})
        if spans:parts.append({'part':part['part'],'spans':spans})
    return ([] if missing else parts),missing

def quote_roles(normalized,allowed_modes):
    """Conjunctive complete native successful-quote parts, by exact quote state."""
    from .task_prefix_coverage import digest
    groups=defaultdict(list)
    for o in checked_occurrences(normalized):
        s=o['effective_state'];q=s.get('quote_result');b=o['binding']
        if (not isinstance(q,dict) or not q.get('quoteId') or q.get('errors')
                or b.get('quote_id')!=q['quoteId'] or not q.get('shipments')):continue
        if 'site' not in s or not isinstance(s.get('draft'),dict):
            raise ValueError('Malformed successful-quote site/draft scope')
        if b.get('field') in ('selected_service','selected_location','public_quote_lines'):
            if type(b.get('shipment_index')) is not int or not 0 <= b['shipment_index'] < len(q['shipments']):
                raise ValueError('Malformed successful-quote shipment index')
            if b['field']=='selected_service' and (
                    not isinstance(b.get('selected_service'),dict) or not isinstance(b['selected_service'].get('type'),str)):
                raise ValueError('Malformed selected-service binding')
        # A different selected option or cart is a different observation.
        key=digest({'site':s['site'],'quote':q,'draft':s['draft']})
        groups[key].append(o)
    result=[]
    for rows in groups.values():
        base=rows[0];s=base['effective_state'];q=s['quote_result'];count=len(q['shipments'])
        total=[o for o in rows if o['binding'].get('field')=='total'
            and o['binding'].get('authority')=='renderer_native_quote_scalar'
            and o['binding'].get('currency')=='SEK']
        services={o['binding']['shipment_index']:o for o in rows
            if o['binding'].get('field')=='selected_service'}
        locations={o['binding']['shipment_index']:o for o in rows
            if o['binding'].get('field')=='selected_location'}
        lines={o['binding']['shipment_index']:o for o in rows
            if o['binding'].get('field')=='public_quote_lines'
            and o['binding'].get('authority')=='renderer_native_quote_line_listing'}
        indexes=set(range(count))
        def add(field,chosen,value=None):
            if not chosen or any(not o['parts'] for o in chosen):return
            parts=[]
            for i,o in enumerate(chosen):
                parts.extend({**deepcopy(p),'part':str(i)+'.'+p['part']} for p in o['parts'])
            result.append({'id':'quote-'+field+'-'+base['id'],
                'binding':{'field':field,'authority':'conjunctive_native_successful_quote',
                    'site_id':s['site'],'quote_id':q['quoteId'],'value':value},
                'effective_state':s,'parts':parts})
        if total:
            add('complete_cart_payable_minor',[total[0]])
            # The native renderer emits total only for an error-free complete
            # quote. No unavailable/failed quote becomes positive feasibility.
            add('cart_delivery_feasible',[total[0]],True)
        if set(services)==indexes and set(locations)==indexes:
            selected=[o for i in range(count) for o in (services[i],locations[i])]
            add('cart_service_selections',selected)
            if all(services[i]['binding']['selected_service']['type'] in allowed_modes for i in range(count)):
                add('all_cart_delivery_modes_allowed',selected,True)
        if set(lines)==indexes:
            # Each native shipment listing exposes every line's product,
            # displayed configuration and quantity. Requiring all parts avoids
            # treating the total or one shipment as the complete cart.
            add('canonical_cart_lines',[lines[i] for i in range(count)])
    return result
