"""Explicit response-destination requests, separate from product preferences."""
from copy import deepcopy

from .generator import stream
from .world import fingerprint


def extend(bundle, selection_link='retailer'):
    if selection_link not in ('retailer','comparison'):raise ValueError('Unknown selection link destination')
    if selection_link=='retailer':return bundle
    task=bundle['resolved_task']
    if len(task['lines'])!=1 or task['query']['operation']!='select' or task['query'].get('activity','delivery')!='delivery':
        raise ValueError('Comparison-page requests currently support single-product delivery comparisons')
    requirement={'selection_link':'comparison'}
    for key in ('request','initial_accessible_task','resolved_task'):
        bundle[key]['response_requirements']=deepcopy(requirement)
    wording=stream(bundle['prose_seed'],'selection-link-wording').choice((
        'Link the price-comparison page so I can compare retailers myself.',
        'Send me the comparison page for it so I can look through the different retailers.'))
    bundle['public']['user_message']+=' '+wording
    bundle['authoring']['message_segments'].append({'stage':'constraint','text':' '+wording,'sources':['response_requirements.selection_link']})
    bundle['settings']['selection_link']='comparison'
    bundle['semantic_sha256']=fingerprint(bundle)
    return bundle
