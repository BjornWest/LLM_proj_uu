"""Owned, read-only runtime snapshot using the unchanged central quote code."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import FunctionType
from threading import Lock

from . import model, basket_quote, delivery_admission

VERSION = 'accepted-catalog-prepared-quote-v1'


class PreparedQuote:
    __slots__ = ('__world', '__plan', '__call', '__policies', '__binding', '__admission')

    def __init__(self, world, *, plan, admission_plan=None):
        snapshot, policy_plan = deepcopy(world), deepcopy(plan)
        model.validate(snapshot)
        retailers, products = basket_quote._world(snapshot)
        world_hash = basket_quote.model.digest(snapshot)
        validation = basket_quote._validate_plan(snapshot, policy_plan, retailers, products,
                                                 world_sha256=world_hash)
        base_hash = validation['plan_sha256']
        admission = deepcopy(admission_plan)
        namespace = dict(basket_quote.quote.__globals__)
        namespace['_world'] = lambda unused: (retailers, products)
        policies = {rid: basket_quote.public_policy(policy_plan, rid) for rid in retailers}
        admission_hash = None
        menus = None
        if admission is not None:
            oracle = delivery_admission.Oracle(snapshot, policy_plan, admission)
            admission_hash = basket_quote.model.digest(admission)
            menus = {r['retailer_id']: frozenset(r['admitted_route_keys']) for r in admission['retailers']}
            namespace['VERSION'] = delivery_admission.VERSION
            policies = {rid: oracle.public_policy(policy_plan, rid) for rid in retailers}
            validation = {'valid': True, 'plan_sha256': basket_quote.model.digest({
                'basket_plan_sha256': base_hash, 'admission_plan_sha256': admission_hash})}
        choices_cache, choices_lock = {}, Lock()
        original_choices = basket_quote._choices
        def choices(w, r, p, d):
            # Service/destination menus are retailer features, independent of SKU stock.
            key = (r['retailer_id'], basket_quote.model.digest(d))
            with choices_lock:
                if key not in choices_cache:
                    rows = original_choices(w, r, p, d)
                    if menus is not None:
                        rows = [c for c in rows if delivery_admission.route_key(c) in menus[r['retailer_id']]]
                    choices_cache[key] = rows
                return deepcopy(choices_cache[key])
        namespace['_choices'] = choices
        namespace['validate_plan'] = lambda unused_world, unused_plan: validation
        namespace['public_policy'] = lambda unused_plan, rid: deepcopy(policies[rid])
        original = basket_quote.quote
        call = FunctionType(original.__code__, namespace, original.__name__,
                            original.__defaults__, original.__closure__)
        call.__kwdefaults__ = original.__kwdefaults__
        self.__world, self.__plan, self.__call = snapshot, policy_plan, call
        self.__policies, self.__admission = policies, admission_hash
        self.__binding = {'schema_version': VERSION, 'world_id': snapshot['world_id'],
            'world_sha256': world_hash, 'basket_plan_sha256': base_hash,
            'admission_plan_sha256': admission_hash, 'quote_plan_sha256': validation['plan_sha256'],
            'source_sha256': {str(p.relative_to(Path(__file__).resolve().parents[2])): sha256(p.read_bytes()).hexdigest()
                for p in sorted({Path(__file__).resolve(), *[Path(m.__file__).resolve()
                    for m in (basket_quote, delivery_admission, model, basket_quote.model, basket_quote.coupon_quote)]})}}

    @property
    def binding(self):
        return deepcopy(self.__binding)

    def public_policy(self, retailer_id):
        if retailer_id not in self.__policies:
            raise ValueError('Unknown retailer')
        return deepcopy(self.__policies[retailer_id])

    def quote(self, retailer_id, lines, *, destination=None, selections=None, split=False,
              coupon_plan=None, coupon_code=None, signed_in=None, expected_quote_id=None):
        result = self.__call(self.__world, retailer_id, lines, plan=self.__plan,
            destination=destination, selections=selections, split=split, coupon_plan=coupon_plan,
            coupon_code=coupon_code, signed_in=signed_in, expected_quote_id=expected_quote_id)
        if self.__admission is not None:
            result['basket_plan_sha256'] = self.__binding['basket_plan_sha256']
            result['admission_plan_sha256'] = self.__admission
            result['limitations'] += ['Persistent admitted menu; no refill or basket-feasibility repair.']
        return deepcopy(result)


def prepare(world, *, plan, admission_plan=None):
    return PreparedQuote(world, plan=plan, admission_plan=admission_plan)
