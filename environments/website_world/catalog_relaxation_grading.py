"""Ground the answer and its explicitly reported permitted criteria set."""
from copy import deepcopy

from experiments.answer_grading.extraction import claim, obj, validate_claims
from . import catalog_relaxation_task as native, feature_offer_task as feature
from .feature_offer_grading import FeatureOfferGrader, INSTRUCTIONS as FEATURE_INSTRUCTIONS

VERSION = 'website-catalog-relaxation-grading-v1'
INSTRUCTIONS = FEATURE_INSTRUCTIONS+'''
Also extract criteria_used only when the answer explicitly names its criteria set.
Copy the literal label and an exact contiguous quote; do not infer the label from
requirements, feature values, the public task, product identity or prices. Missing
criteria_used is null. Preserve a disallowed label rather than replacing it with
an allowed one. A no-match answer must not invent a used criteria set.'''


class CatalogRelaxationGrader:
    def __init__(self, world, task, reference, bindings, *, inventory=None, surrounding=None):
        inventory = inventory or feature.FieldInventory(task['concept_id'])
        expected = native.reference(world, task, inventory=inventory, surrounding=surrounding)
        if reference != expected:
            raise ValueError('Relaxation reference changed')
        index = expected['selected_index'] if expected['selected_index'] is not None else 0
        self.selected = FeatureOfferGrader(world, task['scenarios'][index]['feature_task'],
            expected['scenario_references'][index], bindings, inventory=inventory, surrounding=surrounding)
        self.schema = obj({**deepcopy(self.selected.schema['properties']), 'criteria_used': claim()})
        self.task, self.reference = deepcopy(task), deepcopy(expected)
        self.contract = {**deepcopy(self.selected.contract), 'version': VERSION, 'operation': task['kind'],
            'priority': task['priority'], 'criteria_labels': [s['label'] for s in task['scenarios']],
            'alternatives_basis': task['alternatives_basis']}
        self.extraction_instructions = INSTRUCTIONS

    def validate_claims(self, claims, answer):
        c = validate_claims(claims, answer, schema=self.schema)
        self.selected.validate_claims({k: v for k,v in c.items() if k != 'criteria_used'}, answer)
        return c

    def grade(self, claims, answer):
        c = self.validate_claims(claims, answer)
        grade = self.selected.grade({k: v for k,v in c.items() if k != 'criteria_used'}, answer)
        correct_criteria = c['criteria_used']['value'] == self.reference['selected_label']
        checks = grade['oracle_grade']['requirements']
        checks['explicit_correct_criteria_set'] = correct_criteria
        grade.update(grading_version=VERSION, claims=c, response_contract=deepcopy(self.contract),
            structured_claims_correct=all(checks.values()), native_reference=deepcopy(self.reference))
        grade['check_details']['explicit_correct_criteria_set'] = {
            'expected': self.reference['selected_label'], 'supplied': c['criteria_used']['value'],
            'answer_quote': c['criteria_used']['evidence'], 'explanation': 'First established available set takes priority over price in a later set.'}
        if type(grade['derivations']) is not list: grade['derivations'] = [grade['derivations']]
        grade['derivations'].append({'criteria_set': deepcopy(c['criteria_used']),
            'native_selected_index': self.reference['selected_index']})
        grade['limitations'].append('Correct criteria/offer does not establish exhaustive search, public completeness or explanation correctness.')
        return grade
