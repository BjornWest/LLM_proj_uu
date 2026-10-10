"""Exact, opt-in checkout-column search over the native basket domain.

Matching is supplied by Product. No sampling, purchase, renderer pricing or old
reference mutation occurs here. Private basket helpers are isolated in _Checkout;
their version and public-quote replay are checked by the dedicated tests.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date
from functools import lru_cache
from itertools import combinations_with_replacement
import math
from time import monotonic

from . import basket_quote as baskets, coupon_quote, model

VERSION = 'native-order-set-optimizer-v1'


class _Exhausted(Exception):
    pass


class _Work:
    def __init__(self, budget):
        if budget is not None and type(budget) is not dict:
            raise ValueError('Search budget must be an object')
        budget = {'max_work': 250000, 'max_seconds': 30.0, **(budget or {})}
        if (set(budget) != {'max_work', 'max_seconds'} or
                type(budget['max_work']) is not int or budget['max_work'] < 1 or
                type(budget['max_seconds']) not in (int, float) or
                not math.isfinite(budget['max_seconds']) or budget['max_seconds'] <= 0):
            raise ValueError('Expected positive max_work and max_seconds')
        self.budget, self.start = budget, monotonic()
        self.counts = defaultdict(int)

    def tick(self, kind):
        self.counts[kind] += 1
        self.counts['work'] += 1
        if (self.counts['work'] > self.budget['max_work'] or
                monotonic() - self.start > self.budget['max_seconds']):
            raise _Exhausted('search_budget_exhausted')


class _Checkout:
    """Prepared native calculator; cache dispatch, never duplicate fee formulas."""
    def __init__(self, world, plan, coupons, destination, work, allowed, deadline, admission_plan=None):
        if baskets.VERSION != 'footwear-basket-quote-v1':
            raise ValueError('Native checkout helper version needs reacceptance')
        baskets.validate_plan(world, plan)
        if coupons is not None:
            coupon_quote.validate_plan(world, coupons)
        self.world, self.plan, self.coupons = world, plan, coupons
        self.retailers, self.products = baskets._world(world)
        self.destination = world['user_location'] if destination is None else baskets._location(destination)
        self.work, self.allowed, self.deadline = work, allowed, deadline
        self.policies = {p['retailer_id']: p for p in plan['retailer_policies']}
        menus=None
        if admission_plan is not None:
            from experiments.accepted_catalog_commerce import delivery_admission
            self.oracle=delivery_admission.Oracle(world,plan,admission_plan)
            self.route_key=delivery_admission.route_key
            menus={r['retailer_id']:frozenset(r['admitted_route_keys']) for r in admission_plan['retailers']}
        self.choices = {rid: {c['choice_id']: c for c in baskets._choices(
            world, r, self.policies[rid], self.destination)
            if (allowed is None or c['destination_type'] in allowed) and
                (menus is None or self.route_key(c) in menus[rid])}
            for rid, r in self.retailers.items()}
        self.active_coupons = {}
        for rid in self.retailers:
            account = next((a for a in (coupons or {}).get('accounts', [])
                            if a['retailer_id'] == rid), None)
            self.active_coupons[rid] = [c for c in (account or {}).get('coupons', [])
                if account['signed_in'] and not c['redeemed'] and
                c['valid_from'] <= world['quote_as_of'] <= c['valid_until']]
        # Each solve owns its caches; class-level lru_cache would retain worlds.
        self.dispatch = lru_cache(None)(self.dispatch)
        self.options = lru_cache(None)(self.options)

    def dispatch(self, rid, oid, quantity, cid):
        self.work.tick('dispatch_evaluations')
        retailer, policy = self.retailers[rid], self.policies[rid]
        offer = next(o for o in retailer['offers'] if o['offer_id'] == oid)
        product = self.products[offer['product_id']]
        choice = self.choices[rid][cid]
        candidates = (baskets._branch_candidates(self.world, retailer, product, offer, quantity, choice)
                      if choice['destination_type'] == 'retailer_branch' else
                      baskets._carrier_candidates(self.world, retailer, policy, product, offer, quantity, choice))
        return min(candidates, key=lambda c: baskets._rank(c, policy)) if candidates else None

    def options(self, rid, quantities):
        self.work.tick('basket_evaluations')
        if not baskets._within_region(self.world, self.destination):
            return ()
        retailer, policy, choices = self.retailers[rid], self.policies[rid], self.choices[rid]
        # Stable offer identities retain the same allocation rounding on replay.
        request = [{'line_id': oid, 'offer_id': oid, 'quantity': q} for oid, q in quantities]
        lines, offers, counts = baskets._prepare_lines(self.world, retailer, self.products, request)
        domains = []
        for line in lines:
            rows = []
            for cid, choice in choices.items():
                dispatch = self.dispatch(rid, line['offer_id'], line['quantity'], cid)
                if dispatch is None:
                    continue
                supply = 'stock' if dispatch['supply'] == 'on_hand' else 'backorder/' + line['brand_id']
                group = (supply, line['shipping_class'] if policy['mixed_destinations'] else None)
                rows.append((cid, group, model.digest(choice['destination'])))
            if not rows:
                return ()
            domains.append((line['line_id'], rows))
        domains.sort(key=lambda row: (len(row[1]), row[0]))
        output = []

        def visit(i, selected, group_choices, destination_id):
            self.work.tick('service_states')
            if i < len(domains):
                lid, rows = domains[i]
                for cid, group, target in rows:
                    if group in group_choices and group_choices[group] != cid:
                        continue
                    if not policy['mixed_destinations'] and destination_id not in (None, target):
                        continue
                    visit(i + 1, {**selected, lid: cid}, {**group_choices, group: cid}, target)
                return
            for split in ([False, True] if policy['optional_split'] else [False]):
                for code in [None] + [c['code'] for c in self.active_coupons[rid]]:
                    self.work.tick('native_options')
                    option, failure = baskets._build_option(
                        self.world, retailer, policy, lines, offers, self.products, counts,
                        choices, selected, split, self.coupons, code, None)
                    if failure or code is not None and option['coupon']['status'] != 'applied':
                        continue
                    arrival = option['arrival']
                    if self.deadline is not None and (arrival['status'] != 'estimated' or
                            arrival['latest_date'] > self.deadline):
                        continue
                    output.append(option)

        visit(0, {}, {}, None)
        return tuple(output)


def solve(world, requirements, *, plan, coupon_plan=None, destination=None,
          allowed_destination_types=None, deadline=None, allow_extras=True,
          quantity_limits=None, max_lines_per_order=None, budget=None, max_solutions=100,
          admission_plan=None):
    """Return optimal / infeasible / inconclusive, with integer costs and evidence.

    requirements: [{requirement_id, quantity, offer_ids}]. A purchased unit can
    satisfy only one requirement. Extras default on. Optional quantity_limits
    declare a restricted per-order offer domain, never an implicit heuristic cap.
    All native required-service combinations and optional splits are considered.
    Result ties are bounded only for reporting; the optimization stays exact.
    """
    if type(allow_extras) is not bool or type(max_solutions) is not int or max_solutions < 1:
        raise ValueError('Invalid extras/report settings')
    if max_lines_per_order is not None and (type(max_lines_per_order) is not int or max_lines_per_order < 1):
        raise ValueError('Declare a positive per-order distinct offer limit')
    if allowed_destination_types is not None and (type(allowed_destination_types) not in (list, tuple, set, frozenset)
            or any(type(v) is not str for v in allowed_destination_types)):
        raise ValueError('Destination types must be an explicit collection of strings')
    allowed = None if allowed_destination_types is None else frozenset(allowed_destination_types)
    if allowed is not None and (not allowed or not allowed <= {
            'home', 'parcel_locker', 'staffed_counter', 'retailer_branch'}):
        raise ValueError('Invalid allowed destination types')
    if deadline is not None and (type(deadline) is not str or date.fromisoformat(deadline).isoformat() != deadline):
        raise ValueError('Deadline must be an ISO date')
    work = _Work(budget)
    checkout = _Checkout(world, plan, coupon_plan, destination, work, allowed, deadline, admission_plan)
    offers, retailer_of, capacity = {}, {}, {}
    for rid, retailer in checkout.retailers.items():
        skus = set()
        for offer in retailer['offers']:
            oid, sid = offer['offer_id'], offer['sku_id']
            if oid in offers or sid in skus or type(offer['price_minor']) is not int or offer['price_minor'] < 0:
                raise ValueError('Expected unique native retailer SKU offers and nonnegative integer prices')
            skus.add(sid)
            if any(type(q) is not int or q < 0 for q in offer['stock_by_source'].values()):
                raise ValueError('Invalid source stock')
            offers[oid], retailer_of[oid] = offer, rid
            for source, quantity in offer['stock_by_source'].items():
                capacity[(rid, sid, source)] = quantity
    if type(requirements) is not list or not requirements:
        raise ValueError('Expected nonempty explicit requirements')
    ids = set()
    for req in requirements:
        if (type(req) is not dict or set(req) != {'requirement_id', 'quantity', 'offer_ids'} or
                type(req['requirement_id']) is not str or not req['requirement_id'].strip() or
                req['requirement_id'] in ids or type(req['quantity']) is not int or req['quantity'] < 1 or
                type(req['offer_ids']) is not list or any(type(o) is not str or o not in offers for o in req['offer_ids']) or
                len(set(req['offer_ids'])) != len(req['offer_ids'])):
            raise ValueError('Invalid explicit requirement/matching domain')
        ids.add(req['requirement_id'])
    limits = {} if quantity_limits is None else quantity_limits
    if type(limits) is not dict or any(o not in offers or type(q) is not int or q < 0 for o, q in limits.items()):
        raise ValueError('Quantity limits must declare nonnegative per-order offer caps')
    demand = tuple(r['quantity'] for r in requirements)
    width = sum(demand)
    unit_min = [min((offers[o]['price_minor'] for o in r['offer_ids']), default=math.inf) for r in requirements]
    active = [c for rows in checkout.active_coupons.values() for c in rows]
    fixed = sum(c['value'] for c in active if c['kind'] == 'fixed')
    rate = 100 - max((c['value'] for c in active if c['kind'] == 'percent'), default=0)
    rounding_orders = min(width, sum(c['kind'] == 'percent' for c in active))
    # At most width useful orders; each percent rounding saves <= 0.5 minor unit.
    def lower(subtotal):
        return max(0, (rate * subtotal - 100 * fixed - 50 * rounding_orders + 99) // 100)

    columns, buckets = [], {}
    best, solutions, ties_truncated = None, [], False
    caps_record, seed_cost = {}, None
    completed, reason = False, None
    seen_base = set()

    def feasible_stock(q):
        use = defaultdict(int)
        for shipment in q['shipments']:
            for item in shipment['items']:
                if item['supply'] == 'on_hand':
                    use[(retailer_of[item['offer_id']], item['sku_id'], item['source_id'])] += item['quantity']
        return tuple(sorted(use.items()))

    def add(rid, quantities, covered, allocation):
        if max_lines_per_order is not None and len(quantities) > max_lines_per_order:
            work.counts['line_domain_prunes'] += 1
            return
        for option in checkout.options(rid, quantities):
            resources = feasible_stock(option)
            coupon = option['coupon']['coupon_id'] if option['coupon']['status'] == 'applied' else None
            key = (covered, resources, coupon)
            cost = option['total_minor']
            bucket = buckets.get(key)
            if bucket is not None and bucket[0] < cost:
                work.counts['dominated_options'] += 1
                continue
            # A coverage column includes an allocation witness; a physical
            # checkout does not. Recovery deduplicates physical order multisets.
            order_id = model.digest({'retailer': rid, 'quantities': quantities,
                                     'option': option['option_id']})
            cid = model.digest({'order_id': order_id, 'coverage': covered})
            if bucket is None or cost < bucket[0]:
                buckets[key] = (cost, {})
            if cid not in buckets[key][1]:
                work.tick('checkout_columns')
                extras = [{'offer_id': oid, 'quantity': q - sum(
                    a['quantity'] for a in allocation if a['offer_id'] == oid)} for oid, q in quantities]
                buckets[key][1][cid] = {'order_id': order_id, 'retailer_id': rid,
                    'lines': [{'line_id': o, 'offer_id': o, 'quantity': q} for o, q in quantities],
                    'fulfilment': allocation, 'extras': [e for e in extras if e['quantity'] > 0],
                    'coverage': covered, 'stock': resources, 'coupon_id': coupon,
                    'coupon_code': option['coupon']['code'], 'quote': option, 'cost': cost}

    def optimize():
        nonlocal best, solutions, ties_truncated, columns
        columns = [c for _, rows in buckets.values() for c in rows.values()]
        columns.sort(key=lambda c: (c['cost'], c['order_id']))
        by_req = [[i for i, c in enumerate(columns) if c['coverage'][k]] for k in range(len(demand))]
        edges = {}

        @lru_cache(None)
        def search(remaining, stock, used):
            work.tick('allocation_states')
            if not any(remaining):
                return 0
            anchor = min((k for k, q in enumerate(remaining) if q), key=lambda k: len(by_req[k]))
            stock_map, used_set = dict(stock), set(used)
            optimum, winners = math.inf, []
            for index in by_req[anchor]:
                work.tick('allocation_edges')
                c = columns[index]
                if c['coupon_id'] is not None and c['coupon_id'] in used_set:
                    continue
                rest = tuple(q - n for q, n in zip(remaining, c['coverage']))
                if min(rest) < 0:
                    continue
                optimistic = lower(sum(n * p for n, p in zip(rest, unit_min) if n))
                if c['cost'] + optimistic > optimum:
                    work.counts['allocation_bound_prunes'] += 1
                    continue
                updated = dict(stock_map)
                for key, q in c['stock']:
                    updated[key] = updated.get(key, 0) + q
                if any(q > capacity[key] for key, q in updated.items()):
                    continue
                next_state = (rest, tuple(sorted(updated.items())),
                              tuple(sorted(used_set | ({c['coupon_id']} if c['coupon_id'] else set()))))
                cost = c['cost'] + search(*next_state)
                if cost < optimum:
                    optimum, winners = cost, [(index, next_state)]
                elif cost == optimum and cost != math.inf:
                    winners.append((index, next_state))
            edges[(remaining, stock, used)] = winners
            return optimum

        root = (demand, (), ())
        cost = search(*root)
        if cost == math.inf:
            return
        found, dedup, truncated = [], set(), False

        def recover(state, chosen):
            nonlocal truncated
            work.tick('solution_recovery')
            if not any(state[0]):
                identity = tuple(sorted(c['order_id'] for c in chosen))
                if identity in dedup:
                    return
                dedup.add(identity)
                if len(found) == max_solutions:
                    truncated = True
                    return
                found.append({'total_minor': cost, 'orders': sorted(chosen, key=lambda c: c['order_id'])})
                return
            for index, next_state in edges[state]:
                if truncated:
                    break
                recover(next_state, chosen + [columns[index]])

        recover(root, [])
        if best is None or cost <= best:
            best, solutions, ties_truncated = cost, found, truncated

    def cap(oid, upper):
        offer = offers[oid]
        bound = None if offer['supplier_order']['enabled'] else max(offer['stock_by_source'].values(), default=0)
        if oid in limits:
            bound = limits[oid] if bound is None else min(bound, limits[oid])
        if upper is not None and rate and offer['price_minor']:
            price_cap = (100 * (upper + fixed) + 50 * rounding_orders) // (rate * offer['price_minor'])
            bound = price_cap if bound is None else min(bound, price_cap)
        return bound

    def bases(rid):
        matches = [sorted(o for o in r['offer_ids'] if retailer_of[o] == rid and cap(o, best) != 0)
                   for r in requirements]

        def visit(k, amounts, coverage, allocation):
            work.tick('required_basket_states')
            if max_lines_per_order is not None and len(amounts) > max_lines_per_order:
                work.counts['line_domain_prunes'] += 1
                return
            subtotal = sum(offers[o]['price_minor'] * q for o, q in amounts.items())
            missing = sum((demand[i] - coverage[i]) * unit_min[i] for i in range(k) if demand[i] > coverage[i])
            missing += sum(demand[i] * unit_min[i] for i in range(k, len(demand)))
            if best is not None and lower(subtotal + missing) > best:
                work.counts['required_bound_prunes'] += 1
                return
            if k == len(demand):
                if any(coverage):
                    quantities = tuple(sorted(amounts.items()))
                    key = (rid, quantities, tuple(coverage))
                    if key not in seen_base:
                        seen_base.add(key)
                        yield quantities, tuple(coverage), allocation
                return
            for n in range(demand[k] + 1):
                for selection in combinations_with_replacement(matches[k], n):
                    work.tick('required_allocations')
                    counts = defaultdict(int)
                    for oid in selection:
                        counts[oid] += 1
                    new = dict(amounts)
                    for oid, q in counts.items():
                        new[oid] = new.get(oid, 0) + q
                    if any(cap(o, best) is not None and q > cap(o, best) for o, q in new.items()):
                        continue
                    rows = allocation + [{'requirement_id': requirements[k]['requirement_id'],
                        'offer_id': o, 'quantity': q} for o, q in sorted(counts.items())]
                    yield from visit(k + 1, new, coverage + [n], rows)

        yield from visit(0, {}, [], [])

    base_rows = []
    try:
        if any(not r['offer_ids'] for r in requirements):
            completed = True
        else:
            # An inexpensive feasible upper bound; not the final reference.
            for k, req in enumerate(requirements):
                covered = tuple(int(i == k) for i in range(len(demand)))
                for oid in sorted(req['offer_ids']):
                    if cap(oid, None) == 0:
                        continue
                    add(retailer_of[oid], ((oid, 1),), covered,
                        [{'requirement_id': req['requirement_id'], 'offer_id': oid, 'quantity': 1}])
            optimize()
            seed_cost = best
            for rid in sorted(checkout.retailers):
                for quantities, covered, allocation in bases(rid):
                    base_rows.append((rid, quantities, covered, allocation))
                    add(rid, quantities, covered, allocation)
            optimize()
            if allow_extras:
                caps_record = {o: cap(o, best) for o in offers}
                if any(q is None for q in caps_record.values()):
                    raise _Exhausted('unbounded_extra_domain_requires_quantity_contract_or_payable_bound')
                for rid, quantities, covered, allocation in base_rows:
                    amounts = dict(quantities)
                    missing = sum((n - c) * p for n, c, p in zip(demand, covered, unit_min) if n > c)
                    subtotal = sum(offers[o]['price_minor'] * q for o, q in quantities)
                    candidates = sorted((o for o in offers if retailer_of[o] == rid and caps_record[o] > amounts.get(o, 0)),
                                        key=lambda o: (offers[o]['price_minor'], o))
                    # A costly extra cannot become cheaper by adding more extras:
                    # this bound already grants all coupon savings and zero shipping.
                    candidates = [o for o in candidates if best is None or
                                  lower(subtotal + missing + offers[o]['price_minor']) <= best]

                    def extras(start, current, cost):
                        for j in range(start, len(candidates)):
                            oid = candidates[j]
                            for extra in range(1, caps_record[oid] - current.get(oid, 0) + 1):
                                work.tick('extra_basket_states')
                                new_cost = cost + offers[oid]['price_minor'] * extra
                                if best is not None and lower(new_cost + missing) > best:
                                    work.counts['extra_bound_prunes'] += 1
                                    break
                                updated = {**current, oid: current.get(oid, 0) + extra}
                                if max_lines_per_order is not None and len(updated) > max_lines_per_order:
                                    work.counts['line_domain_prunes'] += 1
                                    break
                                add(rid, tuple(sorted(updated.items())), covered, allocation)
                                extras(j + 1, updated, new_cost)

                    extras(0, amounts, subtotal)
                optimize()
            completed = True
    except _Exhausted as exc:
        reason = str(exc)
    result = {'schema_version': VERSION, 'world_id': world['world_id'],
        'world_sha256': model.digest(world), 'plan_sha256': model.digest(plan),
        'coupon_plan_sha256': model.digest(coupon_plan) if coupon_plan else None,
        'status': ('optimal' if best is not None else 'infeasible') if completed else 'inconclusive',
        'complete': completed, 'reason': reason, 'currency': 'SEK', 'total_minor': best,
        'solutions': deepcopy(solutions), 'ties_truncated': ties_truncated,
        'tie_scope': 'distinct orders/services; allocation aliases and order permutations deduplicated',
        'domain': {'requirements': deepcopy(requirements), 'allow_extras': allow_extras,
            'quantity_limits': deepcopy(limits), 'extra_quantity_bounds': caps_record,
            **({'max_lines_per_order':max_lines_per_order} if max_lines_per_order is not None else {}),
            'allowed_destination_types': sorted(allowed) if allowed is not None else None,
            'deadline': deadline, 'destination': deepcopy(checkout.destination),
            'max_useful_orders': width, 'canonical_line_id': 'offer_id'},
        'proof': {'minimum_retained_percent': rate, 'available_fixed_discount_minor': fixed,
            'maximum_rounded_percent_orders': rounding_orders,
            'merchandise_lower_bound': 'max(0, ceil((rate * subtotal - 100 * fixed - 50 * rounding_orders) / 100))',
            'order_reduction': 'Remove orders satisfying no requested units; nonnegative prices and no cross-order benefits.',
            'dominance': 'Equal requirement coverage, exact source-stock vector and single-use coupon; strictly cheaper cost.',
            'exhaustion': 'All required allocations, bounded extras, valid service maps and joint order allocations completed.' if completed else None},
        'statistics': {**dict(work.counts), 'seconds': monotonic() - work.start,
            'seed_total_minor': seed_cost, 'retained_columns': len(columns),
            'dispatch_cache': checkout.dispatch.cache_info()._asdict(),
            'basket_cache': checkout.options.cache_info()._asdict()},
        'budget': work.budget,
        'limitations': ['Explicit Product matching; no new task sampling or grader.',
            'Native basket v1 dispatch/transfer/group capabilities only.',
            'No purchase, account mutation or existing reference replacement.',
            'Independent producer acceptance and website line-ID adoption remain separate.']}
    if admission_plan is not None:
        result['admission_plan_sha256']=model.digest(admission_plan)
    return result
