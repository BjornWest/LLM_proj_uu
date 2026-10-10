"""Once-loaded population definitions, privately bound to one execution owner."""
from types import SimpleNamespace

from environments.product_world.shared_state import freeze
from . import model


class PopulationExecution:
    def __init__(self, bind):
        self._loaded = None
        self._bind = bind
        self.functions = SimpleNamespace(**vars(model))
        self.functions.load = self.load
        # These bodies call load through private namespaces, never shared globals.
        for name in ('sample', 'foreign_placement_multiplier'):
            setattr(self.functions, name, bind(getattr(model, name), load=self.load))
        self.functions.list_skus = self.list_skus

    def load(self):
        if self._loaded is None:
            config, registry = model.load()  # file/schema/registry validation once
            concepts = freeze(registry.concepts())
            self._loaded = freeze(config), SimpleNamespace(concepts=lambda: concepts)
        return self._loaded

    def list_skus(self, seed, key, skus, axes, config=None):
        return model.list_skus(seed, key, skus, axes,
                               config=self.load()[0] if config is None else config)
