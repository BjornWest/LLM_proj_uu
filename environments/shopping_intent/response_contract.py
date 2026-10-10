"""Task semantics -> reusable response facts and deterministic check bindings.

This describes what an answer can claim, not the correct values. It does not
inspect candidates, stock, hidden preferences, reference answers or state journals.
New instances of supported operations need no extractor schema of their own.
"""
from copy import deepcopy

VERSION='shopping-response-contract-v2'

MEAN_STATISTIC = {
    'operation': 'mean', 'measure': 'total_minor',
    'population': 'cheapest_eligible_quote_per_retailer',
    'rounding': 'nearest_minor_unit_half_up', 'empty': 'undefined',
}


def validate_query(query, operation, activity):
    """Reject semantics for which the response/check primitives have no meaning.

    Omitted objective/statistic retain the legacy minimal-task defaults. An
    explicitly supplied statistic must describe the entire supported operation.
    """
    objectives = query.get('objective', [])
    allowed = {
        'delivery': {'total_minor', 'arrival_days', 'unit_price'},
        'pickup': {'total_minor', 'ready_days', 'travel_minutes'},
        'inspect': {'travel_minutes', 'total_minor'},
    }[activity]
    if operation == 'assortment':
        allowed = {'matching_model_count'} if activity == 'inspect' else set()
    if not isinstance(objectives, list):
        raise ValueError('Unsupported objective definition')
    for objective in objectives:
        if (not isinstance(objective, dict) or set(objective) != {'field', 'direction'}
                or objective['field'] not in allowed or objective['direction'] not in ('min', 'max')):
            raise ValueError('Unsupported objective for response activity: ' + repr(objective))
    if operation == 'aggregate':
        if activity != 'delivery' or objectives or query.get('unit'):
            raise ValueError('Unsupported aggregate activity/objective/unit semantics')
        if query.get('statistic', MEAN_STATISTIC) != MEAN_STATISTIC:
            raise ValueError('Unsupported statistic definition')
    elif 'statistic' in query:
        raise ValueError('Unsupported statistic for non-aggregate response')

# Vocabulary shared by task rendering, extraction and deterministic checking.
FACTS={
 'status':('status','status','What the answer claims: recommendation, average, no matching option, or uncertainty.'),
 'source_urls':('citations','source_urls','Other cited evidence links copied from the final answer.'),
 'offer_url':('string','offer_url','Exact recommended retailer product URL, preserving variant query parameters.'),
 'sku_id':('string','sku_id','An explicitly stated SKU identifier. Do not extract an ID from a URL.'),
 'retailer_id':('string','retailer_id','Explicit retailer ID or name for the recommendation; never guess an internal ID.'),
 'offer_id':('string','offer_id','Explicitly stated offer identifier.'),
 'comparison_url':('string','comparison_url','The comparison-page URL supplied for the recommendation.'),
 'coupon_code':('string','coupon_code','Coupon code explicitly stated as used for the recommended price.'),
 'offers':('conditional_offers','offers','Every explicitly stated full payable price alternative for the SAME primary recommended SKU/store/fulfilment, including standard and conditional prices. Preserve the conditions linking each price; do not choose the cheapest. Other products must not be mixed into this list.'),
 'total':('money','total_minor','Stated full payable total and currency. Do not calculate omitted totals.'),
 'average':('money','value_minor','Stated mean price and currency. Do not compute it from listed offers.'),
 'average_undefined':('boolean','average_undefined','True only when the answer explicitly says that the mean is undefined or cannot be calculated for an empty population; absent otherwise.'),
 'retailer_count':('integer','retailer_count','Explicit number of retailers included in the average.'),
 'branch_id':('string','branch_id','Explicit branch identifier for pickup or inspection.'),
 'travel_mode':('string','travel_mode','Explicit travel mode for the recommended branch.'),
 'travel_minutes':('integer','travel_minutes','Explicit one-way journey duration in whole minutes.'),
 'arrival_days':('integer','arrival_days','Explicit calendar days until delivery arrives; do not confuse dispatch or pickup readiness with arrival.'),
 'ready_days':('integer','ready_days','Explicit calendar days until ready for collection; not a delivery-arrival estimate.'),
 'unit_price':('ratio','unit_price','Explicit unit-price ratio; automatic prose extraction is not yet supported.'),
}


