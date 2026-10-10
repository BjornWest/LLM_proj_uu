"""Natural address priors bound before the retained catalog sampler runs.

No retailer form, geographical support or sampled world is patched afterward.
The ordinary Execution body and its package/population caches stay unchanged.
"""
from types import SimpleNamespace

from . import model
from .execution import Execution, _bind

VERSION = 'accepted-catalog-natural-address-v1'


class NaturalAddressExecution:
    def __init__(self, *, address_options=None, validation='off'):
        # Validate external controls before constructing or invoking a sampler.
        parameters = model.addresses.parameters(address_options)
        self._parameters = tuple(sorted(parameters.items()))
        self.execution = Execution(validation=validation)
        self._explicit = address_options is not None
        if self._explicit:
            entries = self._parameters
            retained = model.addresses.generate

            def address_context(seed=0, city_id='uppsala', options=None):
                if options is not None:
                    raise ValueError('Address options are already bound to this execution')
                return retained(seed, city_id, options=dict(entries))

            dependency = SimpleNamespace(**vars(model.addresses))
            dependency.generate = address_context
            # This is the retained producer's existing pre-form address stage.
            # Preserve every other private Execution dependency and cache.
            self.execution._generate = _bind(self.execution._generate, addresses=dependency)

    @property
    def parameters(self):
        return dict(self._parameters)

    def generate(self, seed=0, **options):
        return self.execution.generate(seed, **options)

    def record(self):
        return {**self.execution.record(), 'natural_address': {
            'version': VERSION, 'explicit': self._explicit,
            'parameters': self.parameters,
            'parameter_basis': 'incorrect and missing conditional on enabled autofill',
            'sampling_phase': 'before retailer forms, within retained world construction',
            'forced_form_modes': False, 'shipping_coverage_repaired': False}}


def generate(seed=0, *, address_options=None, validation='off', **options):
    return NaturalAddressExecution(address_options=address_options,
        validation=validation).generate(seed, **options)
