"""Explicit fixture audits and grounded answer failures; no new world draws."""
from copy import deepcopy

import pytest

from experiments.accepted_catalog_commerce import basket_quote
from experiments.accepted_catalog_commerce.prepared_quote import prepare
from experiments.accepted_catalog_commerce.test_basket_quote import bridged
from experiments.footwear_world_pilot.test_basket_quote import world
from environments.website_world import catalog_shipping_claim_task as task, catalog_checkout_domain as checkout
from environments.website_world.catalog_shipping_claim_grading import ShippingClaimGrader
from environments.website_world.adapter import digest


def fixture(original, *, threshold=90000, quantity=2, membership=False, no_stock=False, foreign=False):
    w = bridged(original);w['seed'] = 0
    w['config'] = {'concept_ids': ['footwear.walking_shoes']}
    for p in w['products']:
        p['public']['concept_id'] = 'footwear.walking_shoes'
        p['variant_fields'] = {k: {} for k in ('colour', 'width', 'size_eu')}
    r = w['retailers'][0];r['free_shipping_threshold_minor'] = threshold
    offer = min(r['offers'], key=lambda o: o['offer_id']);offer['price_minor'] = 45000
    # An exact-SKU audit must resolve identity independently of the expected
    # target. Carry a second manufactured SKU on the same model page so a
    # response omitting both SKU and selectors really is ambiguous.
    product = next(p for p in w['products'] if p['public']['product_id'] == offer['product_id'])
    # The retained basket fixture intentionally has one SKU per model. Author
    # the alternate explicitly in this local test fixture rather than assuming
    # an unseen manufactured variant exists or changing a real sampled world.
    alternate_sku = deepcopy(next(s for s in product['public']['skus']
                                  if s['sku_id'] == offer['sku_id']))
    alternate_sku.update(sku_id=offer['sku_id']+'/authored-alternate',
                         colour='black' if alternate_sku['colour'] != 'black' else 'blue')
    product['public']['skus'].append(alternate_sku)
    alternate = deepcopy(offer)
    alternate.update(offer_id=offer['offer_id']+'/authored-alternate', sku_id=alternate_sku['sku_id'])
    r['offers'].append(alternate)
    r['catalog'] = [{'product_id':pid, 'pages': [{'page_key':{}, 'listings': [
        {'sku_id':o['sku_id']} for o in r['offers'] if o['product_id']==pid]}]}
        for pid in dict.fromkeys(o['product_id'] for o in r['offers'])]
    if no_stock:
        offer['stock_by_source'] = dict.fromkeys(offer['stock_by_source'], 0)
    if foreign:
        from experiments.footwear_world_pilot.model import cities
        city = cities()['oslo']
        for source in r['source_locations']:
            source['location'].update(city_id='oslo', country=city['country'], latitude=city['latitude'], longitude=city['longitude'])
    plan = basket_quote.make_plan(w, retailer_policies={r['retailer_id']: {'membership_active': membership}})
    q = prepare(w, plan=plan);d = checkout.make(w)
    t = task.make(w, {'kind': task.KIND, 'quantity': quantity, 'delivery_types': ['home']}, quote_context=q, checkout_domain=d)
    ref = task.reference(w, t, quote_context=q, checkout_domain=d)
    links = {}
    for o in r['offers']:
        links[o['offer_id']] = {**{k: o[k] for k in ('offer_id', 'product_id', 'sku_id')},
            'retailer_id': r['retailer_id'], 'url': 'https://shop.test/#/product/'+o['product_id'],
            'selection': {}, 'required_selection': {}}
    g = ShippingClaimGrader(w, t, ref, {'retailer_offers': links}, quote_context=q, checkout_domain=d)
    return w,t,ref,q,d,g


