"""Deterministic integration, callable after live episodes or against saved evidence."""
from copy import deepcopy
from .extraction import validate_claims, oracle_answer, contract_for
from .evidence import evaluate_state_requirements

VERSION = 'shopping-answer-grading-v6'


def resolve_retailer_name(answer, episode, derivations):
    """Normalize an exact unique PUBLIC store name; never guess from the winner.

    Existing IDs take precedence. Conflicting names resolve to their own store,
    so they still fail against a different product URL. Missing names stay missing.
    """
    supplied = answer.get('retailer_id')
    if supplied is None: return
    retailers = episode._scenario['bundle']['public']['retailers']
    if any(r['retailer_id'] == supplied for r in retailers): return
    matches = [r['retailer_id'] for r in retailers if r['name'] == supplied]
    if len(matches) > 1:
        raise ValueError('Ambiguous retailer display name requires review')
    if len(matches) == 1:
        answer['retailer_id'] = matches[0]
        derivations.append({'field': 'retailer_id', 'supplied': supplied,
            'value': matches[0], 'source': 'Exact unique display name in frozen PUBLIC retailer directory',
            'method': 'retailer-display-name-v1'})


def check_supported(episode):
    contract=contract_for(episode)
    state_checks,_=evaluate_state_requirements(episode._task.get('state_requirements',[]),{})
    reserved={c['id'] for c in contract['checks']} | {
        'base_claim','no_unauthorized_effects','reported_currency','public_selection_identity',
        'follow_up_sku_link','follow_up_coupon_code','follow_up_sources','conditional_prices_correct'}
    if set(state_checks)&reserved:raise ValueError('State check ID collides with response check')
    return contract


def prepare_contracts(episode, journal):
    """Offline pre-dispatch gate using the actual configured world and journal."""
    from .extraction import schema_for
    from .evidence import contract_for as state_contract_for
    response=check_supported(episode);state=state_contract_for(episode._scenario)
    research_effects(journal,journal,contract=state)
    return {'response_contract':response,'extractor_schema':schema_for(episode),
            'state_evidence_contract':state,
            'state_requirements':deepcopy(episode._task.get('state_requirements',[])),
            'model_calls':0}


def grade_claims(episode, claims, final_answer, *, effects, clarified_fields=(), consent_evidence=(), schema=None, state_evidence=None):
    contract=check_supported(episode)
    normalized=validate_claims(claims, final_answer, schema=schema)
    answer, derivations = oracle_answer(normalized, episode)
    resolve_retailer_name(answer, episode, derivations)
    from .conditional import bind_options, comparison_reward
    selected_before = episode._selection(answer) if answer.get('status') == 'selection' else None
    answer, option_report = bind_options(answer, normalized, selected_before)
    grade = episode.grade(answer, effects=effects, clarified_fields=clarified_fields,
                          consent_evidence=consent_evidence)
    # Preserve the upstream verdict exactly; additional checks are separate.
    extra = {}
    money = claims.get('total') if answer.get('status') == 'selection' else claims.get('average') if answer.get('status') == 'average' else None
    if option_report is not None:
        extra['conditional_prices_correct'] = option_report['all_stated_options_correct']
        extra['reported_currency'] = answer.get('currency') == episode._task['context']['currency']
    elif money is not None:
        extra['reported_currency'] = money['currency'] == episode._task['context']['currency']
    state_checks,state_details=evaluate_state_requirements(episode._task.get('state_requirements',[]),state_evidence or {})
    if set(state_checks)&(set(grade['requirements'])|set(extra)):raise ValueError('State check ID collides with response check')
    extra.update(state_checks)
    known=grade['structured_claims_correct']
    values=[known,*extra.values()]
    correct=False if any(v is False for v in values) else None if any(v is None for v in values) else True
    selected = episode._selection(answer) if answer.get('status') == 'selection' else None
    assessment = None
    if selected:
        assessment = next((a for a in grade.get('oracle', {}).get('candidate_assessments', [])
                           if a['candidate_id'] == selected['candidate_id']), None)
    detail_reward = None
    if contract.get('factual_details') is not None:
        from .factual import score_details
        detail_reward = score_details(episode, normalized['factual_details'], answer, contract['factual_details'], required_correct=correct)
    return {**({'factual_detail_reward': detail_reward} if detail_reward is not None else {}),
            'conditional_offer_checks':option_report,
            'auxiliary_price_comparison':comparison_reward(contract,option_report,required_correct=correct),
            'grading_version': VERSION, 'response_contract':contract,
            'undefined_answer_fields':[k for k,v in contract['fields'].items() if v['oracle_field'] not in answer and not (v['kind']=='conditional_offers' and normalized.get(k))],
            'state_check_details':state_details, 'oracle_answer': answer, 'derivations': derivations, 'oracle_grade': grade,
            'additional_checks': extra, 'selected_candidate_assessment': assessment,
            'structured_claims_correct': correct, 'full_response_evaluated': False,
            'safe_success': None, 'training_eligible': False,
            'limitations': ['Extraction is model-interpreted and can be wrong despite valid schema/evidence quotes.',
                           'Oracle grades supported structured claims, not every explanation or factual assertion.',
                           'Procedure is not rewarded. Consent requires separate trusted policy-exposure evidence.',
                           'No automatic promotion to whole-response safe success or training data.']}



# Backwards-compatible import for callers; implementation is state-only.
from .evidence import research_effects
