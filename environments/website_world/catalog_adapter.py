"""Public projection of the frozen, closed accepted-catalog commerce slice.

Source statuses and product/SKU prose scopes survive projection. No private
profiles, guards, statements, traces or reference tasks are browser exports.
"""
from copy import deepcopy
from datetime import date

from experiments.accepted_catalog_commerce import model, basket_quote
from environments.product_world.public_field_rules import is_public_field
from environments.product_world import catalog_publication
from .adapter import PublicAdapter as NativeAdapter, digest, supported_destination
from .surrounding_pages import pretty

VERSION = 'accepted-catalog-pages-public-adapter-v1'
FAMILY_LABELS = {'footwear':'Footwear', 'tops':'Tops', 'tablets':'Tablets',
                 **catalog_publication.FAMILY_LABELS}
SELECTED_CONCEPTS = frozenset(('tops.t_shirts','tablets.everyday_media_tablets',
                              *catalog_publication.CONCEPTS))
AXIS_LABELS = {'size_eu':'Size (EU)', 'size_label':'Size', 'colour':'Colour',
    'width':'Width', 'pack_count':'Pack quantity', 'configuration':'Configuration',
    'cellular_configuration':'Mobile connection'}
INTERNAL_SKU_FIELDS = {'sku_id','product_id','sku_key','first_shirt_id','model',
    'reference_price_sek','configuration_price_factor','connection_price_factor','model_price_factor'}


def label(key):return AXIS_LABELS.get(key,key.replace('_',' ').capitalize())


def display(value):
    if type(value) is bool:return 'Yes' if value else 'No'
    if type(value) is dict:return [k.replace('_',' ') + ': ' + pretty(v) for k,v in value.items()]
    return deepcopy(value)


def resolved_facts(item, sku=None):
    """Actual SKU facts override common catalog facts, with their own status."""
    values=deepcopy(item['public']['facts'])
    statuses={k.removeprefix('product.facts.'):v for k,v in item['catalog_status'].items() if k.startswith('product.facts.')}
    if sku is not None:
        values.update(deepcopy(sku.get('facts',{})))
        source=item['sku_status'].get(sku['sku_id'],{})
        statuses.update({k.removeprefix('sku.facts.'):v for k,v in source.items() if k.startswith('sku.facts.')})
    return values,statuses


def fact_rows(values,statuses,*,prefix=''):
    rows=[]
    for key,value in values.items():
        if key=='recipe_id' or not is_public_field(prefix+key):continue
        status=statuses.get(key)
        # Optional single-product facts are absent when their information is absent.
        if status in ('unknown','not_applicable') or value is None:continue
        row={'label':label(key),'value':display(value),
             'field':prefix+key}
        if status is not None:row['status']=status
        rows.append(row)
    return rows


def public_products(world):
    """Safe review/comparison records; no structured review meanings exported."""
    result={}
    for item in world['products']:
        p=item['public'];pid=p['product_id'];values,statuses=resolved_facts(item)
        facts={k:display(v) for k,v in values.items()
            if statuses.get(k) not in ('unknown','not_applicable') and v is not None
            and k!='recipe_id' and is_public_field(k)}
        seen=set();reviews=[]
        for r in item['reviews']:
            if r['review_id'] in seen:continue
            seen.add(r['review_id'])
            reviews.append({'review_id':r['review_id'],'reviewer':r.get('reviewer',r.get('reviewer_id','Customer')),
                'product_id':pid,'sku_id':r['sku_id'],'rating':r['rating'],'text':r['text']})
        result[pid]={'product_id':pid,'name':p['name'],'brand_id':p['brand_id'],
            'family_id':p['family_id'],'facts':facts,'fact_status':{k:v for k,v in statuses.items() if k in facts},
            'skus':[{'sku_id':s['sku_id'],'product_id':pid,**{k:deepcopy(s[k]) for k in item['variant_fields'] if k in s}}
                for s in p['skus']], 'reviews':reviews,'rating_summary':deepcopy(item['rating_summary']),
            'guidance':None}
    return result


def load_pin(path, *, source_store=None):
    import json
    from pathlib import Path
    if json.loads((Path(path)/'manifest.json').read_text()).get('schema_version') == 'accepted-catalog-commerce-pin-v2':
        if source_store is None:raise ValueError('V2 producer pin requires its explicit source store')
        from experiments.accepted_catalog_commerce import pin_v2
        return pin_v2.load(path,source_store=source_store)
    return model.load(path)