def claims(values):
    _,t,r,_,_,g = values;s = t['subject']; c = lambda v, e: {'value': v, 'evidence': e if v is not None else None}
    text = s['product_name']+' at '+s['retailer_name']+'. SKU '+s['sku_id']+'. '
    url = g.identity.links[s['offer_id']]['url'];policy = 'https://shop.test/#/info/shipping'
    text += url+' '+policy+'. '
    quantity = 'Quantity '+str(r['quantity']);options = str(r['option_count'])+' options';free = str(r['free_option_count'])+' free options'
    test = {'meets_threshold': 'Subtotal meets threshold', 'below_threshold': 'Subtotal below threshold', 'no_threshold': 'No threshold'}[r['subtotal_test']]
    verdict = {'all_free': 'All free', 'some_free': 'Some free', 'none_free': 'None free', 'unavailable': 'Unavailable'}[r['assessment']]
    text += '. '.join([quantity, options, free, test, verdict])+'. '
    money = {}
    for field,key in [('unit_price','unit_price_minor'),('subtotal','subtotal_minor'),('advertised_threshold','advertised_threshold_minor'),('minimum_shipping','minimum_shipping_minor'),('maximum_shipping','maximum_shipping_minor')]:
        value = r[key]
        if value is None:money[field] = None;continue
        token = str(value//100)+'.'+f'{value%100:02d}'
        evidence = field.replace('_',' ')+' '+token+' SEK';text += evidence+'. '
        money[field] = {'amount': token, 'currency': 'SEK', 'evidence': evidence}
    result = {'interpretation':'extracted','issues':[], 'status': c('audit',text),
        'product_name':c(s['product_name'],text), 'retailer_name':c(s['retailer_name'],text),
        'sku_id':c(s['sku_id'],text), 'offer_url':c(url,text), 'policy_url':c(policy,text),
        'variant':{k:c(None,None) for k in g.contract['variant_fields']},'source_urls':[],
        'quantity':c(r['quantity'],quantity),'option_count':c(r['option_count'],options),
        'free_option_count':c(r['free_option_count'],free),
        'subtotal_test':c(r['subtotal_test'],test), 'assessment':c(r['assessment'],verdict), **money}
    return text,result


def test_threshold_equality_and_express_charge_are_separate(world):
    v = fixture(world);_,t,r,_,_,g = v
    assert r['subtotal_minor'] == r['advertised_threshold_minor'] == 90000
    assert r['subtotal_test'] == 'meets_threshold' and r['assessment'] == 'some_free'
    assert r['minimum_shipping_minor'] == 0 and r['maximum_shipping_minor'] > 0
    assert g.grade(*reversed(claims(v)))['structured_claims_correct']
    assert 'Reaching the number alone does not guarantee' in t['user_message']


@pytest.mark.parametrize('threshold,quantity,membership,test,assessment', [
    (90001,2,False,'below_threshold','none_free'),
    (90000,1,True,'below_threshold','some_free'),
    (None,2,False,'no_threshold','none_free'),
    (0,1,False,'meets_threshold','some_free')])
def test_absence_zero_and_active_benefit_are_distinct(world,threshold,quantity,membership,test,assessment):
    v = fixture(world,threshold=threshold,quantity=quantity,membership=membership)
    assert v[2]['subtotal_test'] == test and v[2]['assessment'] == assessment
    assert v[-1].grade(*reversed(claims(v)))['structured_claims_correct']


def test_unavailable_extrema_are_undefined_not_free(world):
    v = fixture(world,no_stock=True);r=v[2]
    assert r['assessment'] == 'unavailable' and r['option_count'] == r['free_option_count'] == 0
    assert r['minimum_shipping_minor'] is r['maximum_shipping_minor'] is None
    assert v[-1].grade(*reversed(claims(v)))['structured_claims_correct']


def test_foreign_source_can_meet_number_without_fee_waiver(world):
    v = fixture(world,foreign=True)
    assert v[2]['subtotal_test'] == 'meets_threshold' and v[2]['assessment'] == 'none_free'


@pytest.mark.parametrize('field', ['quantity','option_count','free_option_count'])
def test_wrong_or_missing_integer_claims_fail(world,field):
    v=fixture(world);text,c=claims(v)
    c[field]={'value':None,'evidence':None}
    assert not v[-1].grade(c,text)['structured_claims_correct']
    c[field]={'value':99,'evidence':'99 '+field};text+='99 '+field
    assert not v[-1].grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('field', ['unit_price','subtotal','advertised_threshold','minimum_shipping','maximum_shipping'])
def test_wrong_money_or_currency_fails(world,field):
    v=fixture(world);text,c=claims(v);token=c[field]['amount'];extra=field+' '+token+' USD'
    text+=extra;c[field].update(currency='USD',evidence=extra)
    assert not v[-1].grade(c,text)['structured_claims_correct']
    text,c=claims(v);c[field]=None
    assert not v[-1].grade(c,text)['structured_claims_correct']


def test_exact_sku_not_repaired_from_target_or_amount(world):
    v=fixture(world);text,c=claims(v);c['sku_id']={'value':None,'evidence':None}
    assert not v[-1].grade(c,text)['structured_claims_correct']
    assert len(v[-1].grade(c,text)['identity_resolution']['offer_ids']) > 1
    text,c=claims(v);foreign='foreign-sku';text+=foreign;c['sku_id']={'value':foreign,'evidence':foreign}
    assert not v[-1].grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('url',['https://foreign.test/#/info/shipping','https://shop.test/#/home','https://shop.test/#/info/shipping?foo=1'])
def test_foreign_or_unrelated_policy_link_fails(world,url):
    v=fixture(world);text,c=claims(v);text+=url;c['policy_url']={'value':url,'evidence':url}
    assert not v[-1].grade(c,text)['structured_claims_correct']


def test_negated_assessment_and_ungrounded_values_reject(world):
    v=fixture(world);text,c=claims(v)
    c['assessment']={'value':'all_free','evidence':'Not all free'};text+='Not all free'
    assert v[-1].validate_claims(c,text)['assessment']==c['assessment']
    assert not v[-1].grade(c,text)['structured_claims_correct']
    text,c=claims(v);c['subtotal']['evidence']='absent quote'
    with pytest.raises(ValueError):v[-1].grade(c,text)


@pytest.mark.parametrize('options,field,wording', [
    ({}, 'assessment', 'Not some free'),
    ({'quantity': 1}, 'assessment', 'Not none free'),
    ({'no_stock': True}, 'assessment', 'Not unavailable'),
    ({'quantity': 1}, 'subtotal_test', 'Not below threshold'),
    ({'threshold': None}, 'subtotal_test', 'Not no threshold')])
def test_semantic_wording_is_extractor_owned_and_missing_verdict_fails(world,options,field,wording):
    v=fixture(world,**options);text,c=claims(v)
    c[field]['evidence']=wording;text+=' '+wording
    assert v[-1].validate_claims(c,text)[field]==c[field]
    c[field]={'value':None,'evidence':None}
    assert not v[-1].grade(c,text)['structured_claims_correct']


def test_explicit_does_not_meet_is_below_threshold(world):
    v=fixture(world,quantity=1);text,c=claims(v)
    wording='Subtotal does not meet the threshold'
    c['subtotal_test']['evidence']=wording;text+=' '+wording
    assert v[-1].grade(c,text)['structured_claims_correct']


@pytest.mark.parametrize('field',['assessment','subtotal_test'])
def test_missing_verdict_remains_undefined(world,field):
    v=fixture(world);text,c=claims(v);c.pop(field)
    assert not v[-1].grade(c,text)['structured_claims_correct']


def test_task_quantity_menu_and_world_binding_cannot_drift(world):
    v=fixture(world);w,t,r,q,d,_=v
    before=deepcopy(w);task.reference(w,t,quote_context=q,checkout_domain=d);assert w==before
    t['quantity']+=1
    with pytest.raises(ValueError):task.reference(w,t,quote_context=q,checkout_domain=d)
    with pytest.raises(ValueError):task.make(w,{'kind':task.KIND,'quantity':21},quote_context=q,checkout_domain=d)
    w['retailers'][0]['offers'][0]['price_minor']+=1
    with pytest.raises(ValueError):task.make(w,{'kind':task.KIND},quote_context=q,checkout_domain=d)


@pytest.mark.parametrize('bad',[{'quantity':True},{'quantity':0},{'quantity':1.5},{'retailer_index':-1},{'offer_index':'0'},{'delivery_types':['retailer_branch']},{'delivery_types':['home','home']},{'objective':'cheapest'}])
def test_invalid_notation_rejects_before_factory(bad):
    from environments.website_world import catalog_shipping_claim_generation as generation
    request={'schema':'website-world-generation-v2','seed':87,'task':{'kind':task.KIND,**bad}}
    calls=[]
    with pytest.raises(ValueError):generation.generate(request,world_factory=lambda *a,**k:calls.append(1))
    assert not calls