def compile_response_contract(task):
    query=task['query'];operation=query['operation'];activity=query.get('activity','delivery')
    if operation not in ('select','aggregate','assortment'):raise ValueError('Unsupported response operation: '+str(operation))
    if activity not in ('delivery','pickup','inspect'):raise ValueError('Unsupported response activity')
    validate_query(query, operation, activity)
    fields=['status','source_urls'];checks=[];unsupported=[]
    def eq(identifier,field,path,kind='integer',source='selected',allow_null=False):
        checks.append({'id':identifier,'field':field,'source':source,'path':path,'kind':kind,'allow_null':allow_null})
    if operation=='aggregate':
        fields+=['average','average_undefined','retailer_count']
        statuses=['average','no_match','uncertain']
        eq('reported_average','value_minor',['value_minor'],source='reference',allow_null=True)
        eq('reported_retailer_count','retailer_count',['retailer_count'],source='reference')
    elif operation=='select':
        fields+=['offer_url','sku_id','retailer_id','offer_id','comparison_url','coupon_code']
        statuses=['selection','no_match','uncertain']
        if activity!='inspect':
            fields+=['total','offers'];eq('reported_total','total_minor',['total_minor'])
        if activity in ('pickup','inspect'):
            fields+=['branch_id','travel_mode','travel_minutes']
            eq('reported_branch','branch_id',['branch_id'],kind='string')
            eq('reported_travel_mode','travel_mode',['world_facts','travel_mode'],kind='string')
            eq('reported_travel_minutes','travel_minutes',['travel_minutes'])
        if activity=='delivery' and any(o['field']=='arrival_days' for o in query.get('objective',[])):
            fields+=['arrival_days'];eq('reported_arrival_days','arrival_days',['arrival_days'])
        if activity=='pickup':
            fields+=['ready_days'];eq('reported_ready_days','ready_days',['ready_days'])
        if any(o['field']=='unit_price' for o in query.get('objective',[])) or query.get('unit'):
            fields+=['unit_price'];eq('reported_unit_price','unit_price',['unit_price'],kind='ratio')
            unsupported.append('Unit-price prose extraction needs a reusable ratio interpreter')
        if len(task.get('lines',[None]))!=1:unsupported.append('Basket response extraction is not implemented')
    else:
        statuses=['branch_assortment','no_match','uncertain']
        unsupported.append('Assortment response grading/extraction is not implemented')
    link=task.get('response_requirements',{}).get('selection_link','retailer')
    if link not in ('retailer','comparison'):raise ValueError('Unsupported response link destination')
    specs={key:{'kind':FACTS[key][0],'oracle_field':FACTS[key][1],'description':FACTS[key][2]} for key in fields}
    if operation=='aggregate':specs['source_urls']['description']='Optional useful price-overview/evidence links; individual SKU links are not required.'
    weight=task.get('response_requirements',{}).get('price_comparison_bonus_weight',0)
    if type(weight) not in (int,float) or not 0<=weight<=1:raise ValueError('Invalid price comparison bonus weight')
    if weight and 'offers' not in fields:raise ValueError('Price comparison bonus requires a priced selection')
    result = {'schema_version':VERSION,'operation':operation,'activity':activity,'statuses':statuses,
            'price_comparison_bonus_weight':weight,'fields':specs,'checks':checks,'selection_link':link,'unsupported_extraction':unsupported}
    from .detail_contract import compile_details
    details = compile_details(task)
    if details is not None:
        result.update(schema_version='shopping-response-contract-v3', factual_details=details)
    return result


def response_descriptions(task):
    c=compile_response_contract(task)
    return {key:spec['description'] for key,spec in c['fields'].items()}


def evaluate_response_checks(contract, answer, *, selected=None, reference=None):
    """Exact primitives. A missing value is never equal to an expected null/zero."""
    checks={}
    for spec in contract['checks']:
        root=selected if spec['source']=='selected' else reference
        if root is None:continue
        expected=root
        for key in spec['path']:
            expected=expected.get(key) if isinstance(expected,dict) else None
        field=spec['field'];actual=answer.get(field)
        kind=spec['kind'];valid=(field in answer)
        if expected is None and spec['allow_null']:
            valid=valid and actual is None
        elif kind=='integer':valid=valid and type(actual) is int and type(expected) is int and actual==expected
        elif kind=='string':valid=valid and isinstance(actual,str) and isinstance(expected,str) and actual==expected
        elif kind=='ratio':valid=valid and isinstance(actual,dict) and actual==expected
        else:valid=False
        checks[spec['id']]=bool(valid)
    return checks
