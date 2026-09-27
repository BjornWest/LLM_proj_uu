"""World-facing intent sampled before stores, inventories, routes or reviews exist."""
import copy
import hashlib
import json
from .generator import stream

QUERIES = {
    'cheapest_pickup': ('cheapest','pickup','total_minor'),
    'nearest_pickup': ('cheapest','pickup','travel_minutes'),
    'fastest_pickup': ('fastest','pickup','ready_days'),
    'nearest_inspection': ('cheapest','inspect','travel_minutes'),
    'unit_price': ('cheapest','delivery','unit_price'),
    'widest_assortment': ('cheapest','inspect','matching_model_count'),
}
UNIT_FAMILIES = {'beer':'litre','wine':'litre','dog_food':'kg','cat_food':'kg'}
INSPECTION_FAMILIES = ('footwear','laptops')


def predicate(field, operator, value, label, unit=None):
    return {'field':field,'operator':operator,'value':value,'label':label,'unit':unit,
            'value_type':'boolean' if type(value) is bool else 'number' if type(value) in (int,float) else 'string',
            'surface':'world_evidence'}


def resolve_world(explicit, memories, activity):
    """Explicit same-field/operator overrides, with activity-scoped durable memory."""
    result={}
    for m in memories:
        if m['scope'] not in ('shopping',activity):continue
        p=m['predicate'];result[(p['field'],p['operator'])]={**copy.deepcopy(p),'source':{'kind':'memory','id':m['id'],'channel':m['channel']}}
    for p in explicit:
        result[(p['field'],p['operator'])]={**copy.deepcopy(p),'source':{'kind':'request'}}
    return sorted(result.values(),key=lambda p:(p['field'],p['operator']))


