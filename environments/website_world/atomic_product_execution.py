"""Once-only native grading after the actual capture seals; no model dispatch."""
from pathlib import Path

from . import atomic_product_grading as native
from .catalog_cart_execution import save_new


def grade_saved_return(capture, returned_trace, summary, *, world, task,
                       reference, catalog, bindings, checkout_domain, claims=None):
    capsule, completed = capture.seal(returned_trace, summary)
    report = native.grade(world, task, reference, catalog=catalog, bindings=bindings,
        checkout_domain=checkout_domain, claims=claims, binding=capture.binding,
        capsule=capsule, episode_id=capsule['episode_id'],
        main_trace_sha256=capsule['main_trace_sha256'], policy_completed=completed)
    save_new(Path(returned_trace)/'atomic-product-grade.private.json', report)
    return report
