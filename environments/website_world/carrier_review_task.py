"""Dated carrier-review summaries; hidden shipment quality is not an opinion."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import re

from environments.product_world.review_population import summarize_ratings
from experiments.carrier_service_pilot.prose import POOLS
from .adapter import digest
from .feature_offer_task import ROOT
from experiments import source_binding

VERSION = 'website-carrier-review-task-v1'
KIND = 'summarize_carrier_reviews'
COUNTS = ('positive', 'negative', 'neutral', 'mixed', 'not_assessed')
ASPECTS = ('punctuality', 'window', 'handoff', 'handling', 'tracking',
           'notification_dispatch', 'notification_delivery_day',
           'notification_approaching', 'notification_failed_attempt',
           'collection', 'locker', 'fallback')


class ReviewInventory:
    def __init__(self):
        self.source_hashes = {path: sha256((ROOT/path).read_bytes()).hexdigest() for path in (
            'experiments/carrier_service_pilot/model.py',
            'experiments/carrier_service_pilot/prose.py')}

    def check_sources(self):
        for path, expected in self.source_hashes.items():
            if sha256((ROOT/path).read_bytes()).hexdigest() != expected:
                raise ValueError('Carrier review declaration changed: '+path)


def resolve(spec):
    allowed = {'kind', 'operation', 'carrier_index', 'shipping_class',
               'date_from', 'date_to', 'aspect', 'min_assessed'}
    if type(spec) is not dict or set(spec)-allowed or spec.get('kind') != KIND:
        raise ValueError('Declare a carrier review summary, not private shipment metrics')
    operation = spec.get('operation')
    index = spec.get('carrier_index', 0)
    shipping = spec.get('shipping_class', 'all')
    if operation not in ('rating_summary', 'topic_counts'):
        raise ValueError('Use rating_summary or topic_counts')
    if type(index) is not int or not 0 <= index <= 10000:
        raise ValueError('Carrier index must be a finite identity index')
    if shipping not in ('all', 'regular', 'bulky'):
        raise ValueError('Published class is all/regular/bulky, not destination mode')
    result = {'kind': KIND, 'operation': operation, 'carrier_index': index,
              'shipping_class': shipping}
    for field in ('date_from', 'date_to'):
        if field in spec:
            value = spec[field]
            if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError('Review date bounds must be explicit ISO dates')
            date.fromisoformat(value)
            result[field] = value
    if result.get('date_from', '0001-01-01') > result.get('date_to', '9999-12-31'):
        raise ValueError('Review date interval is inverted')
    if operation == 'rating_summary':
        if {'aspect', 'min_assessed'} & set(spec):
            raise ValueError('Star ratings are not topic opinions')
    else:
        if spec.get('aspect') not in ASPECTS:
            raise ValueError('Choose a declared written carrier-review aspect')
        minimum = spec.get('min_assessed', 1)
        if type(minimum) is not int or not 1 <= minimum <= 1000:
            raise ValueError('Declare min_assessed1..1000')
        result.update(aspect=spec['aspect'], min_assessed=minimum)
    return result


def canonical_public(world):
    corpus = world['carrier_evidence']
    if corpus['schema_version'] != 'carrier-service-evidence-v1':
        raise ValueError('Unsupported carrier-review corpus')
    public = corpus['public']
    if public['corpus_id'] != corpus['corpus_id']:
        raise ValueError('Public carrier-review corpus identity changed')
    carriers = {c['carrier_id']: c for c in public['carriers']}
    if len(carriers) != len(public['carriers']):
        raise ValueError('Duplicate carrier profile identity')
    rows = {}
    for row in public['reviews']:
        if (type(row.get('review_id')) is not str or not row['review_id']
                or type(row.get('reviewer_id')) is not str or not row['reviewer_id']
                or row.get('carrier_id') not in carriers
                or type(row.get('stars')) is not int or not 1 <= row['stars'] <= 5
                or row.get('text') is not None and type(row['text']) is not str):
            raise ValueError('Invalid published carrier-review identity/rating/text')
        if type(row.get('date')) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['date']):
            raise ValueError('Published review needs its actual ISO date')
        date.fromisoformat(row['date'])
        services = carriers[row['carrier_id']]['services']
        if not any(s['service_id'] == row.get('service_id') and
                   s['shipping_class'] == row.get('shipping_class') for s in services):
            raise ValueError('Review service/class belongs to another carrier')
        if row['review_id'] in rows and rows[row['review_id']] != row:
            raise ValueError('Conflicting syndicated carrier review copies')
        rows[row['review_id']] = deepcopy(row)
    return carriers, rows


def make(world, spec, *, inventory):
    inventory.check_sources()
    selection = resolve(spec)
    carriers, _ = canonical_public(world)
    ordered = sorted(carriers)
    if selection['carrier_index'] >= len(ordered):
        raise ValueError('Generated corpus has no selected carrier identity')
    carrier = carriers[ordered[selection['carrier_index']]]
    if selection['operation'] == 'rating_summary':
        instruction = ('Report rating count, written-review count, ratings without text, five star counts, '
            'and mean stars rounded to two decimal places half up. Include silent ratings. '
            'If there are no ratings, say the mean is undefined, not zero.')
    else:
        instruction = ('Count positive, negative, neutral, mixed and not-assessed written comments about '+
            selection['aspect'].replace('_', ' ')+'. Count each comment once; opposite reports in one comment are mixed. '
            'Other written comments count as not assessed. Compare positive versus negative comment counts as '
            'more positive, more negative or tied; report insufficient evidence if fewer than '+
            str(selection['min_assessed'])+' comments assess the topic. Report written-review and assessed counts. '
            'Stars, hidden shipment outcomes and silence do not establish an opinion.')
    scope = 'all published shipping classes' if selection['shipping_class'] == 'all' else selection['shipping_class']+' shipping class'
    if 'date_from' in selection: scope += ', dated on or after '+selection['date_from']
    if 'date_to' in selection: scope += ', dated on or before '+selection['date_to']
    message = ('Summarize the published customer reviews for '+carrier['name']+' for '+scope+'. '+instruction+
        ' Use the complete recorded corpus in this scope and count each canonical review ID once even if syndicated. '
        'Cite the actual carrier review-profile page and name the carrier. Regular shipping can include collection; '
        'this is not a home-only filter. Report attributed experiences, not a guarantee of future delivery quality. Do not buy anything.')
    task = {'schema_version': VERSION, **selection, 'world_id': world['world_id'],
        'world_sha256': digest(world), 'corpus_id': world['carrier_evidence']['corpus_id'],
        'subject': {'carrier_id': carrier['carrier_id'], 'carrier_name': carrier['name']},
        'subject_scope': 'carrier', 'user_message': message, 'memories': [],
        'source_sha256': deepcopy(inventory.source_hashes),
        'corpus_policy': 'Published carrier/service/date scope; canonical review IDs once; no hidden shipment outcomes.'}
    task['task_id'] = 'carrier-review-'+digest(task)[:24]
    return task


def _statements(world, public):
    """Use only source-bound statements actually present in a published comment."""
    matches = [r for r in world['carrier_evidence']['private']['reviews'] if r['review_id'] == public['review_id']]
    if not matches or any(r != matches[0] for r in matches):
        raise ValueError('Written carrier review lacks canonical composition')
    private = matches[0]
    if {k: v for k, v in private.items() if k not in ('statements', 'shipment_id')} != public:
        raise ValueError('Private composition and published carrier review differ')
    statements = private['statements']
    signs = list(dict.fromkeys(s['sentiment'] for s in statements if s['sentiment'] != 'neutral'))
    ordered = [s for s in statements if s['sentiment'] == 'neutral']
    for sign in signs: ordered.extend(s for s in statements if s['sentiment'] == sign)
    parts = []
    for index, statement in enumerate(ordered):
        pool, sign, position = statement['template_id'].rsplit(':', 2)
        if sign != statement['sentiment'] or (pool, sign) not in POOLS or not position.isdecimal():
            raise ValueError('Undeclared carrier-review formulation')
        try: template = POOLS[(pool, sign)][int(position)]
        except (ValueError, IndexError): raise ValueError('Invalid carrier-review formulation identity')
        aspect = statement['aspect']
        expected = ('tracking' if pool.startswith('tracking') else 'collection' if pool == 'fallback_collection'
                    else 'fallback' if pool == 'fallback_retry' else pool)
        if pool.startswith('notification'):
            if aspect not in ASPECTS or not aspect.startswith('notification_'):
                raise ValueError('Notification statement has another aspect')
            template = template.replace('{notification}', aspect.removeprefix('notification_').replace('_', '-'))
            expected = aspect
        if aspect != expected or aspect not in ASPECTS:
            raise ValueError('Statement aspect differs from its declared words')
        # Slot text is retained verbatim, never used to read private shipment facts.
        pattern = re.escape(template)
        pattern = re.sub(r'\\\{[a-z_]+\\\}', '.+?', pattern)
        if not re.fullmatch(pattern, statement['text']):
            raise ValueError('Statement words differ from its formulation')
        text = statement['text']
        forms = [text]
        if index and {ordered[index-1]['sentiment'], sign} == {'positive', 'negative'}:
            forms += [prefix+(text[0].lower()+text[1:]).replace(' i ', ' I ')
                      for prefix in ('But ', 'However, ', 'On the other hand, ')]
            if text.startswith('I '):
                forms += [prefix+text for prefix in ('But ', 'However, ', 'On the other hand, ')]
        parts.append('(?:'+'|'.join(re.escape(v) for v in forms)+')')
    if not parts or not re.fullmatch(' '.join(parts), public['text']):
        raise ValueError('Unrendered or missing carrier-review statement')
    return statements


def reference(world, task, *, inventory):
    spec = {k: task[k] for k in ('kind', 'operation', 'carrier_index', 'shipping_class',
        'date_from', 'date_to', 'aspect', 'min_assessed') if k in task}
    if not source_binding.compatible(task, make(world, spec, inventory=inventory)):
        raise ValueError('Carrier review task/world/source binding changed')
    _, public = canonical_public(world)
    rows = [r for r in public.values() if r['carrier_id'] == task['subject']['carrier_id']
        and (task['shipping_class'] == 'all' or r['shipping_class'] == task['shipping_class'])
        and task.get('date_from', '0001-01-01') <= r['date'] <= task.get('date_to', '9999-12-31')]
    result = {'schema_version': VERSION, 'task_id': task['task_id'], 'world_id': world['world_id'],
        'world_sha256': task['world_sha256'], 'subject': deepcopy(task['subject']),
        'operation': task['operation'], 'canonical_review_ids': sorted(r['review_id'] for r in rows),
        'status': 'summary', 'coverage': 'complete_native_corpus_not_public_exposure'}
    if task['operation'] == 'rating_summary':
        summary = summarize_ratings([{'rating': r['stars'], 'text': r['text'] or ''} for r in rows])
        summary['mean_rounded'] = (str((Decimal(summary['rating_sum'])/summary['rating_count']).quantize(
            Decimal('.01'), rounding=ROUND_HALF_UP)) if rows else None)
        return {**result, 'summary': summary, 'rounding': 'two_decimal_half_up'}
    counts = dict.fromkeys(COUNTS, 0)
    classified = []
    for row in rows:
        if not (row['text'] or '').strip(): continue
        statements = _statements(world, row)
        signs = {s['sentiment'] for s in statements if s['aspect'] == task['aspect']}
        category = ('mixed' if {'positive', 'negative'} <= signs else 'positive' if 'positive' in signs
                    else 'negative' if 'negative' in signs else 'neutral' if 'neutral' in signs else 'not_assessed')
        counts[category] += 1
        classified.append({'review_id': row['review_id'], 'classification': category})
    assessed = sum(counts[k] for k in COUNTS[:-1])
    verdict = ('insufficient_evidence' if assessed < task['min_assessed'] else 'more_positive'
        if counts['positive'] > counts['negative'] else 'more_negative'
        if counts['negative'] > counts['positive'] else 'tie')
    return {**result, 'counts': counts, 'written_review_count': sum(counts.values()),
            'assessed_count': assessed, 'verdict': verdict, 'review_classification': classified}


def public_projection(world):
    """Separate opt-in public profile export; no task-specific or winner filter."""
    carriers, reviews = canonical_public(world)
    return {'schema_version': 'website-carrier-review-publication-v1',
        'source_world_id': world['world_id'], 'source_world_sha256': digest(world),
        'corpus_id': world['carrier_evidence']['corpus_id'],
        'site_id': 'carrier-reviews-01', 'kind': 'carrier_reviews', 'name': 'Parcelvoices',
        'collection_points': deepcopy(world['carrier_evidence']['public']['collection_points']),
        'profiles': [{'carrier': deepcopy(carriers[cid]), 'path': '/carriers/'+cid,
            'reviews': [deepcopy(reviews[rid]) for rid in sorted(reviews) if reviews[rid]['carrier_id'] == cid]}
            for cid in sorted(carriers)],
        'limitations': ['Published experiences only; no hidden shipment metrics or reliability labels.',
                       'Native projection is not public exposure, visits or future-delivery performance.']}