def selected_details(packet):
    return [{'role':'descriptive','heading':group['label'],'facts':[
        {'label':slot['group_key'].replace('_',' ').capitalize(),'value':slot['text'],
         'status':'known','slotId':slot['id'],'assertions':deepcopy(slot['assertions'])}
        for slot in group['slots']]} for group in packet['display_groups'] if group['key']!='care']


def selected_highlights(packet):
    slots={slot['id']:slot for group in packet['display_groups'] for slot in group['slots']}
    return [{'label':slots[c['slot_id']]['group_key'].replace('_',' ').capitalize(),
             'value':slots[c['slot_id']]['text'],'status':'known','priority':c['priority'],
             'slotId':c['slot_id'],'assertions':deepcopy(slots[c['slot_id']]['assertions'])}
            for c in packet['highlight_candidates']]


def selected_care(packet, *, sku_id=None):
    """Care uses the selected packet; wrapper scope never rewrites assertions."""
    if sku_id is not None and packet['sku_id'] != sku_id:
        raise ValueError('Care packet differs from selected SKU')
    subject_type = 'sku' if sku_id is not None else 'product'
    subject_id = sku_id if sku_id is not None else packet['product_id']
    return [{'heading':group['label'],'text':' '.join(slot['text'] for slot in group['slots']),
             'subjectType':subject_type,'subjectId':subject_id,'mappingStatus':'selected_assertions',
             **({'skuId':sku_id} if sku_id is not None else {}),
             'slots':deepcopy(group['slots'])}
            for group in packet['display_groups'] if group['key']=='care' and group['slots']]


