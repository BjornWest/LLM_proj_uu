"""Synthetic structured-claim oracle for exact-variant link tasks.

This does not extract final prose or seal effects. Consumer extraction and
once-only episode grading are separately adopted against this native oracle.
"""
from copy import deepcopy

from . import variant_link_task as native

VERSION = 'website-variant-link-grade-v1'
FIELDS = {'url', 'selection', 'link_encodes_full_selection',
          'recipient_must_select', 'manual_selection'}


def grade(world, task, reference, claims, *, catalog, bindings, navigation_capability):
    """Compare explicit synthetic claims; never repair identity from expected values."""
    expected = native.reference(world, task, catalog=catalog, bindings=bindings,
                                navigation_capability=navigation_capability)
    if reference != expected:
        raise ValueError('Variant-link native reference binding changed')
    checks = {'explicit_contract': type(claims) is dict and set(claims) == FIELDS}
    if checks['explicit_contract']:
        try:
            identity, encoded = native.url_parts(claims['url'])
            wanted_identity, wanted_encoded = native.url_parts(expected['url'])
            checks['merchant_page_and_url_selectors'] = (identity == wanted_identity and encoded == wanted_encoded)
        except ValueError:
            checks['merchant_page_and_url_selectors'] = False
        checks['requested_options'] = type(claims['selection']) is dict and claims['selection'] == expected['selection']
        for key in ('link_encodes_full_selection', 'recipient_must_select'):
            checks[key] = type(claims[key]) is bool and claims[key] == expected[key]
        checks['manual_selection'] = (type(claims['manual_selection']) is dict and
                                      claims['manual_selection'] == expected['manual_selection'])
    return {'schema_version': VERSION, 'task_id': task['task_id'],
            'verdict': 'pass' if all(checks.values()) else 'fail',
            'components': {k: {'status': 'pass' if value else 'fail'} for k, value in checks.items()},
            'claims': deepcopy(claims), 'limitations': [
                'Structured claims only: natural-language extraction/grounding and automatic episode grading are not provided by this function.',
                'Correct recipient-selection explanation does not establish browser visits, public exposure, stock or absence of side effects.']}
