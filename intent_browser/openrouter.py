"""OpenRouter routing defaults; explicit multi-provider overrides remain supported."""
import re

# Akash-first with capacity fallbacks; Deka remains excluded by user preference.
DEFAULT_PROVIDERS = ('akashml', 'chutes', 'phala', 'parasail', 'ionstream', 'cloudflare')
DEFAULT_MAX_TOKENS = 16384


def completion_token_limit(value=None):
    """Resolve the new-run output ceiling; reasoning and answer share it."""
    if value is None:
        return DEFAULT_MAX_TOKENS
    if isinstance(value, str) and re.fullmatch(r'[0-9]+', value):
        value = int(value)
    if type(value) is not int or value <= 0:
        raise ValueError('Completion token limit must be a positive integer')
    return value


def provider_options(providers):
    if isinstance(providers, str):
        providers = providers.split(',')
    slugs = list(dict.fromkeys(p.strip().lower() for p in providers))
    if not slugs or any(not re.fullmatch(r'[a-z0-9-]+(?:/[a-z0-9.-]+)*', p) for p in slugs):
        raise ValueError('Providers must be comma-separated OpenRouter slugs')
    # Explicit order overrides OpenRouter sticky routing; retain session IDs for
    # trace grouping, without claiming cache continuity after a fallback.
    preferred = {'order': ['akashml']} if slugs == list(DEFAULT_PROVIDERS) else {}
    return {'provider': {'only': slugs, 'allow_fallbacks': len(slugs) > 1,
                         'require_parameters': True, **preferred},
            'reasoning': {'enabled': True}}


def routing_record(request, response):
    request = request if isinstance(request, dict) else {}
    response = response if isinstance(response, dict) else {}
    usage = response.get('usage') if isinstance(response.get('usage'), dict) else {}
    provider = request.get('provider') if isinstance(request.get('provider'), dict) else {}
    details = usage.get('prompt_tokens_details') if isinstance(usage.get('prompt_tokens_details'), dict) else {}
    return {'session_id': request.get('session_id'), 'requested_model': request.get('model'),
            'requested_providers': provider.get('only'),
            'requested_provider_order': provider.get('order'),
            'allow_fallbacks': provider.get('allow_fallbacks'),
            'resolved_model': response.get('model'), 'resolved_provider': response.get('provider'),
            'response_id': response.get('id'), 'reported_cost_usd': usage.get('cost'),
            'cached_tokens': details.get('cached_tokens')}
