"""Reuse feature identity/outcome grading with separately bound public memories."""
from copy import deepcopy

from . import feature_offer_task, memory_offer_task
from .feature_offer_grading import FeatureOfferGrader

VERSION = 'website-memory-feature-grading-v1'


class MemoryOfferGrader:
    def __init__(self, world, task, reference, bindings, *, inventory=None, surrounding=None):
        inventory = inventory or feature_offer_task.FieldInventory(task['concept_id'])
        native = memory_offer_task.reference(world, task, inventory=inventory, surrounding=surrounding)
        if reference != native:
            raise ValueError('Native memory reference binding changed')
        self.task, self.reference = deepcopy(task), deepcopy(native)
        self.inner = FeatureOfferGrader(world, task['selection_task'], native['selection_reference'],
            bindings, inventory=inventory, surrounding=surrounding)
        self.schema, self.contract = deepcopy(self.inner.schema), deepcopy(self.inner.contract)
        self.contract.update(version=VERSION, operation=task['kind'], recipient=task['recipient'],
            memory_semantics=task['memory_resolution']['override_policy'],
            evidence_coverage=task['evidence_coverage'])
        self.extraction_instructions = self.inner.extraction_instructions

    def validate_claims(self, claims, answer):
        return self.inner.validate_claims(claims, answer)

    def grade(self, claims, answer):
        grade = self.inner.grade(claims, answer)
        grade['grading_version'] = VERSION
        grade['response_contract'] = deepcopy(self.contract)
        grade['limitations'].append('Recipient/scoped defaults affect native eligibility; correct selection '
            'does not establish actual memory reading, maintenance or clarification-before-search.')
        return grade
