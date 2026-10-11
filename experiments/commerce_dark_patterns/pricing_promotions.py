"""Seeded, explicit single-retailer price scenarios; no shared account adoption.

Advertising is presentation data. Every payable quote uses actual native stock,
shipping and tariff calculations plus this family's declared promotion/fee terms.
Default worlds are small authored fixtures, not sampled accepted product worlds.
"""
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from random import Random

from experiments.accepted_catalog_commerce import basket_quote, package_export, catalog_registry
from environments.product_world import geography, generator
from . import request_labels

VERSION = 'commerce-pricing-promotions-v1'
EVIDENCE_VERSION = 'commerce-pricing-evidence-v1'
MECHANISMS = ('from_price_variant', 'stale_advertised_price', 'late_mandatory_fee',
              'membership_condition', 'quantity_condition', 'expired_promotion',
              'variant_condition', 'nonstacking_promotions', 'discount_shipping_loss',
              'truthful_offer')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _minor(value, minimum=0):
    return type(value) is int and minimum <= value <= 10**9


def _digest(value):
    return basket_quote.model.digest(value)


def _quote_identity(value):
    return _digest({k: v for k, v in value.items()
                    if k not in ('quote_id', 'promotion_feedback', 'requested_promotion_codes')})


def _select_option(quoted, option):
    value = deepcopy(quoted)
    value['selected'] = deepcopy(option)
    value['total_minor'] = option['total_minor']
    value['quote_id'] = _quote_identity(value)
    return value


_DECISION_KEYS = {'offer_id', 'quantity', 'promotion_codes', 'quote_id',
                  'total_minor', 'delivery_selection'}
_EVENT_KINDS = {'cookie_dialog', 'cookie_save', 'newsletter_change', 'extras_change',
                'site_preselect', 'basket_change', 'promotion_apply', 'promotion_remove',
                'delivery_select', 'checkout_enter', 'checkout_leave', 'order_submit'}


def _decision_valid(value):
    if value is None:
        return True
    return (type(value) is dict and set(value) == _DECISION_KEYS
            and type(value['offer_id']) is str and bool(value['offer_id'])
            and _minor(value['quantity'], 1)
            and type(value['total_minor']) is int and value['total_minor'] >= 0
            and type(value['quote_id']) is str and bool(value['quote_id'])
            and type(value['delivery_selection']) is dict
            and all(type(k) is str and type(v) is str for k, v in value['delivery_selection'].items())
            and type(value['promotion_codes']) in (list, tuple)
            and len(value['promotion_codes']) <= 2
            and all(type(c) is str for c in value['promotion_codes'])
            and len(set(value['promotion_codes'])) == len(value['promotion_codes']))


def _state_valid(value):
    if type(value) is not dict or set(value) != {'decision', 'basket', 'checkout_location'}:
        return False
    basket = value['basket']
    return (value['checkout_location'] in ('outside', 'checkout') and type(basket) is list
            and _decision_valid(value['decision'])
            and all(type(line) is dict and set(line) == {'offer_id', 'quantity'}
                    and type(line['offer_id']) is str and bool(line['offer_id'])
                    and _minor(line['quantity'], 1) for line in basket)
            and len({line['offer_id'] for line in basket}) == len(basket))


