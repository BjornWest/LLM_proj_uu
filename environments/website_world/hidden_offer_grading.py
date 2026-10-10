"""Private outcome plus trusted, pinned clarification delivery/ordering evidence."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from . import hidden_offer_task, catalog_clarification, feature_offer_task
from .feature_offer_grading import FeatureOfferGrader

VERSION = 'website-hidden-feature-grading-v1'


class HiddenOfferGrader:
    def __init__(self,world,task,reference,bindings,*,inventory=None,surrounding=None,interaction_trace=None):
        inventory = inventory or feature_offer_task.FieldInventory(task['concept_id'])
        native = hidden_offer_task.reference(world,task,inventory=inventory,surrounding=surrounding)
        if reference != native: raise ValueError('Hidden task native reference changed')
        self.task,self.reference = deepcopy(task),deepcopy(native)
        self.inner = FeatureOfferGrader(world,task['selection_task'],native['selection_reference'],bindings,
                                       inventory=inventory,surrounding=surrounding)
        self.schema,self.contract = deepcopy(self.inner.schema),deepcopy(self.inner.contract)
        self.contract.update(version=VERSION,operation=task['kind'],
            clarification_evaluation='Actual matching callback plus subsequent retained main-request delivery and declared ordering.',
            evidence_coverage=task['evidence_coverage'])
        self.extraction_instructions = self.inner.extraction_instructions
        self.interaction = catalog_clarification.evidence(interaction_trace,task) if interaction_trace is not None else None

    def validate_claims(self,claims,answer): return self.inner.validate_claims(claims,answer)

    def grade(self,claims,answer):
        if self.interaction is not None:
            for name,expected in self.interaction['source_sha256'].items():
                if sha256(Path(name).read_bytes()).hexdigest() != expected:
                    raise ValueError('Retained clarification source changed')
        grade = self.inner.grade(claims,answer); answer_correct = grade['structured_claims_correct']
        interaction = self.interaction or {'status':'unknown','diagnostics':['No authoritative interaction trace supplied']}
        supported = self.reference['clarification_affects_eligibility']
        completed = (False if answer_correct is False else None if not supported or interaction['status'] == 'unknown'
                     else answer_correct and interaction['status'] == 'satisfied')
        grade.update(grading_version=VERSION,response_contract=deepcopy(self.contract),
            answer_outcome_correct=answer_correct,clarification_evaluation=deepcopy(interaction),
            task_binding_supported=supported,structured_claims_correct=completed)
        grade['oracle_grade']['requirements']['clarification_binding_supported'] = supported
        grade['oracle_grade']['requirements']['clarification_delivery_and_ordering'] = (
            None if interaction['status'] == 'unknown' else interaction['status'] == 'satisfied')
        grade['check_details']['clarification_delivery_and_ordering'] = {
            'expected':'Matching personal reply delivered to a subsequent retained main request within the declared ordering.',
            'supplied':deepcopy(interaction),'answer_quote':None,
            'explanation':'Host callback and exact policy-delivery evidence, independent of final answer identity or matching price.'}
        grade['limitations'].append('Hidden reply delivery does not prove attention or reasoning; missing transport proof stays unknown. '
            'Unchanged eligibility across all declared contrasts cannot launch as an effectful clarification task.')
        return grade
