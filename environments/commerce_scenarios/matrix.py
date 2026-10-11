"""Finite saved-world family acceptance; no model dispatch or world manufacture.

Preparation records unsupported native witnesses explicitly. Browser cases use
the shared automatic lifecycle, preserve failed traces and never retry a case.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import traceback

VERSION = 'website-commerce-scenario-matrix-v1'


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)


def _available(offer):
    return any(n > 0 for n in offer['stock_by_source'].values())


def pricing_candidates(world, mechanism):
    """Finite deterministic saved catalog candidates, preserving world prices.

    From-price requires an actual cheaper sibling. Shipping-loss targets a
    subtotal just above the retailer's existing free-shipping threshold and an
    explicit 1..5 quantity/discount overlay; no stock/price/policy is repaired.
    Native preparation independently determines whether a real witness exists.
    """
    candidates = []
    for retailer in sorted(world['retailers'], key=lambda r: r['retailer_id']):
        offers = sorted((o for o in retailer['offers'] if _available(o)), key=lambda o: o['offer_id'])
        groups = defaultdict(list)
        for offer in offers:
            groups[offer['product_id']].append(offer)
        for offer in offers:
            if mechanism in ('from_price_variant', 'variant_condition') and not any(
                    o['price_minor'] < offer['price_minor'] for o in groups[offer['product_id']]):
                continue
            if mechanism == 'discount_shipping_loss':
                threshold = retailer.get('free_shipping_threshold_minor')
                if threshold is None:
                    continue
                for quantity in range(1, 6):
                    excess = offer['price_minor'] * quantity - threshold
                    if 0 <= excess < 3000:
                        candidates.append((retailer['retailer_id'], {
                            'offer_id': offer['offer_id'], 'quantity': quantity, 'discount_minor': excess + 1}))
            else:
                candidates.append((retailer['retailer_id'], {'offer_id': offer['offer_id']}))
    return candidates


def prepare(world_dir, output, *, families=None, seed=7, max_pricing_candidates=64):
    from experiments.commerce_dark_patterns import registry
    from .episode import runtime_arguments
    world_dir, output = Path(world_dir).resolve(strict=True), Path(output).resolve()
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('Declare a finite preparation seed')
    if type(max_pricing_candidates) is not int or not 1 <= max_pricing_candidates <= 256:
        raise ValueError('Declare candidate bound 1..256')
    families = tuple(registry.FAMILIES) if families is None else tuple(families)
    if not families or len(set(families)) != len(families) or set(families) - set(registry.FAMILIES):
        raise ValueError('Declare distinct supported families')
    _, manifest, args = runtime_arguments(world_dir, lazy_publication=True)
    if args['checkout_domain'] is None:
        raise ValueError('These controls require an ordinary shared canonical checkout domain')
    world_path = world_dir/'pin/world.private.json'
    world = json.loads(world_path.read_bytes())
    output.mkdir(exist_ok=False, parents=True)
    instances, cases, unsupported = [], [], []
    for family in families:
        for mechanism in registry.FAMILIES[family]:
            if family == 'pricing_promotions':
                proposals = pricing_candidates(world, mechanism)[:max_pricing_candidates]
            elif family == 'steering_recurrence':
                proposals = [(None, {'basket_plan': args['basket_plan'], 'delivery_plan': args['delivery_plan']})]
            else:
                retailer = next((r for r in sorted(world['retailers'], key=lambda r: r['retailer_id'])
                                 if any(_available(o) for o in r['offers'])), None)
                proposals = [] if retailer is None else [(retailer['retailer_id'], {})]
            instance = None
            tried = []
            for rid, parameters in proposals:
                proposed = registry.prepare(seed, mechanism=mechanism, world=world,
                    retailer_id=rid, parameters=parameters)
                native = proposed['prepared']
                tried.append({'retailer_id': rid, 'parameters': {
                    k: v for k, v in parameters.items() if k not in ('basket_plan', 'delivery_plan')},
                    'status': native.get('status', native.get('witness_status', native.get('reference', {}).get('status'))),
                    'reasons': native.get('reference', {}).get('reasons', [])})
                ready = (native.get('witness_status') == 'world_bound' if family == 'consent_extras' else
                         native.get('reference', {}).get('status') == 'ready_native' if family == 'pricing_promotions' else
                         native.get('status') == 'ready')
                if not ready:
                    continue
                # Corrupt ready references/source bindings are errors, rather
                # than another unsupported witness to skip in a search.
                registry.validate_ready(proposed)
                instance = proposed
                break
            if instance is None:
                unsupported.append({'family': family, 'mechanism': mechanism, 'proposals': tried,
                                    'reason': 'No ready native witness among finite saved-world candidates'})
                continue
            name = mechanism+'-instance.private.json'
            save(output/name, instance)
            record = {'family': family, 'mechanism': mechanism, 'instance': name,
                      'sha256': sha256((output/name).read_bytes()).hexdigest(), 'proposals': tried}
            instances.append(record)
            for case in ('positive', 'wrong'):
                cases.append({**{k: record[k] for k in ('family', 'mechanism', 'instance', 'sha256')},
                              'case': case, 'expected': 'pass' if case == 'positive' else 'fail'})
        first = next((r for r in instances if r['family'] == family), None)
        if first is not None:
            cases.append({**{k: first[k] for k in ('family', 'mechanism', 'instance', 'sha256')},
                          'case': 'incomplete', 'expected': 'inconclusive'})
    value = {'schema': VERSION, 'world_dir': str(world_dir), 'world_sha256': sha256(world_path.read_bytes()).hexdigest(),
             'world_source_sha256': manifest['source_sha256'], 'seed': seed,
             'families': list(families), 'max_pricing_candidates': max_pricing_candidates,
             'instances': instances, 'cases': cases, 'unsupported': unsupported,
             'world_draws': 0, 'provider_requests': 0,
             'qualification': 'Explicit presentation scenarios over an unchanged saved world; finite native witnesses, not conditioned world sampling.'}
    save(output/'matrix.private.json', value)
    return value


def run(matrix_path, output, *, families=None, max_steps=80, max_input_tokens=500000, cases=None):
    from .publication import prepare_episode, run_saved
    matrix_path, output = Path(matrix_path).resolve(strict=True), Path(output).resolve()
    matrix_bytes = matrix_path.read_bytes()
    matrix_pin = sha256(matrix_bytes).hexdigest()
    matrix = json.loads(matrix_bytes)
    if matrix.get('schema') != VERSION:
        raise ValueError('Unknown matrix schema')
    if sha256((Path(matrix['world_dir'])/'pin/world.private.json').read_bytes()).hexdigest() != matrix['world_sha256']:
        raise ValueError('Saved world changed after matrix preparation')
    allowed = set(matrix['families'])
    selected = allowed if families is None else set(families)
    if not selected or selected - allowed:
        raise ValueError('Requested family absent from prepared matrix')
    keys = {row['mechanism']+'-'+row['case'] for row in matrix['cases'] if row['family'] in selected}
    chosen = keys if cases is None else set(cases)
    if not chosen or chosen - keys:
        raise ValueError('Requested control absent from selected matrix families')
    output.mkdir(exist_ok=False, parents=True)
    results = []
    # Two concurrent full-world browser controls exceeded the default256 process
    # cap in the retained kit witness. Preserve that finite cap and run serially.
    for row in matrix['cases']:
        if row['family'] not in selected:
            continue
        key = row['mechanism']+'-'+row['case']
        if key not in chosen:
            continue
        instance = matrix_path.parent/row['instance']
        if sha256(instance.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Frozen native instance changed: '+key)
        prepared = None
        try:
            prepared = prepare_episode(matrix['world_dir'], instance, row['case'])
            config = prepared.config
            if (prepared.instance_sha256 != row['sha256'] or
                    (config['family'], config['mechanism'], config['case']) !=
                    (row['family'], row['mechanism'], row['case'])):
                raise ValueError('Prepared episode differs from frozen matrix control: '+key)
            result = run_saved(prepared, output/key, max_steps=max_steps, max_input_tokens=max_input_tokens)
            record = {'case': row, 'result': result, 'observations': getattr(prepared.policy, 'observations', [])}
            record['accepted'] = (result['publication']['status'] == row['expected']
                                  and result['publication']['control_matches_expectation'] is True)
        except Exception as error:
            record = {'case': row, 'accepted': False, 'system_error': type(error).__name__+': '+str(error),
                      'traceback': traceback.format_exc()}
        finally:
            if prepared is not None:
                prepared.close()
        results.append(record)
        save(output/(key+'-result.json'), record)
        print(json.dumps({'case': key, 'accepted': record['accepted'],
                          'system_error': record.get('system_error')}), flush=True)
    if sha256(matrix_path.read_bytes()).hexdigest() != matrix_pin:
        raise ValueError('Frozen matrix changed during control execution')
    summary = {'schema': VERSION, 'matrix_sha256': matrix_pin,
               'tags': ['scripted', 'commerce-dark-patterns'], 'families': sorted(selected),
               'selected_cases': sorted(chosen), 'results': results,
               'all_selected_controls_pass': bool(results) and all(r['accepted'] for r in results),
               'unsupported': [r for r in matrix['unsupported'] if r['family'] in selected],
               'world_draws': 0, 'provider_requests': 0, 'retries': 0,
               'broader_effects': 'unknown'}
    save(output/'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparing = commands.add_parser('prepare')
    preparing.add_argument('--world', required=True)
    preparing.add_argument('--output', required=True)
    preparing.add_argument('--family', action='append')
    preparing.add_argument('--seed', type=int, default=7)
    executing = commands.add_parser('run')
    executing.add_argument('--matrix', required=True)
    executing.add_argument('--output', required=True)
    executing.add_argument('--family', action='append')
    executing.add_argument('--case', action='append', help='Exact mechanism-case key; omitted selects the full matrix')
    executing.add_argument('--max-steps', type=int, default=80)
    executing.add_argument('--max-input-tokens', type=int, default=500000)
    args = parser.parse_args()
    if args.command == 'prepare':
        value = prepare(args.world, args.output, families=args.family, seed=args.seed)
        print(json.dumps({'cases': len(value['cases']), 'unsupported': value['unsupported']}), flush=True)
    else:
        value = run(args.matrix, args.output, families=args.family,
                    max_steps=args.max_steps, max_input_tokens=args.max_input_tokens, cases=args.case)
        raise SystemExit(0 if value['all_selected_controls_pass'] and not value['unsupported'] else 1)


if __name__ == '__main__':
    main()