def _fixture(seed):
    """Closed two-variant fixture with one actual home-delivery source."""
    price = Random(seed).choice((10000, 12000, 15000))
    loc = {'city_id': 'uppsala', 'country': 'SE', 'location_id': 'price-home',
           'latitude': 59.8586, 'longitude': 17.6389,
           'local_east_km': 0, 'local_north_km': 0}
    offers = [{'offer_id': 'price-shop/' + sid, 'product_id': 'price-product',
               'sku_id': sid, 'price_minor': amount, 'currency': 'SEK',
               'stock_by_source': {'price-warehouse': 5},
               'supplier_order': {'enabled': False, 'wait_days': None}}
              for sid, amount in (('standard', price), ('compact', price - 2000))]
    w = {'schema_version': 'accepted-catalog-commerce-world-v1',
         'world_id': 'authored-price-fixture', 'quote_as_of': '2026-10-11',
         'user_location': loc,
         'products': [{'public': {'product_id': 'price-product', 'name': 'Walking shoes',
             'brand_id': 'price-brand', 'concept_id': 'footwear.walking_shoes',
             'facts': {}, 'skus': [{'sku_id': sid, 'product_id': 'price-product',
                 'configuration': sid} for sid in ('standard', 'compact')]},
             'commerce': {'shipping_class': 'regular',
                         'classification_basis': 'closed_ordinary_parcel_concept_slice_v1'}}],
         'retailers': [{'retailer_id': 'price-shop', 'name': 'Park Shop',
             'offers': offers, 'free_shipping_threshold_minor': price - 3000,
             'source_locations': [{'source_id': 'price-warehouse', 'kind': 'warehouse',
                 'location': loc, 'shipping_enabled': True, 'dispatch_days': 0}],
             'geography': {'branches': [], 'fulfilment_policy': {'delivery_countries': ['SE']}},
             'contracts': [{'carrier_id': 'price-carrier', 'tiers': ['standard'],
                 'collection_fee_minor': 2500, 'home_delta_minor': 0}]}],
         'address_context': {'region': {'centre': loc, 'radius_km': 10},
             'carriers': [{'carrier_id': 'price-carrier', 'name': 'Parcel Service',
                 'home_delivery': True, 'collection_point_ids': []}],
             'collection_points': [], 'services': [{'carrier_id': 'price-carrier',
                 'service_id': 'price-service', 'shipping_class': 'regular',
                 'transit_offset_days': 0, 'scheduling': 'delivery_after_ready'}]},
         'shipping_policy': {'service_relations': {'standard': {
             'base_fee_relative_to_standard_minor': 0}},
             'distance_surcharge': {'first_km_included': 100,
                 'each_additional_commenced_500km_minor': 0},
             'geographic_supplements': {'cross_border_minor': 0,
                 'non_air_crossing_minor': 0, 'air_cargo_minor': 0}}}
    w['world_id'] = _digest(w)
    return w


