"""Native one-page requirements and exact paired source projection.

A validated native make callback binds the full task/world/catalog/URLs/domain.
Source presence never asserts model receipt or successful task execution.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import re

VERSION='compiled-task-requirements-v1'
NATIVE='website-atomic-product-task-v1'
QUALIFIED_NATIVE='website-atomic-product-task-v2'
NATIVE_SCHEMAS=frozenset((NATIVE,QUALIFIED_NATIVE))
KINDS={'read_listed_price','read_public_fact','select_exact_variant','add_exact_quantity'}


def require(ok,message):
    if not ok:raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def compile_atomic(task, *, native_make, world, catalog, bindings, checkout_domain):
    require(type(task) is dict and type(task.get('spec')) is dict,'Structured native task/spec required')
    source_schema=task.get('schema_version')
    require(type(source_schema) is str and source_schema in NATIVE_SCHEMAS and type(task.get('kind')) is str and task['kind'] in KINDS,'Supported exact native atomic task required')
    fact=task.get('public_fact')
    if source_schema==QUALIFIED_NATIVE:
        require(task['kind']=='read_public_fact' and type(fact) is dict and
                type(fact.get('qualifier_declaration')) is dict and bool(fact['qualifier_declaration']),
                'Atomic v2 requires a declaration-bearing public fact')
    else:
        require(type(fact) is not dict or 'qualifier_declaration' not in fact,
                'Atomic v1 cannot carry a qualifier declaration; recreate a v2 task')
    require(callable(native_make),'Checked native atomic factory required')
    canonical=native_make(world,task['spec'],catalog=catalog,bindings=bindings,checkout_domain=checkout_domain)
    require(digest(task)==digest(canonical),'Native task/world/public catalog/domain mismatch')
    scope={k:task[k] for k in ('retailer_id','product_id','sku_id','offer_id','page_id')}
    pages=[p for p in catalog['products'] if p['id']==task['page_id']]
    require(len(pages)==1,'Exact atomic catalog page required')
    page=pages[0]
    variant=next(v for v in page['variants'] if v['offerId']==task['offer_id'])
    complete_selection={**page.get('pageKey',{}),**task['selection']}
    labels={o['key']:o['label'] for o in page['options']}
    for axis in page.get('pageKey',{}):
        rows=[r for g in variant.get('details',[]) for r in g['facts'] if r.get('field')=='sku.'+axis]
        require(len(rows)==1,'Unique native fixed-axis label required')
        labels[axis]=rows[0]['label']
    needs=[dict(id='configuration',field_role='selected_configuration',entity_scope='offer',unit=None,
        qualifiers={**scope,'selection':deepcopy(complete_selection),'axis_labels':labels},task_source_path='selection',producer_assertion_id=None,source_mapping='not_bound')]
    kind=task['kind']
    if kind=='read_listed_price':
        needs.append(dict(id='item_price',field_role='listed_price_minor',entity_scope='offer',unit='SEK_minor',qualifiers=deepcopy(scope),task_source_path='kind',producer_assertion_id=None,source_mapping='not_bound'))
    if kind=='read_public_fact':
        fact=task['public_fact'];row=fact['row']
        needs.append(dict(id='requested_public_fact',field_role=row.get('field') or 'public_formulation_slot',entity_scope='offer_public_row',unit=row.get('unit'),qualifiers={**scope,'heading':fact['heading'],'row':deepcopy(row)},task_source_path='public_fact',producer_assertion_id=None,source_mapping='not_bound'))
    terminal=[]
    if kind=='add_exact_quantity':
        terminal.append(dict(id='cart_quantity',field_role='basket_quantity',entity_scope='offer_cart_state',unit='retail_sale_units',qualifiers=deepcopy(scope),task_source_path='spec.quantity',producer_assertion_id=None,source_mapping='not_bound'))
    graph_nodes=[dict(id=n['id'],op='input',field=n['field_role'],value_type='integer' if n['id'] in ('item_price','cart_quantity') else 'object',unit=n['unit'],qualifiers=deepcopy(n['qualifiers'])) for n in needs]
    graph_nodes.append(dict(id='all_context',op='all',children=[n['id'] for n in needs]))
    semantics=dict(kind=kind,scope=deepcopy(scope),selection=deepcopy(task['selection']),initial_selection=deepcopy(task['initial_selection']),quantity=task['spec'].get('quantity'),fact=deepcopy(task['public_fact']),ranking=False,global_candidate_search=False)
    return dict(schema=VERSION,source_schema=source_schema,task_id=task['task_id'],task_sha256=digest(task),semantic_sha256=digest(semantics),semantics=semantics,
        world_binding=dict(world_id=task['world_id'],native_sha256=task['world_sha256'],catalog_sha256=task['catalog_sha256'],bindings_sha256=task['bindings_sha256'],checkout_domain_sha256=task['checkout_domain_sha256'],digest_convention='spaced_sorted_json'),
        information_needs=needs,terminal_source_needs=terminal,candidate_graph=dict(nodes=graph_nodes,roots=['all_context'],required_scope_fields=['retailer_id','product_id','sku_id','offer_id','state_id']),
        global_requirements=[dict(id='native_terminal_state',operation='actual_before_after_state_and_native_grade',implemented=False)] if kind in ('select_exact_variant','add_exact_quantity') else [],
        public_task_context=dict(user_message=task['user_message'],memories=deepcopy(task['memories'])),capability=dict(task_semantics='canonical_native_task',source_mapping='not_bound',exposure_mapping='not_bound',native_completion='not_established'))


def span_sources(capture,parts):
    """Audit exact original AX field and UTF-16 intervals, returning source keys."""
    norm=capture['normalized'];runs={r['id']:r for r in norm['runs']};sources={s['id']:s for s in norm['ax_sources']};axes={str(a['nodeId']):a for a in capture['raw_ax']}
    refs=[]
    for part in parts:
        require(part['spans'],'Missing required public part')
        for span in part['spans']:
            run=runs[span['source_id']];source=sources[span['source_id']];binding=source['binding'];ax=axes[binding['node_id']]
            require(not ax.get('ignored') and binding.get('snapshot_id')==norm['snapshot_id'] and binding['document_id']==norm['document_id'] and binding['frame_id']==norm['frame_id'],'Original AX scope unavailable')
            field=binding['field'];require(field in ('name','value'),'Unsupported AX source field')
            actual=ax.get(field,{}).get('value');actual=str(actual) if field=='value' else actual
            require(source['text']==run['text']==actual and ax.get('backendDOMNodeId')==run['backend_node_id'],'AX source/run mismatch')
            require(run['sha256']==hashlib.sha256(run['text'].encode()).hexdigest(),'Changed original run')
            start,end=span['start'],span['end'];raw=run['text'].encode('utf-16-le')
            require(type(start) is int and type(end) is int and 0<=start<end<=len(raw)//2,'Invalid UTF-16 part')
            text=raw[start*2:end*2].decode('utf-16-le')
            refs.append(dict(part=part['part'],text=text,source_id=span['source_id'],start=start,end=end,binding=deepcopy(binding),whole_field=start==0 and end==len(raw)//2,key=digest([norm['snapshot_id'],norm['frame_id'],norm['document_id'],run['sha256'],span])))
    require(refs,'Public evidence required')
    return refs


def heading_source(capture,refs,heading):
    norm=capture['normalized'];axes={str(a['nodeId']):a for a in capture['raw_ax']}
    label=next(r for r in refs if r['part']=='label');node=axes[label['binding']['node_id']];visited=set()
    while node and node['nodeId'] not in visited:
        visited.add(node['nodeId'])
        if node.get('role',{}).get('value') in ('Section','region'):
            heads=[axes[str(i)] for i in node.get('childIds',[]) if str(i) in axes and axes[str(i)].get('role',{}).get('value')=='heading' and axes[str(i)].get('name',{}).get('value')==heading and not axes[str(i)].get('ignored')]
            require(len(heads)==1,'Requested native fact heading not established in this section')
            h=heads[0];binding=dict(snapshot_id=norm['snapshot_id'],frame_id=norm['frame_id'],document_id=norm['document_id'],node_id=str(h['nodeId']),field='name')
            return dict(part='heading',text=heading,source_id='original-ax/'+str(h['nodeId'])+'/name',start=0,end=len(heading.encode('utf-16-le'))//2,binding=binding,whole_field=True,key=digest([binding,heading]),authority='original_snapshot_ax_heading')
        node=axes.get(str(node.get('parentId')))
    raise ValueError('Requested native fact heading not established')


def scalar_text(value):
    if type(value) is str:return value
    if type(value) is bool:return 'true' if value else 'false'
    require(type(value) in (int,float),'Only primitive native public values supported')
    number=Decimal(str(value));require(number.is_finite(),'Nonfinite public value')
    return format(number,'f').rstrip('0').rstrip('.') if '.' in format(number,'f') else format(number,'f')


def validate_rendered_parts(need,refs,value):
    texts={}
    for ref in refs:texts.setdefault(ref['part'],[]).append(ref['text'])
    texts={k:''.join(v) for k,v in texts.items()}
    if need['id']=='requested_public_fact':
        row=need['qualifiers']['row'];expected={'label':row['label'],'heading':need['qualifiers']['heading']}
        expected.update({f'value-{i}':scalar_text(v) for i,v in enumerate(row['value'])} if isinstance(row['value'],list) else {'value':scalar_text(row['value'])})
        if row.get('unit'):expected['unit']=row['unit']
        if row.get('qualifier'):expected['qualifier']=row['qualifier']
        require(texts==expected,'Public fact text disagrees with the task-bound row')
    if need['id'] in ('item_price','cart_quantity'):
        require(len(refs)==1 and refs[0]['whole_field'],'Complete original scalar AX field required')
    if need['id']=='item_price':
        # Frozen renderer: en-GB grouping, SEK prefix or SEK/kr suffix. Never
        # trust only metadata when a different amount was actually captured.
        amount=texts.get('amount_with_currency','')
        money=re.fullmatch(r'(?:SEK ([0-9][0-9,]*(?:\.[0-9]{1,2})?)|([0-9][0-9,]*(?:\.[0-9]{1,2})?) (?:SEK|kr))',amount)
        require(money is not None,'Unsupported public item money text')
        number=money.group(1) or money.group(2)
        require(re.fullmatch(r'(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?',number) is not None,'Invalid public money grouping')
        require(Decimal(number.replace(',',''))*100==value,'Public item amount differs from metadata')
    if need['id']=='cart_quantity':
        require(texts=={'quantity':str(value)},'Public cart quantity differs from metadata')
    if need['id']=='configuration':
        for axis,value in need['qualifiers']['selection'].items():
            require(texts[axis+'.value']==scalar_text(value),'Wrong public configuration value')
            # Fixed page dimensions are labelled by their public fact row, not
            # by an interactive option definition. Producer-bound fixed labels
            # still have exact AX spans.
            label=need['qualifiers']['axis_labels'].get(axis)
            require(label and texts[axis+'.label']==label,'Wrong public option label')


def match(need,o):
    b=o['binding'];s=o['effective_state'];q=need['qualifiers']
    require(b.get('site_id',s.get('site'))==q['retailer_id'] and b.get('product_id',s.get('product_id'))==q['product_id'] and b.get('sku_id',s.get('sku_id'))==q['sku_id'],'Different native offer subject')
    for key,target in [('site','retailer_id'),('product_id','product_id'),('sku_id','sku_id'),('offer_id','offer_id'),('page_id','page_id')]:
        require(s.get(key)==q[target],'Different effective-state subject: '+key)
    require('retailer_id' not in s or s['retailer_id']==q['retailer_id'],'Contradictory effective-state retailer identity')
    for key in ('offer_id','page_id','retailer_id'):
        require(key not in b or b[key]==q[key],'Contradictory occurrence identity: '+key)
    field=b.get('field');parts=o['parts']
    if need['id']=='configuration':
        require(field=='selected_configuration' and b.get('authority')=='native_visible_configuration_join' and b.get('displayed_value')==q['selection'],'Full requested configuration required')
        wanted={axis+'.'+part for axis in q['selection'] for part in ('label','value')}
        selected=[p for p in parts if p['part'] in wanted]
        require({p['part'] for p in selected}==wanted,'All configuration axes required')
        return selected,deepcopy(b['displayed_value'])
    if need['id']=='item_price':
        require(field=='listing_price' and b.get('authority')=='renderer_native_scalar' and b.get('currency')=='SEK' and type(b.get('value_minor')) is int,'Exact item amount/currency required')
        require(type(b.get('value')) in (int,float),'Primitive native item price required')
        amount=Decimal(str(b['value']))
        require(amount.is_finite() and amount>=0 and amount*100==b['value_minor'],'Minor unit mismatch')
        return [p for p in parts if p['part']=='amount_with_currency'],b['value_minor']
    if need['id']=='cart_quantity':
        require(field=='basket_quantity' and b.get('authority')=='renderer_native_cart_quantity' and type(b.get('value')) is int and b['value']>=0,'Native cart control required')
        return [p for p in parts if p['part']=='quantity'],b['value']
    row=q['row'];selector=('field',row['field']) if row.get('field') else ('slot_id',row['slotId'])
    require(b.get(selector[0])==selector[1] and b.get('authority')==('native_public_field' if selector[0]=='field' else 'selected_slot'),'Exact requested native field/slot required')
    require(b.get('status') in (None,'known') and type(b.get('displayed_value')) is type(row['value']) and b.get('displayed_value')==row['value'] and b.get('unit')==row.get('unit') and b.get('qualifier')==row.get('qualifier'),'Public value/unit/qualifier mismatch')
    wanted={'label'}|({f'value-{i}' for i in range(len(row['value']))} if isinstance(row['value'],list) else {'value'})
    if row.get('unit'):wanted.add('unit')
    if row.get('qualifier'):wanted.add('qualifier')
    selected=[p for p in parts if p['part'] in wanted]
    require({p['part'] for p in selected}==wanted,'Every requested fact part required')
    return selected,{k:deepcopy(row.get(k)) for k in ('label','value','unit','qualifier')}


def project_sources(compiled,capture,*,capture_context=None,terminal=False):
    rows=[];norm=capture.get('normalized')
    context_valid=capture_context==compiled['world_binding']
    for need in compiled['terminal_source_needs'] if terminal else compiled['information_needs']:
        row=dict(id=need['id'],field_role=need['field_role'],source_state='unknown',reason='No exact task-subject public occurrence in this capture',matches=[],rejected_matches=[],model_delivery='not_tested')
        if not context_valid:row['reason']='Trusted task/world/catalog capture context missing or different'
        if norm and context_valid:
            for o in [*norm['occurrences'],*norm.get('derived_occurrences',[])]:
                b=o.get('binding') or {}
                field={'configuration':'selected_configuration','item_price':'listing_price','cart_quantity':'basket_quantity'}.get(need['id'])
                if field and b.get('field')!=field:continue
                if need['id']=='requested_public_fact':
                    requested=need['qualifiers']['row']
                    if requested.get('field') and b.get('field')!=requested['field']:continue
                    if not requested.get('field') and b.get('slot_id')!=requested.get('slotId'):continue
                try:
                    parts,value=match(need,o);refs=span_sources(capture,parts)
                    if need['id']=='requested_public_fact':refs.append(heading_source(capture,refs,need['qualifiers']['heading']))
                    validate_rendered_parts(need,refs,value)
                except (ValueError,KeyError,TypeError,AttributeError,UnicodeError,ArithmeticError) as error:
                    row['rejected_matches'].append(dict(occurrence_id=o.get('id'),reason=str(error)));continue
                row['matches'].append(dict(occurrence_id=o['id'],effective_state=deepcopy(o['effective_state']),parts=refs,value=value))
        if row['rejected_matches'] and not row['matches']:row['reason']='; '.join(dict.fromkeys(r['reason'] for r in row['rejected_matches']))
        if row['matches']:row.update(source_state='mapped',reason=None)
        rows.append(row)
    return rows
