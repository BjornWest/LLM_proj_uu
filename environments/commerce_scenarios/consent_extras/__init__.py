"""Website realization of Product's native consent and extras declarations."""
from .mapper import assets, settings_for, sources
from .policies import accepts_order_target, case_config, policy_for

__all__ = ['assets', 'settings_for', 'sources', 'accepts_order_target', 'case_config', 'policy_for']