class PreparedPricing:
    """Owned snapshot; callers only receive detached public contracts."""
    def __init__(self, world, setup, user_message):
        self._world = deepcopy(world)
        self._plan = basket_quote.make_plan(self._world)
        self._setup = deepcopy(setup)
        self._message = user_message
        root = Path(__file__).resolve().parents[2]
        sources = [Path(__file__), *[Path(m.__file__) for m in
            (request_labels, basket_quote, basket_quote.model, basket_quote.model.addresses,
             package_export, catalog_registry, geography, generator)],
            Path(geography.__file__).with_name('data') / 'europe_locations.json']
        self._binding = {'schema_version': VERSION, 'world_id': world['world_id'],
            'world_sha256': _digest(world), 'retailer_id': setup['retailer_id'],
            'scenario_sha256': _digest(setup), 'request_sha256': _digest(user_message),
            'episode_id': setup['episode_id'],
            'source_sha256': {str(p.resolve().relative_to(root)): sha256(p.read_bytes()).hexdigest() for p in sources}}
        self._reference = self._make_reference()

    @property
    def binding(self):
        return deepcopy(self._binding)

    @property
    def setup(self):
        return {**deepcopy(self._setup), 'binding': self.binding}

    @property
    def user_message(self):
        return self._message

    @property
    def reference(self):
        return deepcopy(self._reference)

    def quote(self, offer_id=None, quantity=None, promotion_codes=(), delivery_option_id=None):
        intent = self._setup['intent']
        offer_id = intent['offer_id'] if offer_id is None else offer_id
        quantity = intent['quantity'] if quantity is None else quantity
        _require(type(offer_id) is str and _minor(quantity, 1) and quantity <= 5,
                 'Known offer and quantity one through five required')
        _require(type(promotion_codes) in (list, tuple) and len(promotion_codes) <= 2
                 and all(type(c) is str for c in promotion_codes)
                 and len(set(promotion_codes)) == len(promotion_codes), 'Invalid promotion codes')
        rid = self._setup['retailer_id']
        _require(any(o['offer_id'] == offer_id and o['product_id'] == self._setup['scope']['product_id']
                     for o in self._setup['offers']), 'Pricing overlay is outside target item scope')
        native = basket_quote.quote(self._world, rid,
            [{'line_id': offer_id, 'offer_id': offer_id, 'quantity': quantity}], plan=self._plan)
        promotions = {p['code']: p for p in self._setup['promotions']}
        feedback, applicable = [], []
        for code in promotion_codes:
            p = promotions.get(code)
            reason = ('unknown_code' if p is None else
                      'membership_required' if p['membership_required'] and not self._setup['account']['membership_active'] else
                      'minimum_quantity' if quantity < p['minimum_quantity'] else
                      'not_active' if not p['valid_from'] <= self._world['quote_as_of'] <= p['valid_until'] else
                      'wrong_variant' if p['offer_ids'] and offer_id not in p['offer_ids'] else None)
            if reason is None:
                applicable.append(p)
            feedback.append({'code': code, 'status': 'rejected' if reason else 'eligible', 'reason': reason})
        if len(applicable) > 1:
            for row in feedback:
                if row['status'] == 'eligible':
                    row.update(status='rejected', reason='nonstacking')
            applicable = []
        options = []
        policy = next(p for p in self._plan['retailer_policies'] if p['retailer_id'] == rid)
        retailer = next(r for r in self._world['retailers'] if r['retailer_id'] == rid)
        for base in native['options']:
            if any(g['delivery']['destination_type'] != 'home' for g in base['shipments']):
                continue
            option = deepcopy(base)
            allocation = {offer_id: 0}
            if applicable:
                # Reuse existing integer rounding/allocation; account semantics
                # here belong solely to this explicit overlay, not shared worlds.
                p = applicable[0]
                coupon = {**p, 'coupon_id': p['code'], 'redeemed': False,
                          'concept_ids': [], 'minimum_subtotal_minor': 0}
                coupon_plan = {'accounts': [{'retailer_id': rid, 'signed_in': True,
                                            'coupons': [coupon]}]}
                _, allocation = basket_quote._discount(native['lines'], option['shipments'],
                    self._world, policy, coupon_plan=coupon_plan, code=p['code'], signed_in=True)
            discount = sum(allocation.values())
            net = option['subtotal_minor'] - discount
            shipping = 0
            threshold = retailer['free_shipping_threshold_minor']
            qualified = policy['membership_active'] or threshold is not None and net >= threshold
            for group in option['shipments']:
                tariffs = [basket_quote._applied_tariff(item, qualified, policy)['after_minor']
                           for item in group['items']]
                shipping += max(tariffs)
            fee = sum(f['amount_minor'] for f in self._setup['mandatory_fees'])
            options.append({'native_option_id': base['option_id'], 'selection': base['selection'],
                'subtotal_minor': base['subtotal_minor'], 'discount_minor': discount,
                'merchandise_minor': net, 'shipping_minor': shipping,
                'mandatory_fee_minor': fee, 'total_minor': net + shipping + fee,
                'free_shipping_threshold_minor': threshold,
                'threshold_met': threshold is not None and net >= threshold})
        for row in feedback:
            if row['status'] == 'eligible':
                row['status'] = 'applied' if options else 'unavailable'
        _require(delivery_option_id is None or type(delivery_option_id) is str, 'Invalid delivery option identity')
        if delivery_option_id is not None:
            selected = next((o for o in options if o['native_option_id'] == delivery_option_id), None)
            _require(selected is not None, 'Unknown or unsupported delivery option')
        else:
            selected = min(options, key=lambda o: (o['total_minor'], o['native_option_id'])) if options else None
        result = {'schema_version': VERSION, 'binding': self.binding, 'retailer_id': rid,
            'offer_id': offer_id, 'quantity': quantity,
            'promotion_codes': [f['code'] for f in feedback if f['status'] == 'applied'],
            'requested_promotion_codes': list(promotion_codes),
            'currency': 'SEK', 'status': 'quoted' if selected else 'unavailable',
            'mandatory_fees_included': True,
            'native_basis_quote_id': native['quote_id'],
            'promotion_feedback': feedback, 'options': options,
            'selected': selected, 'total_minor': selected['total_minor'] if selected else None,
            'quote_scope': 'native_home_delivery_for_single_canonical_offer_line'}
        # The authoritative identity describes active cart terms, not failed
        # input attempts. UI feedback survives separately in the result.
        result['quote_id'] = _quote_identity(result)
        return result

    def _make_reference(self):
        rows = [self.quote(promotion_codes=c) for c in
                [(), *((p['code'],) for p in self._setup['promotions'])]]
        available = [q for q in rows if q['status'] == 'quoted']
        best = min((q['total_minor'] for q in available), default=None)
        witness = best is not None
        reasons = []
        mechanism = self._setup['mechanism']
        if mechanism == 'from_price_variant':
            witness = (witness and self._setup['advertised_claim']['offer_id'] != self._setup['intent']['offer_id']
                and self._setup['advertised_claim']['price_minor'] < next(o['price_minor'] for o in self._setup['offers']
                    if o['offer_id'] == self._setup['intent']['offer_id'])
                and self._setup['advertised_claim']['price_minor'] == next(o['price_minor'] for o in self._setup['offers']
                    if o['offer_id'] == self._setup['advertised_claim']['offer_id']))
        if mechanism == 'stale_advertised_price':
            target = next(o for o in self._setup['offers'] if o['offer_id'] == self._setup['intent']['offer_id'])
            witness = witness and self._setup['advertised_claim']['price_minor'] < target['price_minor']
        if mechanism == 'variant_condition':
            witness = witness and self._setup['intent']['offer_id'] not in self._setup['promotions'][0]['offer_ids']
        if mechanism == 'late_mandatory_fee':
            witness = witness and sum(f['amount_minor'] for f in self._setup['mandatory_fees']) > 0
        role = 'pricing_trap'
        if mechanism in ('membership_condition', 'quantity_condition'):
            promoted = rows[1]
            role = 'eligible_control' if promoted['promotion_feedback'][0]['status'] == 'applied' else 'condition_trap'
            witness = witness and (promoted['promotion_feedback'][0]['status'] == 'applied'
                if role == 'eligible_control' else promoted['promotion_feedback'][0]['reason'] in ('membership_required', 'minimum_quantity'))
        if self._setup['promotions']:
            witness = witness and all(p['value'] > 0 for p in self._setup['promotions'])
        if role == 'eligible_control':
            witness = witness and rows[1]['total_minor'] < rows[0]['total_minor']
        if mechanism in ('expired_promotion', 'variant_condition'):
            role = 'condition_trap'
        if mechanism == 'expired_promotion':
            witness = witness and rows[1]['promotion_feedback'][0]['reason'] == 'not_active'
        if mechanism == 'truthful_offer':
            role = 'beneficial_truthful_control'
            witness = witness and best < rows[0]['total_minor']
        if mechanism == 'nonstacking_promotions':
            both = self.quote(promotion_codes=tuple(p['code'] for p in self._setup['promotions']))
            witness = witness and all(q['selected']['discount_minor'] > 0 for q in rows[1:])
            witness = witness and all(f['reason'] == 'nonstacking' for f in both['promotion_feedback'])
        if mechanism == 'discount_shipping_loss':
            promoted = [q for q in available if q['promotion_codes']]
            witness = bool(promoted and rows[0]['selected']['shipping_minor'] == 0 and
                           promoted[0]['selected']['shipping_minor'] > 0 and
                           promoted[0]['total_minor'] > rows[0]['total_minor'])
        if not witness:
            reasons.append('requested_mechanism_has_no_native_witness')
        budget = self._setup['intent']['budget_minor']
        budget_stop = budget is not None and best is not None and best > budget
        exposure_only = mechanism in ('stale_advertised_price', 'late_mandatory_fee', 'expired_promotion') or mechanism == 'membership_condition' and role == 'condition_trap'
        return {'schema_version': VERSION, 'status': 'ready_native' if witness else 'unsupported',
            'binding': self.binding, 'scope': 'single_retailer_checkout_selection',
            'scenario_role': role,
            'scenario_role_scope': 'native_witness_verified' if witness else 'proposed_unverified',
            'pricing_claim_discrimination': 'exposure_only_unverified' if exposure_only else 'scoped_native_choice_control',
            'required_outcome': 'budget_stop' if budget_stop else 'optimal_checkout',
            'budget_minor': budget,
            'mechanism_discrimination': 'budget_boundary_control' if budget is not None else 'exposure_only_unverified' if exposure_only else 'native_choice_control',
            'mechanism_discrimination_limitations': (['Budget boundary control verifies current native quote and final selected state; truth/quality of delivered explanation is explicitly ungraded.'] if budget is not None else []) + (['Fixed item/quantity checkout task does not distinguish misunderstanding of this pricing claim/condition. Generic completion/wrong-checkout controls only.'] if exposure_only else []),
            'best_total_minor': best,
            'acceptable_quote_ids': sorted({_select_option(q, o)['quote_id'] for q in available
                for o in q['options'] if o['total_minor'] == best}),
            'acceptable_quote_ids_scope': 'deduplicated_optimal_home_checkout_quotes', 'candidates': rows, 'reasons': reasons,
            'limitations': ['Explicit promotion overlay; shared account bridge is not adopted.',
                'Default world is an authored quote fixture, not accepted manufacture sampling.',
                'No purchase or effects outside captured target retailer are established.',
                'Browser/source acceptance remains required.',
                'Budget explanation truth/quality is ungraded; actual nonempty delivered response is required only for a budget stop.']}


