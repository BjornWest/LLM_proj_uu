"""Explicit ungraded escape for offline harness unit fixtures, never model evaluation."""
from intent_browser.runner import run_episode as _run_episode


def run_episode(*args, **kwargs):
    kwargs.setdefault('allow_ungraded', True)
    kwargs.setdefault('ungraded_reason', 'Offline harness regression fixture; no automatic task-grade claim')
    return _run_episode(*args, **kwargs)
