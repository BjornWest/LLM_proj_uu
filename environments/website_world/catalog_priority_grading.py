"""Reuse feature/identity grounding; rank by explicitly declared priorities."""
from copy import deepcopy

from . import catalog_priority_task as native, feature_offer_task as feature
from .feature_offer_grading import FeatureOfferGrader

VERSION = 'website-catalog-priority-grading-v1'


class CatalogPriorityGrader:
    def __init__(self,world,task,reference,bindings,*,inventory=None,surrounding=None):
        inventory = inventory or feature.FieldInventory(task['concept_id'])
        expected = native.reference(world,task,inventory=inventory,surrounding=surrounding)
        if reference != expected:raise ValueError('Priority reference changed')
        self.identity = FeatureOfferGrader(world,task['feature_task'],expected['feature_reference'],
            bindings,inventory=inventory,surrounding=surrounding)
        self.identity.eligible = {r['offer_id'] for r in expected['candidates']}
        self.identity.winners = {r['offer_id'] for r in expected['winners']}
        self.identity.reference['status'] = expected['status']
        self.schema = deepcopy(self.identity.schema)
        self.task,self.reference = deepcopy(task),deepcopy(expected)
        self.contract = {**deepcopy(self.identity.contract),'version':VERSION,'operation':task['kind'],
            'ranking':task['ranking'],'priorities':deepcopy(task['priorities']),
            'tie_policy':task['tie_policy'],'explanations':'ungraded'}
        self.extraction_instructions = self.identity.extraction_instructions
        self.validate_claims = self.identity.validate_claims

    def grade(self,claims,answer):
        grade = self.identity.grade(claims,answer)
        checks = grade['oracle_grade']['requirements']
        if 'cheapest_listed_offer' in checks:
            checks['optimal_declared_priorities'] = checks.pop('cheapest_listed_offer')
            grade['check_details'].pop('cheapest_listed_offer')
            grade['check_details']['optimal_declared_priorities'] = {
                'expected':{'values':deepcopy(self.reference['best_priority_values']),
                    'tie_price_minor':self.reference['tie_price_minor']},
                'supplied':deepcopy(grade['selected_candidate_assessment']),
                'explanation':'Resolve the stated SKU independently, then apply known lexicographic numeric features and final listed-price tie-break.'}
        grade.update(grading_version=VERSION,response_contract=deepcopy(self.contract),
            native_reference=deepcopy(self.reference),structured_claims_correct=all(checks.values()))
        if type(grade['derivations']) is not list:grade['derivations']=[grade['derivations']]
        grade['derivations'].append({'ranking':self.task['ranking'],'priority_values':deepcopy(self.reference['best_priority_values'])})
        grade['limitations'].append('No utility score, comparative feature claims, explanation correctness or public exposure is inferred.')
        return grade
