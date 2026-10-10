"""Connect authored footwear and population references into inspectable worlds."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

from experiments.world_sampling_defaults import model as population
from experiments.address_checkout_pilot import model as addresses
from experiments.carrier_service_pilot.model import generate as carrier_reviews
from environments.product_world import footwear_context_pilot as footwear
from environments.product_world.footwear_retail_content import render_retail_content, bind_page_content
from environments.product_world.footwear_sizing import brand_review_overview, product_review_overview, retailer_fit_notice
from environments.product_world.review_population import summarize_ratings
from environments.product_world.geography import cities, location, neighbour_countries, haversine, route
from environments.product_world.locations import plan_locations
from environments.product_world.naming import retailer_name

VERSION = 'footwear-world-pilot-v1'
ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name('config.json')
OBJECTIVES = ('cheapest_delivered', 'closest_in_stock', 'widest_assortment')


def digest(value):
    return addresses.digest(value)


def seed_for(seed, key):
    return int.from_bytes(hashlib.sha256(f'{VERSION}/{seed}/{key}'.encode()).digest()[:4], 'big')


def rng(seed, key):
    return population.stream(seed, VERSION+'/'+key)


def draw(seed, key, weights):
    return population.weighted(rng(seed, key), weights)


@lru_cache(maxsize=32768)
def _route(origin_json, destination_json, mode):
    return route(json.loads(origin_json), json.loads(destination_json), mode)


def travel(origin, destination, mode='freight'):
    return _route(json.dumps(origin, sort_keys=True), json.dumps(destination, sort_keys=True), mode)


def transit(origin, destination, carrier_offset=0, tier='standard'):
    evidence = travel(origin, destination)
    if evidence['status'] != 'estimated':
        return None
    crossings = sum(leg['kind'] != 'road' for leg in evidence['legs'])
    base = 1 if origin['city_id'] == destination['city_id'] else 1 + math.ceil(evidence['distance_km']/650) + crossings
    if 'air_cargo' in evidence['crossing_kinds']:
        base += 2
    standard = max(1, base + carrier_offset)
    return max(1, standard + {'economy': 1, 'standard': 0, 'express': -1}[tier])


def stock_distribution(retailer_tendency, product_tendency, config):
    scores = {'low': -1, 'typical': 0, 'high': 1}
    combined = scores[retailer_tendency] + scores[product_tendency]
    directions = {'well_stocked': 1, 'patchy': 0, 'mostly_depleted': -1}
    weights = {c: w*config['alignment_multiplier']**(combined*directions[c])
               for c, w in config['condition_weights'].items()}
    total = sum(weights.values())
    return {c: w/total for c, w in weights.items()}


def rounded_price(raw_minor, reference_minor, config):
    step = next(step for upper, step in config['rounding_bands_sek'] if upper is None or reference_minor < upper*100)*100
    # Retain the shared reference price's commercial ending on the offset grid.
    offset = round((raw_minor-reference_minor)/step)*step
    return max(step, reference_minor+offset)


def offer_price(seed, retailer_id, product, config):
    reference = int(product['public']['reference_price_sek']*100)
    r = rng(seed, retailer_id+'/'+product['public']['product_id']+'/price')
    match = r.random() < config['reference_match_probability']
    offset = 0 if match else max(config['offset_min'], min(config['offset_max'], r.gauss(0, config['offset_standard_deviation'])))
    price = rounded_price(reference*(1+offset), reference, config)
    return price, {'matched_reference_draw': match, 'offset_draw': offset, 'reference_minor': reference}


def task_recipe(seed, objective, concept_id=None):
    if objective not in OBJECTIVES:
        raise ValueError('Unsupported bounded task objective')
    concept_id = concept_id or rng(seed, 'task/concept').choice(['footwear.walking_shoes', 'footwear.walking_sandals'])
    if concept_id not in ('footwear.walking_shoes', 'footwear.walking_sandals'):
        raise ValueError('Concept is not authored in this example')
    task = {'objective': objective, 'concept_id': concept_id, 'size_eu': rng(seed, 'task/size').choice([40, 41, 42]),
            'width': 'standard', 'maximum_minor': rng(seed, 'task/budget').choice([100000, 140000, 180000]),
            'delivery_destination_types': ['home'], 'maximum_driving_minutes': 90,
            'facts': {}, 'memory_atoms': [], 'hidden_specs': {}}
    # The fact is chosen before products; do not pick an observed convenient value.
    if rng(seed, 'task/fact').random() < .5:
        task['facts']['cushioning'] = 'substantial'
        task['memory_atoms'].append({'type': 'product_requirement', 'concept_id': concept_id,
                                     'field': 'cushioning', 'operator': 'eq', 'value': 'substantial'})
    return task


def task_prose(task, city):
    noun = 'walking shoes' if task['concept_id'].endswith('walking_shoes') else 'walking sandals'
    budget = task['maximum_minor']//100
    ending = f'EU {task["size_eu"]}, regular width, with a budget of {budget} kr'
    if task['objective'] == 'cheapest_delivered':
        message = f'Can you find the cheapest {noun} in {ending}, including delivery to my address in {city}?'
    elif task['objective'] == 'closest_in_stock':
        message = f'Which physical shop is the shortest drive from my home in {city} and has {noun} in {ending} in stock? It needs to be within a 90-minute drive.'
    else:
        message = f'I want to try on {noun}. Which physical shop has the widest choice that fits {ending}? Somewhere within a 90-minute drive of my home in {city}.'
    memories = ['When shopping for '+noun+', please stick to pairs with substantial cushioning.'] if task['facts'].get('cushioning')=='substantial' else []
    return {'user_message': message, 'memories': memories}


def choose_home(seed, rid, user, international, method, geo):
    known = cities()
    domestic = sorted(c['city_id'] for c in known.values() if c['country'] == user['country'] and c['city_id'] != user['city_id'])
    adjacent = neighbour_countries(user['country'])
    other_countries = sorted({c['country'] for c in known.values()}-{user['country']})
    neighbours = bool(adjacent) and rng(seed, rid+'/foreign-adjacent').random() < geo['foreign_connected_country_probability']
    country = rng(seed, rid+'/foreign-country').choice(adjacent if neighbours else other_countries)
    country_cities = [c for c in known.values() if c['country'] == country]
    foreign = min(country_cities, key=lambda c: (haversine(user, c), c['city_id']))['city_id'] if neighbours else rng(seed, rid+'/foreign-city').choice(country_cities)['city_id']
    weights = dict(geo['base_home_location_weights'])
    if not domestic:
        weights['same_user_city'] += weights['other_city_in_user_country']; weights['other_city_in_user_country'] = 0
    weights['foreign_country'] *= population.foreign_placement_multiplier(user['city_id'], foreign, method, international)
    category = draw(seed, rid+'/home-category', weights)
    return user['city_id'] if category == 'same_user_city' else rng(seed, rid+'/home-domestic').choice(domestic) if category == 'other_city_in_user_country' else foreign


def generate(seed=0, *, objective='cheapest_delivered', concept_id=None, city_id='uppsala', controls=None):
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('Seed must be a nonnegative 31-bit integer')
    if city_id not in cities():
        raise ValueError('Unknown city')
    cfg = json.loads(CONFIG.read_text()); spec = footwear.load_spec()
    plan = json.loads(addresses.PLAN.read_text())
    geo = plan['retailer_population_contract']['geography_and_delivery_policy']; shipping = geo['delivery_options_proposal']
    task = task_recipe(seed, objective, concept_id)
    rich_products = []; rich_brands = []

    def brand_factory(base, earlier):
        brand = footwear.sample_brand(seed_for(seed, 'brands'), len(rich_brands), spec, existing=rich_brands)
        brand['brand_id'] = base['brand_id']; rich_brands.append(brand)
        return {**base, **brand, 'positioning': max(brand['positioning_weights'], key=brand['positioning_weights'].get)}

    def product_factory(base, brand, earlier):
        concept = base['concept_id'].split('.')[1]; pid = base['product_id']; product_seed = seed_for(seed, pid)
        product = footwear.sample_product(product_seed, concept, brand, spec=spec, existing_products=[p['public'] for p in rich_products])
        public = product['public']; old = public['product_id']; public['product_id'] = pid
        for sku in public['skus']:
            sku['sku_id'] = pid+sku['sku_id'][len(old):]; sku['product_id'] = pid
        public['facts']['shipping_class'] = 'regular'
        raw_reference = public['reference_price_sek']
        step = 50 if raw_reference<2000 else 100
        ending = 0 if rng(seed, pid+'/reference-ending').random()<cfg['authoring_defaults']['round_reference_probability'] else -1
        public['reference_price_sek'] = max(1,round((raw_reference-ending)/step)*step+ending)
        product['private']['reference_price_rounding'] = {'positioning_based_draw_sek':raw_reference,'rounding_step_sek':step,'ending':ending}
        product['sample_seed'] = product_seed
        product['stock_tendency'] = draw(seed, pid+'/stock-tendency', cfg['stock']['tendency_weights'])
        product['retail_content'] = render_retail_content(public, seed=product_seed)
        product['reviews'] = footwear.sample_reviews(product_seed, product, spec=spec, count=cfg['authoring_defaults']['product_ratings'])
        for review in product['reviews']:
            review['reviewer_id'] = review['review_id']+'/person'
        product['rating_summary'] = summarize_ratings(product['reviews'])
        product['review_overview'] = product_review_overview(product)
        colours = sorted({s['colour'] for s in public['skus']})
        base_colour = rng(seed, pid+'/standard-colour').choice(colours) if rng(seed, pid+'/has-standard-colour').random() < cfg['authoring_defaults']['standard_colour_probability'] else None
        widths = {s['width'] for s in public['skus']}
        product['axes'] = {'colour': {'kind': 'colour', 'roles': {c: 'base' if c == base_colour else 'alternative' for c in colours}},
                           'width': {'kind': 'configuration', 'roles': {w: 'base' if w == 'standard' else 'extension' for w in sorted(widths)}},
                           'size_eu': {'kind': 'size'}}
        rich_products.append(product)
        return {**base, 'positioning': product['private']['positioning'], 'name': public['name'], 'model_name': public['model_name']}

    metadata = population.sample(seed, tasks=[task['concept_id']], controls=controls, concept_ids=cfg['concept_ids'],
                                 brand_factory=brand_factory, product_factory=product_factory)
    address = addresses.generate(seed, city_id)
    task['user_context'] = {'home_address': deepcopy(address['addresses'][0]['address']), 'home_location_id': 'user-home'}
    task['memory_atoms'].append({'type': 'known_home_address', 'value': deepcopy(address['addresses'][0]['address'])})
    carriers = carrier_reviews(seed, city_id, {'shipments_per_carrier': cfg['authoring_defaults']['carrier_histories_per_carrier']})
    user = address['addresses'][0]['location']; profiles = {}; homes = {}
    method = 'delivery' if objective == 'cheapest_delivered' else 'pickup'
    for retailer in metadata['retailers']:
        rid = retailer['retailer_id']; scale = retailer['scale']; kind = {'small': 'local_shop', 'medium': 'regional_chain', 'large': 'major_retailer'}[scale]
        international = rng(seed, rid+'/international').random() < geo['international_shipping_probability_by_profile'][kind]
        profiles[rid] = {'profile_id': kind, 'international_probability': int(international),
                         'branch_count': rng(seed, rid+'/branches').randint(*cfg['authoring_defaults']['branch_count_ranges'][scale])}
        homes[rid] = choose_home(seed, rid, user, international, method, geo)
    network = plan_locations(seed, user, profiles, config={'transfer_probability': geo['stock_transfers']['enabled_probability']},
                             merchant_home_cities=homes, branch_shipping={'enabled_probability': geo['branch_shipping']['enabled_probability']})
    products_by_id = {p['public']['product_id']: p for p in rich_products}; retailers = []
    for ordinal, retailer in enumerate(metadata['retailers'], 1):
        rid = retailer['retailer_id']; merchant = next(m for m in network['merchants'] if m['retailer_id'] == rid)
        retailer = deepcopy(retailer); retailer['geography'] = merchant
        retailer['name'] = retailer_name(seed, rid, ordinal, 'marketplace' if retailer['template_id'] in ('marketplace','department_store') else 'footwear',
                                         merchant['headquarters']['country'], merchant['headquarters']['city_id'])
        tendency = draw(seed, rid+'/stock-tendency', cfg['stock']['tendency_weights']); retailer['stock_tendency'] = tendency
        retailer['supplier_enabled'] = rng(seed, rid+'/supplier-enabled').random() < cfg['supplier']['retailer_enabled_probability']
        retailer['source_locations'] = [{'source_id': merchant['warehouse']['location_id'], 'kind': 'warehouse', 'location': merchant['warehouse'], 'shipping_enabled': True,
                                         'dispatch_days': int(draw(seed, rid+'/warehouse-dispatch', geo['dispatch_timing']['warehouse_calendar_day_probabilities']))}]
        for branch in merchant['branches']:
            retailer['source_locations'].append({'source_id': branch['branch_id'], 'kind': 'branch', 'location': branch['location'],
                                                 'shipping_enabled': branch['shipping_enabled'],
                                                 'dispatch_days': int(draw(seed, branch['branch_id']+'/dispatch', geo['dispatch_timing']['branch_calendar_day_probabilities']))})
        retailer['initial_form'] = addresses.autofill(seed, rid, address['addresses'], address['outside_postcode'], address['parameters'])
        threshold = shipping['free_shipping_threshold']
        retailer['free_shipping_threshold_minor'] = rng(seed, rid+'/free-threshold-value').choice(threshold['threshold_minor_values_equal_weight']) if rng(seed, rid+'/free-threshold-enabled').random() < threshold['enabled_probability_by_profile'][profiles[rid]['profile_id']] else None
        retailer['contracts'] = []
        for contract in retailer.pop('shipping_options'):
            # Metadata uses zero-based placeholder carrier IDs; bind once to shared carrier identities.
            cid = address['carriers'][int(contract['carrier_id'].split('-')[1])]['carrier_id']
            retailer['contracts'].append({'carrier_id': cid, 'tiers': contract['tiers'],
                                          'collection_fee_minor': int(draw(seed, rid+'/'+cid+'/collection-fee', shipping['retailer_carrier_standard_collection_base_fee_minor_probabilities'])),
                                          'home_delta_minor': int(draw(seed, rid+'/'+cid+'/home-fee', shipping['home_delivery_relative_to_collection_minor_probabilities']))})
        retailer['catalog'] = []; retailer['offers'] = []; retailer['conditions'] = []
        for pid in retailer['product_ids']:
            product = products_by_id[pid]; public = product['public']
            chosen = population.list_skus(seed, rid+'/'+pid, public['skus'], product['axes'])
            policy = population.grouping_policy(seed, rid, {'colour': ['selector','page_partition'], 'width': ['selector','page_partition'] if public['concept']=='walking_shoes' else ['page_partition'], 'size_eu': ['selector']})
            listed = {s['sku_id']: s for s in public['skus'] if s['sku_id'] in chosen['sku_ids']}
            amounts = {sid: {} for sid in listed}; probabilities = stock_distribution(tendency, product['stock_tendency'], cfg['stock'])
            for source in retailer['source_locations']:
                condition = draw(seed, rid+'/'+pid+'/'+source['source_id']+'/condition', probabilities)
                retailer['conditions'].append({'product_id': pid, 'source_id': source['source_id'], 'condition': condition, 'probabilities': probabilities})
                for sid in listed:
                    key = rid+'/'+sid+'/'+source['source_id']; zero = rng(seed, key+'/zero').random() < cfg['stock']['zero_probability'][condition]
                    amounts[sid][source['source_id']] = 0 if zero else rng(seed, key+'/quantity').randint(*cfg['stock']['quantity_ranges'][retailer['scale']][condition])
            price, price_trace = offer_price(seed, rid, product, cfg['retailer_price'])
            wait = rng(seed, rid+'/'+pid+'/supplier-wait').randint(*cfg['supplier']['outlier_wait_days' if rng(seed, rid+'/'+pid+'/supplier-outlier').random()<cfg['supplier']['outlier_probability'] else 'normal_wait_days'])
            disclosure = 'shipping_policy' if rng(seed, rid+'/'+pid+'/supplier-disclosure').random()<cfg['supplier']['policy_only_disclosure_probability'] else 'product_page'
            warehouse = retailer['source_locations'][0]['source_id']
            for sid in listed:
                regular_online_stock = any(s['shipping_enabled'] and amounts[sid][s['source_id']]>0 for s in retailer['source_locations'])
                supplier_enabled = retailer['supplier_enabled'] and not regular_online_stock and rng(seed, rid+'/'+sid+'/supplier-eligible').random()<cfg['supplier']['sku_eligible_probability']
                retailer['offers'].append({'offer_id': rid+'/'+sid, 'product_id': pid, 'sku_id': sid, 'price_minor': price, 'currency': 'SEK',
                                           'stock_by_source': amounts[sid], 'supplier_order': {'enabled': supplier_enabled, 'wait_days': wait if supplier_enabled else None, 'disclosure': disclosure if supplier_enabled else None},
                                           'price_trace': price_trace})
            groups = footwear.group_pages(public, [{'sku_id': sid, 'stock': amounts[sid][warehouse]} for sid in listed], policy)
            notice = retailer_fit_notice(product['private']['fit_tendency'], spec['fit_notice_probability'], rng(seed, rid+'/'+pid+'/fit-notice'))
            for page in groups:
                page['retail_content'] = bind_page_content(product['retail_content'], page, policy); page['retail_content']['fit_notice'] = notice
                page['warehouse_sold_out'] = page.pop('sold_out')
            retailer['catalog'].append({'product_id': pid, 'policy': policy, 'pages': groups, 'listing_trace': chosen})
        retailers.append(retailer)
    world = {'schema_version': VERSION, 'seed': seed, 'quote_as_of': cfg['quote_as_of'], 'status': 'isolated_authoring_world',
             'controls': metadata['controls'], 'task': {**task, **task_prose(task, cities()[city_id]['name'])},
             'user_location': user, 'address_context': {k: v for k,v in address.items() if k != 'retailers'},
             'shipping_policy': deepcopy(shipping),
             'brands': rich_brands, 'brand_overviews': [brand_review_overview(b,rich_products) for b in rich_brands],
             'products': rich_products, 'retailers': retailers, 'carrier_evidence': carriers,
             'config': cfg, 'diagnostics': metadata['diagnostics'], 'limitations': cfg['limitations'],
             'provenance': {'pilot_config_sha256': digest(cfg), 'footwear_spec_sha256': digest(spec),
                            'population_defaults_sha256': digest(population.load()[0]), 'plan_sha256': digest(plan)}}
    world['task']['memories'].append('My home address is '+', '.join(address['addresses'][0]['display_lines'])+'.')
    world['reference'] = solve(world)
    world['summary'] = summary(world)
    world['world_id'] = digest(world)
    validate(world)
    return world


def delivery_options(world, retailer, offer, *, destination=None):
    """Single-item quotes from one actual source; never sum source stock."""
    destination = destination or world['user_location']; geo = retailer['geography']; user_country = destination['country']
    centre=world['address_context']['region']['centre']
    if destination['city_id']!=centre['city_id'] or math.hypot(destination['local_east_km']-centre['local_east_km'],destination['local_north_km']-centre['local_north_km'])>world['address_context']['region']['radius_km']:
        return []
    if user_country not in geo['fulfilment_policy']['delivery_countries']:
        return []
    context = world['address_context']; carriers = {c['carrier_id']: c for c in context['carriers']}
    services = {s['carrier_id']: s for s in context['services'] if s['shipping_class']=='regular'}
    proposals = world['shipping_policy']
    result = []
    sources = [(s,0,'on_hand') for s in retailer['source_locations'] if s['shipping_enabled'] and offer['stock_by_source'][s['source_id']]>=1]
    if not sources and offer['supplier_order']['enabled']:
        sources = [(retailer['source_locations'][0],offer['supplier_order']['wait_days'],'supplier_order')]
    for source, wait, supply in sources:
        for contract in retailer['contracts']:
            cid = contract['carrier_id']; carrier = carriers[cid]; service = services[cid]
            targets = [('home',destination,None)] + [(p['type'],p['location'],p) for p in context['collection_points'] if p['point_id'] in carrier['collection_point_ids']]
            for kind, target, point in targets:
                if point and math.hypot(target['local_east_km']-destination['local_east_km'], target['local_north_km']-destination['local_north_km'])>3:
                    continue
                freight = travel(source['location'], target)
                if freight['status']!='estimated':
                    continue
                distance_policy=proposals['distance_surcharge'];supplements=proposals['geographic_supplements']
                distance_fee = math.ceil(max(0,freight['distance_km']-distance_policy['first_km_included'])/500)*distance_policy['each_additional_commenced_500km_minor']
                border = source['location']['country'] != target['country']
                supplement = distance_fee+(supplements['cross_border_minor'] if border else 0)+(supplements['non_air_crossing_minor'] if any(k!='air_cargo' for k in freight['crossing_kinds']) else 0)+(supplements['air_cargo_minor'] if 'air_cargo' in freight['crossing_kinds'] else 0)
                threshold = retailer['free_shipping_threshold_minor']
                free = not border and threshold is not None and offer['price_minor']>=threshold
                for tier in contract['tiers']:
                    relation = proposals['service_relations'][tier]
                    collection_base = contract['collection_fee_minor']+relation['base_fee_relative_to_standard_minor']
                    if tier=='economy':collection_base=max(relation['minimum_base_fee_minor'],collection_base)
                    fee = max(0,collection_base+(contract['home_delta_minor'] if kind=='home' else 0))+supplement
                    # Standard waiver; faster-tier extra remains, economy has no extra.
                    if free:fee=max(0,relation['base_fee_relative_to_standard_minor'])
                    ready = wait+source['dispatch_days']+transit(source['location'],target,service['transit_offset_days'],tier)
                    result.append({'source_id':source['source_id'],'supply':supply,'carrier_id':cid,'carrier_name':carrier['name'],'tier':tier,
                                   'destination_type':kind,'point_id':point['point_id'] if point else None,
                                   'ready_days':ready,'arrival_date':(date.fromisoformat(world['quote_as_of'])+timedelta(days=ready)).isoformat(),
                                   'shipping_minor':fee,'total_minor':offer['price_minor']+fee,'route':freight,'supplier_wait_days':wait,
                                   'scheduling':service['scheduling'] if kind=='home' else 'collection_after_ready',
                                   'collection_hours':point['weekly_hours'] if point else None})
    return result


def pickup_options(world, retailer, offer, *, include_transfers=True):
    result = []; warehouse = retailer['source_locations'][0]
    for branch in retailer['geography']['branches']:
        bid = branch['branch_id']; stock = offer['stock_by_source'][bid]; ready = 0; source = bid
        if stock<1:
            if not include_transfers or not retailer['geography']['fulfilment_policy']['warehouse_transfer_enabled'] or offer['stock_by_source'][warehouse['source_id']]<1:
                continue
            days = transit(warehouse['location'], branch['location'])
            if days is None:continue
            ready = warehouse['dispatch_days']+days; source = warehouse['source_id']
        driving = travel(world['user_location'],branch['location'],'driving')
        if driving['status']!='estimated':continue
        result.append({'branch_id':bid,'branch_name':branch['name'],'source_id':source,'ready_days':ready,'requires_transfer':source!=bid,
                       'price_minor':offer['price_minor'],'travel':{mode:travel(world['user_location'],branch['location'],mode) for mode in ('walking','cycling','driving')}})
    return result


def matches(world, product, sku, task=None):
    task = task or world['task']
    return (product['concept_id']==task['concept_id'] and sku['size_eu']==task['size_eu'] and sku['width']==task['width'] and
            all(product['facts'].get(k)==v for k,v in task['facts'].items()))


def solve(world):
    """Bounded offline reference calculation; not a response grader."""
    task=world['task']; products={p['public']['product_id']:p['public'] for p in world['products']}
    candidates=[]; assortment={}
    for retailer in world['retailers']:
        for offer in retailer['offers']:
            product=products[offer['product_id']];sku=next(s for s in product['skus'] if s['sku_id']==offer['sku_id'])
            if not matches(world,product,sku):continue
            base={'retailer_id':retailer['retailer_id'],'offer_id':offer['offer_id'],'product_id':product['product_id'],'sku_id':sku['sku_id'],'name':product['name'],'price_minor':offer['price_minor']}
            if task['objective']=='cheapest_delivered':
                for q in delivery_options(world,retailer,offer):
                    if q['destination_type'] in task['delivery_destination_types'] and q['total_minor']<=task['maximum_minor']:
                        candidates.append({**base,**q,'score':q['total_minor']})
            elif offer['price_minor']<=task['maximum_minor']:
                for q in pickup_options(world,retailer,offer,include_transfers=False):
                    if q['travel']['driving']['duration_minutes']>task['maximum_driving_minutes']:continue
                    row={**base,**q,'score':q['travel']['driving']['duration_minutes']}
                    if task['objective']=='closest_in_stock':candidates.append(row)
                    else:
                        group=assortment.setdefault(q['branch_id'],{'retailer_id':retailer['retailer_id'],'branch_id':q['branch_id'],'branch_name':q['branch_name'],'products':{},'travel':q['travel']})
                        group['products'].setdefault(product['product_id'],[]).append(base)
    if task['objective']=='widest_assortment':
        candidates=[{**g,'matching_product_count':len(g['products']),'score':-len(g['products'])} for g in assortment.values()]
    if not candidates:return {'status':'no_match','candidates':0,'winners':[],'scope':'Bounded two-concept, global-retailer reference; no evidence-coverage restriction.'}
    score=min(c['score'] for c in candidates);winners=[c for c in candidates if c['score']==score]
    return {'status':'match','candidates':len(candidates),'best_score':score,'winners':winners,'ties_retained':True,
            'count_basis':'Distinct products at one branch; not colours, sizes or summed retailer inventory.' if task['objective']=='widest_assortment' else 'All eligible options; no undocumented tie breaker.'}


def summary(world):
    owners={p['public']['product_id']:0 for p in world['products']}
    for r in world['retailers']:
        for pid in r['product_ids']:owners[pid]+=1
    return {'brands':len(world['brands']),'products':len(world['products']),'manufactured_skus':sum(len(p['public']['skus']) for p in world['products']),
            'retailers':len(world['retailers']),'listed_offers':sum(len(r['offers']) for r in world['retailers']),
            'branches':sum(len(r['geography']['branches']) for r in world['retailers']),
            'products_at_multiple_stores':sum(n>1 for n in owners.values()),'unlisted_products':sum(n==0 for n in owners.values()),
            'ratings':sum(len(p['reviews']) for p in world['products']),'written_reviews':sum(bool(r['text']) for p in world['products'] for r in p['reviews']),
            'carrier_ratings':len(world['carrier_evidence']['public']['reviews'])}


def validate(world):
    products={p['public']['product_id']:p for p in world['products']}
    if len(products)!=len(world['products']):raise ValueError('Duplicate product IDs')
    skus={s['sku_id']:s for p in products.values() for s in p['public']['skus']}
    if len(skus)!=sum(len(p['public']['skus']) for p in products.values()):raise ValueError('Duplicate SKU IDs')
    brand_ids={b['brand_id'] for b in world['brands']}
    names=set()
    for p in products.values():
        public=p['public'];name=(public['brand_id'],public['model_name'].casefold())
        if name in names or public['brand_id'] not in brand_ids:raise ValueError('Invalid brand/name identity')
        names.add(name)
        for review in p['reviews']:
            if review['sku_id'] not in skus or skus[review['sku_id']]['product_id']!=public['product_id']:raise ValueError('Review SKU binding mismatch')
    for retailer in world['retailers']:
        source_ids={s['source_id'] for s in retailer['source_locations']}
        offers={o['sku_id']:o for o in retailer['offers']}
        if len(offers)!=len(retailer['offers']):raise ValueError('Duplicate listing')
        pages=[s['sku_id'] for entry in retailer['catalog'] for page in entry['pages'] for s in page['listings']]
        if set(pages)!=set(offers) or len(pages)!=len(offers):raise ValueError('Page membership differs from listed SKUs')
        for offer in offers.values():
            if offer['sku_id'] not in skus or skus[offer['sku_id']]['product_id']!=offer['product_id'] or offer['product_id'] not in retailer['product_ids']:raise ValueError('Invented SKU/product listing')
            if set(offer['stock_by_source'])!=source_ids or any(type(q) is not int or q<0 for q in offer['stock_by_source'].values()):raise ValueError('Invalid source stock')
    if 'world_id' in world and digest({k:v for k,v in world.items() if k!='world_id'})!=world['world_id']:raise ValueError('World hash mismatch')
