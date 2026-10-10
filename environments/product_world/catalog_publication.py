"""Shared pruned scalar publication for explicitly adopted graph packages.

No manufacturing/review traversal or validators run here. Older packages often
have no authored semantic IDs. Their visible scalar records keep exact native
field/subject/status identity, explicitly without claiming an authored meaning.
Compound prose is withheld until its own semantic adapter exists.
"""
from functools import lru_cache

from experiments.accepted_catalog_commerce.catalog_registry import ADDITIONS
from . import reviewed_feature_publication as reviewed
from .feature_publication import _lookup, _metadata, _MISSING
from .disclosure_sampling import DisclosureDistribution, DEFAULT_HIGHLIGHT_BIAS
from .retailer_disclosure import sample_retailer_disclosure, disclosure_count_weights
from .shared_state import mutable

VERSION = 'generic-catalog-selected-content-v1'
CONCEPTS = ADDITIONS
FAMILY_LABELS = {
    'footwear': 'Footwear', 'jackets': 'Jackets', 'headphones': 'Headphones',
    'phones': 'Phones', 'phone_cases': 'Phone cases', 'chargers': 'Chargers',
    'keyboards': 'Keyboards', 'cat_food': 'Cat food', 'dog_food': 'Dog food',
}
FAMILY_LABELS.update({'cat_litter': 'Cat litter', 'pet_bowls': 'Pet bowls and fountains', 'pet_toys': 'Pet toys', 'pet_harnesses': 'Pet harnesses', 'laptops': 'Laptops', 'memory_cards': 'Memory cards', 'ssd': 'Storage drives', 'monitors': 'Monitors', 'printer_ink': 'Printer ink', 'camera_lenses': 'Camera lenses', 'beer': 'Beer', 'cookware': 'Cookware', 'brush_heads': 'Replacement toothbrush heads'})

FAMILY_LABELS.update({'bedding': 'Bedding', 'cleansers': 'Cleansers', 'cookware': 'Pans and shallow cookware', 'foundation': 'Foundation and complexion bases', 'kitchen_utensils': 'Kitchen utensils and preparation tools', 'knitwear': 'Knitwear', 'moisturizers': 'Moisturizers', 'pots': 'Pots', 'serums': 'Serums', 'toothbrushes': 'Toothbrushes', 'tops': 'Tops', 'towels': 'Towels', 'trousers': 'Trousers', 'wine': 'Wine'})

@lru_cache(maxsize=256)
def policy(concept_id):
    if concept_id not in CONCEPTS:
        raise ValueError('Concept has no released generic commerce publication')
    return reviewed.load_reviewed_policy(concept_id)


def inventory(concept_id):
    definition = policy(concept_id)
    groups = definition['disclosure_groups']
    return {'concept_id': concept_id, 'protocol': VERSION,
            'groups': {k: g['highlight_priority'] for k, g in groups.items()},
            'capacity': len(groups),
            'sku_dependent': any(p.startswith('sku.') for g in groups.values() for p in g['fields']),
            'policy_sha256': reviewed.policy_sha256(concept_id)}


def _status(value, definition, recorded):
    if isinstance(recorded, dict):
        recorded = ('not_applicable' if recorded.get('applicable') is False else
                    'known' if recorded.get('known') is True else 'unknown')
    for key, label in [('unknown_values', 'unknown'), ('not_applicable_values', 'not_applicable')]:
        if any(type(value) is type(v) and value == v for v in definition.get(key, [])):
            return label
    # Constant fallback is a source declaration, never a fabricated varying status.
    if recorded is None and 'constant' in definition and not definition.get('applicable_when'):
        constant = definition['constant']
        if type(value) is type(constant) and value == constant:
            return 'known'
    return recorded


def _label(path):
    return path.split('.')[-1].replace('_', ' ').capitalize()


def _text(record):
    value = record['value']
    if type(value) is bool:
        value = 'Yes' if value else 'No'
    unit = record.get('unit')
    result = _label(record['field']) + ': ' + str(value) + ((' ' + str(unit)) if unit else '')
    # Preserve scope/test/reference basis visibly when one is declared.
    qualifiers = record['qualifiers']
    details = [str(v) for k, v in qualifiers.items() if k != 'semantic_status']
    if details:
        result += ' (' + '; '.join(details) + ')'
    return result + '.'


