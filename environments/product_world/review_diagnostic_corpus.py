"""Prospective controlled review fixtures; ordinary world sampling is unchanged.

This is explicit diagnostic authoring over a retained world, not an ordinary
seeded draw or evidence of actual customers. Reuse source-pinned pilot atoms;
declare new jogging atoms separately rather than relabelling walking sentences.
The existing native topic-count grader remains the authority for final counts.
"""
from copy import deepcopy
from hashlib import sha256
import json

VERSION = 'controlled-review-diagnostic-corpus-v1'
CASES = ('opposite-opinions-one-comment', 'similar-different-circumstances',
         'pagination-first-page-reversal')
JOGGING = {
    'positive': 'When I jogged across wet paving, the soles felt secure.',
    'negative': 'When I jogged across wet paving, the soles slipped.',
}
JOGGING_CONTEXT = {'activity': 'jogging', 'surface': 'wet paving', 'source': 'first_hand'}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             allow_nan=False).encode()).hexdigest()


def create(world_bytes, bank_bytes, *, expected_world_sha256,
           expected_bank_sha256, product_id, case):
    """Return a detached diagnostic world and statement-level authoring receipt.

    Caller must generate new surrounding/task/reference bindings for this world.
    Historical recipes/corpora must never be rebound in place. No file IO, hidden
    source substitution, model calls, stock/price changes or automatic conditioning.
    """
    if (type(world_bytes) is not bytes or type(bank_bytes) is not bytes
            or sha256(world_bytes).hexdigest() != expected_world_sha256
            or sha256(bank_bytes).hexdigest() != expected_bank_sha256):
        raise ValueError('Consume the exact retained world and declared phrase-bank bytes')
    if case not in CASES:
        raise ValueError('Unknown controlled diagnostic case')
    world, bank = json.loads(world_bytes), json.loads(bank_bytes)
    products = [p for p in world['products'] if p['public']['product_id'] == product_id]
    if len(products) != 1 or products[0]['public']['concept_id'] != 'footwear.walking_shoes':
        raise ValueError('This bounded pilot fixture requires one walking-shoe model')
    product = products[0]
    original = deepcopy(product)
    rows = product['reviews']
    ids = [r['review_id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Require unique canonical review rows')
    skus = {s['sku_id'] for s in product['public']['skus']}
    if any(r['sku_id'] not in skus for r in rows):
        raise ValueError('Every review must retain a manufactured SKU')
    written = [r for r in rows if r['text'].strip()]
    if len(written) != 18:
        raise ValueError('Require the retained eighteen-comment fixture')
    grip = bank['aspects']['wet_paving_grip']
    if grip['context'] != {'activity': 'walking', 'surface': 'wet paving', 'source': 'first_hand'}:
        raise ValueError('The accepted wet-paving declaration changed')
    reports = []
    for row in written:
        if 'statements' in row:
            raise ValueError('Use the pilot evidence statement representation only')
        if row['presentation']['text'] != row['text']:
            raise ValueError('Existing public composition disagrees')
        statements = row['evidence']['statements']
        hits = [i for i, s in enumerate(statements) if s['meaning'] == 'wet_paving_grip']
        if len(hits) > 1:
            raise ValueError('The baseline is no longer the unique-topic pilot')
        if hits:
            index = hits[0]
            statement = statements[index]
            if statement['context'] != grip['context'] or statement['polarity'] not in ('positive', 'negative'):
                raise ValueError('Require exact original walking/wet-paving opinions')
            reports.append((row, index, statement['polarity']))
    positive = [r for r in reports if r[2] == 'positive']
    negative = [r for r in reports if r[2] == 'negative']
    if len(positive) != 2 or len(negative) != 3:
        raise ValueError('Require the retained two-positive/three-negative baseline')
    receipt = {'schema': VERSION, 'fixture_kind': 'explicit_controlled_diagnostic',
        'case': case, 'source_world_sha256': expected_world_sha256,
        'source_bank_sha256': expected_bank_sha256, 'source_world_id': world['world_id'],
        'product_id': product_id, 'new_model_calls': 0, 'ordinary_world_draws': 0,
        'review_changes': [], 'declared_extra_contexts': [],
        'required_rebinding': ['world pin', 'surrounding', 'native task/reference', 'recipe'],
        'public_review_page_size': 18 if case != CASES[2] else 4}

    def atom(row, aspect, polarity, variant, *, prefix=''):
        declaration = bank['aspects'][aspect]
        text = declaration[polarity][variant]
        if prefix:
            if not text.startswith('I '):
                raise ValueError('Occasion prefix requires an unchanged first-person atomic clause')
            text = prefix+text
        return {'meaning': aspect, 'polarity': polarity,
            'context': deepcopy(declaration['context']), 'sku_id': row['sku_id'],
            'text': text, 'realization_id': f'{aspect}/{polarity}/{variant}',
            'diagnostic_provenance': {'bank_sha256': expected_bank_sha256,
                'aspect': aspect, 'polarity': polarity, 'variant': variant, 'prefix': prefix}}

    def edit(row, statements, note):
        before = deepcopy(row)
        row['evidence']['statements'] = statements
        segments = [{'statement_index': i, 'connector': 'plain', 'text': s['text']}
                    for i, s in enumerate(statements)]
        row['text'] = ' '.join(s['text'] for s in segments)
        row['presentation'] = {'schema_version': 'review-composition-v1',
                               'text': row['text'], 'segments': segments}
        # Do not pretend new reports follow the original one-polarity latent sample.
        row['private'] = {'fixture_kind': receipt['fixture_kind'], 'source_schema': VERSION,
            'original_sampled_private': deepcopy(before['private']), 'length': len(statements)}
        receipt['review_changes'].append({'review_id': row['review_id'], 'sku_id': row['sku_id'],
            'reason': note, 'original_row': before, 'revised_row_sha256': digest(row)})

    if case == CASES[0]:
        for row, index, _ in (negative[0], positive[0]):
            statements = deepcopy(row['evidence']['statements'])
            statements[index:index+1] = [
                atom(row, 'wet_paving_grip', 'positive', 1, prefix='On one walk, '),
                atom(row, 'wet_paving_grip', 'negative', 1, prefix='On a later walk, ')]
            edit(row, statements, 'Two firsthand occasions in the same requested context; one mixed comment.')
        row, _, _ = negative[1]
        statements = deepcopy(row['evidence']['statements'])
        statements = [s for s in statements if s['meaning'] != 'walking_comfort']
        statements.append(atom(row, 'walking_comfort', 'positive', 0))
        edit(row, statements, 'Positive comfort with negative grip remains negative for the requested aspect.')
        receipt['expected_topic_counts'] = {'positive': 1, 'negative': 2,
            'neutral': 0, 'mixed': 2, 'not_assessed': 13}
    elif case == CASES[1]:
        receipt['declared_extra_contexts'] = [{'aspect': 'wet_paving_grip',
            'context': JOGGING_CONTEXT, 'realizations': JOGGING,
            'origin': 'new explicit diagnostic declaration in this versioned module'}]
        # Retain the original walking clause and add the opposite jogging opinion.
        for row, _, polarity in (negative[0], positive[0]):
            other = 'positive' if polarity == 'negative' else 'negative'
            statements = deepcopy(row['evidence']['statements'])
            statements.append({'meaning': 'wet_paving_grip', 'polarity': other,
                'context': deepcopy(JOGGING_CONTEXT), 'sku_id': row['sku_id'],
                'text': JOGGING[other], 'realization_id': VERSION+'/jogging/'+other,
                'diagnostic_provenance': {'declaration': VERSION, 'context': 'jogging', 'polarity': other}})
            edit(row, statements, 'Opposite opinion while jogging does not change the walking classification.')
        receipt['expected_topic_counts'] = {'positive': 2, 'negative': 3,
            'neutral': 0, 'mixed': 0, 'not_assessed': 13}
    else:
        # The actual renderer sorts by (-rating, review_id), not producer row order.
        # Use its existing highest-first sort; preserve every original row/order.
        first_page = sorted(written, key=lambda r: (-r['rating'], r['review_id']))[:4]
        counts = {'positive': 0, 'negative': 0, 'neutral': 0, 'mixed': 0, 'not_assessed': 0}
        for row in first_page:
            matches = [s['polarity'] for s in row['evidence']['statements']
                       if s['meaning'] == 'wet_paving_grip' and s['context'] == grip['context']]
            counts[matches[0] if matches else 'not_assessed'] += 1
        if counts != {'positive': 1, 'negative': 0, 'neutral': 0, 'mixed': 0, 'not_assessed': 3}:
            raise ValueError('Actual highest-first first page no longer reverses the full-corpus balance')
        receipt['start_query'] = {'sort': 'highest'}
        receipt['required_rebinding'] = ['surrounding review_page_size4', 'fresh recipe/start URL']
        receipt['first_page_review_ids'] = [row['review_id'] for row in first_page]
        receipt['expected_topic_counts'] = {'positive': 2, 'negative': 3,
            'neutral': 0, 'mixed': 0, 'not_assessed': 13}
        receipt['expected_first_page_counts'] = counts
    # Ratings, canonical identities, subjects, silent rows and denominator stay exact.
    old_rows = {r['review_id']: r for r in original['reviews']}
    for row in rows:
        old = old_rows[row['review_id']]
        for field in ('review_id', 'reviewer', 'product_id', 'sku_id', 'rating'):
            if row[field] != old[field]:
                raise ValueError('Diagnostic changed native rating or owner identity')
        if not old['text'].strip() and row != old:
            raise ValueError('Diagnostic changed a silent rating')
    if len(rows) != len(old_rows) or sum(bool(r['text'].strip()) for r in rows) != 18:
        raise ValueError('Diagnostic changed the recorded rating/written population')
    if case != CASES[2]:
        world['world_id'] = 'review-diagnostic-'+digest({'version': VERSION, 'case': case,
            'product_id': product_id, 'world_sha256': expected_world_sha256,
            'bank_sha256': expected_bank_sha256})[:32]
    receipt['diagnostic_world_id'] = world['world_id']
    receipt['diagnostic_world_digest'] = digest(world)
    return world, receipt
