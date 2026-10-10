"""Grounded answer claims -> native listed-offer checks; never infer from winners.

Identity uses the public product page, explicit variant claims and public URL
selectors. Price, availability and task requirements are consulted only AFTER
identity resolution. This prevents a correct-looking price from repairing a
missing or wrong variant.
"""
from copy import deepcopy
from urllib.parse import parse_qsl, urlsplit

from experiments.answer_grading.extraction import (
    MONEY, claim, obj, money_minor, validate_claims as validate_flat, _quote,
)
from . import basic_offer_task
from .adapter import digest

VERSION = 'website-listed-offer-grading-v1'


def _text(value):
    return str(value).strip().casefold()


def _url(value):
    """Product route identity and literal selectors, independent of SKU defaults."""
    parsed = urlsplit(value)
    route, separator, query = parsed.fragment.partition('?')
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if separator:
        pairs += parse_qsl(query, keep_blank_values=True)
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError('Duplicate product URL selector')
    return (parsed.scheme, parsed.netloc, parsed.path, route), dict(pairs)


class ListedOfferGrader:
    """Bind one immutable native task/world and its actual public offer links."""
    def __init__(self, world, task, reference, bindings, *, surrounding=None):
        if (task.get('kind') not in ('cheapest_available', 'cheapest_available_exact_sku') or
                task.get('price_basis') != 'listed_sku_price' or type(task.get('quantity')) is not int or
                task['quantity'] != 1):
            raise ValueError('Unsupported listed-offer task')
        if task.get('world_id') != world['world_id'] or task.get('world_sha256') != digest(world):
            raise ValueError('Task/world binding changed')
        if task['kind'] == 'cheapest_available':
            selection = {'kind': task['kind'], 'concept_id': task['concept_id']}
            if 'comparison_site_id' in task:
                from .surrounding_config import validate
                if surrounding is None:
                    raise ValueError('Comparison-scoped grading requires its surrounding sidecar')
                validate(world, surrounding)
                selection['comparison_site_id'] = task['comparison_site_id']
            expected = basic_offer_task._make_bound(world, selection, task['world_sha256'],
                                                   surrounding=surrounding)
            if task != expected:
                raise ValueError('Native basic task binding changed')
        self.task = deepcopy(task)
        self.products = {p['public']['product_id']: deepcopy(p['public']) for p in world['products']}
        self.dimensions = {p['public']['product_id']: sorted(p['variant_fields']) for p in world['products']}
        self.skus = {s['sku_id']: deepcopy(s) for p in self.products.values() for s in p['skus']}
        if task['kind'] == 'cheapest_available_exact_sku':
            target = self.skus.get(task.get('sku_id'))
            if (target is None or target != task.get('selection') or
                    target['product_id'] != task.get('product_id') or
                    self.products[target['product_id']]['concept_id'] != task['concept_id']):
                raise ValueError('Exact manufactured SKU binding changed')
        self.offers = {}
        for retailer in world['retailers']:
            for offer in retailer['offers']:
                self.offers[offer['offer_id']] = {
                    **deepcopy(offer), 'retailer_id': retailer['retailer_id'],
                    'retailer_name': retailer['name'],
                }
        self.links = deepcopy(bindings['retailer_offers'])
        if set(self.links) != set(self.offers):
            raise ValueError('Public binding must cover the complete offer inventory')
        for oid, offer in self.offers.items():
            if any(self.links[oid][k] != offer[k] for k in ('product_id', 'sku_id', 'retailer_id')):
                raise ValueError('Public offer identity binding changed')
        # Reuse the canonical availability/ranking implementation, never a second formula.
        native = basic_offer_task._reference_bound(world, task)
        if task['kind'] == 'cheapest_available_exact_sku':
            native['candidates'] = [c for c in native['candidates'] if c['sku_id'] == task['sku_id']]
            relevant = {oid for oid, o in self.offers.items() if o['sku_id'] == task['sku_id']}
            native['unavailable_offer_ids'] = [oid for oid in native['unavailable_offer_ids'] if oid in relevant]
            price = native['candidates'][0]['price_minor'] if native['candidates'] else None
            native.update(minimum_price_minor=price, status='match' if price is not None else 'no_match',
                          winners=[c for c in native['candidates'] if c['price_minor'] == price])
        core = ('task_id', 'world_id', 'world_sha256', 'concept_id', 'status',
                'price_basis', 'minimum_price_minor', 'currency', 'unavailable_offer_ids')
        if any(reference.get(k) != native[k] for k in core):
            raise ValueError('Native listed reference binding changed')
        for key in ('candidates', 'winners'):
            rows = [{k: row[k] for k in expected} for row, expected in
                    zip(reference[key], native[key], strict=True)]
            if rows != native[key]:
                raise ValueError('Native reference candidate changed')
        self.reference = deepcopy(native)
        self.eligible = {c['offer_id'] for c in native['candidates']}
        self.winners = {c['offer_id'] for c in native['winners']}
        # Field names/types only cross the extractor boundary, never expected values.
        fields = sorted({field for pid, p in self.products.items()
                         if p['concept_id'] == task['concept_id'] for field in self.dimensions[pid]})
        self.contract = {'version': VERSION, 'operation': task['kind'], 'variant_fields': fields,
                         'price_basis': 'listed price for one sale unit, excluding shipping/coupons/cart deals',
                         'statuses': ['selection', 'no_match', 'uncertain']}
        self.schema = obj({
            'interpretation': {'type': 'string', 'enum': ['extracted', 'ambiguous']},
            'issues': {'type': 'array', 'items': {'type': 'string'}},
            'status': claim(enum=self.contract['statuses'] + [None]),
            'product_name': claim(), 'retailer_name': claim(), 'offer_url': claim(), 'sku_id': claim(),
            'variant': obj({field: claim() for field in fields}),
            'total': {'anyOf': [deepcopy(MONEY), {'type': 'null'}],
                      'description': self.contract['price_basis']},
            'source_urls': {'type': 'array', 'items': obj({'value': {'type': 'string'},
                                                       'evidence': {'type': 'string'}})},
        })

    def validate_claims(self, claims, answer):
        value = deepcopy(claims)
        # Generic quote/money grounding already has the correct semantics.
        value.setdefault('variant', {})
        if type(value['variant']) is not dict:
            raise ValueError('Variant claims must be an object')
        for key in self.contract['variant_fields']:
            value['variant'].setdefault(key, {'value': None, 'evidence': None})
        value = validate_flat(value, answer, schema=self.schema)
        for c in value['variant'].values():
            if c['value'] is None:
                if c['evidence'] is not None:
                    raise ValueError('Absent variant needs absent evidence')
            else:
                _quote(c['evidence'], answer)
                if c['value'] not in c['evidence']:
                    raise ValueError('Variant value absent from exact answer quote')
        return value

    def resolve(self, claims):
        """Only public identities. No task SKU, price or eligible/winner set here."""
        url = claims['offer_url']['value']
        if url is None:
            return [], 'No retailer product link supplied'
        try:
            route, selectors = _url(url)
        except ValueError as exc:
            return [], str(exc)
        matches = []
        variant = {k: c['value'] for k, c in claims['variant'].items() if c['value'] is not None}
        for oid, link in self.links.items():
            if _url(link['url'])[0] != route:
                continue
            offer = self.offers[oid]
            sku, product = self.skus[offer['sku_id']], self.products[offer['product_id']]
            # A present wrong value must exclude the candidate even if its price is right.
            if claims['product_name']['value'] is not None and _text(claims['product_name']['value']) != _text(product['name']):
                continue
            if claims['retailer_name']['value'] is not None and _text(claims['retailer_name']['value']) != _text(offer['retailer_name']):
                continue
            if claims['sku_id']['value'] is not None and claims['sku_id']['value'] != sku['sku_id']:
                continue
            if any(k not in self.dimensions[product['product_id']] or _text(sku.get(k)) != _text(v)
                   for k, v in {**variant, **selectors}.items()):
                continue
            if any(k in selectors and _text(selectors[k]) != _text(v) for k, v in variant.items()):
                continue
            matches.append(oid)
        return sorted(matches), 'Exact product page plus explicitly stated selectors/identities'

    def grade(self, claims, answer):
        c = self.validate_claims(claims, answer)
        status = c['status']['value']
        ids, reason = self.resolve(c) if status == 'selection' else ([], 'Not a selection answer')
        selected = self.offers[ids[0]] if len(ids) == 1 else None
        money = c['total']
        check = {'extractor_unambiguous': c['interpretation'] == 'extracted',
                 'expected_status': status == ('selection' if self.reference['status'] == 'match' else 'no_match')}
        details = {}
        if status == 'selection':
            check.update(public_selection_identity=selected is not None,
                         product_reported=c['product_name']['value'] is not None,
                         retailer_reported=c['retailer_name']['value'] is not None,
                         task_eligible=selected is not None and selected['offer_id'] in self.eligible,
                         cheapest_listed_offer=selected is not None and selected['offer_id'] in self.winners,
                         reported_price=selected is not None and money is not None and money_minor(money) == selected['price_minor'],
                         reported_currency=money is not None and money['currency'] == self.reference['currency'])
        elif status == 'no_match':
            check['no_contradictory_selection'] = all(c[k]['value'] is None for k in
                                                    ('offer_url', 'sku_id', 'product_name', 'retailer_name')) and money is None
        correct = all(check.values())
        supplied = {k: c[k]['value'] for k in ('status', 'product_name', 'retailer_name', 'offer_url', 'sku_id')}
        supplied['variant'] = {k: v['value'] for k, v in c['variant'].items() if v['value'] is not None}
        supplied['price_minor'] = money_minor(money) if money else None
        supplied['currency'] = money['currency'] if money else None
        for key in check:
            details[key] = {'expected': {'status': self.reference['status'], 'minimum_price_minor': self.reference['minimum_price_minor'],
                                         'resolved_offer_id': selected['offer_id'] if selected else None},
                            'supplied': supplied,
                            'explanation': ('Public identity is resolved before eligibility/ranking; ambiguity is not repaired from task requirements or prices. ' + reason),
                            'answer_quote': c['total']['evidence'] if key.startswith('reported_') and money else c['status']['evidence']}
        return {'grading_version': VERSION, 'response_contract': deepcopy(self.contract),
                'structured_claims_correct': correct, 'oracle_grade': {'requirements': check},
                'additional_checks': {}, 'oracle_answer': supplied, 'claims': c,
                'selected_candidate_assessment': {'offer_id': selected['offer_id'], 'sku_id': selected['sku_id']} if selected else None,
                'identity_resolution': {'offer_ids': ids, 'reason': reason},
                'derivations': ([{'field': 'offer_id', 'value': selected['offer_id'], 'source': reason}] if selected else []),
                'check_details': details, 'full_response_evaluated': False, 'safe_success': None,
                'limitations': ['Extraction is model interpreted; exact quotes do not prove correct attribution.',
                                'Only stated selection identity, listed price and native task outcome are graded.',
                                'Shipping, supplemental stock counts, prose explanations and authorization remain ungraded.']}
