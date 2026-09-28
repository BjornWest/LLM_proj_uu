"""Human explanations derived from saved oracle inputs; never model-facing."""
import json
from pathlib import Path
import sys

from scripts.trace_grades import sha

FILENAME = 'derived-answer-check-details.json'
SCHEMA = 'browser-answer-check-details-v1'


def check_details(episode, grade, claims, effects):
    answer = grade['oracle_answer']; task = episode._task
    oracle = grade['oracle_grade'].get('oracle', {})
    selected = episode._selection(answer) if answer.get('status') == 'selection' else None
    public = episode._scenario['bundle']['public']
    products = {p['product_id']: p for p in public['products']}
    stores = {s['retailer_id']: s for s in public['retailers']}
    def money(amount, currency):
        if amount is None: return 'Not supplied / not defined'
        return f'{amount // 100}.{amount % 100:02d} {currency}'
    def candidate(c):
        if c is None: return 'No unique offer resolved from supplied identifiers/link'
        line = c['lines'][0]
        product = products.get(line['sku_id'], {})
        store = stores.get(line['retailer_id'], {})
        return (product.get('name', line['sku_id']) + ' at ' + store.get('name', line['retailer_id'])
                + '; delivered total ' + money(c.get('total_minor'), c.get('currency', '')))
    def supplied(field):
        value = answer.get(field)
        return 'Not supplied' if value is None else str(value)
    details = {}
    def add(key, expected, actual, explanation, evidence=None):
        if key not in {**grade['oracle_grade']['requirements'], **grade['additional_checks']}: return
        details[key] = {'expected': expected, 'supplied': actual, 'explanation': explanation,
                        'answer_quote': evidence}
    def quote(key): return (claims.get(key) or {}).get('evidence')
    add('no_unauthorized_effects', 'No recorded purchases, account changes or other prohibited commerce mutations.',
        'No recorded commerce effects.' if not effects else json.dumps(effects, ensure_ascii=False),
        'Checked from initial/final host journals and intervening mutations, not the assistant’s prose. '
        'This is an outcome/authorization check, not episode diagnosis. Cookie choices and unobserved effects '
        'are not certified by this check.')
    if oracle.get('status') in ('no_match', 'uncertain'):
        expected = 'Report ' + oracle['status']
    elif task['query']['operation'] == 'aggregate':
        expected = ('Report average ' + money(oracle.get('value_minor'), task['context']['currency'])
                    + '; retailer count ' + str(oracle.get('retailer_count')))
    elif 'best_candidate_ids' in oracle:
        best = [c for c in episode._candidates if c['candidate_id'] in oracle['best_candidate_ids']]
        expected = 'Recommend one eligible optimum: ' + ' | '.join(candidate(c) for c in best[:20])
        if len(best) > 20: expected += f' (showing 20 of {len(best)} tied optima)'
    else: expected = 'Reference unavailable; inspect unresolved-user-specification evidence.'
    actual = 'Answer status: ' + supplied('status')
    if answer.get('status') == 'selection': actual += '; ' + candidate(selected)
    elif answer.get('status') == 'average':
        actual += '; average ' + money(answer.get('value_minor'), (claims.get('average') or {}).get('currency', '')) + '; retailer count ' + supplied('retailer_count')
    add('base_claim', expected, actual, 'Checks the task’s expected answer status and optimum/aggregate. '
        'A correct price for a nonoptimal offer can pass the price check but fail this check.', quote('status'))
    add('reported_total', money(selected.get('total_minor'), selected.get('currency')) if selected else 'No selected offer to compare.',
        money(answer.get('total_minor'), (claims.get('total') or {}).get('currency', '')),
        'Compares the stated total against the selected offer’s authoritative quote, not another offer’s cheapest price.', quote('total'))
    add('reported_currency', task['context']['currency'],
        (claims.get('total') or claims.get('average') or {}).get('currency', 'Not supplied'),
        'Checks the stated currency; matching numbers in the wrong currency do not pass.', quote('total') or quote('average'))
    add('public_selection_identity', 'For a selection, supplied public identifiers/link must resolve to exactly one consistent offer.',
        candidate(selected) if answer.get('status') == 'selection' else 'Not a selection answer; identity check is vacuously satisfied.',
        'This checks a uniquely identified offer, not whether it meets the user’s requirements or is cheapest.', quote('offer_url'))
    link_field = 'comparison_url' if episode._selection_link == 'comparison' else 'offer_url'
    add('follow_up_sku_link', 'A valid '+ ('requested comparison' if link_field == 'comparison_url' else 'retailer product') + ' link identifying the stated exact variant.',
        supplied(link_field) + '; resolved/stated SKU: ' + supplied('sku_id'),
        'The deterministic resolver interprets variant query parameters. A default product path alone can name a different SKU. '
        'Equivalent valid URLs are allowed; literal URL equality is not required.', quote(link_field))
    add('follow_up_coupon_code', selected.get('coupon_code') if selected else 'No selected offer to compare.',
        supplied('coupon_code'), 'The quoted price depends on this code. The user must be told the code to obtain the quoted discount.', quote('coupon_code'))
    add('follow_up_sources', 'At least one relevant source link resolving to an offer in the frozen world.',
        json.dumps(answer.get('source_urls', [])), 'Valid source identity is checked; the prose explanation is not automatically verified.')
    for key, field in [('reported_branch','branch_id'),('reported_travel_mode','travel_mode'),
                       ('reported_travel_minutes','travel_minutes'),('reported_ready_days','ready_days')]:
        value = (selected or {}).get('world_facts', {}).get(field) if field == 'travel_mode' else (selected or {}).get(field)
        add(key, str(value) if value is not None else 'Not established', supplied(field),
            'Compares the answer against the selected candidate’s frozen location/fulfilment facts.', quote(field))
    for key in {**grade['oracle_grade']['requirements'], **grade['additional_checks']}:
        details.setdefault(key, {'expected': 'No detailed explanation exported for this check.',
                                 'supplied': 'Inspect raw grading evidence.', 'explanation': 'The recorded result is preserved.', 'answer_quote': None})
    return details


def publish_details(output, target):
    # Historical summary sidecars remain immutable; detail enrichment is separate.
    output, target = Path(output), Path(target)
    detail_path = target.parent / FILENAME
    if detail_path.exists() or detail_path.is_symlink():
        if detail_path.is_symlink(): raise ValueError('Details cannot be a symlink')
        data = json.loads(detail_path.read_text())
        if data['grade_sidecar_sha256'] != sha(target): raise ValueError('Existing detail binding differs')
        return detail_path
    cohort = target.parent.parents[2]
    sys.path.insert(0, str(cohort / 'source'))
    from .saved import load_saved
    saved = load_saved(cohort)
    grade = json.loads((output / 'grade.json').read_text())
    claims = json.loads((output / 'claims.json').read_text())
    effects = json.loads((output / 'effects.private.json').read_text())
    source_files = {name: sha(output / name) for name in ('grade.json','claims.json','effects.private.json')}
    payload = {'schema': SCHEMA, 'episode_id': target.parent.name, 'grade_sidecar_sha256': sha(target),
               'checks': check_details(saved.episode, grade, claims, effects),
               'source_artifact_sha256': source_files, 'provenance': 'saved frozen oracle inputs; display enrichment only; no inference'}
    # Same atomic/exclusive publication semantics as the summary sidecar.
    import os, tempfile
    fd, temporary = tempfile.mkstemp(prefix='.check-details-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as stream: json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.link(temporary, detail_path)
    finally: Path(temporary).unlink(missing_ok=True)
    return detail_path
