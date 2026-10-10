"""Resolve public pack identity before checking exact unit-price optimality."""
from copy import deepcopy

from experiments.answer_grading.extraction import MONEY, claim, obj, validate_claims, money_minor, _quote
from . import catalog_unit_price_task as native, feature_offer_task as feature
from .feature_offer_grading import FeatureOfferGrader, INSTRUCTIONS as FEATURE_INSTRUCTIONS

VERSION = 'website-catalog-unit-price-grading-v2'
INSTRUCTIONS = FEATURE_INSTRUCTIONS+'''
For this task total remains the stated listed WHOLE-PACK price, not SEK/kg.
Also copy explicitly stated quantity_g (integer grams), quantity_unit (g),
unit_price (money amount/currency) and unit_price_unit (kg) from the final answer.
Do not convert kg to g, calculate a unit price, or fill anything from the request,
product identity or native data. Each amount/unit requires its own exact quote.
Missing quantity/unit/unit_price claims are null. Preserve wrong values.'''
EXTRA = {'quantity_g', 'quantity_unit', 'unit_price', 'unit_price_unit'}


class CatalogUnitPriceGrader:
    def __init__(self, world, task, reference, bindings, *, inventory=None, surrounding=None):
        inventory = inventory or feature.FieldInventory(task['concept_id'])
        expected = native.reference(world, task, inventory=inventory, surrounding=surrounding)
        if reference != expected:
            raise ValueError('Unit-price reference changed')
        derived, _ = native.quantity_inventory(world, inventory)
        self.identity = FeatureOfferGrader(world, task['feature_task'], expected['feature_reference'],
            bindings, inventory=derived, surrounding=surrounding)
        # Keep the existing independent identity and stock/price/feature checks;
        # change only the optimal-offer set, then explicitly name its new meaning.
        self.identity.winners = {r['offer_id'] for r in expected['winners']}
        self.schema = obj({**deepcopy(self.identity.schema['properties']),
            'quantity_g': claim('integer'), 'quantity_unit': claim(),
            'unit_price': {'anyOf': [deepcopy(MONEY), {'type': 'null'}]}, 'unit_price_unit': claim()})
        self.task, self.reference = deepcopy(task), deepcopy(expected)
        self.contract = {**deepcopy(self.identity.contract), 'version': VERSION, 'operation': task['kind'],
            'ranking': task['ranking'], 'quantity_field': task['quantity_field'],
            'quantity_basis': task['quantity_basis'], 'unit_price_unit': task['unit_price_unit'],
            'display_rounding': task['display_rounding']}
        self.extraction_instructions = INSTRUCTIONS

    def validate_claims(self, claims, answer):
        base = self.identity.validate_claims({k:v for k,v in claims.items() if k not in EXTRA}, answer)
        c = validate_claims({**base, **{k:v for k,v in claims.items() if k in EXTRA}}, answer, schema=self.schema)
        if c['unit_price'] is not None:
            _quote(c['unit_price']['evidence'], answer)
            money_minor(c['unit_price'])
        return c

    def grade(self, claims, answer):
        c = self.validate_claims(claims, answer)
        grade = self.identity.grade({k:v for k,v in c.items() if k not in EXTRA}, answer)
        checks = grade['oracle_grade']['requirements']
        if 'cheapest_listed_offer' in checks:
            checks['lowest_exact_unit_price'] = checks.pop('cheapest_listed_offer')
            grade['check_details'].pop('cheapest_listed_offer')
        selected = grade['selected_candidate_assessment']
        row = next((r for r in self.reference['candidates'] if selected and r['offer_id'] == selected['offer_id']), None)
        if c['status']['value'] == 'selection':
            checks.update(reported_net_food_grams=row is not None and c['quantity_g']['value'] == row['quantity_g'],
                reported_quantity_unit=c['quantity_unit']['value'] == 'g',
                reported_unit_price=row is not None and c['unit_price'] is not None and
                    money_minor(c['unit_price']) == row['unit_price_minor'] and c['unit_price']['currency'] == 'SEK',
                reported_unit_price_unit=c['unit_price_unit']['value'] == 'kg')
        elif c['status']['value'] == 'no_match':
            checks['no_contradictory_unit_price'] = c['unit_price'] is None and all(
                c[k]['value'] is None for k in ('quantity_g','quantity_unit','unit_price_unit'))
        for key in ('lowest_exact_unit_price','reported_net_food_grams','reported_quantity_unit',
                    'reported_unit_price','reported_unit_price_unit','no_contradictory_unit_price'):
            if key in checks:
                grade['check_details'][key] = {'expected': deepcopy(row),
                    'minimum_unit_price_exact': deepcopy(self.reference['minimum_unit_price_exact']),
                    'supplied': {k:deepcopy(c[k]) for k in EXTRA},
                    'explanation': 'Exact whole-pack integer-ore/net-food-grams ratio ranks before two-decimal half-up display.'}
        grade.update(grading_version=VERSION, claims=c, response_contract=deepcopy(self.contract),
            structured_claims_correct=all(checks.values()), native_reference=deepcopy(self.reference))
        if type(grade['derivations']) is not list: grade['derivations'] = [grade['derivations']]
        grade['derivations'].append({'selected_pack': deepcopy(row), 'exact_unit_price_ranking': self.task['ranking']})
        grade['limitations'].append('No public quantity disclosure/visit proof, arithmetic explanation, delivered price or purchase-effect certification.')
        return grade