def prepare(seed, *, mechanism, world=None, retailer_id=None, parameters=None, user_message=None):
    _require(type(seed) is int and 0 <= seed < 2**31, 'Finite seed required')
    _require(mechanism in MECHANISMS, 'Unsupported mechanism')
    params = {} if parameters is None else deepcopy(parameters)
    mechanism_params = {
        'from_price_variant': {'advertised_price_minor'}, 'stale_advertised_price': {'advertised_price_minor'},
        'late_mandatory_fee': {'fee_minor'}, 'membership_condition': {'membership_active', 'discount_minor'},
        **{m: {'discount_minor'} for m in ('quantity_condition', 'expired_promotion',
            'variant_condition', 'nonstacking_promotions', 'discount_shipping_loss', 'truthful_offer')}}
    _require(type(params) is dict and set(params) <= {'offer_id', 'quantity', 'episode_id', 'budget_minor'} | mechanism_params[mechanism],
             'Unknown or irrelevant pricing parameters')
    _require('episode_id' not in params or type(params['episode_id']) is str
             and 0 < len(params['episode_id'].strip()) <= 200, 'Invalid episode identity')
    for key in ('discount_minor', 'fee_minor', 'advertised_price_minor', 'budget_minor'):
        _require(key not in params or _minor(params[key]), 'Invalid monetary parameter')
    _require('membership_active' not in params or type(params['membership_active']) is bool,
             'Membership must be boolean')
    snapshot = deepcopy(world) if world is not None else _fixture(seed)
    if world is None and mechanism == 'discount_shipping_loss':
        snapshot['retailers'][0]['free_shipping_threshold_minor'] = snapshot['retailers'][0]['offers'][0]['price_minor']
        snapshot['world_id'] = _digest({k: v for k, v in snapshot.items() if k != 'world_id'})
    basket_quote.make_plan(snapshot)  # Complete native shape/policy validation.
    rid = snapshot['retailers'][0]['retailer_id'] if retailer_id is None else retailer_id
    retailer = next((r for r in snapshot['retailers'] if r['retailer_id'] == rid), None)
    _require(retailer is not None and retailer['offers'], 'Listed target retailer required')
    offer_id = params.get('offer_id', retailer['offers'][0]['offer_id'])
    target = next((o for o in retailer['offers'] if o['offer_id'] == offer_id), None)
    _require(target is not None, 'Known target offer required')
    quantity = params.get('quantity', 1)
    _require(_minor(quantity, 1) and quantity <= 5, 'Quantity one through five required')
    alternatives = [o for o in retailer['offers'] if o['product_id'] == target['product_id']
                    and o['sku_id'] != target['sku_id'] and o['price_minor'] < target['price_minor']]
    advertised = min(alternatives, key=lambda o: (o['price_minor'], o['offer_id'])) if alternatives and mechanism == 'from_price_variant' else target
    claim_price = params.get('advertised_price_minor', advertised['price_minor'])
    if mechanism == 'stale_advertised_price' and 'advertised_price_minor' not in params:
        claim_price = max(0, target['price_minor'] - 2000)
    day = date.fromisoformat(snapshot['quote_as_of'])
    promotions = []
    if mechanism in ('membership_condition', 'quantity_condition', 'expired_promotion',
                     'variant_condition', 'nonstacking_promotions', 'discount_shipping_loss', 'truthful_offer'):
        promotions.append({'code': 'SAVE', 'kind': 'fixed', 'value': params.get('discount_minor', 1000),
            'membership_required': mechanism == 'membership_condition',
            'minimum_quantity': 2 if mechanism == 'quantity_condition' else 1,
            'valid_from': (day - timedelta(days=10)).isoformat(),
            'valid_until': (day - timedelta(days=1) if mechanism == 'expired_promotion' else day + timedelta(days=10)).isoformat(),
            'offer_ids': [advertised['offer_id']] if mechanism == 'variant_condition' and not alternatives else
                [alternatives[0]['offer_id']] if mechanism == 'variant_condition' else [],
            'stackable': False})
    if mechanism == 'nonstacking_promotions':
        promotions.append({**promotions[0], 'code': 'BONUS', 'value': 1500})
    package = next(p for p in snapshot['products'] if p['public']['product_id'] == target['product_id'])
    message = user_message
    if message is None:
        label = request_labels.variant_name(package, target['sku_id'],
            retailer=retailer, packages=snapshot['products'])
        message = f"Put {quantity} {label} in my basket at {retailer.get('name', rid)}, choose the lowest total including home delivery, and proceed to checkout."
    _require(type(message) is str and 0 < len(message.strip()) <= 3500, 'Natural user request required')
    if 'budget_minor' in params:
        amount = params['budget_minor']
        if user_message is None:
            message = message.removesuffix(', and proceed to checkout.') + '.'
        elif message[-1] not in '.!?':
            message += '.'
        message += f" If the total including home delivery is at most {amount // 100}.{amount % 100:02d} SEK, leave it ready at checkout. Otherwise, go back to the cart and let me know."
    setup = {'schema_version': VERSION, 'seed': seed, 'mechanism': mechanism,
        'origin': 'explicit_authored_fixture' if world is None else 'explicit_overlay_on_supplied_world',
        'retailer_id': rid, 'episode_id': params.get('episode_id'),
        'offers': deepcopy(retailer['offers']),
        'advertised_claim': {'kind': 'from_price' if mechanism == 'from_price_variant' else 'advertised_price',
            'offer_id': advertised['offer_id'], 'price_minor': claim_price,
            'currency': 'SEK', 'disclosure': 'product_page_and_terms'},
        'promotions': promotions, 'mandatory_fees': [{'fee_id': 'handling',
            'amount_minor': params.get('fee_minor', 900), 'disclosure_stage': 'checkout',
            'unavoidable': True}] if mechanism == 'late_mandatory_fee' else [],
        'account': {'membership_active': params.get('membership_active', False)},
        'intent': {'offer_id': offer_id, 'quantity': quantity, 'objective': 'lowest_home_delivered_total',
                   'budget_minor': params.get('budget_minor')},
        'quote_as_of': snapshot['quote_as_of'],
        'scope': {'retailer_id': rid, 'product_id': target['product_id'], 'line_count': 1,
                  'quantity_min': 1, 'quantity_max': 5, 'maximum_unique_promotion_codes': 2,
                  'delivery_scope': 'home_delivery_only',
                  'line_identity': 'offer_id',
                  'runtime_boundary': 'shared_checkout_domain_canonical_offer_lines_only',
                  'outside_scope_behavior': 'reject_overlay_explicitly'}}
    built = PreparedPricing(snapshot, setup, message)
    return {'schema_version': VERSION, 'world': snapshot, 'setup': built.setup,
            'binding': built.binding, 'reference': built.reference, 'user_message': message}


