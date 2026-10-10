"""Explicit public transport for the additive native basket oracle.

No renderer arithmetic, sampling, purchase mutation or task/grader promotion.
"""
from copy import deepcopy

from experiments.footwear_world_pilot import basket_quote
from .adapter import digest, supported_destination
from . import checkout_domain


class Baskets:
    def __init__(self, adapter, plan, coupons=None, domain=None, *, oracle=basket_quote, domain_provider=checkout_domain, delivery_plan=None,prepared=None):
        self.oracle, self.domain_provider = oracle, domain_provider
        validation=self.oracle.validate_plan(adapter.world, plan)
        if prepared is not None:
            binding=prepared.binding
            if binding['world_sha256']!=plan['world_sha256'] or binding['quote_plan_sha256']!=validation['plan_sha256']:
                raise ValueError('Prepared quote binding differs from basket transport')
        self.prepared=prepared
        self.adapter, self.plan, self.coupons = adapter, deepcopy(plan), coupons
        self.plan_id = digest(plan) if delivery_plan is None else digest({
            'basket_plan':plan,'delivery_plan':delivery_plan})
        self.domain = deepcopy(domain)
        self._bound_domain = None
        if prepared is not None and domain is not None:
            from . import catalog_checkout_domain
            if domain_provider is catalog_checkout_domain:
                self._bound_domain = catalog_checkout_domain._BoundDomain(adapter.world, domain)
        self.domain_id = (self._bound_domain.identifier if self._bound_domain is not None else
                          self.domain_provider.validate(adapter.world, domain) if domain is not None else None)

    def public_domain(self, retailer_id):
        if self._bound_domain is not None:
            return self._bound_domain.public(retailer_id)
        return self.domain_provider.public(self.adapter.world, self.domain, retailer_id)

    def policy(self, retailer_id):
        policy = self.prepared.public_policy(retailer_id) if self.prepared is not None else self.oracle.public_policy(self.plan, retailer_id)
        result = {k: deepcopy(policy[k]) for k in (
            'optional_split', 'mixed_destinations', 'qualification_scope',
            'bulky_treatment', 'membership_active', 'branch_transfer_fee')}
        if 'delivery_admission' in policy:
            result['delivery_admission']={k:deepcopy(policy['delivery_admission'][k])
                for k in ('sampled_count','initial_route_count','fixed_menu','home_coverage')}
        return result

    def _quote(self,world,retailer_id,lines,**kwargs):
        if self.prepared is None:return self.oracle.quote(world,retailer_id,lines,**kwargs)
        kwargs.pop('plan')
        return self.prepared.quote(retailer_id,lines,**kwargs)

    def quote(self, retailer_id, request):
        required = {'revision', 'world_id', 'plan_id', 'lines', 'address',
                    'selections', 'split', 'coupon_code'}
        if self.domain is not None:
            required.add('domain_id')
        if not isinstance(request, dict) or set(request) != required:
            raise ValueError('Supply the complete basket quote request')
        if type(request['revision']) is not int or request['revision'] < 0:
            raise ValueError('Invalid draft revision')
        if request['world_id'] != self.adapter.world['world_id'] or request['plan_id'] != self.plan_id:
            raise ValueError('Basket world or policy binding changed')
        if not isinstance(request['lines'], list) or not 1 <= len(request['lines']) <= 64:
            raise ValueError('Supply between one and 64 basket lines')
        if not isinstance(request['address'], dict):
            raise ValueError('Supply recipient and delivery address fields')
        if request['coupon_code'] is not None and (not isinstance(request['coupon_code'], str) or not request['coupon_code']):
            raise ValueError('Coupon code must be nonempty text or null')
        if request['selections'] is not None and not isinstance(request['selections'], dict):
            raise ValueError('Delivery selections must be a line-to-service mapping')
        lines, selections = request['lines'], request['selections']
        if self.domain is not None:
            if request['domain_id'] != self.domain_id:
                raise ValueError('Shared checkout domain binding changed')
            if self._bound_domain is not None:
                lines, aliases = self._bound_domain.canonical_lines(retailer_id, lines)
            else:
                lines, aliases = self.domain_provider.canonical_lines(
                    self.adapter.world, self.domain, retailer_id, lines)
            selections = self.domain_provider.canonical_selections(selections, aliases)
        destination = supported_destination(self.adapter.world, request['address'])
        kwargs = dict(plan=self.plan, destination=destination, split=request['split'],
            coupon_code=request['coupon_code'] or None,
            coupon_plan=self.coupons.plan if self.coupons else None,
            signed_in=self.coupons.account(retailer_id)['signed_in'] if self.coupons else None)
        raw = self._quote(self.adapter.world, retailer_id, lines,
                                 selections=selections, **kwargs)
        reset = raw['status'] == 'invalid_plan' and request['selections'] is not None
        if reset:
            raw = self._quote(self.adapter.world, retailer_id, lines,
                                     selections=None, **kwargs)
        # The storefront explicitly adopts the producer's published preview as
        # its ordinary default. Requote that exact selection; never synthesize a
        # selected quote or choose a task-dependent/cheapest option here.
        if raw['selected'] is None and raw['offer_context_option_id']:
            context = next(o for o in raw['options'] if o['option_id'] == raw['offer_context_option_id'])
            raw = self._quote(self.adapter.world, retailer_id, lines,
                                     selections=context['selection'], **kwargs)
        choices = {c['choice_id']: c for c in raw['delivery_choices']}
        points = {p['point_id']: p for p in self.adapter.world['address_context']['collection_points']}
        retailer = self.adapter.retailers[retailer_id]
        branches = {b['branch_id']: b for b in retailer['geography']['branches']}

        def delivery(choice_id):
            c = choices[choice_id]
            kind = c['destination_type']
            point = points.get(c['point_id'])
            branch = branches.get(c.get('branch_id'))
            location = {'id': c['point_id'] or c['destination']['location_id']}
            if kind == 'home':
                a = request['address']
                location.update(name='Your address', address=f"{a['street']}" +
                    (f", Apartment {a['unit']}" if a.get('unit') else '') + f", {a['postcode']} {a['city']}")
            elif point:
                location.update(name=point['name'], address=point.get('address', point['location']['city']))
            elif branch:
                location.update(name=branch['name'], address=branch['location']['city'])
            else:
                raise ValueError('Unknown public collection destination')
            return {'id': choice_id, 'company': c['carrier_name'] or retailer['name'],
                    'name': c['tier'].capitalize() if c['tier'] else 'Shop collection',
                    'type': kind, 'location': location, 'collectionHours': deepcopy(c['collection_hours']),
                    'payment': 'online'}

        def option(value):
            if value is None:
                return None
            shipments = []
            for g in value['shipments']:
                items = g['items']
                shipments.append({'key': g['group_id'], 'lineIds': g['line_ids'],
                    'requiredGroupId': g['required_group_id'], 'delivery': delivery(g['choice_id']),
                    'arrival': deepcopy(g['arrival']), 'shippingMinor': g['shipping_minor'],
                    'merchandiseMinor': g['merchandise_minor'], 'discountMinor': g['discount_minor'],
                    'qualification': deepcopy(g['qualification']),
                    'backorder': any(i['supply'] == 'supplier_order' for i in items),
                    'local': all(i['destination_type'] == 'retailer_branch' and not i['requires_transfer'] for i in items),
                    'items': [{k: deepcopy(i[k]) for k in ('line_id', 'sku_id', 'quantity',
                        'source_id', 'supply', 'requires_transfer', 'arrival', 'tariff', 'discount_minor')} for i in items]})
            return {'id': value['option_id'], 'selection': deepcopy(value['selection']),
                'shipments': shipments, 'arrival': deepcopy(value['arrival']),
                'subtotalMinor': value['subtotal_minor'], 'discountMinor': value['discount_minor'],
                'shippingMinor': value['shipping_minor'], 'totalMinor': value['total_minor'],
                'coupon': deepcopy(value['coupon']), 'splitEffective': value['optional_split_effective'],
                'lineDiscountAllocations': deepcopy(value['line_discount_allocations'])}

        can_split = False
        if raw['selected'] is not None and self.policy(retailer_id)['optional_split']:
            alternate = self._quote(self.adapter.world, retailer_id, lines,
                selections=raw['selected']['selection'], **{**kwargs, 'split': not request['split']})
            can_split = raw['selected']['optional_split_effective'] or bool(
                alternate['selected'] and alternate['selected']['optional_split_effective'])
        result = {'revision': request['revision'], 'requestId': digest(request),
            'worldId': raw['world_id'], 'planId': self.plan_id, 'quoteId': raw['quote_id'],
            'status': raw['status'], 'reasons': deepcopy(raw['reasons']),
            'selected': option(raw['selected']), 'options': [option(o) for o in raw['options']],
            'groupOffers': [{k: deepcopy(g[k]) for k in ('selection_group_id', 'line_ids',
                'option_id', 'conditional_context_option_id', 'selection', 'shipping_minor',
                'complete_basket_total_minor', 'arrival')} for g in raw['group_delivery_offers']],
            'selectionReset': reset, 'canSplit': can_split}
        mode=getattr(self.adapter,'delivery_orders',{}).get(retailer_id)
        if mode is not None:
            from .delivery_options import sorted_projection
            return sorted_projection(result,mode)
        return result