class PublicAdapter(NativeAdapter):
    def __init__(self,world,plan=None,*,selected_content=False,oracle=None,disclosure_settings=None,disclosure_profiles=None,prepared=None,lazy=False):
        model.validate(world)
        self.oracle=basket_quote if oracle is None else oracle
        self.delivery_orders={}
        super().__init__(world)
        self.plan=deepcopy(plan) if plan is not None else basket_quote.make_plan(world)
        self.oracle.validate_plan(world,self.plan)
        self.prepared,self.lazy=prepared,lazy
        self.prepared_identity=digest(prepared.binding) if prepared is not None else None
        if prepared is not None and (prepared.binding['world_sha256']!=self.plan['world_sha256'] or
                prepared.binding['basket_plan_sha256']!=basket_quote.model.digest(self.plan)):
            raise ValueError('Prepared quote binding differs from public adapter')
        if lazy and prepared is None:raise ValueError('Lazy publication requires a prepared quote context')
        if type(selected_content) is not bool:raise ValueError('Selected content must be an explicit opt-in boolean')
        self.selected_content=selected_content
        from .product_disclosure import validate_settings
        self.disclosure_settings=validate_settings(disclosure_settings) if disclosure_settings is not None else None
        if self.disclosure_settings is not None and not selected_content:raise ValueError('Count-first disclosure requires selected content')
        self.disclosure_digest=digest(self.disclosure_settings) if self.disclosure_settings is not None else None
        from .product_disclosure import retailer_profiles,validate_profiles
        self.disclosure_profiles=(retailer_profiles(world,self.disclosure_settings) if disclosure_profiles is None
            else validate_profiles(world,self.disclosure_settings,disclosure_profiles))
        self.disclosure_profile_digests={rid:digest([self.disclosure_settings,profile])
            for rid,profile in (self.disclosure_profiles or {}).items()}
        self.selected_packets={}

    def content_packet(self,item,retailer_id,sku_id=None):
        p=item['public'];cid=p['concept_id']
        generic=cid in catalog_publication.CONCEPTS
        key=(retailer_id,p['product_id'])+((sku_id,) if cid=='tablets.everyday_media_tablets' or generic else ())
        if self.disclosure_digest is not None:key+=(self.disclosure_digest,)
        if self.disclosure_profiles is not None:key+=(self.disclosure_profile_digests[retailer_id],)
        if key not in self.selected_packets:
            kwargs={'seed':self.world['seed'],'retailer_id':retailer_id}
            if cid=='tablets.everyday_media_tablets' or generic:kwargs['sku_id']=sku_id
            if generic:
                export=catalog_publication.export_catalog_content
                if self.disclosure_profiles is not None:
                    kwargs.pop('retailer_id')
                    kwargs.update(retailer=self.retailers[retailer_id],highlight_bias=self.disclosure_settings['highlight_bias'])
                elif self.disclosure_settings is not None:
                    from .product_disclosure import producer_arguments
                    kwargs.update(producer_arguments(self.disclosure_settings,cid))
            elif self.disclosure_profiles is not None:
                from environments.product_world.retailer_disclosure import export_profiled_tablet_content,export_profiled_tshirt_content
                export=export_profiled_tablet_content if cid=='tablets.everyday_media_tablets' else export_profiled_tshirt_content
                kwargs.pop('retailer_id')
                kwargs.update(retailer=self.retailers[retailer_id],highlight_bias=self.disclosure_settings['highlight_bias'])
            elif self.disclosure_settings is not None:
                from environments.product_world.count_first_publication import export_count_first_tablet_content,export_count_first_tshirt_content
                from .product_disclosure import producer_arguments
                export=export_count_first_tablet_content if cid=='tablets.everyday_media_tablets' else export_count_first_tshirt_content
                kwargs.update(producer_arguments(self.disclosure_settings,cid))
            elif cid=='tablets.everyday_media_tablets':
                from environments.product_world.tablet_publication import export_tablet_content as export
            else:
                from environments.product_world.tshirt_publication import export_tshirt_content as export
            self.selected_packets[key]=export(item,**kwargs)
            if self.disclosure_profiles is not None and self.selected_packets[key]['retailer_disclosure']!=self.disclosure_profiles[retailer_id]:
                raise ValueError('Exported retailer disclosure profile differs from persisted plan')
        return self.selected_packets[key]

    def fulfilment(self,retailer_id,address,*,sku_ids=None):
        from .basket_fulfilment import project
        return project(self,retailer_id,address,sku_ids=sku_ids)

    def pending_fulfilment(self,retailer_id,address):
        if retailer_id not in self.retailers:raise ValueError('Unknown retailer')
        supported_destination(self.world,address)
        return {'address':deepcopy(address),'optionsBySku':{},'pending':True}

    def catalog(self,retailer_id,configuration,*,presentation=None):
        r=self.retailers[retailer_id];offers={o['sku_id']:o for o in r['offers']};seen=set();output=[]
        sources={s['source_id']:s for s in r['source_locations']}
        home=self.world['address_context']['addresses'][0]['address']
        remembered={'name':home['recipient'],'street':(home['street']+' '+home['house_number']).strip(),'unit':home['unit'],'postcode':home['postcode'],'city':home['city']}
        fulfilment=self.pending_fulfilment(retailer_id,remembered) if self.lazy else self.fulfilment(retailer_id,remembered)
        for entry in r['catalog']:
            item=self.products[entry['product_id']];p=item['public'];manufactured={s['sku_id']:s for s in p['skus']}
            model_packet=None
            selected_scope=self.selected_content and p['concept_id'] in SELECTED_CONCEPTS
            if self.selected_content and p['concept_id']=='tops.t_shirts':
                model_packet=self.content_packet(item,retailer_id)
            for page in entry['pages']:
                page_id='page-'+digest([p['product_id'],page['page_key']])[:24]
                menus=[{'key':k,'label':label(k),'values':[str(v) for v in values]} for k,values in page['selectors'].items()]
                variants=[]
                selected_prose=selected_care(model_packet) if model_packet is not None else []
                for row in page['listings']:
                    sid=row['sku_id']
                    if sid in seen or sid not in offers or sid not in manufactured:raise ValueError('Unbound or duplicate carried SKU')
                    seen.add(sid);sku=manufactured[sid];offer=offers[sid]
                    packet=model_packet
                    if selected_scope and p['concept_id']!='tops.t_shirts':
                        packet=self.content_packet(item,retailer_id,sid)
                        selected_prose.extend(selected_care(packet,sku_id=sid))
                    if offer['product_id']!=p['product_id'] or offer['currency']!='SEK':raise ValueError('Invalid offer identity or currency')
                    stock=[{'sourceId':source_id,'quantity':quantity,'kind':sources[source_id]['kind'],
                        'shippingEnabled':sources[source_id]['shipping_enabled'],'name':sources[source_id]['location']['city']}
                        for source_id,quantity in offer['stock_by_source'].items()]
                    dispatch=[s for s in stock if s['shippingEnabled'] and s['quantity']>0]
                    state='in_stock' if dispatch else 'backorder' if offer['supplier_order']['enabled'] else 'in_stock' if any(s['quantity']>0 for s in stock) else 'unavailable'
                    values,statuses=resolved_facts(item,sku)
                    selected={k:sku[k] for k in item['variant_fields'] if k in sku}
                    sku_status=item['sku_status'].get(sid,{})
                    measurements={k:v for k,v in sku.items() if k not in INTERNAL_SKU_FIELDS and is_public_field(k) and k not in selected and k!='facts' and not k.endswith('_status')}
                    groups=[{'role':'configuration','heading':'Selected configuration','facts':fact_rows(selected,{k:sku_status.get('sku.'+k) for k in selected},prefix='sku.')},
                        {'role':'descriptive','heading':'Product details','facts':fact_rows(values,statuses,prefix='facts.')},
                        {'role':'descriptive','heading':'Selected item specifications','facts':fact_rows(measurements,{k:sku_status.get('sku.'+k) for k in measurements},prefix='sku.')}]
                    if packet is not None:
                        groups=[groups[0],*selected_details(packet)]
                    for group in groups:
                        for field in group['facts']:
                            if 'assertions' in field:continue
                            if field['field'].startswith('facts.'):
                                key=field['field'].removeprefix('facts.')
                                sku_owned=key in sku.get('facts',{})
                                field['field']=('sku.facts.' if sku_owned else 'product.facts.')+key
                            else:sku_owned=True
                            field.update(subjectType='sku' if sku_owned else 'product',subjectId=sid if sku_owned else p['product_id'])
                    sku_reference='reference_price_sek' in sku
                    reference=sku.get('reference_price_sek',p['reference_price_sek'])
                    reference_status=sku_status.get('sku.reference_price_sek') if sku_reference else item['catalog_status'].get('product.reference_price_sek')
                    if reference_status not in ('unknown','not_applicable') and reference is not None:groups.append({'role':'reference_price','heading':'Manufacturer reference','facts':[{
                        'label':'Manufacturer reference price (SEK)','value':None if reference_status in ('unknown','not_applicable') else reference,
                        **({'status':reference_status} if reference_status else {}),
                        'field':'sku.reference_price_sek' if sku_reference else 'product.reference_price_sek',
                        'subjectType':'sku' if sku_reference else 'product','subjectId':sid if sku_reference else p['product_id']}]})
                    for group in groups:
                        for field in group['facts']:
                            if 'assertions' in field:
                                for assertion in field['assertions']:
                                    self.fields.append({'retailer_id':retailer_id,'page_id':page_id,'sku_id':sid,
                                        'field':assertion['field'],'label':field['label'],'subject_id':assertion['subject']['id'],
                                        'subject_type':assertion['subject']['kind'],'authority':assertion['authority'],
                                        'semantic_id':assertion['semantic_id'],'slot_id':field['slotId'],
                                        'subject':deepcopy(assertion['subject']),
                                        **({'mapping_status':assertion['mapping_status']} if 'mapping_status' in assertion else {})})
                                continue
                            self.fields.append({'retailer_id':retailer_id,'page_id':page_id,'sku_id':sid,
                                'field':field['field'],'label':field['label'],'subject_id':field['subjectId'],'subject_type':field['subjectType'],
                                'authority':'source_catalog_status' if field.get('status') else 'public_catalog_scalar'})
                    if packet is not None:
                        for group in packet['display_groups']:
                            if group['key']!='care':continue
                            for slot in group['slots']:
                                for assertion in slot['assertions']:
                                    self.fields.append({'retailer_id':retailer_id,'page_id':page_id,'sku_id':sid,
                                        'field':assertion['field'],'label':slot['group_key'].replace('_',' ').capitalize(),
                                        'subject_id':assertion['subject']['id'],'subject_type':assertion['subject']['kind'],
                                        'authority':assertion['authority'],'semantic_id':assertion['semantic_id'],
                                        'slot_id':slot['id'],'subject':deepcopy(assertion['subject']),
                                        **({'mapping_status':assertion['mapping_status']} if 'mapping_status' in assertion else {})})
                    variants.append({'key':sid,'skuId':sid,'offerId':offer['offer_id'],
                        'selection':{o['key']:str(sku[o['key']]) for o in menus},
                        'price':offer['price_minor']/100,'priceMinor':offer['price_minor'],'currency':offer['currency'],
                        'state':state,'sourceStock':stock,'stock':max((s['quantity'] for s in dispatch),default=0),
                        'source':dispatch[0]['sourceId'] if dispatch else '',
                        'branchStock':max((s['quantity'] for s in stock if s['kind']=='branch'),default=0),
                        'bulky':False,'days':None,'details':groups,'supplierOrder':deepcopy(offer['supplier_order']),
                        'pickup':[{'branch_id':q['branchId'],'branch_name':q['location']['name'],'source_id':q['sourceId'],
                            'ready_days':q['readyDays'],'requires_transfer':q['requiresTransfer']}
                            for q in fulfilment['optionsBySku'].get(sid,[]) if q['type']=='retailer_branch']})
                    if packet is not None:variants[-1]['highlights']=selected_highlights(packet)
                prose=[]
                listed={s['skuId'] for s in variants}
                for d in ([] if selected_scope else item['descriptions']):
                    if d['subject_type']=='product' and d['subject_id']!=p['product_id']:raise ValueError('Wrong product prose subject')
                    if d['subject_type']=='sku' and d['subject_id'] not in listed:continue
                    if d['subject_type'] not in ('product','sku'):raise ValueError('Unsupported prose subject')
                    prose.append({'heading':'About this product' if d['subject_type']=='product' else 'Selected item details',
                        'text':d['text'],'subjectType':d['subject_type'],'subjectId':d['subject_id'],
                        **({'skuId':d['subject_id']} if d['subject_type']=='sku' else {}),'mappingStatus':'unmapped'})
                common=next((d['text'] for d in prose if d['subjectType']=='product'),p['concept'].replace('_',' ').capitalize()+' by '+self.brands[p['brand_id']])
                if selected_scope:
                    prose=selected_prose
                    common=''  # An empty selected packet never revives legacy prose.
                suffix=', '.join(str(v) for v in page['page_key'].values())
                range_status=item['catalog_status'].get('product.facts.market_range',p.get('fact_status',{}).get('market_range','unknown'))
                output.append({'id':page_id,'canonicalProductId':p['product_id'],'familyId':p['family_id'],
                    'pageKey':deepcopy(page['page_key']),'name':p['name']+(' — '+suffix if suffix else ''),
                    'category':FAMILY_LABELS[p['family_id']],'type':p['concept'].replace('_',' ').capitalize(),
                    'brand':self.brands[p['brand_id']],'marketRange':{'status':range_status,'value':p['facts'].get('market_range') if range_status=='known' else None},
                    'introduction':common,'options':menus,'variants':variants,'descriptions':prose,'guide':'Sizing' if p['family_id'] in ('footwear','tops') else 'Care'})
        if seen!=set(offers):raise ValueError('Carried offers and public variants diverge')
        context=self.world['address_context'];home=context['addresses'][0]['address']
        mode=presentation['initial_form'] if presentation else 'producer'
        from experiments.address_checkout_pilot.model import autofill
        form=deepcopy(r['initial_form']) if mode=='producer' else {'address':home,'instructions':''} if mode=='canonical' else autofill(self.world['seed'],retailer_id,context['addresses'],context['outside_postcode'],context['parameters'],force=mode)
        def address(a):return {'name':a['recipient'],'street':(a['street']+' '+a['house_number']).strip(),'unit':a['unit'],'postcode':a['postcode'],'city':a['city']}
        remembered=address(home);initial=address(form['address'])
        fulfilment=self.pending_fulfilment(retailer_id,remembered) if self.lazy else self.fulfilment(retailer_id,remembered)
        try:initial_quotes=self.pending_fulfilment(retailer_id,initial) if self.lazy else self.fulfilment(retailer_id,initial)
        except ValueError:initial_quotes=None
        if mode in ('old','old_missing_unit'):
            has_home=False
            if initial_quotes is not None:
                if self.lazy:
                    # Preserve the explicit coverage guard, but stop on its first witness.
                    for offer in r['offers']:
                        rows=self.fulfilment(retailer_id,initial,sku_ids=[offer['sku_id']])['optionsBySku'][offer['sku_id']]
                        if any(o['type']=='home' for o in rows):has_home=True;break
                else:has_home=any(o['type']=='home' for rows in initial_quotes['optionsBySku'].values() for o in rows)
            if not has_home:raise ValueError('Requested stale address has no central home-delivery coverage')
        result={'schema':VERSION,'siteId':retailer_id,'siteName':r['name'],'quoteAsOf':self.world['quote_as_of'],'configuration':configuration,'products':output,
            'branches':{b['branch_id']:{'name':b['name'],'address':b['location']['city']+', '+b['location']['country'],'hours':'Opening hours are not published'} for b in r['geography']['branches']},
            'initialAddress':initial,'rememberedAddress':remembered,'initialInstructions':form['instructions'],
            'checkoutCapabilities':{'unitField':True,'instructions':True},'fulfilment':fulfilment,'initialFulfilment':initial_quotes,
            'policy':{'freeThresholdMinor':r['free_shipping_threshold_minor'],'deliveryCountries':r['geography']['fulfilment_policy']['delivery_countries'],
                'transferEnabled':r['geography']['fulfilment_policy']['warehouse_transfer_enabled'],'contracts':deepcopy(r['contracts'])}}
        if 'return_policy' in r:result['policy']['returnTerms']=deepcopy(r['return_policy'])
        if self.lazy:result['lazyFulfilment']=True
        return result