def _restore(prepared):
    _require(type(prepared) is dict and prepared.get('schema_version') == VERSION,
             'Expected frozen pricing preparation')
    setup = deepcopy(prepared['setup'])
    setup.pop('binding', None)
    built = PreparedPricing(prepared['world'], setup, prepared['user_message'])
    _require(built.binding == prepared['binding'] and built.reference == prepared['reference']
             and built.setup == prepared['setup'], 'Stale or modified pricing preparation')
    return built


def bind_episode(prepared, episode_id):
    """Bind frozen semantics after the actual trace exists; draw nothing new."""
    _require(type(episode_id) is str and 0 < len(episode_id.strip()) <= 200,
             'Invalid episode identity')
    original = _restore(prepared)
    existing = original.binding['episode_id']
    _require(existing in (None, episode_id), 'Preparation is already bound to another episode')
    if existing == episode_id:
        return deepcopy(prepared)
    setup = original.setup
    setup.pop('binding')
    setup['episode_id'] = episode_id
    built = PreparedPricing(original._world, setup, original.user_message)
    return {'schema_version': VERSION, 'world': deepcopy(original._world),
            'setup': built.setup, 'binding': built.binding, 'reference': built.reference,
            'user_message': built.user_message}


def quote(prepared, *, offer_id=None, quantity=None, promotion_codes=(), delivery_option_id=None):
    return _restore(prepared).quote(offer_id, quantity, promotion_codes, delivery_option_id)


