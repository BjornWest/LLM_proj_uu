"""Grounded shipping-deal audit; resolve the exact public SKU before amounts."""
from copy import deepcopy
import re
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from experiments.answer_grading.extraction import MONEY, claim, money_minor, _quote, validate_claims
from . import basic_offer_task, catalog_shipping_claim_task as native
from .adapter import digest
from .listed_offer_grading import ListedOfferGrader

VERSION = 'website-catalog-shipping-claim-grading-v1'
MONEY_FIELDS = ('unit_price', 'subtotal', 'advertised_threshold', 'minimum_shipping', 'maximum_shipping')
ENUMS = {'subtotal_test': ['no_threshold', 'below_threshold', 'meets_threshold'],
         'assessment': ['unavailable', 'none_free', 'some_free', 'all_free']}
PATTERNS = {
    'no_threshold': r'\b(no (?:free[- ](?:shipping|delivery) )?(?:threshold|minimum)|no_threshold)\b',
    'below_threshold': r'\b(below (?:the )?(?:threshold|minimum)|does not (?:reach|meet) (?:the )?(?:threshold|minimum)|below_threshold)\b',
    'meets_threshold': r'\b((?:reaches?|meets?) (?:the )?(?:threshold|minimum)|meets_threshold)\b',
    'unavailable': r'\b(unavailable|no (?:delivery |shipping )?options (?:are )?available)\b',
    'none_free': r'\b(none (?:of (?:these|the) options (?:are )?)?(?:are )?free|no (?:delivery |shipping )?options? (?:are )?free|none_free)\b',
    'some_free': r'\b(some (?:of (?:these|the) options (?:are )?)?(?:are )?free|some_free)\b',
    'all_free': r'\b(all (?:of (?:these|the) options (?:are )?)?(?:are )?free|all_free)\b',
}
INSTRUCTIONS = '''Extract the final answer into the schema; do not solve the audit.
No private expected values, quote oracle or tools are available. Never infer a
missing SKU, amount, count or verdict from the request, another claim or arithmetic.
Every claim needs an exact contiguous final-answer quote. Copy actual product,
retailer, product URL, explicitly stated SKU and option attributes. Normalize
subtotal reaches/meets threshold to meets_threshold; below/does not meet threshold
to below_threshold; explicitly no threshold to no_threshold. Shipping assessment
is all_free, some_free, none_free or unavailable only when explicitly stated for
the requested complete basket/method scope. A subtotal reaching a threshold does
not imply an assessment. Quantity and option counts are explicitly stated integers.
Money fields are stated decimal amounts with their actual currency. Missing values
are null; undefined shipping extrema are null only as reported, never zero. Keep
an absent threshold distinct from a zero threshold. Conflicting audits are ambiguous.
Use status audit for a concrete audit, uncertain for an unresolved question.
Do not credit explanations, visits or cart effects. Return JSON only.'''


