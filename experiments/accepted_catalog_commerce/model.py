"""One population -> accepted manufacture -> real assortment/stock/price sources.

This is an additive, explicitly bounded commerce producer, not a legacy Episode
conversion or a claim that every accepted authoring package is adopted.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from pathlib import Path
import shutil

from experiments.footwear_world_pilot import model as native
from experiments.address_checkout_pilot import model as addresses
from experiments.carrier_service_pilot.model import generate as carrier_reviews
from experiments.world_sampling_defaults import model as population
from environments.product_world import footwear_context_pilot as footwear
from environments.product_world.geography import cities
from environments.product_world.locations import plan_locations
from environments.product_world import retailer_naming
from . import package_export
from .catalog_registry import naming_profile

VERSION='accepted-catalog-commerce-world-v1'
NAME_POOL=('Aster','Boreal','Cedar','Dalen','Eira','Fjord','Grove','Hedmark','Iris','Jora',
           'Klint','Linden','Mela','Norr','Orla','Pine','Runda','Solvik','Tova','Vela',
           'Wren','Yara','Zori','Alva','Brisa','Corin','Elva','Fenn','Hara','Isla')

# Used only after the original footwear pool is exhausted. Keeping the earlier
# pool intact preserves every previously successful append-only brand draw.
FOOTWEAR_OVERFLOW_NAMES=('Avilda','Brunora','Dovika','Elnara','Falkero','Glendora',
    'Havina','Idelund','Junora','Kallero','Lumora','Merova','Novira','Ostella',
    'Pravik','Ravena','Seldora','Toriva','Ulmera','Virelund','Wendora','Ylvena')

def _footwear_brand_spec(spec, existing):
    scope=spec['brand_sampling']['scopes']['footwear']
    used={b['name'].strip().casefold() for b in existing}
    if any(n.strip().casefold() not in used for n in scope['names']):
        return spec
    # Share all unchanged definitions; only this small name list is extended.
    sampling=spec['brand_sampling'];scopes=sampling['scopes']
    reserved={n.strip().casefold() for s in scopes.values() for n in s['names']}
    extra=[n for n in FOOTWEAR_OVERFLOW_NAMES if n.casefold() not in reserved]
    return {**spec,'brand_sampling':{**sampling,'scopes':{
        **scopes,'footwear':{**scope,'names':[*scope['names'],*extra]}}}}

def rng(seed,key): return population.stream(seed,VERSION+'/'+key)
def seed_for(seed,key): return int.from_bytes(sha256(f'{VERSION}/{seed}/{key}'.encode()).digest()[:4],'big')
def draw(seed,key,weights): return population.weighted(rng(seed,key),weights)

def _axes(seed,public,fields):
    result={}
    for axis,d in fields.items():
        if not set(d['retail_presentation']['allowed'])-{'description'}:continue
        values=sorted({s[axis] for s in public['skus']})
        if axis in ('size_eu','size_label'):
            result[axis]={'kind':'size'}
        elif axis=='colour':
            base=rng(seed,public['product_id']+'/standard-colour').choice(values) if rng(seed,public['product_id']+'/has-standard-colour').random()<.7 else None
            result[axis]={'kind':'colour','roles':{v:'base' if v==base else 'alternative' for v in values}}
        else:
            # Explicit slice roles: footwear regular width and the first declared
            # tablet/config/pack option are common; other configurations extensions.
            base='standard' if axis=='width' and 'standard' in values else values[0]
            result[axis]={'kind':'configuration','roles':{v:'base' if v==base else 'extension' for v in values}}
    return result

def _grouping(seed,rid,product,listings):
    fields=product['variant_fields'];public=product['public'];policy={}
    for axis,d in fields.items():
        allowed=d['retail_presentation']['allowed'];key=d['retail_presentation'].get('policy_key',axis)
        policy[axis]=rng(seed,rid+'/grouping/'+key).choice(allowed)
    canonical={s['sku_id']:s for s in public['skus']};groups={}
    for listing in listings:
        s=canonical[listing['sku_id']]
        key=tuple((axis,s[axis]) for axis,mode in sorted(policy.items()) if mode=='separate_page')
        groups.setdefault(key,[]).append({**deepcopy(s),**listing})
    pages=[{'page_key':dict(k),'selectors':{a:sorted({s[a] for s in rows}) for a,m in policy.items() if m=='selector'},
        'listings':rows,'warehouse_sold_out':all(s['stock']==0 for s in rows),
        'retail_content':{'description':{'text':' '.join(x['text'] for x in product['descriptions'] if x['subject_type']=='product'),
                            'mapping_status':'unmapped'},'fit_notice':None}}
        for k,rows in sorted(groups.items())]
    return policy,pages

def _offer_price(seed,rid,public,sku,cfg):
    # Preserve SKU configuration/pack reference prices; commercial variation is
    # retailer/model-correlated and rounded against the exact chosen SKU basis.
    basis=sku.get('reference_price_sek',public['reference_price_sek'])
    reference=int((Decimal(str(basis))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    if reference<=0:raise ValueError('Positive manufacturer price basis required')
    stream=rng(seed,rid+'/'+public['product_id']+'/price');match=stream.random()<cfg['reference_match_probability']
    offset=0 if match else max(cfg['offset_min'],min(cfg['offset_max'],stream.gauss(0,cfg['offset_standard_deviation'])))
    price=native.rounded_price(reference*(1+offset),reference,cfg)
    return price,{'reference_minor':reference,'reference_basis':'exact_sku' if 'reference_price_sek' in sku else 'product',
                  'matched_reference_draw':match,'offset_draw':offset}

def generate(seed=0, *, concept_ids=package_export.CONCEPTS,
             tasks=('footwear.walking_shoes',),controls=None,city_id='uppsala',review_count=0):
    if type(seed) is not int or not 0<=seed<2**31 or city_id not in cities():raise ValueError('Supported seed/city required')
    if type(concept_ids) not in (list,tuple) or not concept_ids or len(set(concept_ids))!=len(concept_ids) or set(concept_ids)-set(package_export.SUPPORTED_CONCEPTS):
        raise ValueError('Declare a unique supported accepted concept slice')
    if set(tasks)-set(concept_ids):raise ValueError('Task concentration concepts must belong to the declared slice')
    gates={cid:package_export.source_gate(cid) for cid in concept_ids}
    cfg=json.loads(native.CONFIG.read_text());cfg['concept_ids']=list(concept_ids)
    plan=json.loads(addresses.PLAN.read_text());geo=plan['retailer_population_contract']['geography_and_delivery_policy'];shipping=geo['delivery_options_proposal']
    spec=footwear.load_spec();rich=[];brands=[]
    def brand_factory(base,earlier):
        if base['scope_id']=='footwear':
            b=footwear.sample_brand(seed_for(seed,'brands'),len([x for x in brands if x['scope_id']=='footwear']),_footwear_brand_spec(spec,brands),existing=brands)
            b={**base,**b,'brand_id':base['brand_id'],'scope_id':base['scope_id']}
        else:
            weights={'budget':{'budget':7,'mainstream':3,'premium':1},'mainstream':{'budget':2,'mainstream':7,'premium':2},'premium':{'budget':1,'mainstream':3,'premium':7}}
            available=[n for n in NAME_POOL if n not in {x['name'] for x in brands if x['scope_id']==base['scope_id']}]
            if not available:raise ValueError('Scoped name capacity exhausted; adjust explicit population support')
            b={**base,'name':rng(seed,base['brand_id']+'/name').choice(available),'positioning_weights':weights[base['positioning']]}
        brands.append(b);return b
    def product_factory(base,brand,earlier):
        item=package_export.sample(seed_for(seed,base['product_id']),base['concept_id'],brand,base['product_id'],earlier=rich,review_count=review_count)
        item['sample_seed']=seed_for(seed,base['product_id']);item['stock_tendency']=draw(seed,base['product_id']+'/stock-tendency',cfg['stock']['tendency_weights'])
        item['axes']=_axes(seed,item['public'],item['variant_fields']);rich.append(item)
        return {**base,'positioning':item['private']['profiles']['positioning'],'name':item['public']['name']}
    metadata=population.sample(seed,tasks=tasks,controls=controls,concept_ids=concept_ids,brand_factory=brand_factory,product_factory=product_factory)
    address=addresses.generate(seed,city_id);user=address['addresses'][0]['location'];profiles={};homes={}
    for r in metadata['retailers']:
        rid=r['retailer_id'];kind={'small':'local_shop','medium':'regional_chain','large':'major_retailer'}[r['scale']]
        international=rng(seed,rid+'/international').random()<geo['international_shipping_probability_by_profile'][kind]
        profiles[rid]={'profile_id':kind,'international_probability':int(international),
                      'branch_count':rng(seed,rid+'/branches').randint(*cfg['authoring_defaults']['branch_count_ranges'][r['scale']])}
        homes[rid]=native.choose_home(seed,rid,user,international,'delivery',geo)
    network=plan_locations(seed,user,profiles,config={'transfer_probability':geo['stock_transfers']['enabled_probability']},
        merchant_home_cities=homes,branch_shipping={'enabled_probability':geo['branch_shipping']['enabled_probability']})
    headquarters={m['retailer_id']:m['headquarters'] for m in network['merchants']}
    names=retailer_naming.allocate(seed,[{
        'retailer_id':r['retailer_id'],
        'profile':naming_profile(r['template_id']),
        'country':headquarters[r['retailer_id']]['country'],
        'city_id':headquarters[r['retailer_id']]['city_id']} for r in metadata['retailers']])
    products={p['public']['product_id']:p for p in rich};retailers=[]
    for base in metadata['retailers']:
        r=deepcopy(base);rid=r['retailer_id'];merchant=next(m for m in network['merchants'] if m['retailer_id']==rid);r['geography']=merchant
        r['name']=names[rid]
        tendency=draw(seed,rid+'/stock-tendency',cfg['stock']['tendency_weights']);r['stock_tendency']=tendency
        r['supplier_enabled']=rng(seed,rid+'/supplier-enabled').random()<cfg['supplier']['retailer_enabled_probability']
        r['source_locations']=[{'source_id':merchant['warehouse']['location_id'],'kind':'warehouse','location':merchant['warehouse'],'shipping_enabled':True,
                               'dispatch_days':int(draw(seed,rid+'/warehouse-dispatch',geo['dispatch_timing']['warehouse_calendar_day_probabilities']))}]
        r['source_locations'] += [{'source_id':b['branch_id'],'kind':'branch','location':b['location'],'shipping_enabled':b['shipping_enabled'],
            'dispatch_days':int(draw(seed,b['branch_id']+'/dispatch',geo['dispatch_timing']['branch_calendar_day_probabilities']))} for b in merchant['branches']]
        r['initial_form']=addresses.autofill(seed,rid,address['addresses'],address['outside_postcode'],address['parameters'])
        threshold=shipping['free_shipping_threshold'];r['free_shipping_threshold_minor']=rng(seed,rid+'/free-threshold-value').choice(threshold['threshold_minor_values_equal_weight']) if rng(seed,rid+'/free-threshold-enabled').random()<threshold['enabled_probability_by_profile'][profiles[rid]['profile_id']] else None
        r['contracts']=[]
        for contract in r.pop('shipping_options'):
            cid=address['carriers'][int(contract['carrier_id'].split('-')[1])]['carrier_id']
            r['contracts'].append({'carrier_id':cid,'tiers':contract['tiers'],
                'collection_fee_minor':int(draw(seed,rid+'/'+cid+'/collection-fee',shipping['retailer_carrier_standard_collection_base_fee_minor_probabilities'])),
                'home_delta_minor':int(draw(seed,rid+'/'+cid+'/home-fee',shipping['home_delivery_relative_to_collection_minor_probabilities']))})
        r['catalog']=[];r['offers']=[];r['conditions']=[]
        for pid in r['product_ids']:
            p=products[pid];public=p['public'];listing=population.list_skus(seed,rid+'/'+pid,public['skus'],p['axes'])
            listed={s['sku_id']:s for s in public['skus'] if s['sku_id'] in listing['sku_ids']};amounts={sid:{} for sid in listed}
            probabilities=native.stock_distribution(tendency,p['stock_tendency'],cfg['stock'])
            for source in r['source_locations']:
                condition=draw(seed,rid+'/'+pid+'/'+source['source_id']+'/condition',probabilities)
                r['conditions'].append({'product_id':pid,'source_id':source['source_id'],'condition':condition,'probabilities':probabilities})
                for sid in listed:
                    key=rid+'/'+sid+'/'+source['source_id'];zero=rng(seed,key+'/zero').random()<cfg['stock']['zero_probability'][condition]
                    amounts[sid][source['source_id']]=0 if zero else rng(seed,key+'/quantity').randint(*cfg['stock']['quantity_ranges'][r['scale']][condition])
            wait=rng(seed,rid+'/'+pid+'/supplier-wait').randint(*cfg['supplier']['outlier_wait_days' if rng(seed,rid+'/'+pid+'/supplier-outlier').random()<cfg['supplier']['outlier_probability'] else 'normal_wait_days'])
            disclosure='shipping_policy' if rng(seed,rid+'/'+pid+'/supplier-disclosure').random()<cfg['supplier']['policy_only_disclosure_probability'] else 'product_page'
            for sid,s in listed.items():
                on_hand=any(source['shipping_enabled'] and amounts[sid][source['source_id']]>0 for source in r['source_locations'])
                supplier=r['supplier_enabled'] and not on_hand and rng(seed,rid+'/'+sid+'/supplier-eligible').random()<cfg['supplier']['sku_eligible_probability']
                price,trace=_offer_price(seed,rid,public,s,cfg['retailer_price'])
                r['offers'].append({'offer_id':rid+'/'+sid,'product_id':pid,'sku_id':sid,'price_minor':price,'currency':'SEK','stock_by_source':amounts[sid],
                    'supplier_order':{'enabled':supplier,'wait_days':wait if supplier else None,'disclosure':disclosure if supplier else None},'price_trace':trace})
            warehouse=r['source_locations'][0]['source_id'];policy,pages=_grouping(seed,rid,p,[{'sku_id':sid,'stock':amounts[sid][warehouse]} for sid in listed])
            r['catalog'].append({'product_id':pid,'policy':policy,'pages':pages,'listing_trace':listing})
        retailers.append(r)
    world={'schema_version':VERSION,'seed':seed,'quote_as_of':cfg['quote_as_of'],'status':'opt_in_candidate_commerce',
        'controls':metadata['controls'],'concentration_concepts':list(tasks),'user_location':user,
        'address_context':{k:v for k,v in address.items() if k!='retailers'},'shipping_policy':deepcopy(shipping),
        'brands':brands,'products':rich,'retailers':retailers,
        'carrier_evidence':carrier_reviews(seed,city_id,{'shipments_per_carrier':cfg['authoring_defaults']['carrier_histories_per_carrier']}),
        'config':cfg,'diagnostics':metadata['diagnostics'],
        'provenance':{'accepted_package_gates':gates,'retailer_naming_version':retailer_naming.VERSION,'native_commerce_config_sha256':native.digest(cfg),
                      'population_defaults_sha256':native.digest(population.load()[0]),'plan_sha256':native.digest(plan)},
        'limitations':(['Closed five-concept/three-family slice; not all accepted authoring packages.'] if set(concept_ids)<=set(package_export.CONCEPTS) else ['Explicit registered ordinary-parcel slice; not all accepted authoring packages.'])+[
            'Explicit ordinary-parcel commerce classification; manufacturer facts remain unchanged.',
            'Prose mapping remains unmapped unless independently accepted by an explicit later export.',
            'Central basket quotes only; no broad task/matching/grader, account/coupon or purchase adoption.',
            'Current declared SKU-role heuristics and brand positioning weights are tunable fixtures.',
            'Sparse populations/listings/stock are retained; no winner or seed repair.']}
    world['summary']={'brands':len(brands),'products':len(rich),'skus':sum(len(p['public']['skus']) for p in rich),
        'retailers':len(retailers),'offers':sum(len(r['offers']) for r in retailers),
        'families':dict(Counter(p['public']['family_id'] for p in rich)),
        'unlisted_products':len(set(products)-{pid for r in retailers for pid in r['product_ids']})}
    # Assortment sampling above needs roles keyed by the typed SKU values.
    # Persist only JSON object keys before computing any world/plan binding:
    # numeric keys otherwise change their sorted order when the world is loaded.
    for product in rich:
        for definition in product['axes'].values():
            roles=definition.get('roles')
            if roles is not None and any(type(key) is not str for key in roles):
                definition['roles']=json.loads(json.dumps(roles,allow_nan=False))
    world['world_id']=native.digest(world);validate(world);return world

def validate(world):
    if world.get('schema_version')!=VERSION:raise ValueError('Unsupported commerce schema')
    products={p['public']['product_id']:p for p in world['products']};skus={s['sku_id']:s for p in products.values() for s in p['public']['skus']}
    if len(products)!=len(world['products']) or len(skus)!=sum(len(p['public']['skus']) for p in products.values()):raise ValueError('Duplicate manufacture identity')
    for pid,p in products.items():
        if p['public']['concept_id'] not in package_export.SUPPORTED_CONCEPTS or any(s['product_id']!=pid for s in p['public']['skus']):
            raise ValueError('Unsupported concept or foreign manufacture')
    seen=set()
    for r in world['retailers']:
        sources={s['source_id'] for s in r['source_locations']};listed=set()
        for o in r['offers']:
            if o['offer_id'] in seen or o['sku_id'] not in skus or skus[o['sku_id']]['product_id']!=o['product_id'] or o['product_id'] not in r['product_ids']:raise ValueError('Offer/manufacture/assortment join failed')
            if o['currency']!='SEK' or type(o['price_minor']) is not int or o['price_minor']<=0:raise ValueError('Invalid retailer price')
            if set(o['stock_by_source'])!=sources or any(type(q) is not int or q<0 for q in o['stock_by_source'].values()):raise ValueError('Invalid source stock')
            seen.add(o['offer_id']);listed.add(o['sku_id'])
        pages=[s['sku_id'] for c in r['catalog'] for p in c['pages'] for s in p['listings']]
        if set(pages)!=listed or len(pages)!=len(listed):raise ValueError('Pages and actual listed offers diverge')
    return {'valid':True,'offers':len(seen)}

def pin_sources(world):
    """Complete existing producer source/gate closure, shared by pin formats."""
    from environments.website_world.generation import source_files
    root=package_export.ROOT
    consumer_prefixes=('environments/website_world/', 'environments/website_drafts/',
        'environments/connected_shopping/', 'environments/procedural_commerce/',
        'environments/product_review_sites/', 'intent_browser/')
    paths={root/name for name in source_files() if not name.startswith(consumer_prefixes)}
    paths.update(Path(__file__).parent.glob('*.py'))
    paths.add(root/'docs/agents/accepted-catalog-commerce.md')
    from .catalog_registry import ADDITIONS
    adopted = set(world['config']['concept_ids']) & set(ADDITIONS)
    if adopted:
        from environments.product_world import catalog_publication, reviewed_feature_publication
        from environments.product_world import feature_publication, disclosure_sampling, retailer_disclosure
        for module in (catalog_publication, reviewed_feature_publication, feature_publication,
                       disclosure_sampling, retailer_disclosure):
            paths.add(Path(module.__file__))
        catalogue = reviewed_feature_publication.CATALOGUE
        paths.add(catalogue/'manifest.json')
        paths.update(catalogue/(cid+'.json') for cid in adopted)
    for gate in world['provenance']['accepted_package_gates'].values():
        paths.update(root/name for name in gate['source_hashes'])
    return {str(path.resolve().relative_to(root)):package_export.digest_file(path.resolve())
            for path in sorted(paths)}


def freeze(world, output):
    """Private immutable producer packet; never mount this as a website root."""
    validate(world)
    from . import basket_quote
    root=package_export.ROOT;output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    source_pins=pin_sources(world)
    for name in source_pins:
        target=output/'source-snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/name,target)
    ledger=json.loads(package_export.LEDGER.read_text())
    entries={cid:ledger[cid] for cid in world['provenance']['accepted_package_gates']
             if cid not in package_export.PILOTS}
    artifacts={'world.private.json':world,'basket-plan.private.json':basket_quote.make_plan(world),
               'accepted-entries.private.json':entries,
               'generation-input.private.json':{'seed':world['seed'],'concept_ids':world['config']['concept_ids'],
                   'tasks':world['concentration_concepts'],'controls':world['controls'],
                   'city_id':world['user_location']['city_id'],'review_count':len(world['products'][0]['reviews']) if world['products'] else 0}}
    for name,value in artifacts.items():(output/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    manifest={'schema_version':'accepted-catalog-commerce-pin-v1','world_id':world['world_id'],
        'status':'producer_candidate_consumer_acceptance_pending',
        'files':{n:package_export.digest_file(output/n) for n in artifacts},'source_sha256':source_pins,
        'summary':world['summary'],'source_bytes':sum((root/n).stat().st_size for n in source_pins),
        'model_inference_calls':0,'purchases':0,'limitations':world['limitations']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');return manifest

def load(output):
    output=Path(output).resolve();m=json.loads((output/'manifest.json').read_text())
    if m['schema_version']!='accepted-catalog-commerce-pin-v1':raise ValueError('Unsupported producer pin')
    for name,expected in m['files'].items():
        path=(output/name).resolve()
        if not path.is_relative_to(output) or package_export.digest_file(path)!=expected:raise ValueError('Commerce pin artifact changed: '+name)
    for name,expected in m['source_sha256'].items():
        path=(package_export.ROOT/name).resolve()
        if not path.is_relative_to(package_export.ROOT) or package_export.digest_file(path)!=expected:raise ValueError('Commerce source changed: '+name)
    world=json.loads((output/'world.private.json').read_text());validate(world)
    if world['world_id']!=m['world_id']:raise ValueError('Commerce pin identity differs')
    return world,m