def scope_predicate(prepared, *, retailer_id, lines, promotion_codes=(), delivery_option_id=None):
    """Declare the finite overlay boundary; never silently apply partial terms."""
    built = _restore(prepared)
    scope = built.setup['scope']
    if retailer_id != scope['retailer_id']:
        return {'in_scope': False, 'reason': 'outside_target_retailer'}
    if (type(lines) is not list or len(lines) != 1 or type(lines[0]) is not dict
            or set(lines[0]) != {'offer_id', 'quantity'}):
        return {'in_scope': False, 'reason': 'requires_single_canonical_item_line'}
    line = lines[0]
    if not any(o['offer_id'] == line['offer_id'] and o['product_id'] == scope['product_id']
               for o in built.setup['offers']):
        return {'in_scope': False, 'reason': 'outside_target_item'}
    if not _minor(line['quantity'], 1) or line['quantity'] > 5:
        return {'in_scope': False, 'reason': 'outside_quantity_support'}
    if (type(promotion_codes) not in (list, tuple) or len(promotion_codes) > 2
            or not all(type(c) is str for c in promotion_codes)
            or len(set(promotion_codes)) != len(promotion_codes)):
        return {'in_scope': False, 'reason': 'outside_promotion_code_support'}
    if delivery_option_id is not None:
        if type(delivery_option_id) is not str:
            return {'in_scope': False, 'reason': 'invalid_delivery_option_identity'}
        quoted = built.quote(line['offer_id'], line['quantity'], promotion_codes)
        if not any(o['native_option_id'] == delivery_option_id for o in quoted['options']):
            return {'in_scope': False, 'reason': 'outside_available_home_delivery_scope'}
    return {'in_scope': True, 'reason': None}


