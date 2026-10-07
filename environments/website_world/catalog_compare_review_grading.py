"""One compound extraction, exact unchanged native subgraders, conjunctive grade."""
from copy import deepcopy

from jsonschema import Draft202012Validator
from experiments.answer_grading.extraction import obj
from . import catalog_compare_review_task as native
from .catalog_comparison_grading import CatalogComparisonGrader, INSTRUCTIONS as FACT_INSTRUCTIONS
from .catalog_review_grading import ReviewSummaryGrader, INSTRUCTIONS as REVIEW_INSTRUCTIONS

VERSION = 'website-catalog-compare-review-grading-v1'


class CatalogCompareReviewGrader:
    def __init__(self, world, task, reference, bindings, site_registry, *, surrounding,
                 inventory=None, review_inventory=None):
        if inventory is None:
            from .feature_offer_task import FieldInventory
            inventory = FieldInventory(task['concept_id'])
        if review_inventory is None:
            from .catalog_review_task import ReviewInventory
            review_inventory = ReviewInventory(task['concept_id'])
        expected = native.reference(world, task, inventory=inventory, review_inventory=review_inventory)
        if reference != expected:
            raise ValueError('Compound native reference changed')
        self.task, self.reference = deepcopy(task), deepcopy(expected)
        self.comparison = CatalogComparisonGrader(world, task['comparison_task'], expected['comparison'],
                                                  bindings, inventory=inventory)
        self.reviews = {role: ReviewSummaryGrader(world, t, expected['reviews'][role],
            site_registry, surrounding=surrounding, inventory=review_inventory)
            for role, t in task['review_tasks'].items()}
        self.schema = obj({'comparison': deepcopy(self.comparison.schema),
                           'reviews': obj({role: deepcopy(g.schema) for role, g in self.reviews.items()})})
        subjects = '; '.join(role + ' is ' + t['subject']['product_name']
                            for role, t in task['review_tasks'].items())
        self.extraction_instructions = ('Extract the single final answer into the compound schema. '
            'Extract comparison and both review summaries independently; never fill missing information '
            'from another part or compute missing values. Review output keys identify the named models: '
            + subjects + '.\nCOMPARISON RULES:\n' + FACT_INSTRUCTIONS
            + '\nREVIEW RULES:\n' + REVIEW_INSTRUCTIONS)
        self.contract = {'version': VERSION, 'operation': native.KIND,
            'completion': expected['completion'], 'required_obligations': deepcopy(task['required_obligations']),
            'comparison': deepcopy(self.comparison.contract),
            'reviews': {role: deepcopy(g.contract) for role, g in self.reviews.items()},
            'visits_exposure_attention': 'not_inferred'}

    def grade(self, claims, answer):
        # Let each existing parent perform its own complete validation, including
        # ReviewSummaryGrader's absent-variant -> null normalization. Only the
        # compound envelope is new; no expected values are inserted here.
        envelope = obj({'comparison': {'type': 'object'},
                        'reviews': obj({role: {'type': 'object'} for role in self.reviews})})
        Draft202012Validator(envelope).validate(claims)
        reports = {'comparison': self.comparison.grade(claims['comparison'], answer)}
        reports.update({role: g.grade(claims['reviews'][role], answer) for role, g in self.reviews.items()})
        normalized = {'comparison': deepcopy(reports['comparison']['claims']),
                      'reviews': {role: deepcopy(reports[role]['claims']) for role in self.reviews}}
        Draft202012Validator(self.schema).validate(normalized)
        checks, details = {}, {}
        for role, report in reports.items():
            checks[role + '.complete'] = report['structured_claims_correct']
            details[role + '.complete'] = {'expected': True, 'supplied': report['structured_claims_correct'],
                'explanation': 'Conjunction of unchanged native requirements for this part.'}
            for key, value in report['oracle_grade']['requirements'].items():
                checks[role + '.' + key] = value
                details[role + '.' + key] = deepcopy(report['check_details'][key])
        return {'grading_version': VERSION, 'structured_claims_correct': all(checks.values()),
            'claims': normalized, 'response_contract': deepcopy(self.contract),
            'native_reference': deepcopy(self.reference), 'oracle_answer': deepcopy(self.reference),
            'oracle_grade': {'requirements': checks}, 'additional_checks': {},
            'selected_candidate_assessment': {role: deepcopy(r['selected_candidate_assessment'])
                                              for role, r in reports.items()},
            'derivations': [{'part': role, 'native_derivations': deepcopy(r['derivations'])}
                            for role, r in reports.items()],
            'check_details': details, 'native_subreports': reports,
            'limitations': ['Correct compound answer and source links do not prove navigation, delivery or attention.',
                'Whole-run effects and recording authority require separate exact consumer acceptance.',
                'Public disclosure sufficiency is separate from native known/unknown/NA truth.']
                + list(dict.fromkeys(s for r in reports.values() for s in r['limitations']))}
