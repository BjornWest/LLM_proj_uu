"""Answer-corrupting tier-2 hindrances for scripts/hindrance_suite.py.

The hindrance changes which offer is the correct answer of a find-then-buy
errand, so the agent must read and verify prices instead of avoiding a side
effect. Each base pattern has a clean twin in which the apparent winner (what
listings or a comparison site suggest) is also the true winner.

- size_price_step: a derived world where the native item-price winner's
  requested size (all colours/widths of that model at that shop) costs more
  than the runner-up. Listings and comparison "from" prices still show the base
  price of the other sizes; the product page shows the true price once the size
  is selected. Light adds a note beside the price; heavy is the plain native page.
- remote_area_surcharge: a derived world where the delivered-cheapest shop's
  home delivery carries a surcharge (added to its carrier contracts' home fee),
  so another shop is cheapest in total. The checkout's home-delivery rows say
  which part is the remote-area surcharge; light also states it on the product page.
- stale_comparison: native world; one comparison-site row shows an out-of-date
  price below the true winner, while that shop's own pages show the real,
  higher price. Light marks the row's age; heavy shows only the site-wide date.

Derived worlds copy the generated world directory, change only the declared
world fields, keep the world identity (so every sampled layout stays the same)
and re-bind the dependent digests. The true winner is recomputed by the native
oracles on the changed world; grading is the native order component on it.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PIECE = Path(__file__).with_name('hindrance_answers.js')
BASES = ('size_price_step', 'remote_area_surcharge', 'stale_comparison')
LEVELS = ('light', 'heavy')
EXECUTIONS = tuple(f'{b}_{l}' for b in BASES for l in LEVELS)
SURCHARGES = (4900, 6900, 8900, 9900, 12900, 14900, 19900, 24900)
STALE_DAYS = 9


def base_of(mechanism):
    for level in LEVELS:
        if mechanism.endswith('_' + level):
            return mechanism[:-len(level) - 1]
    return mechanism


def level_of(mechanism):
    return mechanism.rsplit('_', 1)[-1]


def is_answer(mechanism):
    return base_of(mechanism) in BASES


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def sek(minor):
    return f'SEK {minor // 100}' + (f'.{minor % 100:02d}' if minor % 100 else '')


def nice_above(minor, margin):
    """Smallest shop-like price ending in 9 kronor strictly above minor + margin."""
    return int(math.ceil((minor + margin + 100) / 1000) * 1000 - 100)


def nice_below(minor, margin):
    return int(math.floor((minor - margin) / 1000) * 1000 - 100)


# Derived worlds -------------------------------------------------------------

def derive_world(source, target, mutate):
    """Copy a generated world, apply `mutate(world)` and re-bind its digests.

    The world id and every sampled plan stay the same; digests of the changed
    world (both digest flavours) and of files that embed them are replaced to a
    fixpoint, then the pin and generation manifests are re-hashed.
    """
    from environments.website_world.adapter import digest
    from experiments.accepted_catalog_commerce import basket_quote
    flavours = (digest, basket_quote.model.digest)
    source, target = Path(source), Path(target)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('winner.json', 'answer-*.json'))
    path = target/'pin/world.private.json'
    world = read(path)
    before = [f(world) for f in flavours]
    identity = world['world_id']
    mutate(world)
    if world['world_id'] != identity:
        raise ValueError('Derived worlds keep the world identity')
    after = [f(world) for f in flavours]
    if before == after:
        raise ValueError('Derived world mutation changed nothing')
    path.write_text(json.dumps(world, indent=2, ensure_ascii=False) + '\n')
    mapping = dict(zip(before, after))
    documents = {p: read(p) for p in target.rglob('*.json') if p != path and 'source-snapshot' not in p.parts}

    def rebind():
        changed = True
        while changed:
            changed = False
            for p, value in documents.items():
                text = p.read_text()
                new = text
                for old, replacement in mapping.items():
                    new = new.replace(old, replacement)
                if new != text:
                    p.write_text(new)
                    updated = json.loads(new)
                    for f in flavours:
                        if f(value) != f(updated):
                            mapping[f(value)] = f(updated)
                    documents[p] = updated
                    changed = True
    rebind()
    # The comparison sidecar replays from the world: its public listings must be
    # unchanged; only private provenance (which offers sit at a minimum) may move.
    from environments.website_world import ecosystem, native_review_ecosystem, rich_ecosystem
    sidecar_path = target/'surrounding.private.json'
    sidecar = read(sidecar_path)
    producer = next(m for m in (native_review_ecosystem, rich_ecosystem, ecosystem)
                    if m.VERSION == sidecar['schema_version'])
    replayed = producer.generate(world, sidecar['controls'])
    public = lambda value: {k: v for k, v in value.items() if k != 'provenance_private'}
    if public(replayed) != public(sidecar):
        raise ValueError('Derived world changes public comparison listings')
    if replayed != sidecar:
        for f in flavours:
            mapping[f(sidecar)] = f(replayed)
        sidecar_path.write_text(json.dumps(replayed, indent=2, ensure_ascii=False) + '\n')
        documents[sidecar_path] = replayed
        rebind()
    for manifest, base in ((target/'pin/manifest.json', target/'pin'), (target/'manifest.json', target)):
        value = read(manifest)
        value['files'] = {name: sha256((base/name).read_bytes()).hexdigest() for name in value['files']}
        manifest.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    return target


# Native candidates ----------------------------------------------------------

def baskets_of(world_dir):
    from environments.website_world.simulated_order_publication import basket_context
    world_dir = Path(world_dir)
    world = read(world_dir/'pin/world.private.json')
    return world, basket_context(world, read(world_dir/'basket-plan.private.json'),
        read(world_dir/'checkout-domain.private.json'), read(world_dir/'delivery-plan.private.json'))


def candidates(world_dir, generated):
    """Every in-stock offer matching the winner's predicates, with native delivered totals."""
    from environments.website_world import feature_offer_task as oracle
    from environments.website_world import simulated_order_task as ordering
    world_dir = Path(world_dir)
    world, baskets = baskets_of(world_dir)
    inventory = oracle.FieldInventory(generated['concept'])
    surrounding = read(world_dir/'surrounding.private.json')
    saved = read(generated['oracle_task'])
    spec = {k: saved[k] for k in ('kind', 'concept_id', 'availability', 'predicates')}
    task = oracle.make(world, spec, inventory=inventory, surrounding=surrounding)
    reference = oracle.reference(world, task, inventory=inventory, surrounding=surrounding)
    rows = []
    for row in reference['candidates']:
        if row.get('availability') != 'in_stock':
            continue
        spec = {**generated['order_spec'], 'retailer_id': row['retailer_id'], 'offer_id': row['offer_id']}
        native = ordering.reference(baskets, ordering.make(baskets, spec))
        if native['status'] != 'ready':
            continue
        rows.append({**row, 'home_shipping_minor': native['minimum_shipping_minor'],
                     'delivered_minor': row['price_minor'] + native['minimum_shipping_minor']})
    return {'reference_winners': [w['offer_id'] for w in reference['winners']], 'rows': rows,
            'task': task, 'reference': reference}