def fingerprint(bundle):
    semantic={k:bundle[k] for k in ('request','memory_facts','resolved_task')}
    if 'world_memory_facts' in bundle:semantic['world_memory_facts']=bundle['world_memory_facts']
    if 'cookie_memory_facts' in bundle:semantic['cookie_memory_facts']=bundle['cookie_memory_facts']
    if 'product_review_memory_facts' in bundle:semantic['product_review_memory_facts']=bundle['product_review_memory_facts']
    if 'retailer_memory_facts' in bundle:semantic['retailer_memory_facts']=bundle['retailer_memory_facts']
    if 'account_memory_facts' in bundle:semantic['account_memory_facts']=bundle['account_memory_facts']
    semantic['hidden_user_specifications']=[{k:v for k,v in h.items() if k!='reply'} for h in bundle['hidden_user_specifications']]
    return hashlib.sha256(json.dumps(semantic,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def extend(bundle, query, preferences='auto', *, price_range_sek=None):
    if preferences not in ('auto','none','reputation','domestic','reputation_domestic'):
        raise ValueError('Unknown world preference recipe')
    request=bundle['request'];lines=request['lines'];seed=bundle['seed']
    if len(lines)!=1:
        if preferences not in ('auto','none') or query in QUERIES:raise ValueError('World preference recipes currently require one product line')
        return bundle
    family=lines[0]['family_id'];activity=QUERIES.get(query,('', 'delivery', ''))[1]
    if query=='nearest_inspection' and family not in INSPECTION_FAMILIES:
        raise ValueError('Inspection tasks currently support footwear and laptops')
    if query=='unit_price' and family not in UNIT_FAMILIES:
        raise ValueError('Unit-price tasks require beer, wine or pet food')
    if activity!='delivery' and 'destination_location' not in request['context']:
        raise ValueError('Collection/inspection tasks require a sampled user location')
    if preferences=='auto':preferences=stream(seed,'world-preference-recipe').choice(('none','none','reputation','domestic','reputation_domestic'))
    if query not in QUERIES and preferences=='none':return bundle
    request['query']['activity']=activity
    if query in QUERIES:
        field=QUERIES[query][2]
        request['query']['objective']=[{'field':field,'direction':'min'}]
        if query=='fastest_pickup':request['query']['objective'].append({'field':'total_minor','direction':'min'})
        if query=='unit_price':
            request['query']['unit']=UNIT_FAMILIES[family]
        if activity!='delivery':
            request['constraints'].pop('delivery_mode',None)
            request['constraints'].pop('arrival_days_max',None)
            request['context']['price_basis']='item_and_mandatory_collection_charges_excluding_personal_travel'
        if activity=='inspect':request['constraints'].clear()
        if query=='widest_assortment':
            from .assortment import configure
            configure(bundle,price_range_sek)
    wanted=[];r=stream(seed,'world-requirements')
    if activity in ('pickup','inspect'):
        wanted.append(predicate('travel_mode','eq',r.choice(('walking','cycling','driving')),'travel mode'))
        if r.random()<.5:wanted.append(predicate('travel_minutes','le',r.choice((15,30,45,60)),'one-way travel time','minutes'))
        else:wanted.append(predicate('travel_km','le',r.choice((2,5,10,25)),'one-way travel distance','km'))
        if activity=='pickup':
            # No redundant no-transfer + ready-now pair. Positive waiting allowances
            # leave transfer eligibility to the independently sampled world.
            if query=='nearest_pickup' or r.random()<.4:wanted.append(predicate('requires_stock_transfer','eq',False,'stock transfer'))
            elif query!='fastest_pickup':wanted.append(predicate('ready_days','le',r.choice((2,5,7)),'collection readiness','days'))
    if 'reputation' in preferences:
        wanted.extend((predicate('merchant_mean_stars','ge',r.choice((3,3.5,4)),'mean customer rating','stars'),
                       predicate('merchant_review_count','ge',r.choice((10,20,40)),'published review count')))
    if 'domestic' in preferences:wanted.append(predicate('merchant_country','eq',request['context']['destination'],'retailer home country'))
    explicit=[];memories=[];mode=bundle['settings']['resolved_memory_mode']
    for i,p in enumerate(wanted):
        remembered=mode!='none' and (i==0 or stream(seed,f'world-placement/{i}').random()<.55)
        if remembered:
            channel=mode if mode in ('profile','episodic') else ('profile' if i%2==0 else 'episodic')
            memories.append({'id':f'world-memory-{i+1}','subject':'self','scope':activity if p['field'] in ('travel_mode','travel_minutes','travel_km','requires_stock_transfer','ready_days') else 'shopping',
                'channel':channel,'predicate':copy.deepcopy(p),'provenance':'synthetic_prior_user_statement'})
        else:explicit.append(copy.deepcopy(p))
    if mode=='override' and memories:
        fact=next((m for m in memories if m['predicate']['field'] in ('travel_mode','travel_minutes','merchant_mean_stars')),None)
        if fact:
            p=fact['predicate'];explicit.append({**copy.deepcopy(p),'temporary_override':True})
            alternatives={'travel_mode':('walking','cycling','driving'),'travel_minutes':(15,30,45,60),'merchant_mean_stars':(3,3.5,4)}[p['field']]
            p['value']=next(v for v in alternatives if v!=p['value'])
    request['explicit_world_requirements']=explicit
    bundle['world_memory_facts']=memories
    requirements=resolve_world(explicit,memories,activity)
    for key in ('initial_accessible_task','resolved_task'):
        bundle[key]['query']=copy.deepcopy(request['query'])
        bundle[key]['context']=copy.deepcopy(request['context'])
        bundle[key]['constraints']=copy.deepcopy(request['constraints'])
        bundle[key]['world_requirements']=copy.deepcopy(requirements)
    bundle['settings'].update(query=query,resolved_query=query,world_preferences=preferences,world_intent_version='world-intent-v1')
    from .render import render
    bundle['public'],bundle['authoring']['message_segments']=render(request,bundle['memory_facts'],bundle['prose_seed'],memories)
    bundle['semantic_sha256']=fingerprint(bundle)
    return bundle


def phrase(p, rng):
    v=p['value'];field=p['field']
    if field=='travel_mode':return rng.choice({'walking':("I'll be walking","I need to get there on foot"),'cycling':("I'll go by bike","I want to cycle there"),'driving':("I'll drive there","I'll be going by car")}[v])
    if field=='travel_minutes':return rng.choice((f"keep the journey to {v} minutes each way",f"I can travel for up to {v} minutes one way"))
    if field=='travel_km':return rng.choice((f"keep the trip to {v} km each way",f"I don't want to travel more than {v} km one way"))
    if field=='requires_stock_transfer':return "it must already be in stock at the branch; I don't want to wait for a transfer"
    if field=='ready_days':return rng.choice((f"I can wait up to {v} days before collecting it",f"it needs to be ready for collection within {v} days"))
    if field=='merchant_mean_stars':return rng.choice((f"only shops averaging at least {v} out of 5 in customer reviews",f"the shop needs an average customer rating of {v}/5 or higher"))
    if field=='merchant_review_count':return f"the shop needs at least {v} published customer reviews"
    if field=='merchant_country':
        country={'SE':'Sweden','NO':'Norway','DK':'Denmark','FI':'Finland','IS':'Iceland','GB':'the UK','IE':'Ireland','NL':'the Netherlands','BE':'Belgium','LU':'Luxembourg','FR':'France','DE':'Germany','AT':'Austria','CH':'Switzerland','ES':'Spain','PT':'Portugal','IT':'Italy'}[v]
        return f"stick to retailers based in {country}"
    raise ValueError('Unknown world requirement')
