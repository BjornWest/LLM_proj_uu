"""Independent public offer and branch identities before locality/stock/rank."""
from copy import deepcopy

from experiments.answer_grading.extraction import claim, _quote, normalize_claims
from jsonschema import Draft202012Validator
from . import catalog_branch_task as native, feature_offer_task
from .feature_offer_grading import FeatureOfferGrader, INSTRUCTIONS as FEATURE_INSTRUCTIONS

VERSION = 'website-catalog-branch-stock-grading-v2'
BRANCH_FIELDS = ('branch_id', 'branch_name', 'branch_city', 'branch_country')
INSTRUCTIONS = FEATURE_INSTRUCTIONS + '''
Also extract the expressly named retailer branch and city, and country/branch ID
only if stated. Do not copy locality from the request, guess a branch from price,
stock or a URL, or infer an omitted branch name. Each non-null value needs an exact
final-answer quote. The price is the listed item price, not collection/shipping fees.
An unambiguous primary branch is required; do not choose whichever would pass.'''


# Explicit names for the bundled country population. This is claim identity
# normalization only: it never supplies an omitted country or uses stock/rank.
COUNTRY_NAMES = {
    'AT': ('Austria', 'Österrike'), 'BE': ('Belgium', 'Belgien'),
    'CH': ('Switzerland', 'Schweiz'), 'DE': ('Germany', 'Tyskland'),
    'DK': ('Denmark', 'Danmark'), 'ES': ('Spain', 'Spanien'),
    'FI': ('Finland',), 'FR': ('France', 'Frankrike'),
    'GB': ('United Kingdom', 'Storbritannien', 'UK'),
    'IE': ('Ireland', 'Irland'), 'IS': ('Iceland', 'Island'),
    'IT': ('Italy', 'Italien'), 'LU': ('Luxembourg', 'Luxemburg'),
    'NL': ('Netherlands', 'Nederländerna'), 'NO': ('Norway', 'Norge'),
    'PT': ('Portugal',), 'SE': ('Sweden', 'Sverige'),
}
COUNTRY_ALIASES = {native.text(name): code for code, names in COUNTRY_NAMES.items()
                   for name in (code, *names)}


def country_identity(value):
    """Finite explicit country names, or a literal two-letter country code."""
    normalized = native.text(value)
    if normalized in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[normalized]
    if len(normalized) == 2 and normalized.isascii() and normalized.isalpha():
        return normalized.upper()
    return None


class CatalogBranchGrader:
    def __init__(self, world, task, reference, bindings, *, inventory=None, surrounding=None):
        inventory = inventory or feature_offer_task.FieldInventory(task['concept_id'])
        expected = native.reference(world, task, inventory=inventory, surrounding=surrounding)
        if reference != expected:
            raise ValueError('Native branch reference binding changed')
        self.identity = FeatureOfferGrader(world, task['feature_task'], expected['feature_reference'],
            bindings, inventory=inventory, surrounding=surrounding)
        self.identity.reference = deepcopy(expected)
        self.identity.eligible = {r['offer_id'] for r in expected['candidates']}
        self.identity.winners = {r['offer_id'] for r in expected['winners']}
        self.task, self.reference = deepcopy(task), deepcopy(expected)
        self.schema = deepcopy(self.identity.schema)
        for field in BRANCH_FIELDS:
            self.schema['properties'][field] = claim()
            self.schema['required'].append(field)
        self.contract = {**self.identity.contract, 'version': VERSION, 'operation': task['kind'],
                         'collection_scope': task['collection_scope']}
        self.extraction_instructions = INSTRUCTIONS
        self.eligible = {(r['offer_id'], r['branch_id']) for r in expected['branch_candidates']}
        self.winners = {(r['offer_id'], r['branch_id']) for r in expected['branch_winners']}

    def grade(self, claims, answer):
        c = normalize_claims(claims, schema=self.schema)
        c.setdefault('variant', {})
        basic = self.identity.validate_claims(
            {k: c[k] for k in self.identity.schema['properties']}, answer)
        c.update(basic)
        Draft202012Validator(self.schema).validate(c)
        for field in BRANCH_FIELDS:
            value = c[field]
            if value['value'] is None:
                if value['evidence'] is not None:
                    raise ValueError('Absent branch claim needs absent evidence')
            else:
                _quote(value['evidence'], answer)
                if value['value'] not in value['evidence']:
                    raise ValueError('Branch value absent from its answer quote')
        result = self.identity.grade(basic, answer)
        selected = result['selected_candidate_assessment']
        matches = []
        if selected is not None and c['branch_name']['value'] is not None and c['branch_city']['value'] is not None:
            rid = self.identity.offers[selected['offer_id']]['retailer_id']
            for branch in self.reference['branch_inventory'][rid]:
                if (native.text(branch['branch_name']) == native.text(c['branch_name']['value'])
                        and native.text(branch['city']) == native.text(c['branch_city']['value'])
                        and (c['branch_id']['value'] is None or c['branch_id']['value'] == branch['branch_id'])
                        and (c['branch_country']['value'] is None or
                             (country_identity(c['branch_country']['value']) is not None and
                              country_identity(c['branch_country']['value']) == country_identity(branch['country'])))):
                    matches.append(branch)
        key = (selected['offer_id'], matches[0]['branch_id']) if selected and len(matches) == 1 else None
        checks = result['oracle_grade']['requirements']
        if c['status']['value'] == 'selection':
            checks.update(public_branch_identity=len(matches) == 1,
                          physical_branch_and_locality=key in self.eligible,
                          cheapest_branch_offer=key in self.winners)
        elif c['status']['value'] == 'no_match':
            checks['no_contradictory_branch'] = all(c[k]['value'] is None for k in BRANCH_FIELDS)
        result.update(grading_version=VERSION, response_contract=deepcopy(self.contract), claims=c,
                      structured_claims_correct=all(checks.values()))
        result['identity_resolution']['branch_ids'] = [b['branch_id'] for b in matches]
        result['oracle_answer'].update({field: c[field]['value'] for field in BRANCH_FIELDS})
        for field in ('public_branch_identity', 'physical_branch_and_locality',
                      'cheapest_branch_offer', 'no_contradictory_branch'):
            if field in checks:
                result['check_details'][field] = {
                    'passed': checks[field], 'branch_ids': [b['branch_id'] for b in matches],
                    'explanation': 'Explicit branch identity before native city, physical stock or listed-price ranking.'}
        result['limitations'] += ['Branch identity is resolved over all retailer branches before stock/locality/ranking.',
            'No opening hours, readiness guarantee, travel, reservations, fees or actual collection effects are graded.',
            'Website branch/stock projection acceptance and exposure are separate.']
        return result
