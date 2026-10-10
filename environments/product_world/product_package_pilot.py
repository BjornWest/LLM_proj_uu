"""Port the accepted pilot into executable packages without changing old worlds."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from . import footwear_context_pilot as legacy
from .footwear_retail_content import load_recipe
from .product_package import ProductPackage, VERSION

DIRECTORY = Path(__file__).with_name('data')/'product_packages'


def infer(value, **extra):
    if isinstance(value, bool):
        result = {'type': 'boolean'}
    elif isinstance(value, int):
        result = {'type': 'integer'}
    elif isinstance(value, float):
        result = {'type': 'number'}
    elif isinstance(value, str):
        result = {'type': 'string'}
    elif isinstance(value, list):
        result = {'type': 'array', 'items': infer(value[0]) if value else {'type': 'string'}}
    elif isinstance(value, dict):
        result = {'type': 'object', 'properties': {k: infer(v) for k, v in value.items()}}
    else:
        raise ValueError('Unsupported fixture type')
    return {**result, **extra}


def compile_document(concept, spec=None):
    """Export, never overwrite an authored package automatically on normal load."""
    spec = legacy.load_spec() if spec is None else spec
    cfg = spec['concepts'][concept]; prefix = f'product/{concept}'
    fields = {
        'brand.brand_id': {'type': 'string', 'input': True},
        'brand.positioning_weights': {'type': 'object', 'input': True},
        'brand.emphasis_weights': {'type': 'object', 'input': True},
        'brand.eligible_concepts': {'type': 'array', 'items': {'type': 'string'}, 'input': True},
        'product.product_id': {'type': 'string', 'input': True},
        'profile.positioning': {'type': 'enum', 'values': list(spec['positioning_multipliers'])},
        'profile.emphasis': {'type': 'enum', 'values': list(spec['emphasis_multipliers'])},
        'profile.execution': {'type': 'number', 'min': 0, 'max': 1},
    }
    steps = [
        {'id': 'positioning', 'target': 'profile.positioning', 'sample': 'weighted_choice', 'weights_from': 'brand.positioning_weights', 'stream': prefix+'/positioning'},
        {'id': 'emphasis', 'target': 'profile.emphasis', 'sample': 'weighted_choice', 'weights_from': 'brand.emphasis_weights', 'stream': prefix+'/emphasis'},
        {'id': 'execution', 'target': 'profile.execution', 'sample': 'uniform', 'min': spec['execution_range'][0], 'max': spec['execution_range'][1], 'stream': prefix+'/execution'},
    ]

    def adjusted(field, eligible=None):
        return [{'when': f'profile.{axis} == {value!r}', 'multiply': {k: v for k, v in multipliers[field].items() if eligible is None or k in eligible}}
                for axis in ('emphasis', 'positioning') for value, multipliers in spec[axis+'_multipliers'].items()
                if field in multipliers and multipliers[field]]

    bundles = {k: {**v, 'base_mass_g': cfg['base_mass_g_per_shoe_eu40'][k]}
               for k, v in spec['construction_packages'].items()}
    fields['internal.construction'] = infer(next(iter(bundles.values())))
    fields['internal.construction']['properties']['base_mass_g']['unit'] = 'g'
    steps.append({'id': 'construction', 'target': 'internal.construction', 'sample': 'weighted_choice',
                  'weights': spec['construction_weights'], 'values': bundles, 'adjustments': adjusted('construction'), 'stream': prefix+'/construction'})
    for name in ('cushioning', 'footbed', 'sole_structure'):
        path = 'product.facts.'+name
        fields[path] = infer(next(iter(bundles.values()))[name])
        steps.append({'id': name, 'target': path, 'derive': 'internal.construction.'+name})
    fixed = {**cfg['fixed'], 'mass_basis': 'one item, EU 40 reference configuration', 'waterproof_rating': 'not specified'}
    if concept == 'walking_sandals':
        fixed['toe_coverage'] = 'open'
    for name, value in fixed.items():
        fields['product.facts.'+name] = infer(value, constant=value)
    fields['product.facts.waterproof_rating']['unknown_values'] = ['not specified']
    material = 'product.facts.component_materials.'+cfg['component']
    fields[material] = {'type': 'enum', 'values': list(cfg['material_weights'])}
    fields['product.facts.component_materials.outsole'] = {'type': 'string', 'constant': 'rubber'}
    steps.append({'id': 'material', 'target': material, 'sample': 'weighted_choice', 'weights': cfg['material_weights'], 'adjustments': adjusted('material', cfg['material_weights']), 'stream': prefix+'/material'})
    for name, source, multiplier in [('fastening', cfg['fastening_weights'], 'fastening'), ('sole_tread', spec['tread_weights'], 'tread')]:
        path = 'product.facts.'+name
        fields[path] = {'type': 'enum', 'values': list(source)}
        steps.append({'id': name, 'target': path, 'sample': 'weighted_choice', 'weights': source, 'adjustments': adjusted(multiplier), 'stream': prefix+'/'+multiplier})
    fields['internal.mass_noise_g'] = {'type': 'integer', 'unit': 'g'}
    fields['product.facts.reference_mass_g'] = {'type': 'integer', 'unit': 'g'}
    steps.extend([
        {'id': 'mass_noise', 'target': 'internal.mass_noise_g', 'sample': 'uniform_int', 'min': -15, 'max': 15, 'stream': prefix+'/mass'},
        {'id': 'mass', 'target': 'product.facts.reference_mass_g', 'derive': 'internal.construction.base_mass_g + internal.mass_noise_g'},
    ])
    fields['product.widths'] = {'type': 'array', 'items': {'type': 'enum', 'values': ['standard', 'narrow', 'wide']}, 'min_items': 1}
    fields['product.colours'] = {'type': 'set', 'items': {'type': 'enum', 'values': spec['colours']}, 'min_items': 1}
    fields['product.sizes_eu'] = {'type': 'array', 'items': {'type': 'integer'}, 'min_items': 1}
    steps.extend([
        {'id': 'width_set', 'target': 'product.widths', 'sample': 'weighted_choice', 'weights': cfg['width_set_weights'], 'values': spec['width_sets'], 'stream': prefix+'/width_set'},
        {'id': 'colours', 'target': 'product.colours', 'sample': 'weighted_subset', 'weights': cfg['colour_weights'], 'count_weights': spec['colour_count_weights'],
         'streams': {'count': prefix+'/colour_count', 'item': prefix+'/colour_{index}'}},
        {'id': 'size_range', 'target': 'product.sizes_eu', 'sample': 'weighted_choice', 'weights': spec['size_range_weights'], 'values': spec['size_ranges'], 'stream': prefix+'/size_range'},
    ])
    for path, definition in {
        'group.width': {'type': 'enum', 'values': ['standard', 'narrow', 'wide']},
        'group.colour_mode': {'type': 'enum', 'values': ['all', 'subset']},
        'group.colour_count': {'type': 'integer'},
        'group.colours': {'type': 'set', 'items': {'type': 'string'}},
        'group.colour': {'type': 'string'},
        'group.size_mode': {'type': 'enum', 'values': ['full', 'subrange', 'alternating']},
        'group.sizes': {'type': 'array', 'items': {'type': 'integer'}, 'min_items': 1},
        'group.size': {'type': 'integer'},
    }.items():
        fields[path] = definition
    sku_properties = {'sku_id': {'type': 'string'}, 'product_id': {'type': 'string'},
                      'colour': {'type': 'string'}, 'width': {'type': 'string'}, 'size_eu': {'type': 'integer'}}
    fields['product.skus'] = {'type': 'array', 'items': {'type': 'object', 'properties': sku_properties}, 'min_items': 1}
    steps.append({'id': 'width_groups', 'for_each': {'binding': 'group.width', 'from': 'product.widths'}, 'steps': [
        {'id': 'width_colour_mode', 'target': 'group.colour_mode', 'sample': 'weighted_choice', 'weights': {'all': 1, 'subset': 0},
         'cases': [{'when': "group.width != 'standard'", 'weights': spec['extra_width_colour_weights']}], 'stream': prefix+'/colour_coverage/{width}'},
        {'id': 'width_colour_count', 'target': 'group.colour_count', 'sample': 'uniform_int', 'min': 'len(product.colours)', 'max': 'len(product.colours)',
         'cases': [{'when': "group.colour_mode == 'subset' and len(product.colours) > 1", 'min': 1, 'max': 'len(product.colours) - 1'}], 'stream': prefix+'/colour_subset_count/{width}'},
        {'id': 'width_colours', 'target': 'group.colours', 'sample': 'weighted_subset', 'weights': cfg['colour_weights'], 'eligible_from': 'product.colours',
         'count_from': 'group.colour_count', 'streams': {'item': prefix+'/colour_subset/{width}/{index}'}},
        {'id': 'colour_groups', 'for_each': {'binding': 'group.colour', 'from': 'group.colours'}, 'steps': [
            {'id': 'size_mode', 'target': 'group.size_mode', 'sample': 'weighted_choice', 'weights': spec['variant_size_weights'], 'stream': prefix+'/sizes/{colour}/{width}/mode'},
            {'id': 'size_coverage', 'target': 'group.sizes', 'sample': 'uniform_choice', 'values_from': 'coverage_groups(product.sizes_eu, group.size_mode)', 'stream': prefix+'/sizes/{colour}/{width}/coverage'},
            {'id': 'sku_sizes', 'for_each': {'binding': 'group.size', 'from': 'group.sizes'}, 'steps': [
                {'id': 'skus', 'target': 'product.skus', 'emit': {
                    'sku_id': "product.product_id + '-' + group.colour + '-' + group.width + '-' + str(group.size)",
                    'product_id': 'product.product_id', 'colour': 'group.colour', 'width': 'group.width', 'size_eu': 'group.size'}}]}]}]})
    fields['product.reference_price_sek'] = {'type': 'number', 'unit': 'SEK'}
    lo, hi = cfg['price_ranges_sek']['budget']
    steps.append({'id': 'price', 'target': 'product.reference_price_sek', 'sample': 'uniform', 'min': lo, 'max': hi, 'round_to': 10,
                  'cases': [{'when': f'profile.positioning == {p!r}', 'min': a, 'max': b} for p, (a, b) in cfg['price_ranges_sek'].items() if p != 'budget'], 'stream': prefix+'/price'})
    language = []
    bank = json.loads((legacy.DATA/'statements.json').read_text())
    for aspect, definition in bank['aspects'].items():
        if concept not in definition.get('concepts', [concept]):
            continue
        for stance in ('positive', 'negative', 'fits', 'too_short', 'too_long'):
            if stance not in definition:
                continue
            formulations = definition[stance]
            slots = set()
            from string import Formatter
            for text in formulations:
                slots |= {s for _, s, _, _ in Formatter().parse(text) if s is not None}
            mappings = {'heel_contact': repr('back of the shoe' if concept == 'walking_shoes' else 'heel strap'),
                        'usual_size': 'review.usual_size_eu', 'purchased_size': 'sku.size_eu'}
            if 'usual_size' in slots:
                fields['review.usual_size_eu'] = {'type': 'number', 'optional': True}
            language.append({'id': aspect+'/'+stance, 'meaning': {'kind': 'customer_experience', 'aspect': aspect,
                            'polarity': 'positive' if stance in ('positive', 'fits') else 'negative',
                            'stance': stance, 'context': definition['context'], 'source': definition['context'].get('source', 'first_hand')},
                             'slots': {s: mappings[s] for s in slots}, 'formulations': formulations})
    recipe = load_recipe()
    for f in recipe['fields']:
        if concept not in f.get('concepts', [concept]):
            continue
        path = f['scope']+'.'+f['path']
        if f['scope'] == 'sku':
            fields[path] = deepcopy(sku_properties[f['path']])
        if path not in fields:
            continue
        roles = recipe['concepts'][concept]['role_overrides'].get(f['id'], f['eligible_roles'])
        fields[path]['retail_presentation'] = {'allowed': [{'page_partition': 'separate_page', 'descriptive': 'description'}.get(r, r) for r in roles], 'policy_key': f['id']}
    fields['product.name'] = {'type': 'string', 'optional': True}
    for block in recipe['concepts'][concept]['description_blocks']:
        predicates = [f'product.{path} == {expected!r}' for path, expected in block['requires'].items()]
        meaning = {'kind': 'catalog_fact', 'fact_paths': list(block['slots'].values())}
        if predicates:
            meaning['predicate'] = ' and '.join(predicates)
        language.append({'id': 'description/'+block['id'], 'meaning': meaning,
                         'slots': {slot: 'product.'+path for slot, path in block['slots'].items()},
                         'formulations': [v['text'] for v in block['variants']]})
    return {'schema_version': VERSION, 'concept_id': cfg['registry_id'], 'random_namespace': legacy.VERSION,
            'status': 'ported_reference_not_live_runtime', 'fields': fields, 'steps': steps, 'language': language,
            'bindings': [], 'rules': [{'id': 'brand_scope', 'require': f'{concept!r} in brand.eligible_concepts'}], 'metadata': {'source_spec': str(legacy.DATA/'spec.json'),
            'execution_contract': 'Independent of positioning/emphasis; existing rating and review-topic modules consume it.',
            'variant_contract': 'Same manufactured distributions; canonical unordered colour serialization can change exact variant outcomes for the same seed.'}}


def export(directory=DIRECTORY):
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for concept in legacy.load_spec()['concepts']:
        document = compile_document(concept)
        ProductPackage(document)
        path = directory/(document['concept_id']+'.json')
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False)+'\n')
        paths.append(path)
    return paths


def sample_pilot_package(seed, concept, brand, *, overrides=None, path=None):
    document = compile_document(concept) if path is None else None
    package = ProductPackage(document) if document is not None else ProductPackage.load(path)
    inputs = {'brand': brand, 'product': {'product_id': 'pilot-'+concept}}
    result = package.sample(seed, inputs=inputs, overrides={'profile.'+k: v for k, v in (overrides or {}).items()})
    return package, result


def sample_ported_product(seed, concept, brand, *, product_id=None, existing_products=(), overrides=None):
    """Explicit opt-in factory adapter; old sample_product/worlds stay untouched.

    Public output is selected deliberately. Full DSL entities include latent
    profiles and trace state and must never be passed directly to retail pages.
    Existing footwear review/retail consumers remain reused here, not reauthored.
    """
    spec = legacy.load_spec()
    cfg = spec['concepts'][concept]
    package = ProductPackage.load(DIRECTORY/(cfg['registry_id']+'.json'))
    pid = product_id or 'pilot-'+concept
    result = package.sample(seed, inputs={'brand': brand, 'product': {'product_id': pid}},
                            overrides={'profile.'+k: v for k, v in (overrides or {}).items()})
    entities = result['entities']
    from .product_naming import sample_product_name
    name, name_trace = sample_product_name(spec['product_names'], brand_id=brand['brand_id'],
                                         existing_products=existing_products, rng=legacy.stream(seed, f'product/{concept}/name'))
    sampled = entities['product']
    public = {'product_id': pid, 'family_id': 'footwear', 'concept_id': cfg['registry_id'],
              'concept': concept, 'name': brand['name']+' '+name, 'model_name': name,
              'brand_id': brand['brand_id'], 'facts': sampled['facts'],
              'reference_price_sek': sampled['reference_price_sek'], 'skus': sampled['skus']}
    construction = next(r['option'] for r in result['trace'] if r['id'] == 'construction')
    return {'public': public, 'private': {**entities['profile'], 'trace': result['trace'],
            'construction_package': construction, 'fit_tendency': brand['fit_tendency'],
            'name_sampling': name_trace, 'variant_plan': {'schema_version': 'product-package-variant-trace-v1',
            'base_sizes_eu': sampled['sizes_eu'], 'draws': [r for r in result['trace'] if r['target'].startswith('group.')]},
            'package_schema_version': VERSION, 'overrides': dict(overrides or {})}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', action='store_true')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--concept', default='walking_shoes')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.export:
        for path in export():
            print(path)
        return
    spec = legacy.load_spec(); brand = legacy.sample_brand(args.seed, 0, spec)
    package, result = sample_pilot_package(args.seed, args.concept, brand)
    result['validation'] = {'status': 'compiled_and_sampled', 'sku_count': len(result['entities']['product']['skus'])}
    raw = json.dumps(result, indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(raw)
    else:
        print(raw, end='')


if __name__ == '__main__':
    main()
