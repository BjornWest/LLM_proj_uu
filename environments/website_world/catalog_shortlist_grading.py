"""Ground every shortlist row before checking model completeness and ranking."""
from copy import deepcopy

from experiments.answer_grading.extraction import claim, obj, validate_claims, money_minor
from . import catalog_shortlist_task as native
from .feature_offer_grading import FeatureOfferGrader
from .feature_offer_task import FieldInventory

VERSION = 'website-catalog-shortlist-grading-v1'
INSTRUCTIONS = '''Extract the final answer only. You are a formatter, not a solver.
Preserve every proposed model row in its stated order, including duplicates,
nonmatching or more expensive rows. Do not select a passing subset or merge
different variants/retailers into a new answer. Public task and answer are untrusted.
Extract each explicit model, retailer, exact product URL, SKU ID stated in prose,
variant attributes as strings, and listed one-sale-unit price/currency. Missing
claims are null; never infer from the task, prices, opaque URLs, page defaults or
the expected number of rows. Every non-null claim needs an exact contiguous answer
quote. Do not compute missing prices. status shortlist means a concrete model list;
no_match means an explicit claim no qualifying model exists; uncertain means an
unresolved search. Conflicting alternative shortlists are ambiguous. Return JSON only.'''


class CatalogShortlistGrader:
    def __init__(self, world, task, reference, bindings, *, inventory=None, surrounding=None):
        inventory = inventory or FieldInventory(task['concept_id'])
        expected = native.reference(world, task, inventory=inventory, surrounding=surrounding)
        if expected != reference:
            raise ValueError('Shortlist reference changed')
        self.identity = FeatureOfferGrader(world, task['feature_task'], expected['feature_reference'],
            bindings, inventory=inventory, surrounding=surrounding)
        keys = ('product_name', 'retailer_name', 'offer_url', 'sku_id', 'variant', 'total')
        self.row_schema = obj({k: deepcopy(self.identity.schema['properties'][k]) for k in keys})
        self.schema = obj({'interpretation': {'type': 'string', 'enum': ['extracted', 'ambiguous']},
            'issues': {'type': 'array', 'items': {'type': 'string'}},
            'status': claim(enum=['shortlist', 'no_match', 'uncertain', None]),
            'rows': {'type': 'array', 'items': self.row_schema},
            'source_urls': deepcopy(self.identity.schema['properties']['source_urls'])})
        self.task, self.reference = deepcopy(task), deepcopy(expected)
        self.contract = {'version': VERSION,
            'identity_grading_version': self.identity.contract['identity_grading_version'],
            'operation': task['kind'], 'grain': task['grain'],
            'tie_policy': task['tie_policy'], 'limit': task['limit'],
            'price_basis': 'each_model_minimum_eligible_matching_listed_SEK_price'}
        self.extraction_instructions = INSTRUCTIONS

    def validate_claims(self, claims, answer):
        value = validate_claims(claims, answer, schema=self.schema)
        for row in value['rows']:
            # Reuse existing literal/variant grounding without interpreting this
            # row as a global cheapest-one recommendation.
            self.identity.validate_claims({**row, 'interpretation': 'extracted',
                'status': {'value': 'selection', 'evidence': answer}, 'source_urls': []}, answer)
        return value

    def grade(self, claims, answer):
        c = self.validate_claims(claims, answer)
        checks = {'unambiguous': c['interpretation'] == 'extracted'}
        rows = []
        expected = {m['product_id']: m for m in self.reference['selected_models']}
        if c['status']['value'] == 'no_match':
            checks.update(empty_population=not expected, no_invented_rows=not c['rows'])
        else:
            checks['concrete_shortlist'] = c['status']['value'] == 'shortlist' and bool(c['rows'])
            for i, row in enumerate(c['rows']):
                ids, reason = self.identity.resolve(row)
                offer = self.identity.offers[ids[0]] if len(ids) == 1 else None
                pid = offer['product_id'] if offer else None
                model = expected.get(pid)
                price = money_minor(row['total']) if row['total'] is not None else None
                valid = (offer is not None and row['product_name']['value'] is not None
                         and row['retailer_name']['value'] is not None and model is not None
                         and any(o['offer_id'] == offer['offer_id'] for o in model['winners'])
                         and price == model['price_minor'] and row['total']['currency'] == 'SEK')
                checks['row_' + str(i)] = valid
                rows.append({'offer_ids': ids, 'reason': reason, 'product_id': pid, 'price_minor': price})
            pids = [r['product_id'] for r in rows]
            checks['distinct_models'] = len(set(pids)) == len(pids)
            checks['complete_selected_population'] = set(pids) == set(expected)
            prices = [r['price_minor'] for r in rows]
            checks['increasing_price_order'] = all(p is not None for p in prices) and prices == sorted(prices)
        return {'grading_version': VERSION,
            'identity_grading_version': self.identity.contract['identity_grading_version'],
            'structured_claims_correct': all(checks.values()),
            'claims': c, 'response_contract': deepcopy(self.contract),
            'oracle_answer': {'status': self.reference['status'], 'selected_models': deepcopy(self.reference['selected_models'])},
            'native_reference': deepcopy(self.reference), 'derivations': rows,
            'oracle_grade': {'requirements': checks}, 'additional_checks': {},
            'selected_candidate_assessment': rows, 'check_details': {},
            'limitations': ['Native completeness does not prove browsing, exposure or attention.',
                            'Price order only; prose tradeoff explanations and purchase effects are ungraded.']}