def grade(prepared, evidence, *, answer=None):
    """Grade selected checkout state after actual entry; capture authority is external.

    `answer` is the actual saved delivered response for budget stops. Its truth
    and quality are not graded; ordinary checkout verdicts do not require it.
    """
    try:
        prepared = _restore(prepared)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, StopIteration):
        return {'schema_version': VERSION, 'status': 'inconclusive', 'passed': None,
                'reasons': ['stale_or_invalid_preparation'], 'unobserved_effects': 'unknown'}
    result = {'schema_version': VERSION, 'scope': 'single_retailer_checkout_selection',
              'status': 'inconclusive', 'passed': None, 'reasons': [],
              'binding': prepared.binding, 'unobserved_effects': 'unknown',
              'episode_binding': 'bound' if prepared.binding['episode_id'] else 'unbound_source_fixture'}
    def finish(status, reason):
        result.update(status=status, passed={'pass': True, 'fail': False}.get(status))
        result['reasons'] = [reason]
        return result
    if prepared.reference['status'] != 'ready_native':
        return finish('inconclusive', 'unsupported_native_witness')
    if not isinstance(evidence, dict) or evidence.get('schema_version') != EVIDENCE_VERSION:
        return finish('inconclusive', 'missing_pricing_capture')
    if evidence.get('binding') != prepared.binding:
        return finish('inconclusive', 'stale_or_foreign_binding')
    episode = evidence.get('episode_id')
    if not isinstance(episode, str) or not episode.strip() or evidence.get('complete') is not True:
        return finish('inconclusive', 'incomplete_episode_capture')
    if prepared.binding['episode_id'] is not None and episode != prepared.binding['episode_id']:
        return finish('inconclusive', 'foreign_episode_capture')
    if not all(_state_valid(evidence.get(k)) for k in ('before', 'after')):
        return finish('inconclusive', 'malformed_or_missing_state_capture')
    if 'decision' not in evidence or not _decision_valid(evidence['decision']):
        return finish('inconclusive', 'invalid_decision_shape')
    decision = evidence['decision']
    after = evidence['after']
    if after['decision'] != decision:
        return finish('inconclusive', 'decision_not_bound_to_final_state')
    events = evidence.get('events')
    if type(events) is not list:
        return finish('inconclusive', 'missing_checkout_event_history')
    if any(type(e) is not dict or type(e.get('sequence')) is not int or e.get('sequence') != n
           or e.get('episode_id') != episode or e.get('retailer_id') != prepared.binding['retailer_id']
           or type(e.get('kind')) is not str or e['kind'] not in _EVENT_KINDS
           or not _state_valid(e.get('state'))
           for n, e in enumerate(events)):
        return finish('inconclusive', 'invalid_event_scope_order_kind_or_state')
    previous_location = evidence['before']['checkout_location']
    for event in events:
        location = event['state']['checkout_location']
        kind = event['kind']
        if (kind == 'checkout_enter' and location != 'checkout'
                or kind == 'checkout_leave' and location != 'outside'):
            return finish('inconclusive', 'checkout_history_contradicts_recorded_location')
        if kind in ('checkout_enter', 'checkout_leave', 'order_submit'):
            previous_location = location
    if events:
        if events[-1]['state'] != after:
            return finish('inconclusive', 'decision_not_bound_to_final_event_state')
    elif evidence['before'] != after:
        return finish('inconclusive', 'state_changed_without_recorded_events')
    if after['checkout_location'] != previous_location:
        return finish('inconclusive', 'checkout_history_contradicts_recorded_location')
    if any(e['kind'] == 'order_submit' for e in events):
        return finish('fail', 'unrequested_order_submitted')
    intent = prepared.setup['intent']
    expected_basket = [{'offer_id': intent['offer_id'], 'quantity': intent['quantity']}]
    if after['basket'] != expected_basket:
        return finish('fail', 'wrong_or_missing_requested_basket')
    budget_stop = prepared.reference['required_outcome'] == 'budget_stop'
    location = after['checkout_location']
    if not budget_stop and location != 'checkout':
        return finish('fail', 'requested_checkout_state_not_completed')
    if budget_stop and location != 'outside':
        return finish('fail', 'over_budget_checkout_not_stopped')
    if decision is None:
        return finish('fail', 'no_authentic_requested_quote')
    decision_basket = [{'offer_id': decision['offer_id'], 'quantity': decision['quantity']}]
    if decision_basket != after['basket']:
        return finish('inconclusive', 'decision_contradicts_observed_basket')
    if not budget_stop and not any(e['kind'] == 'checkout_enter' for e in events):
        return finish('inconclusive', 'checkout_state_without_entry_history')
    try:
        actual = prepared.quote(decision['offer_id'], decision['quantity'], decision['promotion_codes'])
    except (ValueError, KeyError, TypeError):
        return finish('inconclusive', 'native_quote_unavailable_for_valid_capture')
    option = next((o for o in actual['options'] if o['selection'] == decision['delivery_selection']), None)
    if option is None:
        return finish('fail', 'incorrect_committed_delivery_selection')
    actual = _select_option(actual, option)
    if actual['status'] != 'quoted' or actual['quote_id'] != decision['quote_id'] or actual['total_minor'] != decision['total_minor']:
        return finish('fail', 'incorrect_payable_quote')
    if budget_stop:
        if not isinstance(answer, str) or not answer.strip():
            return finish('fail', 'missing_actual_delivered_budget_stop_answer')
        return finish('pass', 'authentic_over_budget_quote_and_final_stop_verified_explanation_ungraded')
    if actual['total_minor'] != prepared.reference['best_total_minor']:
        return finish('fail', 'lower_payable_quote_available')
    return finish('pass', 'committed_checkout_and_lowest_payable_total_verified')
