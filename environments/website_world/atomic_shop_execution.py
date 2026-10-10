"""Once-only saved-return hook for the additive address-only consumer.

The Website episode must attach the existing raw capture callbacks and perform
declared prepared-cart UI setup before the policy baseline. This hook launches
no browser/model and does not authorize a new source union's effect envelope.
"""
from pathlib import Path
from . import atomic_shop_grading as native
from .catalog_cart_execution import save_new


def grade_saved_return(capture, returned_trace, summary, *, world, task,
                       reference, checkout_domain):
    capsule, completed = capture.seal(returned_trace, summary)
    report = native.grade(world, task, reference, checkout_domain=checkout_domain,
        binding=capture.binding, capsule=capsule, episode_id=capsule['episode_id'],
        main_trace_sha256=capsule['main_trace_sha256'], policy_completed=completed)
    save_new(Path(returned_trace)/'atomic-address-grade.private.json', report)
    return report
