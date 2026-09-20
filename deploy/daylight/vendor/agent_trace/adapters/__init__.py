"""Environment-specific trace interpretation."""
from . import civ5

# Generic mode deliberately adds no game-specific labels or inference.
PARSERS = {'generic': None, 'civ5': civ5, 'browsergym': None}
MODES = ('auto', *PARSERS)
