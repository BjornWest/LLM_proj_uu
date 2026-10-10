"""Additive, opt-in commercial range stage; preserves frozen domain packages.

Canonical scalar: product.facts.market_range. Status is separately exported.
Run ``python -m environments.product_world.market_range --help`` for a stage draw.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

from .concept_registry import ConceptRegistry
from .product_package import ProductPackage

POLICY_PATH = Path(__file__).parent / 'data/shared_product_features/market_range.json'
ROOT = Path(__file__).resolve().parents[2]
VERSION = 'product-market-range-export-v1'
FIELD = 'product.facts.market_range'
VALUES = ('women', 'men', 'unisex')
POSITIONING = ('budget', 'mainstream', 'premium')


@lru_cache(maxsize=1)
def _concepts():
    return {c['id']: c['family_id'] for c in ConceptRegistry.load().concepts()}


def _weights(value):
    if not isinstance(value, dict) or set(value) != set(VALUES):
        raise ValueError('Market-range weights must declare women, men and unisex')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not math.isfinite(v) or v < 0 for v in value.values()) or sum(value.values()) <= 0:
        raise ValueError('Market-range weights must be finite, nonnegative and nonempty')
    return deepcopy(value)


def load_policy():
    policy = json.loads(POLICY_PATH.read_text())
    if policy['schema_version'] != 'product-market-range-policy-v1' or policy['field'] != FIELD:
        raise ValueError('Unsupported market-range policy')
    _weights(policy['default_weights'])
    premium = _weights(policy['premium_fragrance_weights'])
    if premium['unisex'] != 0:
        raise ValueError('Premium fragrance must exclude unisex')
    return policy


def applicability(concept_id, *, pack_format=None):
    """Known catalog IDs only. Unspecified conditional construction is unknown."""
    family = _concepts().get(concept_id)
    if family is None:
        raise ValueError(f'Unknown product concept: {concept_id}')
    policy = load_policy()
    conditional = policy['conditional_concepts'].get(concept_id)
    if conditional:
        if pack_format is None:
            return 'unknown'
        if pack_format not in conditional['values']:
            raise ValueError('Unsupported running-pack format')
        return 'known' if pack_format in conditional['applicable_values'] else 'not_applicable'
    return 'known' if family in policy['family_ids'] else 'not_applicable'


def stage_document(concept_id, *, weights=None):
    """Executable existing DSL. Caller resolves conditional applicability first.

    This is a separate program after positioning, before retailer allocation;
    domain facts/SKU identities/prices/review draws are unchanged.
    """
    family = _concepts().get(concept_id)
    policy = load_policy()
    if family not in policy['family_ids'] and concept_id not in policy['conditional_concepts']:
        raise ValueError('Concept does not have a market-range stage')
    fields = {
        'product.product_id': {'type': 'string', 'input': True},
        'request.accepted_market_ranges': {'type': 'set', 'items': {'type': 'enum', 'values': list(VALUES)},
                                           'min_items': 1, 'input': True, 'optional': True},
        FIELD: {'type': 'enum', 'values': list(VALUES),
                'retail_presentation': {'allowed': ['description']}}
    }
    step = {'id': 'market_range', 'target': FIELD, 'sample': 'weighted_choice',
            'weights': _weights(weights if weights is not None else policy['default_weights'])}
    if family == 'fragrance':
        fields['profile.positioning'] = {'type': 'enum', 'values': list(POSITIONING), 'input': True}
        step['cases'] = [{'when': "profile.positioning == 'premium'",
                          'weights': deepcopy(policy['premium_fragrance_weights'])}]
    language = []
    for value, label in [('women', "Women's"), ('men', "Men's"), ('unisex', 'Unisex')]:
        predicate = f"{FIELD} == '{value}'"
        language.append({'id': f'market_range.description.{value}', 'when': predicate,
                         'meaning': {'kind': 'catalog_fact', 'predicate': predicate},
                         'formulations': [f'{label} fragrance.' if family == 'fragrance'
                                          else f'{label} range.']})
    return {'schema_version': 'product-package-v1', 'concept_id': concept_id,
            'fields': fields, 'steps': [step], 'rules': [],
            'bindings': [{'id': 'market_range.requirement', 'role': 'task_requirement',
                          'predicate': f'{FIELD} in request.accepted_market_ranges',
                          'support': 'explicit_opt_in_predicate_not_registered_with_task_sampler'},
                         {'id': 'market_range.filter', 'role': 'filter',
                          'predicate': f'{FIELD} in request.accepted_market_ranges'}],
            'language': language,
            'metadata': {'shared_feature': 'product-market-range-policy-v1',
                         'identity_level': 'product',
                         'stage': 'after_positioning_before_retailer_allocation'}}


def sample_market_range(seed, *, concept_id, product_id, positioning=None,
                        pack_format=None, weights=None):
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError('Seed must be a nonnegative integer')
    if not isinstance(product_id, str) or not product_id:
        raise ValueError('Product identity is required')
    if positioning is not None and positioning not in POSITIONING:
        raise ValueError('Unsupported positioning')
    if weights is not None:
        _weights(weights)
    status = applicability(concept_id, pack_format=pack_format)
    if concept_id.startswith('fragrance.') and positioning is None:
        status = 'unknown'  # Premium exclusion cannot be established without this input.
    result = {'schema_version': VERSION, 'concept_id': concept_id, 'product_id': product_id,
              'fields': {FIELD: {'status': status}}, 'descriptions': [], 'trace': [],
              'assertions': [], 'source_files': {
                  str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (POLICY_PATH, Path(__file__), Path(__file__).with_name('product_package.py'),
                            Path(__file__).with_name('product_expressions.py'))}}
    if status != 'known':
        return result
    document = stage_document(concept_id, weights=weights)
    package = ProductPackage(document)
    # Product identity separates streams even if the same world seed is reused.
    draw_seed = int.from_bytes(hashlib.sha256(f'{VERSION}/{seed}/{product_id}'.encode()).digest()[:8], 'big')
    inputs = {'product': {'product_id': product_id}}
    if concept_id.startswith('fragrance.'):
        inputs['profile'] = {'positioning': positioning}
    draw = package.sample(draw_seed, inputs=inputs)
    value = draw['entities']['product']['facts']['market_range']
    result['fields'][FIELD]['value'] = value
    result['trace'] = draw['trace']
    result['stage_sha256'] = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    result['assertions'] = [{'id': 'catalog.market_range', 'kind': 'field_value', 'field': FIELD,
                             'subject': {'kind': 'product', 'id': product_id},
                             'authority': 'catalog_fact', 'status': 'known', 'value': value}]
    statement = package.formulate(f'market_range.description.{value}', draw['entities'], seed=draw_seed)
    # Private producer metadata; renderer strips it, retaining ordinary statement text.
    statement['public_content'] = {'schema': 'product-public-content-v1', 'mapping_status': 'complete',
                                   'assertions': deepcopy(result['assertions']),
                                   'source_files': deepcopy(result['source_files']),
                                   'concept_id': concept_id, 'pool_id': statement['meaning_id'],
                                   'formulation_id': statement['formulation_id'],
                                   'stage_sha256': result['stage_sha256']}
    result['descriptions'] = [statement]
    return result


def augment_product(item, *, seed, weights=None):
    """Copy a rich preview product, inheriting one canonical range for all SKUs.

    An independent opt-in projection, not a retrofit of historical accepted facts.
    Existing declarations are protected from accidental resampling.
    """
    result = deepcopy(item)
    public = result['public']
    if 'market_range' in public.get('facts', {}) or 'market_range' in result.get('private', {}):
        raise ValueError('Product already has a market-range declaration/stage')
    private = result.setdefault('private', {})
    positioning = private.get('profiles', {}).get('positioning', private.get('positioning'))
    sampled = sample_market_range(seed, concept_id=public['concept_id'], product_id=public['product_id'],
                                  positioning=positioning, pack_format=public.get('facts', {}).get('pack_format'),
                                  weights=weights)
    field = sampled['fields'][FIELD]
    public.setdefault('fact_status', {})['market_range'] = field['status']
    if field['status'] == 'known':
        public.setdefault('facts', {})['market_range'] = field['value']
        result.setdefault('descriptions', []).extend(deepcopy(sampled['descriptions']))
    private['market_range'] = sampled
    return result


def matches_market_range(public, accepted_ranges):
    """Exact set predicate. Unisex inclusion is an explicit task/UI choice."""
    if not accepted_ranges or not set(accepted_ranges) <= set(VALUES):
        raise ValueError('Expected a nonempty set of declared ranges')
    value = public.get('facts', {}).get('market_range')
    status = public.get('fact_status', {}).get('market_range', 'unknown')
    return status == 'known' and value in accepted_ranges


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('concept_id')
    parser.add_argument('--product-id', default='example-product')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--positioning', choices=POSITIONING)
    parser.add_argument('--pack-format', choices=['running_vest', 'backpack'])
    parser.add_argument('--stage', action='store_true', help='Print executable notation rather than sample')
    args = parser.parse_args()
    output = stage_document(args.concept_id) if args.stage else sample_market_range(
        args.seed, concept_id=args.concept_id, product_id=args.product_id,
        positioning=args.positioning, pack_format=args.pack_format)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