def export_catalog_content(item, *, sku_id, seed, retailer_id=None, retailer=None,
                           count_weights=None, highlight_bias=DEFAULT_HIGHLIGHT_BIAS,
                           required_groups=(), forbidden_groups=(), allowed_counts=None,
                           selected_groups=None):
    """Count first, then topics; resolve only known/applicable approved scalars.

    Retailer profiles use the existing shared tendency. Explicit selected_groups
    is for fixtures, not a new task-dependent manufacturing repair. Empty/partial
    outputs are final: consumers must not revive raw dictionaries or paragraphs.
    """
    public = item['public']; cid = public['concept_id']; definition = policy(cid)
    sku = next((s for s in public['skus'] if s['sku_id'] == sku_id), None)
    if sku is None or sku['product_id'] != public['product_id']:
        raise ValueError('Select a manufactured SKU of this product')
    inv = inventory(cid); profile = None
    if retailer is not None:
        if count_weights is not None:
            raise ValueError('Choose retailer profile or explicit count weights')
        profile = sample_retailer_disclosure(seed, retailer)
        if retailer_id is not None and retailer_id != profile['retailer_id']:
            raise ValueError('Retailer identity differs from its profile')
        retailer_id = profile['retailer_id']
        count_weights = disclosure_count_weights(inv['capacity'], profile['tendency'])
    if type(seed) is not int or type(retailer_id) is not str or not retailer_id:
        raise ValueError('Declare integer seed and retailer identity')
    distribution = DisclosureDistribution(inv['groups'], count_weights=count_weights,
                                          highlight_bias=highlight_bias)
    if selected_groups is None:
        selection = distribution.sample(seed=seed, retailer_id=retailer_id,
            product_id=public['product_id'], concept_id=cid, required_groups=required_groups,
            forbidden_groups=forbidden_groups, allowed_counts=allowed_counts)
        chosen = set(selection['selected_groups'])
    else:
        if required_groups or forbidden_groups or allowed_counts is not None:
            raise ValueError('Explicit fixture topics cannot also have sampled conditions')
        chosen = set(selected_groups)
        if chosen - set(inv['groups']):
            raise ValueError('Unknown generic disclosure group')
        selection = {'selected_groups': sorted(chosen), 'count': len(chosen),
                     'count_source': 'explicit_fixture_groups'}
    statuses = {**item['catalog_status'], **item['sku_status'].get(sku_id, {})}
    entities = {'product': public, 'sku': sku}
    mapped = reviewed.resolve_scalar_records(definition, entities, statuses)
    slots = []; withheld = []
    for key, group in definition['disclosure_groups'].items():
        if key not in chosen:
            continue
        records = []
        for path in group['fields']:
            field = definition['fields'][path]
            if field['role'] not in ('literal', 'descriptive'):
                continue
            value = _lookup(entities, path)
            if value is _MISSING or value is None or type(value) not in (str, int, float, bool):
                continue
            status = _status(value, field['definition'], statuses.get(path))
            if status != 'known':
                continue
            if field['semantic_id']:
                record = mapped.get(path)
                if record is None:
                    continue  # Never erase an authored qualifier to make it publishable.
                record = mutable(record)
                record['mapping_status'] = 'authored_scalar_assertion'
            else:
                # Direct declared scalar identity only. No compound assertion or
                # subjective experience is manufactured from the field label.
                subject = {'kind': 'sku' if path.startswith('sku.') else 'product',
                           'id': sku_id if path.startswith('sku.') else public['product_id']}
                qualifiers = _metadata(field.get('required_qualifiers', {}), entities)
                if qualifiers is _MISSING or qualifiers.get('semantic_status', 'known') != 'known':
                    continue
                if field['definition'].get('basis'):
                    qualifiers.setdefault('basis', mutable(field['definition']['basis']))
                if field['definition'].get('component'):
                    subject['component'] = mutable(field['definition']['component'])
                record = {'field': path, 'semantic_id': None, 'authority': 'source_catalog_field',
                          'subject': subject, 'value': value, 'status': 'known',
                          'unit': field['definition'].get('unit'), 'qualifiers': qualifiers,
                          'mapping_status': 'native_scalar_field_without_authored_meaning'}
            records.append(record)
        if not records or (group.get('atomic') and len(records) != len(group['fields'])):
            withheld.append(key)
            continue
        slots.append({'id': group['id'], 'group_key': key, 'display_group': group['display_group'],
                      'fields': [r['field'] for r in records], 'assertions': records,
                      'text': ' '.join(_text(r) for r in records)})
    display = [{'key': key, 'label': spec['label'],
                'preferred_representation': spec['preferred_representation'],
                'slots': [s for s in slots if s['display_group'] == key]}
               for key, spec in definition['display_groups'].items()
               if any(s['display_group'] == key for s in slots)]
    published = {s['group_key'] for s in slots}
    selection.update(published_count=len(published), unavailable_selected_groups=sorted(chosen-published))
    packet = {'schema': VERSION, 'protocol': VERSION, 'concept_id': cid,
              'product_id': public['product_id'], 'sku_id': sku_id, 'retailer_id': retailer_id,
              'policy_sha256': inv['policy_sha256'], 'display_groups': display,
              'highlight_candidates': [{'slot_id': s['id'], 'priority': inv['groups'][s['group_key']]}
                 for s in slots if definition['disclosure_groups'][s['group_key']]['highlight_candidate']],
              'withheld_groups': withheld, 'disclosure_selection': selection,
              'limits': ['Source-native scalar identity is not an authored task/review meaning.',
                         'Compound prose has no generic fallback; omitted groups stay omitted.']}
    if profile is not None:
        packet['retailer_disclosure'] = profile
        selection['count_source'] = profile['protocol']
    return packet
