"""Conjunctive selected-configuration and successful-quote public span joins."""
from collections import defaultdict
from copy import deepcopy
import json

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
                parts=[] if missing_axes else parts,unresolved_axes=missing_axes))
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