def basket_shop_source(source, *, canonical_domain=False):
    """Capability-only changes to a copied renderer; original draft stays intact."""
    replacements = {
        '${worldBinding?1:20}': '${worldBinding?.basket?20:worldBinding?1:20}',
        'if(worldBinding&&(Number(values.quantity)!==1||state.cart.length&&!state.editing))':
            'if(worldBinding&&!worldBinding.basket&&(Number(values.quantity)!==1||state.cart.length&&!state.editing))',
        'quantity>(worldBinding?1:20)': 'quantity>(worldBinding?.basket?20:worldBinding?1:20)',
        "feedback=worldBinding?'This delivery inquiry supports a quantity of one.':'Quantity must be between 1 and 20.';":
            "feedback=worldBinding&&!worldBinding.basket?'This delivery inquiry supports a quantity of one.':'Quantity must be between 1 and 20.';",
        'for(const shipment of result.shipments)state.deliveryChoices[shipment.key]=shipment.selected.id;':
            'if(!worldBinding?.basket)for(const shipment of result.shipments)state.deliveryChoices[shipment.key]=shipment.selected.id;',
        'if(!result.canSplit)state.split=false;': 'if(!worldBinding?.basket&&!result.canSplit)state.split=false;',
        'function deliveryForm() {':
            'function deliveryForm() {\n  if(worldBinding?.basket)return worldBinding.deliveryForm({state,e,money,serviceTypes});',
        "if(document.activeElement?.closest('[data-form=\"address\"]'))invalidateAddressViews();":
            "if(document.activeElement?.closest('[data-form=\"address\"],[data-form=\"quantity\"],[data-form=\"add\"],[data-form=\"coupon\"]'))invalidateAddressViews();",
        'function shipmentName(s) {':
            'function shipmentName(s) {if(worldBinding?.basket)return s.backorder?`${s.brand} supplier order`:"Items delivered together";',
        'if(input.dataset.serviceGroup){':
            'if(input.dataset.serviceGroup&&worldBinding?.basket){if(worldBinding.selectDelivery(state,input.value))revise("Delivery service selected. Totals recalculated.");return;}\n  if(input.dataset.serviceGroup){',
        'applyReset(state,initialAddress,policy);':
            'applyReset(state,initialAddress,policy);if(policy!=="preserve")state.basketSelection=null;',
        "state.addressStatus='unvalidated';state.deliveryChoices={};":
            "state.addressStatus='unvalidated';state.deliveryChoices={};state.basketSelection=null;",
        "state.addressStatus='pending';state.deliveryChoices={};":
            "state.addressStatus='pending';state.deliveryChoices={};state.basketSelection=null;",
    }
    for old, new in replacements.items():
        if old not in source:
            raise ValueError(f'Basket renderer hook changed: {old}')
        source = source.replace(old, new)
    if canonical_domain:
        hooks = {
            '${worldBinding?.basket?20:worldBinding?1:20}': '${worldBinding?.basket?worldBinding.quantityLimit(v):worldBinding?1:20}',
            '||quantity>20)': '||quantity>(worldBinding?.basket?worldBinding.quantityLimit(variant):20))',
            'existing.quantity+quantity>20': 'existing.quantity+quantity>(worldBinding?.basket?worldBinding.quantityLimit(variant):20)',
            "feedback='The maximum quantity is 20.';": "feedback=`The maximum quantity is ${worldBinding.quantityLimit(variant)}.`;",
            'quantity>(worldBinding?.basket?20:worldBinding?1:20)': 'quantity>(worldBinding?.basket?worldBinding.quantityLimit(byVariant(l.key).variant):worldBinding?1:20)',
            "'Quantity must be between 1 and 20.';": "`Quantity must be between 1 and ${worldBinding.quantityLimit(byVariant(l.key).variant)}.`;",
            'if(editing){editing.key=variant.key;editing.quantity=quantity;state.editing=null;}':
                'if(editing){const other=state.cart.find(l=>l.id!==editing.id&&l.key===variant.key);if(other){if(other.quantity+quantity>worldBinding.quantityLimit(variant)){feedback="The combined quantity exceeds this item limit.";render();return;}other.quantity+=quantity;state.cart=state.cart.filter(l=>l.id!==editing.id);}else{editing.key=variant.key;editing.quantity=quantity;}state.editing=null;}',
            'else state.cart.push({id:String(++state.serial),key:variant.key,quantity});':
                'else {if(state.cart.length>=worldBinding.maxLinesPerOrder()){feedback="The basket has reached its item-line limit.";render();return;}state.cart.push({id:String(++state.serial),key:variant.key,quantity});}',
        }
        for old, new in hooks.items():
            if old not in source:
                raise ValueError('Canonical basket renderer hook changed: ' + old)
            source = source.replace(old, new)
    return source
