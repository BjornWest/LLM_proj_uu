"""Mixed-catalog binding of the existing exact order-set search.

Search, allocation, stock accounting, extra-item bounds and dispatch/fee formulas
are reused unchanged. Only checkout preparation and the versioned envelope differ.
Each call owns its caches; historical module globals are never patched.
"""
from functools import lru_cache
from types import FunctionType

from experiments.footwear_world_pilot import order_set_optimizer as historical
from . import basket_quote as baskets

VERSION = 'accepted-catalog-order-set-optimizer-v1'


def _bind(function, **bindings):
    result = FunctionType(function.__code__, {**function.__globals__, **bindings},
                          function.__name__, function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


class _Checkout(historical._Checkout):
    """Prepare the accepted commerce envelope for the unchanged search methods."""

    dispatch = _bind(historical._Checkout.dispatch, baskets=baskets)
    options = _bind(historical._Checkout.options, baskets=baskets)

    def __init__(self, world, plan, coupons, destination, work, allowed, deadline,
                 admission_plan=None):
        if baskets.VERSION != 'accepted-catalog-basket-quote-v1':
            raise ValueError('Accepted checkout helper version needs reacceptance')
        # Central public quote rejects accounts too. Do not let a private search
        # path accidentally enable a capability its public replay cannot offer.
        if coupons is not None:
            raise ValueError('Accepted-catalog account/coupon bridge is not adopted')
        baskets.validate_plan(world, plan)
        self.world, self.plan, self.coupons = world, plan, None
        self.retailers, self.products = baskets._world(world)
        self.destination = world['user_location'] if destination is None else baskets._location(destination)
        self.work, self.allowed, self.deadline = work, allowed, deadline
        self.policies = {p['retailer_id']: p for p in plan['retailer_policies']}
        menus = None
        if admission_plan is not None:
            from . import delivery_admission
            self.oracle = delivery_admission.Oracle(world, plan, admission_plan)
            self.route_key = delivery_admission.route_key
            menus = {r['retailer_id']: frozenset(r['admitted_route_keys'])
                     for r in admission_plan['retailers']}
        self.choices = {
            rid: {c['choice_id']: c for c in baskets._choices(world, r, self.policies[rid], self.destination)
                  if (allowed is None or c['destination_type'] in allowed)
                  and (menus is None or self.route_key(c) in menus[rid])}
            for rid, r in self.retailers.items()}
        self.active_coupons = {rid: [] for rid in self.retailers}
        self.dispatch = lru_cache(None)(self.dispatch)
        self.options = lru_cache(None)(self.options)


_solve = _bind(historical.solve, _Checkout=_Checkout, VERSION=VERSION)


def solve(world, requirements, *, plan, coupon_plan=None, destination=None,
          allowed_destination_types=None, deadline=None, allow_extras=True,
          quantity_limits=None, max_lines_per_order=None, budget=None,
          max_solutions=100, admission_plan=None):
    """Exact minimum combined payable total over the declared shared cart domain.

The requirement input is [{requirement_id, quantity, offer_ids}], independently
matched by Product. Budget exhaustion is inconclusive, including when a feasible
incumbent exists. This adapter adds no implicit quantity caps or stock filters.
    """
    result = _solve(world, requirements, plan=plan, coupon_plan=coupon_plan,
                    destination=destination, allowed_destination_types=allowed_destination_types,
                    deadline=deadline, allow_extras=allow_extras, quantity_limits=quantity_limits,
                    max_lines_per_order=max_lines_per_order, budget=budget,
                    max_solutions=max_solutions, admission_plan=admission_plan)
    result['limitations'] = [
        'Explicit source-bound Product matching; task and answer grading are separate.',
        'Accepted ordinary-parcel basket v1 capabilities; account/coupon bridge unsupported.',
        'No purchase, account mutation or historical reference replacement.',
        'Public quote replay, Website and Inspect adoption require independent acceptance.']
    return result
