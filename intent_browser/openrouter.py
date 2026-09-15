"""OpenRouter routing defaults; provider allowlist does not impose an order."""
import re

DEFAULT_PROVIDERS = ('chutes', 'dekallm', 'phala', 'parasail', 'akashml', 'ionstream', 'cloudflare')
DEFAULT_MAX_TOKENS = 4096


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
    return {'provider': {'only': slugs, 'allow_fallbacks': True, 'require_parameters': True},
            'reasoning': {'enabled': True}}


def routing_record(request, response):
    request = request if isinstance(request, dict) else {}
    response = response if isinstance(response, dict) else {}
    usage = response.get('usage') if isinstance(response.get('usage'), dict) else {}
    provider = request.get('provider') if isinstance(request.get('provider'), dict) else {}
    details = usage.get('prompt_tokens_details') if isinstance(usage.get('prompt_tokens_details'), dict) else {}
    return {'session_id': request.get('session_id'), 'requested_model': request.get('model'),
            'requested_providers': provider.get('only'),
            'resolved_model': response.get('model'), 'resolved_provider': response.get('provider'),
            'response_id': response.get('id'), 'reported_cost_usd': usage.get('cost'),
            'cached_tokens': details.get('cached_tokens')}
