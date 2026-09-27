"""Trusted single-line candidate adapter for frozen geographic shopping worlds."""
from decimal import Decimal

from environments.shopping_intent.oracle import analyze
from .generator import digest
from .locations import validate_locations, quote
from .stores import validate_store_world
from .reviews import statistics


def candidates_for(scenario):
    world=scenario['bundle'];locations=scenario.get('locations');task=scenario['task']['resolved_task']
    if len(task['lines'])!=1:raise ValueError('Reference adapter supports single-product tasks; basket shipping needs a separate adapter')
    if locations is None:raise ValueError('Reference adapter requires geographic quotes')
    validate_store_world(world);validate_locations(world,locations)
    if task['context'].get('destination_location')!=locations['public']['user_location'] or task['context']['destination']!=locations['public']['user_location']['country']:
        raise ValueError('Task destination and geographic evidence disagree')
    line=task['lines'][0];activity=task['query'].get('activity','delivery')
    if activity not in ('delivery','pickup','inspect'):raise ValueError('Unknown world activity')
    mode=next((p['value'] for p in task.get('world_requirements',[]) if p['field']=='travel_mode'),'driving')
    reviews=scenario.get('merchant_reviews');ratings={}
    if reviews is not None:
        provenance=reviews['private_provenance']
        if provenance['source_world_sha256']!=world['world_sha256'] or provenance['public_sha256']!=digest(reviews['public']):
            raise ValueError('Review evidence belongs to another world or was changed')
        for company in reviews['public']['companies']:
            if company['company_id'] in ratings or company['statistics']!=statistics(company['reviews']):
                raise ValueError('Inconsistent merchant review corpus')
            ratings[company['company_id']]=company['statistics']
    stores={s['retailer_id']:s for s in world['public']['retailers']}
    review_evidence={}
    if task.get('product_review_requirements') and scenario.get('product_review_evidence') is not None:
        from .product_review_tasks import summaries_for
        review_evidence=summaries_for(world,scenario['product_review_evidence'],task['product_review_requirements'])
    products={p['product_id']:p for p in world['public']['products']}
    models={v['product_id']:g['group_id'] for g in world['public']['product_groups'] for v in g['variants']}
    merchants={m['retailer_id']:m for m in locations['public']['merchants']}
    accounts=None
    if scenario.get('accounts') is not None:
        from .accounts import AccountSession
        accounts=AccountSession(world,scenario['accounts'])
    candidates=[]
    for offer in world['public']['offers']:
        product=products[offer['product_id']]
        if product['category']!=line['family_id']:continue
        merchant=merchants[offer['retailer_id']]
        branches=[None] if activity=='delivery' else merchant['branches']
        for branch in branches:
            q=quote(world,locations,offer['offer_id'],method=activity,branch_id=branch['branch_id'] if branch else None,quantity=line['quantity'])
            if task['query']['operation']=='assortment':
                # A try-on visit uses today's branch stock and listed item price,
                # not an online coupon or a future warehouse transfer.
                q['total_minor']=offer['price_minor']*line['quantity']
            if accounts is not None and activity!='inspect':q=accounts.best_quote(q)
            rating=ratings.get(offer['retailer_id'],{})
            facts={'merchant_country':stores[offer['retailer_id']]['location']['country'],
                   'merchant_mean_stars':rating.get('mean_stars'),'merchant_review_count':rating.get('review_count')}
            travel=q['travel'][mode] if q['travel'] else None
            if travel:
                facts.update(travel_mode=mode,travel_minutes=travel['duration_minutes'],travel_km=travel['distance_km'],
                             ready_days=q['ready_days'],requires_stock_transfer=q['requires_stock_transfer'])
            if branch: facts['branch_stock_quantity']=q['branch_stock_quantity']
            candidate={'candidate_id':offer['offer_id']+'|'+(branch['branch_id'] if branch else 'delivery'),
                'offer_id':offer['offer_id'],'branch_id':branch['branch_id'] if branch else None,'activity':activity,
                'total_minor':q['total_minor'],'arrival_days':q['ready_days'] if activity=='delivery' else None,
                'ready_days':q['ready_days'],'travel_minutes':travel['duration_minutes'] if travel else None,
                'purchasable':q['eligible'] if activity!='inspect' else None,
                'inspectable':q['eligible'] if activity=='inspect' else None,
                'currency':q['currency'],'destination':task['context']['destination'],
                'delivery_modes':['home' if activity=='delivery' else activity],
                'world_facts':facts,'fulfilment_reason_codes':q['reason_codes'],
                'lines':[{'line_id':line['id'],'family_id':product['category'],'quantity':line['quantity'],
                          'sku_id':product['product_id'],'model_id':models[product['product_id']],
                          'retailer_id':offer['retailer_id'],'facts':product['attributes']}]}
            if accounts is not None and activity!='inspect':
                candidate.update(coupon_id=q.get('coupon_id'),coupon_code=q.get('coupon_code'),discount_minor=q.get('discount_minor',0))
            if task['query'].get('unit'):
                attrs=product['attributes']
                amount=attrs['pack_count']*attrs['volume_ml'] if task['query']['unit']=='litre' else int(Decimal(str(attrs['net_weight_kg']))*1000)
                candidate['unit_price']=None if q['total_minor'] is None else {'cost_minor':q['total_minor'],'quantity_milliunits':amount*line['quantity']}
            if task.get('product_review_requirements'):
                candidate['product_review_evidence']=review_evidence.get(product['product_id'],{})
            candidates.append(candidate)
    return candidates


def evaluate(scenario):
    candidates=candidates_for(scenario)
    return {'schema_version':'world-reference-outcome-v1','candidate_count':len(candidates),
        'outcome':analyze(scenario['task']['resolved_task'],candidates,coverage_complete=True),
        'candidates':candidates,
        'scope':'Frozen single-product reference analysis; not a browser run or full free-text response grade.'}
