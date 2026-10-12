"""Carrier subject binding over the shared grounded review arithmetic grader."""
from copy import deepcopy
from urllib.parse import urlsplit, parse_qsl, unquote

from experiments.answer_grading.extraction import claim, obj, validate_claims, _quote
from . import carrier_review_task as native
from .numeric_claim_grounding import validate_mean_claim
from .catalog_review_grading import ReviewSummaryGrader, INSTRUCTIONS

VERSION = 'website-carrier-review-grading-v2'


class CarrierReviewGrader(ReviewSummaryGrader):
    def __init__(self, world, task, reference, site_registry, *, publication, inventory=None):
        inventory = inventory or native.ReviewInventory()
        expected = native.reference(world, task, inventory=inventory)
        if reference != expected or publication != native.public_projection(world):
            raise ValueError('Carrier review reference/publication binding changed')
        entries = [s for s in site_registry if s['site_id'] == publication['site_id']]
        if len(entries) != 1:
            raise ValueError('Need one actual carrier-review publication identity')
        entry = entries[0]
        if entry['kind'] != publication['kind'] or entry['name'] != publication['name']:
            raise ValueError('Carrier review site identity changed')
        origin = urlsplit(entry['origin'])
        if (origin.scheme not in ('http', 'https') or not origin.netloc
                or origin.path not in ('', '/') or origin.query or origin.fragment):
            raise ValueError('Carrier review origin must be absolute and path-free')
        self.origins = {(origin.scheme, origin.netloc)}
        self.task, self.reference = deepcopy(task), deepcopy(expected)
        counts = (['rating_count', 'written_review_count', 'rating_only_count',
                   *[f'star_{n}_count' for n in range(1, 6)]] if task['operation'] == 'rating_summary'
                  else [*native.COUNTS, 'written_review_count', 'assessed_count'])
        self.contract = {'version': VERSION, 'operation': task['operation'],
            'count_fields': counts, 'unit': 'canonical_review', 'subject_scope': 'carrier',
            'shipping_class': task['shipping_class'],
            'date_bounds': {k: task[k] for k in ('date_from', 'date_to') if k in task},
            'exposure': 'not_inferred_from_native_corpus_or_link', 'rounding': 'two_decimal_half_up'}
        self.schema = obj({'interpretation': {'type': 'string', 'enum': ['extracted', 'ambiguous']},
            'issues': {'type': 'array', 'items': {'type': 'string'}},
            'status': claim(enum=['summary', 'uncertain', None]),
            'carrier_name': claim(), 'review_url': claim(),
            **{k: claim('integer') for k in counts}, 'mean_rating': claim(),
            'mean_undefined': claim('boolean'),
            'verdict': claim(enum=['more_positive', 'more_negative', 'tie', 'insufficient_evidence', None]),
            'source_urls': {'type': 'array', 'items': obj({'value': {'type': 'string'},
                'evidence': {'type': 'string'}})}})
        self.extraction_instructions = (INSTRUCTIONS+
            '\nThis is a carrier profile, not a product/SKU review. Extract carrier_name and review_url; '
            'there are no variant fields. Service class and inclusive date bounds are specified by the public request. '
            'Regular does not imply home-only delivery. Do not infer opinions from hidden shipment quality.')

    def validate_claims(self, claims, answer):
        c = validate_claims(claims,answer,schema=self.schema,
                            semantic_fields=('verdict','mean_rating','mean_undefined'))
        validate_mean_claim(c['mean_rating'],answer)
        return c

    def _identity(self, claims):
        name, url = claims['carrier_name']['value'], claims['review_url']['value']
        if name is None or name.casefold() != self.task['subject']['carrier_name'].casefold() or url is None:
            return False, []
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        if ((parts.scheme, parts.netloc) not in self.origins or parts.fragment
                or len({k for k, _ in pairs}) != len(pairs)
                or unquote(parts.path) != '/carriers/'+self.task['subject']['carrier_id']):
            return False, []
        for key, value in pairs:
            if key in ('shipping_class', 'date_from', 'date_to'):
                if value != self.task.get(key): return False, []
            elif key == 'page':
                if not value.isdecimal() or int(value) < 1: return False, []
            elif key == 'sort':
                if value not in ('newest', 'oldest'): return False, []
            else:
                return False, []
        return True, []

    def grade(self, claims, answer):
        # Counts, exact rounded means, directional verdicts and quote grounding use
        # the existing product-review core. Only entity/route identity is adapted.
        result = super().grade(claims, answer)
        result['grading_version'] = VERSION
        result['selected_candidate_assessment'] = {'subject': deepcopy(self.task['subject'])}
        result['derivations'] = [result['derivations']]
        result['limitations'] = ['Canonical review IDs once; ratings include silent entries and topic counts use written statements only.',
            'Class/date filters are published scope; regular delivery is not a home-only scope.',
            'No latent quality/history metric supplies an opinion or future delivery guarantee.',
            'Correct answer and source link do not certify visits, exposure, attention or purchase effects.']
        return result