def rows_of(found):
    return {r['offer_id']: {k: r[k] for k in r if k not in ('evidence',)} for r in found['rows']}


def unique_min(rows, key):
    if not rows:
        return None
    best = min(r[key] for r in rows)
    winners = [r for r in rows if r[key] == best]
    return winners[0] if len(winners) == 1 else None


def size_field(world, offer):
    sku = next(s for p in world['products'] for s in p['public']['skus'] if s['sku_id'] == offer['sku_id'])
    for name in ('size_eu', 'size_label'):
        if name in sku:
            return name, sku[name]
    raise ValueError('Winner has no size axis')


# Plans ----------------------------------------------------------------------

def plan(generated, base, output):
    """Witness for one base pattern on one generated world, cached beside the world."""
    world_dir = Path(generated['world_dir'])
    cache = world_dir/f'answer-{base}.json'
    if cache.exists():
        return read(cache)
    clean = candidates(world_dir, generated)
    home = next(a for a in read(world_dir/'pin/world.private.json')['address_context']['addresses']
                if a['address_id'] == 'user-home')
    result = {'postcode': home['address']['postcode'], 'schema': 'hindrance-answer-plan-v1', 'base': base, 'seed': generated['seed'],
              'concept': generated['concept'], 'clean_world_dir': str(world_dir),
              'clean_candidates': [{k: r[k] for k in ('offer_id', 'retailer_id', 'product_id', 'price_minor',
                  'home_shipping_minor', 'delivered_minor')} for r in clean['rows']]}
    try:
        result.update(globals()['_plan_' + base](generated, clean, Path(output)))
        result['status'] = 'ready'
    except Skip as reason:
        result.update(status='skipped', reason=str(reason))
    save(cache, result)
    return result


class Skip(Exception):
    pass


