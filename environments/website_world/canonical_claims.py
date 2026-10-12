"""Public declaration domains -> canonical claims; never inspect task outcomes."""
from copy import deepcopy
from collections.abc import Mapping
import math

from jsonschema import Draft202012Validator
from experiments.answer_grading.extraction import claim, obj, _quote
from .catalog_predicates import _same

VERSION = 'website-canonical-claim-domains-v1'
MAX_INTEGER_MENU = 128
UNMATCHED = '__unmatched_option__'


def _label(value, *, retail_axis=False):
    if type(value) is bool:
        # Merchant tuples are encoded with str(sku value); fact cells use the
        # existing normalized true/false representation.
        return str(value) if retail_axis else 'true' if value else 'false'
    if type(value) not in (str, int, float) or isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Canonical option must be a finite scalar')
    return str(value)


def declared_values(definition, *, retail_axis=False):
    """Full retail labels or known fact vocabulary; never expected outcomes."""
    if not isinstance(definition, Mapping):
        raise ValueError('Field declaration must be an object')
    typ = definition.get('type')
    if typ == 'boolean':
        values = [False, True]
    elif typ == 'enum':
        values = definition.get('values')
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError('Declared enum needs a nonempty domain')
    elif typ == 'integer' and retail_axis:
        lower, upper = definition.get('min'), definition.get('max')
        if (type(lower) is not int or type(upper) is not int or lower < 0
                or not 0 < upper-lower+1 <= MAX_INTEGER_MENU
                or definition.get('unit') or definition.get('step', 1) != 1):
            return None
        values = range(lower, upper+1)
    else:
        # Continuous facts, constants and open strings are not vocabularies.
        return None
    # Fact cells carry logical state separately. Retail tuples instead use
    # their literal menu labels, including any declared unspecified label.
    sentinels = [] if retail_axis else [*definition.get('unknown_values', []),
                                       *definition.get('not_applicable_values', [])]
    values = [v for v in values if not any(_same(v, s) for s in sentinels)]
    labels = [_label(v, retail_axis=retail_axis) for v in values]
    normalized = [v.strip().casefold() for v in labels]
    if (any(not v or v == UNMATCHED.casefold() for v in normalized)
            or len(set(normalized)) != len(normalized)):
        raise ValueError('Declared options are blank, reserved or ambiguous')
    return labels


def canonical_claim(values, *, separate_status=False):
    result = claim(enum=[*values, UNMATCHED, None])
    description = (
        'Map only unambiguous answer wording/case to a canonical label; preserve its exact quote. '
        'Never convert units or size systems, infer from the request/URL/reference/default, '
        'or guess a nearest label. A stated unmatched value uses '+UNMATCHED+' with its quote; '
        'null means genuinely absent. Ambiguity requires interpretation=ambiguous.')
    if separate_status:
        description += (' Unknown and not-applicable assertions belong to the cell status; '
                        'their value and value evidence must both be null.')
    result['properties']['value']['description'] = description
    return result


def variant_schema(items, fields):
    """Union full public declarations without inspecting SKU/candidate values."""
    declarations = []
    for item in items:
        declared = item.get('variant_fields', {})
        if not isinstance(declared, Mapping):
            raise ValueError('Variant declarations must be an object')
        declarations.append(declared)
    properties = {}
    for field in fields:
        definitions = [d[field] for d in declarations if field in d]
        domains = [declared_values(d, retail_axis=True) for d in definitions]
        if domains and all(d is not None for d in domains):
            values = list(dict.fromkeys(v for domain in domains for v in domain))
            properties[field] = canonical_claim(values)
        else:
            properties[field] = claim()
    return obj(properties)


def validate_variant_claims(value, answer, schema):
    """Schema/provenance and literal fallback, independent of field names.

    Do not feed nested axis names through flat money/status special cases.
    Canonical meaning is extractor-owned; an unmatched assertion remains
    non-null so existing native identity comparisons fail rather than omit it.
    """
    Draft202012Validator(schema).validate(value)
    for field, entry in value.items():
        if entry['value'] is None:
            if entry['evidence'] is not None:
                raise ValueError('Absent variant needs absent evidence')
        else:
            _quote(entry['evidence'], answer)
            if ('enum' not in schema['properties'][field]['properties']['value']
                    and entry['value'] not in entry['evidence']):
                raise ValueError('Variant value absent from exact answer quote')
    return deepcopy(value)