class ShippingClaimGrader:
    def __init__(self, world, task, reference, bindings, *, quote_context, checkout_domain):
        expected = native.reference(world, task, quote_context=quote_context, checkout_domain=checkout_domain)
        if reference != expected:
            raise ValueError('Shipping claim reference binding changed')
        base = basic_offer_task._make_bound(world, {'kind': basic_offer_task.KIND,
            'concept_id': task['subject']['concept_id']}, digest(world))
        self.identity = ListedOfferGrader(world, base, basic_offer_task._reference_bound(world, base), bindings)
        self.task, self.reference = deepcopy(task), deepcopy(expected)
        self.schema = deepcopy(self.identity.schema)
        del self.schema['properties']['total'];self.schema['required'].remove('total')
        self.schema['properties']['status'] = claim(enum=['audit', 'uncertain', None])
        extras = {key: {'anyOf': [deepcopy(MONEY), {'type': 'null'}]} for key in MONEY_FIELDS}
        extras.update({key: claim('integer') for key in ('quantity', 'option_count', 'free_option_count')})
        extras.update({key: claim(enum=values+[None]) for key, values in ENUMS.items()})
        extras['policy_url'] = claim()
        self.schema['properties'].update(extras); self.schema['required'].extend(extras)
        self.contract = {'version': VERSION, 'operation': task['kind'],
            'quantity_basis': 'retail_sale_units', 'variant_fields': self.identity.contract['variant_fields'],
            'delivery_types': task['delivery_types'], 'price_basis': 'one exact SKU basket, no extras/coupons/new memberships',
            'threshold_basis': 'merchandise subtotal; actual option fee is independent',
            'scope': 'complete admitted basket options in declared destination modes'}
        self.extraction_instructions = INSTRUCTIONS

    def validate_claims(self, claims, answer):
        c = deepcopy(claims);c.setdefault('variant', {})
        if type(c['variant']) is not dict:
            raise ValueError('Variant claims must be an object')
        for key in self.contract['variant_fields']:
            c['variant'].setdefault(key, {'value': None, 'evidence': None})
        # Semantic phrase normalization has explicit grounding separate from
        # literal string validation; expected outcomes never repair a quote.
        enums = {key: c.get(key, {'value': None, 'evidence': None}) for key in ENUMS}
        for key in ENUMS:c[key] = {'value': None, 'evidence': None}
        c = validate_claims(c, answer, schema=self.schema)
        c.update(enums); Draft202012Validator(self.schema).validate(c)
        for key, row in enums.items():
            if row['value'] is None:
                if row['evidence'] is not None:raise ValueError('Absent assessment requires absent evidence')
            else:
                _quote(row['evidence'], answer)
                wording = re.search(PATTERNS[row['value']], row['evidence'], re.I)
                if not wording:
                    raise ValueError('Assessment lacks explicit matching wording')
                # The phrase itself must be asserted. Keep the legitimate
                # below-threshold phrase "does not meet" inside its match;
                # reject a negation outside any normalized verdict instead.
                if re.search(r"\b(?:not|never|neither|cannot|can't|isn't|aren't)\s*(?:that\s*)?$",
                             row['evidence'][:wording.start()], re.I):
                    raise ValueError('Negated assessment is unsupported')
                if row['value'] in ('meets_threshold', 'all_free') and re.search(r'\b(?:not|never|neither|doesn.t)\b', row['evidence'], re.I):
                    raise ValueError('Negated affirmative assessment is unsupported')
        for row in c['variant'].values():
            if row['value'] is None:
                if row['evidence'] is not None:raise ValueError('Absent variant needs absent evidence')
            else:
                _quote(row['evidence'], answer)
                if row['value'] not in row['evidence']:raise ValueError('Variant absent from quoted answer')
        for key in MONEY_FIELDS:
            if c[key] is not None:
                _quote(c[key]['evidence'], answer); money_minor(c[key])
        return c

    def grade(self, claims, answer):
        c = self.validate_claims(claims, answer)
        ids, reason = self.identity.resolve(c)
        subject = self.task['subject'];ref = self.reference
        checks = {'extractor_unambiguous': c['interpretation'] == 'extracted',
            'audit_reported': c['status']['value'] == 'audit',
            'exact_public_offer': ids == [subject['offer_id']],
            'product_reported': c['product_name']['value'] is not None,
            'retailer_reported': c['retailer_name']['value'] is not None}
        for key in ('quantity', 'option_count', 'free_option_count', 'subtotal_test', 'assessment'):
            checks[key] = c[key]['value'] is not None and c[key]['value'] == ref[key]
        for key in MONEY_FIELDS:
            expected = ref[{'unit_price': 'unit_price_minor', 'subtotal': 'subtotal_minor',
                'advertised_threshold': 'advertised_threshold_minor', 'minimum_shipping': 'minimum_shipping_minor',
                'maximum_shipping': 'maximum_shipping_minor'}[key]]
            checks[key] = (c[key] is None if expected is None else c[key] is not None and
                money_minor(c[key]) == expected and c[key]['currency'] == 'SEK')
        link = self.identity.links[subject['offer_id']]['url']
        policy = urlsplit(c['policy_url']['value'] or ''); actual = urlsplit(link)
        checks['actual_policy_or_checkout_link'] = (policy.scheme, policy.netloc, policy.path) == (
            actual.scheme, actual.netloc, actual.path) and policy.fragment in ('/info/shipping', '/checkout') and not policy.query
        return {'grading_version': VERSION, 'response_contract': deepcopy(self.contract),
            'structured_claims_correct': all(checks.values()), 'oracle_grade': {'requirements': checks},
            'claims': c, 'additional_checks': {}, 'identity_resolution': {'offer_ids': ids, 'reason': reason},
            'oracle_answer': {k: deepcopy(ref[k]) for k in ('subject', 'quantity', 'subtotal_test', 'assessment', 'option_count', 'free_option_count')},
            'selected_candidate_assessment': {'offer_id': ids[0]} if len(ids) == 1 else None,
            'derivations': [], 'check_details': {k: {'passed': v} for k,v in checks.items()},
            'full_response_evaluated': False, 'safe_success': None,
            'limitations': ['Only literal audit facts and exact public SKU/source identity are graded.',
                'Threshold causality/explanation, visits, persisted baskets and purchase effects are not graded.',
                'Public fees are complete basket fees; zero shipping can have causes other than the threshold.']}
