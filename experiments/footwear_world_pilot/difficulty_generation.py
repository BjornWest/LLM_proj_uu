"""Additive natural address difficulty stage over the frozen footwear producer.

The old call is unchanged when options are absent. Explicit probabilities affect
only naturally sampled checkout forms/address provenance, never stock, offers,
locations or the native monetary reference. Forced fixture modes and coupon
population are outside this stage.
"""
from copy import deepcopy

from experiments.address_checkout_pilot import model as addresses
from . import model

VERSION = 'footwear-natural-address-difficulty-v1'


def generate(seed=0, *, objective='cheapest_delivered', concept_id=None,
             city_id='uppsala', controls=None, address_options=None):
    """Generate a fresh native world with optional validated address priors.

    ``incorrect_probability`` and ``missing_probability`` are conditional on
    autofill, not absolute probabilities. Missing and incorrect may co-occur.
    Existing native masks, wrong-address categories and coverage limitations are
    retained exactly; no individual retailer or winner is edited by this API.
    """
    # Validate controls before the base generator performs any sampling.
    parameters = addresses.parameters(address_options)
    world = model.generate(seed, objective=objective, concept_id=concept_id,
                           city_id=city_id, controls=controls)
    if address_options is None:
        return world
    context = addresses.generate(seed, city_id, options=deepcopy(parameters))
    # Same seed/city must retain the complete actual destination support; option
    # settings are not permission to redraw a convenient home or old address.
    for key in ['addresses', 'outside_postcode']:
        if context[key] != world['address_context'][key]:
            raise ValueError('Natural address controls changed geographic support')
    original_world_id = world['world_id']
    world['address_context'] = {k: deepcopy(v) for k, v in context.items() if k != 'retailers'}
    for retailer in world['retailers']:
        retailer['initial_form'] = addresses.autofill(
            seed, retailer['retailer_id'], context['addresses'],
            context['outside_postcode'], parameters)
    world['provenance']['natural_address_difficulty'] = {
        'schema_version': VERSION,
        'base_world_id': original_world_id,
        'parameters': deepcopy(parameters),
        'parameter_basis': 'incorrect/missing conditional on enabled autofill',
        'retailer_selection': 'all actual retailers; independent natural form draws',
        'forced_form_modes': False,
        'shipping_coverage_repaired': False}
    # The inherited reference still has the same task/locations/offers/stock and
    # is independently recomputed to verify that no commercial state changed.
    reference = model.solve(world)
    if reference != world['reference']:
        raise ValueError('Address-only stage unexpectedly changed commercial reference')
    world['reference'] = reference
    world.pop('world_id')
    world['world_id'] = model.digest(world)
    model.validate(world)
    return world
