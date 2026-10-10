"""Additive feature/reference conditioning with natural address probability input.

Existing unified/feature compilers, recipes, worlds and page renderers are frozen.
Only this entry point releases the already named difficulty.address_probabilities
field for accepted-catalog feature tasks. World-factory results must prove that
the declared priors reached the sampler; ignored overrides fail closed.
"""
from copy import deepcopy

from experiments.accepted_catalog_commerce.natural_address import NaturalAddressExecution
from experiments.address_checkout_pilot.model import parameters
from . import conditioned_feature_generation
from .adapter import digest

VERSION = 'website-natural-feature-generation-v1'


def compile_request(request):
    if type(request) is not dict:
        raise ValueError('Declare a feature generation request')
    proxy = deepcopy(request)
    difficulty = proxy.get('difficulty', {})
    if type(difficulty) is not dict:
        raise ValueError('Difficulty must be an object')
    explicit = 'address_probabilities' in difficulty
    if explicit and type(difficulty['address_probabilities']) is not dict:
        raise ValueError('Address probabilities must be an object')
    options = parameters(difficulty.pop('address_probabilities')) if explicit else None
    config = conditioned_feature_generation.compile_request(proxy)
    return {'proxy_request': proxy, 'configuration': config,
            'address_options': options}


def generate(request, *, world_factory=None):
    config = compile_request(request)
    options = config['address_options']
    engine = None
    if options is None:
        factory = world_factory
    else:
        if world_factory is None:
            engine = NaturalAddressExecution(address_options=options, validation='off')

        def factory(seed, **world_options):
            if engine is not None:
                world = engine.generate(seed, **world_options)
            else:
                world = world_factory(seed, **world_options,
                                      address_options=deepcopy(options))
            # This is an external factory/input contract, not exhaustive
            # generated-context verification or a post-sampling form repair.
            actual = world.get('address_context', {}).get('parameters')
            if (type(actual) is not dict or set(actual) != set(options) or
                    parameters(actual) != options):
                raise ValueError('World factory ignored declared natural address priors')
            return world

    result = conditioned_feature_generation.generate(config['proxy_request'],
                                                     world_factory=factory)
    result['feature_offer_request'] = deepcopy(request)
    result['resolved_configuration']['request'] = deepcopy(request)
    result['resolved_configuration']['address_options'] = deepcopy(options)
    result['audit']['natural_feature_proxy_request_sha256'] = result['audit']['request_sha256']
    result['audit']['request_sha256'] = digest(request)
    result['audit']['natural_address'] = {'version': VERSION,
        'parameters': deepcopy(options), 'explicit': options is not None,
        'sampler_record': engine.record() if engine is not None else None,
        'world_repaired': False, 'factory_parameters_verified': options is not None}
    return result
