"""Provider-reported operational counters; missing is never silently zero."""
from decimal import Decimal, InvalidOperation
import math

DEFAULT_THRESHOLDS = {'high_episode_tokens': 100000, 'large_request_tokens': 32000,
                      'long_reasoning_tokens': 2000, 'low_cache_fraction': .1,
                      'cache_min_requests': 3, 'cache_min_prompt_tokens': 1000,
                      'zero_cache_streak': 3}


def thresholds(overrides=None):
    result = {**DEFAULT_THRESHOLDS, **(overrides or {})}
    if set(result) != set(DEFAULT_THRESHOLDS):
        raise ValueError('Unknown metric threshold')
    for key, value in result.items():
        if key == 'low_cache_fraction':
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Cache threshold must be between zero and one')
        elif type(value) is not int or value < 1:
            raise ValueError('Token/count thresholds must be positive integers')
    return result


def obj(value):
    return value if isinstance(value, dict) else {}


def counter(value):
    return value if type(value) is int and value >= 0 else None


def request_metrics(step):
    request, response = obj(step.get('model_request')), obj(step.get('model_response'))
    usage = obj(response.get('usage'))
    prompt, completion = counter(usage.get('prompt_tokens')), counter(usage.get('completion_tokens'))
    cached = counter(obj(usage.get('prompt_tokens_details')).get('cached_tokens'))
    reasoning = counter(obj(usage.get('completion_tokens_details')).get('reasoning_tokens'))
    inconsistencies = []
    if cached is not None and prompt is not None and cached > prompt:
        inconsistencies.append('cached_tokens_exceed_prompt_tokens')
    if reasoning is not None and completion is not None and reasoning > completion:
        inconsistencies.append('reasoning_tokens_exceed_completion_tokens')
    cost = None
    try:
        value = Decimal(str(usage.get('cost')))
        if value.is_finite() and value >= 0:
            cost = str(value)
    except InvalidOperation:
        pass
    return {'step': step['step'], 'attempt_recorded': bool(request or response),
            'requested_model': request.get('model'), 'resolved_model': response.get('model'),
            'resolved_provider': response.get('provider'), 'response_id': response.get('id'),
            'prompt_tokens': prompt, 'completion_tokens': completion,
            'total_tokens': prompt + completion if prompt is not None and completion is not None else None,
            'reported_total_tokens': counter(usage.get('total_tokens')),
            'cached_tokens': cached, 'reasoning_tokens': reasoning,
            'uncached_tokens': prompt - cached if prompt is not None and cached is not None and cached <= prompt else None,
            'cache_pair_valid': prompt is not None and cached is not None and cached <= prompt,
            'cost_usd': cost, 'counter_inconsistencies': inconsistencies,
            'reasoning_configuration': request.get('reasoning'), 'max_tokens': request.get('max_tokens')}


def aggregate(rows):
    attempts = [r for r in rows if r['attempt_recorded']]
    totals = {}
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cached_tokens',
                  'reasoning_tokens', 'uncached_tokens', 'cost_usd'):
        values = [r[field] for r in attempts if r[field] is not None]
        value = (str(sum((Decimal(x) for x in values), Decimal(0))) if field == 'cost_usd' else sum(values)) if values else None
        totals[field] = {'known_sum': value, 'reported_requests': len(values),
                         'missing_requests': len(attempts) - len(values),
                         'complete': bool(attempts) and len(values) == len(attempts)}
    pairs = [r for r in attempts if r['cache_pair_valid']]
    denominator = sum(r['prompt_tokens'] for r in pairs)
    streak = longest = 0
    for r in attempts:
        streak = streak + 1 if r['cache_pair_valid'] and r['prompt_tokens'] > 0 and r['cached_tokens'] == 0 else 0
        longest = max(longest, streak)
    return {'attempt_records': len(attempts), 'totals': totals,
            'peak_prompt_tokens': max((r['prompt_tokens'] for r in attempts if r['prompt_tokens'] is not None), default=None),
            'peak_reasoning_tokens': max((r['reasoning_tokens'] for r in attempts if r['reasoning_tokens'] is not None), default=None),
            'cache_fraction_known_pairs': sum(r['cached_tokens'] for r in pairs) / denominator if denominator else None,
            'cache_paired_requests': len(pairs), 'cache_paired_prompt_tokens': denominator,
            'longest_reported_zero_cache_streak': longest,
            'providers': sorted({r['resolved_provider'] for r in attempts if isinstance(r['resolved_provider'], str)}),
            'resolved_models': sorted({r['resolved_model'] for r in attempts if isinstance(r['resolved_model'], str)}),
            'measurement': 'Provider-reported native token counts for each resolved model; no local tokenizer estimate. Repeated context counts per request; cache/reasoning are subsets. Prepared/interrupted calls without retained request or response are outside coverage.'}


def metric_flags(rows, summary, config):
    flags = []
    def add(code, step, detail):
        flags.append((code, step, detail))
    for r in rows:
        if r['counter_inconsistencies']:
            add('usage_counter_inconsistent', r['step'], ', '.join(r['counter_inconsistencies']))
        for field, limit, code in [('prompt_tokens', 'large_request_tokens', 'large_request_context'),
                                   ('reasoning_tokens', 'long_reasoning_tokens', 'long_reasoning_output')]:
            if r[field] is not None and r[field] >= config[limit]:
                add(code, r['step'], f"Reported {field}={r[field]}; configured threshold={config[limit]}. Efficiency pointer, not a task failure.")
    total = summary['totals']['total_tokens']['known_sum']
    if total is not None and total >= config['high_episode_tokens']:
        add('high_episode_token_use', None, f'Known input+output tokens={total}; threshold={config["high_episode_tokens"]}. See reporting coverage; subsets are not added twice.')
    fraction = summary['cache_fraction_known_pairs']
    if (fraction is not None and fraction < config['low_cache_fraction'] and
            summary['cache_paired_requests'] >= config['cache_min_requests'] and
            summary['cache_paired_prompt_tokens'] >= config['cache_min_prompt_tokens']):
        add('low_reported_cache_fraction', None, f'Cache fraction over known valid pairs={fraction:.3f}; threshold={config["low_cache_fraction"]}. Cache eligibility and avoidability are unknown.')
    if summary['longest_reported_zero_cache_streak'] >= config['zero_cache_streak']:
        add('reported_zero_cache_streak', None, f'{summary["longest_reported_zero_cache_streak"]} consecutive positive-input requests explicitly report zero cached tokens; not proof of avoidable misses.')
    return flags