def _plan_size_price_step(generated, clean, output):
    if not generated['concept'].startswith('footwear.'):
        raise Skip('size is a separate listing for this concept; size selection on the product page is required')
    rows = sorted(clean['rows'], key=lambda r: (r['price_minor'], r['offer_id']))
    winner = unique_min(rows, 'price_minor')
    if winner is None or winner['offer_id'] != generated['winner']['offer_id']:
        raise Skip('clean native item-price winner is not unique')
    others = [r for r in rows if r['offer_id'] != winner['offer_id'] and
              (r['retailer_id'], r['product_id']) != (winner['retailer_id'], winner['product_id'])]
    runner = unique_min(others, 'price_minor')
    if runner is None:
        raise Skip('no unique runner-up offer at another model or shop')
    if runner['price_minor'] > winner['price_minor'] * 1.35:
        raise Skip(f'runner-up {sek(runner["price_minor"])} is more than 35% above {sek(winner["price_minor"])}')
    stepped = nice_above(runner['price_minor'], max(1000, runner['price_minor'] // 25))
    world = read(Path(generated['world_dir'])/'pin/world.private.json')
    field, size = size_field(world, winner)
    skus = {s['sku_id'] for p in world['products'] if p['public']['product_id'] == winner['product_id']
            for s in p['public']['skus'] if s.get(field) == size}
    def mutate(value):
        retailer = next(r for r in value['retailers'] if r['retailer_id'] == winner['retailer_id'])
        for offer in retailer['offers']:
            if offer['sku_id'] in skus:
                offer['price_minor'] = stepped
    derived = derive_world(generated['world_dir'],
        output/'worlds'/f'{generated["seed"]}-{generated["concept"]}--size_price_step', mutate)
    trapped = candidates(derived, {**generated, 'world_dir': str(derived)})
    truth = unique_min(trapped['rows'], 'price_minor')
    if truth is None or truth['offer_id'] != runner['offer_id'] or trapped['reference_winners'] != [runner['offer_id']]:
        raise Skip('derived world does not make the runner-up the unique native winner')
    base_prices = sorted({o['price_minor'] for r in world['retailers'] if r['retailer_id'] == winner['retailer_id']
                          for o in r['offers'] if o['product_id'] == winner['product_id'] and o['sku_id'] not in skus})
    if not base_prices or base_prices[0] > winner['price_minor']:
        raise Skip('the model has no other size at the base price')
    return {'trapped_world_dir': str(derived), 'true_winner': truth, 'apparent_winner': rows_of(trapped)[winner['offer_id']],
        'trapped_candidates': list(rows_of(trapped).values()), 'clean_winner': winner, 'size_field': field, 'size': size, 'stepped_price_minor': stepped,
        'base_price_minor': winner['price_minor'], 'stepped_sku_ids': sorted(skus),
        'witness': f'Listings/comparison show the model from {sek(winner["price_minor"])}; size {size} costs '
                   f'{sek(stepped)} once selected, above {truth["retailer_id"]} at {sek(truth["price_minor"])}.'}


def _plan_remote_area_surcharge(generated, clean, output):
    rows = clean['rows']
    winner = unique_min(rows, 'delivered_minor')
    item = unique_min(rows, 'price_minor')
    if winner is None or item is None or winner['offer_id'] != item['offer_id']:
        raise Skip('item-price winner is not the unique delivered-cheapest offer in the clean world')
    others = [r for r in rows if r['retailer_id'] != winner['retailer_id']]
    runner = unique_min(others, 'delivered_minor')
    if runner is None:
        raise Skip('no unique delivered runner-up at another shop')
    gap = runner['delivered_minor'] - winner['delivered_minor']
    surcharge = next((x for x in SURCHARGES if x > gap + 1000), None)
    if surcharge is None:
        raise Skip(f'delivered gap {sek(gap)} exceeds the largest realistic surcharge')
    def mutate(value):
        retailer = next(r for r in value['retailers'] if r['retailer_id'] == winner['retailer_id'])
        for contract in retailer['contracts']:
            contract['home_delta_minor'] += surcharge
    derived = derive_world(generated['world_dir'],
        output/'worlds'/f'{generated["seed"]}-{generated["concept"]}--remote_area_surcharge', mutate)
    trapped = candidates(derived, {**generated, 'world_dir': str(derived)})
    rows2 = {r['offer_id']: r for r in trapped['rows']}
    if rows2.get(winner['offer_id'], {}).get('home_shipping_minor') != winner['home_shipping_minor'] + surcharge:
        raise Skip('surcharge is waived or not applied to the cheapest home delivery')
    truth = unique_min(trapped['rows'], 'delivered_minor')
    if truth is None or truth['offer_id'] != runner['offer_id']:
        raise Skip('derived world does not make the runner-up the unique delivered-cheapest offer')
    return {'trapped_world_dir': str(derived), 'true_winner': truth, 'apparent_winner': rows2[winner['offer_id']],
        'trapped_candidates': list(rows_of(trapped).values()), 'clean_winner': winner, 'surcharge_minor': surcharge,
        'witness': f'{winner["retailer_id"]} lists the item at {sek(winner["price_minor"])} (cheapest), but home delivery '
                   f'costs {sek(winner["home_shipping_minor"] + surcharge)} incl. a {sek(surcharge)} remote-area surcharge: '
                   f'{sek(winner["delivered_minor"] + surcharge)} delivered vs {sek(truth["delivered_minor"])} at {truth["retailer_id"]}.'}


def _plan_stale_comparison(generated, clean, output):
    rows = clean['rows']
    winner = unique_min(rows, 'price_minor')
    if winner is None or winner['offer_id'] != generated['winner']['offer_id']:
        raise Skip('clean native item-price winner is not unique')
    sidecar = read(Path(generated['world_dir'])/'surrounding.private.json')
    matching = {(r['product_id'], r['retailer_id']): r for r in rows}
    options = []
    for site in sidecar['sites']:
        if site['kind'] != 'aggregator':
            continue
        listed = [l for l in site['listings'] if (l['product_id'], l['retailer_id']) in matching]
        for listing in listed:
            row = matching[(listing['product_id'], listing['retailer_id'])]
            if row['offer_id'] == winner['offer_id'] or row['retailer_id'] == winner['retailer_id']:
                continue
            if row['price_minor'] <= winner['price_minor'] or listing['price_minor'] <= winner['price_minor']:
                continue
            floor = min([winner['price_minor'], *(l['price_minor'] for l in listed)])
            stale = nice_below(floor, max(1000, floor // 20))
            if stale <= 0 or listing['price_minor'] > stale * 1.5:
                continue
            options.append((row['price_minor'], site['site_id'], listing, row, stale))
    if not options:
        raise Skip('no comparison-listed matching offer above the winner within a realistic stale drop')
    _, site_id, listing, row, stale = min(options, key=lambda o: (o[0], o[1], o[3]['offer_id']))
    site = next(s for s in sidecar['sites'] if s['site_id'] == site_id)
    return {'trapped_world_dir': str(generated['world_dir']), 'true_winner': winner, 'apparent_winner': row,
        'trapped_candidates': clean['rows'], 'clean_winner': winner, 'site_id': site_id, 'site_name': site['name'], 'product_id': listing['product_id'],
        'retailer_id': listing['retailer_id'], 'listed_price_minor': listing['price_minor'],
        'stale_price_minor': stale, 'stale_days': STALE_DAYS,
        'witness': f'{site["name"]} lists {listing["retailer_id"]} at {sek(stale)} (stale; the shop charges '
                   f'{sek(row["price_minor"])}), below the true cheapest {sek(winner["price_minor"])} at {winner["retailer_id"]}.'}


# Runtime overlays -----------------------------------------------------------

def scenario_for(recipe):
    """ScenarioRuntime settings and page pieces for a trapped recipe, or (None, None)."""
    answer, mechanism = recipe['answer'], recipe['mechanism']
    base, level = base_of(mechanism), level_of(mechanism)
    if recipe['clean'] or base == 'stale_comparison' or base == 'size_price_step' and level == 'heavy':
        return None, None
    apparent = answer['apparent_winner']
    presentation = {'execution': mechanism, 'offer_id': apparent['offer_id']}
    if base == 'size_price_step':
        presentation.update(size=str(answer['size']), stepped_minor=answer['stepped_price_minor'],
                            base_minor=answer['base_price_minor'], field=answer['size_field'])
    else:
        presentation.update(surcharge_minor=answer['surcharge_minor'], product_note=level == 'light',
                            postcode=answer['postcode'])
    settings = {'retailer_id': apparent['retailer_id'], 'presentation': presentation}
    return settings, {'answer-hindrance.js': PIECE.read_bytes()}


def apply_comparison(runtime, recipe):
    """Show the stale price on the comparison site's views (trapped stale_comparison only)."""
    answer = recipe['answer']
    views = runtime.surrounding_views[answer['site_id']]
    stale = answer['stale_price_minor']
    from environments.website_world.comparison_pages import money
    shown = 0
    for design in views.views.values():
        for item in design.items:
            if item['id'] != answer['product_id']:
                continue
            for row in item['listings']:
                if row['retailer_id'] == answer['retailer_id']:
                    row['advertised_price_minor'] = stale
                    shown += 1
        if level_of(recipe['mechanism']) == 'light':
            original = design.render
            note = f' (price last checked {answer["stale_days"]} days ago; it may have changed)'
            def render(route, query, raw='', original=original):
                status, body = original(route, query, raw)
                return status, body.replace(money(stale), money(stale) + note)
            design.render = render
    if not shown:
        raise ValueError('Stale comparison row is not mounted')


def sources():
    return {str(Path(__file__).resolve()): sha256(Path(__file__).read_bytes()).hexdigest(),
            str(PIECE.resolve()): sha256(PIECE.read_bytes()).hexdigest()}
