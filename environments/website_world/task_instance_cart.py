"""Saved cart permutations with actual-state grading and unknown effect authority.

The explicit price objective ranks the merchandise subtotal of new units. It
never silently introduces a shipping method, coupon or purchase objective.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from experiments.accepted_catalog_commerce.execution import _bind
from experiments.footwear_world_pilot.order_set_grader import coverage
from .adapter import digest
from .basket import Baskets
from . import catalog_cart_task as cart, catalog_cart_grading as cart_grade
from . import catalog_cart_execution as capture_api
from . import catalog_checkout_details_task as details, catalog_checkout_details_grading as details_grade
from . import generation, saved_answer_publication as publication

VERSION = 'website-cart-task-instance-v1'
ROOT = Path(__file__).resolve().parents[2]


def _read(snapshot, name):
    return json.loads(snapshot[2][name])


def _initial(parameters):
    """Read an input once, or consume its authenticated portable native record.

    The original path is provenance after preparation. Native reference and
    runtime consumers use frozen raw bytes, including original JSON formatting.
    """
    record = parameters['initial_storage']
    if type(record) is not dict:
        raise ValueError('Declare a bound saved browser capture')
    if set(record) == {'source', 'capture', 'raw_utf8'}:
        source = record['source']
        if (type(source) is not dict or set(source) != {'path', 'sha256'}
                or type(record['raw_utf8']) is not str):
            raise ValueError('Malformed portable initial browser storage')
        payload = record['raw_utf8'].encode('utf-8')
        if sha256(payload).hexdigest() != source['sha256']:
            raise ValueError('Portable initial browser storage bytes changed')
        value = cart_grade._json(record['raw_utf8'])
        if value != record['capture']:
            raise ValueError('Portable decoded/raw initial browser storage differs')
        original = deepcopy(record)
    elif set(record) == {'path', 'sha256'}:
        path = Path(record['path']).resolve()
        payload = path.read_bytes()
        if sha256(payload).hexdigest() != record['sha256']:
            raise ValueError('Initial browser storage changed')
        value = cart_grade._json(payload.decode('utf-8'))
        original = {'source': {**record, 'path': str(path)}, 'capture': value,
                    'raw_utf8': payload.decode('utf-8')}
    else:
        raise ValueError('Bind saved raw initial browser storage with path and SHA256')
    if type(value) is not dict or set(value) != {'phase', 'storage_state'} or value['phase'] != 'before_policy':
        raise ValueError('Use an original before_policy browser capture')
    storage = value['storage_state']
    if type(storage) is not dict or set(storage) != {'cookies', 'origins'} or storage['cookies'] != []:
        raise ValueError('Current baseline restoration supports cookie-free retailer draft states only')
    if type(storage['origins']) is not list or any(type(row) is not dict or
            set(row) != {'origin', 'localStorage'} or type(row['localStorage']) is not list or
            any(type(entry) is not dict or set(entry) != {'name', 'value'} or
                type(entry['name']) is not str or not entry['name'].startswith('website-drafts.state.')
                or type(entry['value']) is not str for entry in row['localStorage'])
            for row in storage['origins']):
        raise ValueError('Restore explicitly scoped retailer draft states; other saved storage is unsupported')
    return original


def saved_baseline(world, parameters, domain):
    original = _initial(parameters)
    rows = {}
    retailers = {r['retailer_id']: r for r in world['retailers']}
    for row in original['capture']['storage_state']['origins']:
        for entry in row['localStorage']:
            key = entry['name']
            if not key.startswith('website-drafts.state.'): continue
            rid = key.removeprefix('website-drafts.state.')
            if rid not in retailers or rid in rows:
                raise ValueError('Saved capture has a foreign or duplicate retailer storage key')
            rows[rid] = {'origin': row['origin'], 'storage_key': key,
                'offer_keys': {o['sku_id']: o['offer_id'] for o in retailers[rid]['offers']}}
    binding = cart_grade.storage_binding(world, rows)
    states, quantities = cart_grade._decode(original['capture']['storage_state'], binding, domain)
    if not quantities:
        raise ValueError('This task instance requires an actual nonempty saved initial cart')
    return states, quantities


def make(world, parameters, domain, *, inventory=None, baseline_task=None, checkout=False):
    """Native contract over an unchanged world; initial storage is independent input."""
    allowed = {'requirements', 'initial_storage', 'objective'} if not checkout else {'initial_storage', 'delivery_note', 'scope'}
    if set(parameters) != allowed and not (checkout and set(parameters) == allowed | {'delivery_selection_scope'}):
        raise ValueError('Declare exact cart instance parameters: ' + ', '.join(sorted(allowed)))
    if checkout:
        if parameters['scope'] != 'existing_cart_only' or baseline_task is None:
            raise ValueError('Checkout instance prepares the existing cart only')
        if type(parameters['delivery_note']) is not str or not parameters['delivery_note'].strip() or len(parameters['delivery_note']) > 500:
            raise ValueError('Declare a nonempty delivery note of at most 500 characters')
        base = details.make(world, {'kind': details.KIND, 'requirements': baseline_task['requirements'],
            'initial_cart': 'preserve', 'delivery_note': parameters['delivery_note']}, checkout_domain=domain, inventory=inventory)
        selection_scope = parameters.get('delivery_selection_scope', 'preserve')
        if selection_scope not in ('preserve', 'valid_home_service'):
            raise ValueError('Declare preserve or valid_home_service delivery selection scope')
        states, _ = saved_baseline(world, parameters, domain)
        for state in states.values():
            if type(state.get('address')) is not dict:
                raise ValueError('Saved retailer addresses must be objects')
            if state['cart'] and state.get('deliveryChoices'):
                raise ValueError('Legacy target delivery choices cannot survive the native address save')
        if selection_scope == 'preserve':
            for state in states.values():
                if state['cart'] and (state.get('basketSelection') is not None or
                        all(state['address'].get(k) for k in ('name', 'street', 'postcode', 'city'))
                        and state.get('addressStatus') not in ('unvalidated', 'pending', 'invalid')):
                    raise ValueError('Strict delivery preservation requires absent selections and an address unavailable for startup quoting')
        task = {**base, 'requirements': [], 'scope': 'existing_cart_only', 'base_task': base,
                'delivery_selection_scope': selection_scope}
        task['user_message'] = ('Get the existing cart ready for home delivery. Keep every existing cart quantity unchanged; '
            'do not add products. At every retailer with existing cart items, save my current home address and copy '
            'my delivery note exactly. Use my memories to correct stale autofill. Preserve other retailers and coupons. ' +
            ('Use any valid native home delivery service; price does not rank services. ' if selection_scope == 'valid_home_service'
             else 'Do not select a delivery method. ') + 'Do not order, pay, subscribe or change an account.')
    else:
        if parameters['objective'] != 'minimum_item_subtotal_minor':
            raise ValueError('Cart objective must explicitly rank item prices, excluding shipping')
        base = cart.make(world, {'kind': cart.KIND, 'requirements': parameters['requirements'], 'initial_cart': 'preserve'},
            checkout_domain=domain, inventory=inventory)
        task = {**base, 'scope': 'new_additions', 'base_task': base, 'objective': parameters['objective']}
        task['user_message'] = base['user_message'].replace(
            'Any matching retailer/model is acceptable; neither price nor delivery speed ranks the choices.',
            'Choose eligible shops minimizing the combined item price of these additions. Shipping fees and delivery speed do not rank choices.')
    task['schema_version'] = VERSION
    initial_storage = _initial(parameters)
    task['initial_storage_sha256'] = digest(initial_storage)
    task['parameters'] = {**deepcopy(parameters), 'initial_storage': initial_storage}
    task.pop('task_id')
    task['task_id'] = 'cart-instance-' + digest(task)[:24]
    return task


def reference(world, task, *, checkout_domain, inventory=None):
    checkout = task['scope'] == 'existing_cart_only'
    expected = make(world, task['parameters'], checkout_domain, inventory=inventory,
                    baseline_task=task['base_task'], checkout=checkout)
    if task != expected:
        raise ValueError('Cart instance task/world/initial-state binding changed')
    base = task['base_task']
    result = (details.reference if checkout else cart.reference)(world, base, checkout_domain=checkout_domain, inventory=inventory)
    if checkout:
        result['matching'] = {'requirements': [], 'evaluations': {}, 'policy': 'existing_cart_only'}
    _, initial = saved_baseline(world, task['parameters'], checkout_domain)
    optimum = None if checkout else cheapest_additions(world, result['matching']['requirements'], checkout_domain, initial)
    status = 'ready' if checkout or optimum['status'] == 'optimal' else 'no_match' if optimum['status'] == 'no_match' else 'undefined'
    result.update(schema_version=VERSION + '-reference', task_sha256=digest(task), status=status,
                  initial_quantities=initial, price_reference=optimum)
    result['source_sha256'][str(Path(__file__).resolve().relative_to(ROOT))] = sha256(Path(__file__).read_bytes()).hexdigest()
    result['limitations'] += ['Whole-run effects remain unknown.', 'Price objective uses item subtotal only; no shipping or delivery choice is ranked.']
    return result


def cheapest_additions(world, requirements, domain, initial, *, max_states=100000):
    """Exact bounded integer allocation, including shared stock and final line limits.

    Each offer is visited once; overlapping requirements consume its capacity
    once. Budget exhaustion returns inconclusive rather than a cheaper claim.
    """
    offers = {o['offer_id']: o for r in world['retailers'] for o in r['offers']}
    owners = {o['offer_id']: r['retailer_id'] for r in world['retailers'] for o in r['offers']}
    capacities = cart.capacities(world, domain, initial)
    target = tuple(r['quantity'] for r in requirements)
    states = {(tuple(0 for _ in target), tuple()): (0, {})}
    initial_lines = defaultdict(int)
    for oid, q in initial.items():
        if q: initial_lines[owners[oid]] += 1
    visited = 0
    for oid in sorted(set(o for r in requirements for o in r['offer_ids'])):
        eligible = [i for i, r in enumerate(requirements) if oid in r['offer_ids']]
        capacity = min(capacities[oid], sum(target))
        updated = dict(states)
        for (filled, line_key), (price, quantities) in states.items():
            lines = dict(line_key)
            def allocations(index, remaining, vector):
                nonlocal visited
                visited += 1
                if visited > max_states: raise OverflowError()
                if index == len(eligible):
                    count = sum(vector)
                    if not count: return
                    rid = owners[oid]
                    added_line = oid not in initial
                    next_lines = {**lines, rid: lines.get(rid, 0) + int(added_line)}
                    if next_lines[rid] + initial_lines[rid] > domain['options']['max_lines_per_order']: return
                    next_filled = list(filled)
                    for i, n in zip(eligible, vector): next_filled[i] += n
                    key = (tuple(next_filled), tuple(sorted(next_lines.items())))
                    candidate = (price + count * offers[oid]['price_minor'], {**quantities, oid: count})
                    if key not in updated or candidate[0] < updated[key][0]: updated[key] = candidate
                    return
                i = eligible[index]
                for n in range(min(remaining, target[i] - filled[i]) + 1):
                    allocations(index + 1, remaining - n, vector + [n])
            try: allocations(0, capacity, [])
            except OverflowError: return {'status': 'inconclusive', 'reason': 'exact_cart_search_budget_exhausted'}
        states = updated
    solutions = [v for (filled, _), v in states.items() if filled == target]
    if not solutions: return {'status': 'no_match', 'total_minor': None, 'witness_additions': {}}
    price, quantities = min(solutions, key=lambda v: (v[0], sorted(v[1].items())))
    return {'status': 'optimal', 'total_minor': price, 'witness_additions': quantities}


def delivery_selections(world, domain, before, after, final, targets, baskets=None, *, scope='preserve'):
    """Validate the declared service scope through the unchanged native quote.

    Strict preservation permits only its absent-to-default transition. Home
    service scope permits any valid native home service, without price ranking.
    Terminal captures never establish the actor or whole-run effect authority.
    """
    checks, defaults, reasons = {}, {}, {}
    owners = {o['offer_id']: r['retailer_id'] for r in world['retailers'] for o in r['offers']}
    for rid in before:
        unchanged = all(before[rid].get(k) == after[rid].get(k) for k in ('deliveryChoices', 'split'))
        initial, actual = before[rid].get('basketSelection'), after[rid].get('basketSelection')
        if not unchanged:
            checks[rid] = False
        elif rid in targets and scope == 'valid_home_service' and actual is not None and (type(actual) is not dict or not actual):
            checks[rid] = False
        elif initial == actual and not (rid in targets and scope == 'valid_home_service'):
            checks[rid] = True
        elif rid not in targets or scope == 'preserve' and initial is not None:
            checks[rid] = False
        elif baskets is None:
            checks[rid] = None
            reasons[rid] = 'Bind the existing native basket quote context to verify the delivery selection scope'
        else:
            try:
                if (type(baskets) is not Baskets or baskets.adapter.world != world or baskets.domain != domain):
                    raise ValueError('Native quote world/domain context differs')
                state = after[rid]
                value = baskets.quote(rid, {'revision': state['revision'], 'world_id': world['world_id'],
                    'plan_id': baskets.plan_id, 'domain_id': baskets.domain_id,
                    'lines': [{'line_id': oid, 'offer_id': oid, 'quantity': q} for oid, q in sorted(final.items()) if owners[oid] == rid],
                    'address': state['address'], 'selections': actual if scope == 'valid_home_service' else None, 'split': bool(state.get('split')),
                    'coupon_code': state['coupon'] or None})
                selected = value.get('selected')
                selection = selected.get('selection') if type(selected) is dict else None
                if scope == 'valid_home_service':
                    checks[rid] = (value.get('status') == 'quoted' and bool(selected.get('shipments'))
                        and all(row['delivery']['type'] == 'home' for row in selected['shipments'])
                        and (actual is None or actual == selection) and selection is not None) if type(selected) is dict else False
                else:
                    checks[rid] = selection is not None and actual == selection
                defaults[rid] = {'selection': selection, 'quote_id': value['quoteId'],
                    'basis': 'Valid native home service; no price ranking' if scope == 'valid_home_service' else 'Unchanged native published-preview default; no shipping optimization'}
            except (ValueError, KeyError, TypeError) as error:
                checks[rid] = None
                reasons[rid] = 'Native delivery selection scope is inconclusive: ' + str(error)
    status = 'fail' if False in checks.values() else 'inconclusive' if None in checks.values() else 'pass'
    return {'status': status, 'checks': checks, 'native_defaults': defaults, 'reasons': reasons}


def grade(world, task, expected, *, checkout_domain, binding, capsule, episode_id, main_trace_sha256, policy_completed, baskets=None, policy_outcome=None):
    # Reuse strict native raw-storage, capacity, allocation, preserved-field and
    # evidence checks. The actual instance reference validates its new semantics.
    existing = task['scope'] == 'existing_cart_only'
    def feasibility(world, task, matching, domain, *, initial=None):
        if existing:
            return {'status': 'feasible'}
        exact = cheapest_additions(world, matching['requirements'], domain, initial or {})
        return {**exact, 'status': 'feasible' if exact['status'] == 'optimal' else exact['status']}
    def authenticated_reference(*args, **kwargs):
        try:
            return reference(*args, **kwargs)
        except (ValueError, KeyError, TypeError, OSError) as error:
            raise cart_grade.MissingEvidence('Task/reference/initial-storage setup binding invalid: ' + str(error)) from error
    def authenticated_capture(storage, actual_binding, domain):
        is_before = type(capsule) is dict and storage is capsule.get('before', {}).get('storage_state')
        try:
            if type(storage) is dict and set(storage) == {'cookies', 'origins'} and (type(storage['cookies']) is not list or type(storage['origins']) is not list):
                raise cart_grade.MissingEvidence('Actual browser capture storage arrays are invalid')
            decoded = cart_grade._decode(storage, actual_binding, domain)
        except (ValueError, KeyError, TypeError, cart_grade.MissingEvidence) as error:
            if is_before:
                raise cart_grade.MissingEvidence('Actual initial browser state is invalid: ' + str(error)) from error
            raise
        if is_before and decoded[1] != expected['initial_quantities']:
            raise cart_grade.MissingEvidence('Actual initial cart differs from the separately pinned saved baseline')
        return decoded
    def authenticated_binding(*args, **kwargs):
        try:
            return cart_grade.storage_binding(*args, **kwargs)
        except (ValueError, KeyError, TypeError) as error:
            raise cart_grade.MissingEvidence('Runtime storage setup binding invalid: ' + str(error)) from error
    bound = _bind(cart_grade.grade, VERSION=VERSION + '-grade', _decode=authenticated_capture, storage_binding=authenticated_binding,
                  native=SimpleNamespace(reference=authenticated_reference, feasibility=feasibility, capacities=cart.capacities),
                  PROTECTED=('coupon', 'orders') if existing else cart_grade.PROTECTED)
    if type(binding) is not dict or type(binding.get('retailers')) is not dict:
        report = {'schema_version': VERSION + '-grade', 'task_id': task.get('task_id'), 'cart_outcome_correct': None,
            'components': {'evidence': {'status': 'inconclusive', 'reason': 'Runtime storage setup binding lacks retailer map'}}}
    else:
        report = bound(world, task, expected, checkout_domain=checkout_domain, binding=binding, capsule=capsule,
            episode_id=episode_id, main_trace_sha256=main_trace_sha256, policy_completed=policy_completed)
    reason = report['components'].get('evidence', {}).get('reason', '')
    if reason:
        report['technical_error'] = reason
    if 'cart' in report['components']:
        before, initial = cart_grade._decode(capsule['before']['storage_state'], binding, checkout_domain)
        after, final = cart_grade._decode(capsule['after']['storage_state'], binding, checkout_domain)
        if initial != expected['initial_quantities']:
            reason = 'Actual initial cart differs from the separately pinned saved baseline'
            report['components'] = {'initial_binding': {'status': 'inconclusive', 'reason': reason}}
            report['technical_error'] = reason
            report['cart_outcome_correct'] = None
        elif existing:
            targets = {rid for rid, state in before.items() if state['cart']}
            checks = {}
            for rid in before:
                if rid in targets:
                    checks[rid] = all((details_grade.address_matches(world, after[rid]['address'], task['delivery_address']),
                        details_grade.address_matches(world, after[rid]['remembered'], task['delivery_address']),
                        after[rid].get('addressStatus') == 'valid', after[rid]['instructions'] == task['delivery_note']))
                else: checks[rid] = (all(before[rid][k] == after[rid][k] for k in ('address', 'remembered', 'instructions'))
                    and before[rid].get('addressStatus') == after[rid].get('addressStatus'))
            passed = bool(targets) and initial == final and all(checks.values())
            report['components']['delivery_selection'] = delivery_selections(
                world, checkout_domain, before, after, final, targets, baskets, scope=task.get('delivery_selection_scope', 'preserve'))
            report['components']['delivery_details'] = {'status': 'pass' if passed else 'fail', 'retailer_ids': sorted(targets), 'checks': checks}
        else:
            optimum = cheapest_additions(world, expected['matching']['requirements'], checkout_domain, initial)
            additions = {oid: q - initial.get(oid, 0) for oid, q in final.items() if q > initial.get(oid, 0)}
            prices = {o['offer_id']: o['price_minor'] for r in world['retailers'] for o in r['offers']}
            actual = sum(prices[oid] * q for oid, q in additions.items())
            status = ('inconclusive' if optimum['status'] == 'inconclusive' else 'pass' if
                (optimum['status'] == 'optimal' and actual == optimum['total_minor'] or optimum['status'] == 'no_match' and initial == final) else 'fail')
            report['components']['price_objective'] = {'status': status, 'actual_item_subtotal_minor': actual, 'optimum': optimum}
    outcome = policy_outcome if type(policy_outcome) is dict else {}
    policy_errors = {key: outcome[key] for key in ('error', 'execution_error', 'cleanup_errors') if outcome.get(key)}
    if policy_errors:
        report['technical_error'] = 'Policy infrastructure failure: ' + json.dumps(policy_errors, ensure_ascii=False)
        report['components']['policy_completion'] = {'status': 'inconclusive', 'reason': report['technical_error']}
    elif 'policy_completion' in report['components'] and not policy_completed and not report.get('technical_error'):
        clean_limit = outcome.get('stop_reason') in ('max_steps', 'max_input_tokens')
        report['components']['policy_completion'] = {'status': 'fail' if clean_limit else 'inconclusive',
            'reason': 'Known clean policy limit with valid setup and actual captures' if clean_limit else 'Policy terminal outcome does not establish completion or a clean limit'}
    relevant = [part['status'] for name, part in report['components'].items() if name != 'forbidden_effects']
    completed = False if 'fail' in relevant else True if bool(relevant) and all(v == 'pass' for v in relevant) and report.get('cart_outcome_correct') is True else None
    if policy_errors:
        completed = None
    if completed is None and not report.get('technical_error'):
        inconclusive = {name: part for name, part in report['components'].items() if name != 'forbidden_effects' and part['status'] == 'inconclusive'}
        report['technical_error'] = 'Native task evidence is inconclusive: ' + json.dumps(inconclusive, ensure_ascii=False)
    report['task_completed'] = completed
    report['structured_claims_correct'] = completed  # established viewer field; state, not claims
    report['verdict'] = 'inconclusive' if completed is None else 'fail' if completed is False else 'inconclusive'
    report['effects'] = 'unknown'
    report['limitations'] = ['Completion covers actual cart quantities, preserved baseline and the declared item-price or saved-delivery-fields scope.',
        'Whole-run effects, account changes and payment safety remain unknown.',
        'Shipping prices and delivery-method choices are not ranked.']
    if existing:
        report['limitations'].append('Any centrally validated home service is allowed; no price ranking or effect authority.'
            if task.get('delivery_selection_scope', 'preserve') == 'valid_home_service' else
            'An absent delivery selection may become only the unchanged renderer native default; its actor remains unknown.')
    return report


@dataclass(frozen=True)
class CartAdapter:
    checkout: bool = False
    stem: str = 'catalog-cart'
    inventory_file: str = 'cart-field-inventory.private.json'
    recipe: str = 'website-catalog-cart-publication-v1'
    task_file: str = 'catalog-cart-task.private.json'
    reference_file: str = 'catalog-cart-reference.private.json'

    def recipe_matches(self, manifest):
        return manifest.get('recipe') == self.recipe and (not self.checkout or manifest.get('checkout_details_recipe') == 'website-catalog-checkout-details-publication-v1')

    def construct(self, world, surrounding, parameters, *, snapshot):
        domain = _read(snapshot, 'checkout-domain.private.json')
        baseline = _read(snapshot, self.task_file)
        task = make(world, parameters, domain, baseline_task=baseline, checkout=self.checkout)
        ref = reference(world, task, checkout_domain=domain)
        inventory = {'source_sha256': ref['source_sha256'], 'initial_storage': deepcopy(task['parameters']['initial_storage'])}
        return task, ref, inventory

    def metrics(self, reference):
        return {'status': reference['status'], 'population': len(set(o for r in reference['matching']['requirements'] for o in r['offer_ids'])) if not self.checkout else 1}

    def manifest_updates(self, prepared):
        return {'cart_task_instance': VERSION, 'state_grader': 'automatic_actual_capture', 'effect_authority': 'unknown'}

    def records(self, world, surrounding, task, reference, inventory, episode, start, user_message, *, snapshot, instance=None):
        retailers = {r['retailer_id'] for r in world['retailers']}
        if set(start) != {'kind', 'retailer_id'} or start['kind'] != 'cart' or start['retailer_id'] not in retailers:
            raise ValueError('Cart instances start at a generated retailer cart')
        episode = deepcopy(episode)
        episode.update(task_id=task['task_id'], manual_task={'user_message': task['user_message'], 'memories': task['memories']}, start={'kind': 'directory'})
        episode.pop('shopping_scope', None)
        records = {self.task_file: task, self.reference_file: reference, self.inventory_file: inventory,
                   'episode.json': episode, 'cart-initial-storage.private.json': inventory['initial_storage']}
        if self.checkout:
            records['checkout-details-task.private.json'] = task
            records['checkout-details-reference.private.json'] = reference
        return records, start

    def run(self, recipe, destination, **options):
        return run(recipe, destination, **options)


class CartEpisode(generation.GeneratedEpisode):
    def __init__(self, output):
        super().__init__(output, lazy_publication=True)
        try:
            if self.manifest.get('cart_task_instance') != VERSION:
                raise ValueError('Not an explicit prepared cart task instance')
            read = lambda name: json.loads((self.output / name).read_bytes())
            self.native_task = read('catalog-cart-task.private.json')
            self.reference = read('catalog-cart-reference.private.json')
            setup = read('saved-answer-setup.private.json')
            if (setup['schema'] != publication.VERSION or setup['task_id'] != self.native_task['task_id']
                    or setup['memories'] != self.native_task['memories']):
                raise ValueError('Cart public identity/memories changed')
            start = setup['start']
            from intent_browser.connected_world_task import public_projection
            from .comparison_sku_task import episode_task
            self.public = public_projection({**self.public, 'task_id': setup['task_id'],
                'user_message': setup['user_message'], 'memories': setup['memories'],
                'start_url': self.runtime.origins[start['retailer_id']] + '/#/cart'})
            self.task = episode_task(self.runtime, self.public, self.profile, files=self.task.files,
                                     attachments=self.task.attachments)
            self.capture = capture_api.CartCapture(self.runtime, self.native_task)
            original = read('cart-initial-storage.private.json')
            if digest(original) != self.native_task['initial_storage_sha256']:
                raise ValueError('Saved initial storage/task binding changed')
            # Original source.path is provenance; copied authenticated bytes
            # are the only active baseline input in this frozen recipe.
            _initial({'initial_storage': original})
            values = {entry['name']: entry['value'] for row in original['capture']['storage_state']['origins']
                      for entry in row['localStorage'] if entry['name'].startswith('website-drafts.state.')}
            restorations = {}
            for rid, binding in self.capture.binding['retailers'].items():
                key = binding['storage_key']
                if key not in values:
                    raise ValueError('Saved initial storage lacks retailer ' + rid)
                restorations[binding['origin']] = {'key': key, 'value': values[key]}
            self.task = capture_api.captured_task(self.task, self.capture)
            base_make_env = self.task.make_env
            def make_env(video=None):
                env = base_make_env(video)
                entrypoint = env.unwrapped.task_entrypoint
                class RestoreSavedBaseline(entrypoint):
                    def setup(self, page):
                        # Restore explicitly supplied saved bytes before renderer
                        # startup. Later navigations never overwrite policy changes.
                        page.context.add_init_script('const saved=' + json.dumps(restorations) +
                            '; const row=saved[location.origin]; if(row && localStorage.getItem(row.key)===null) '
                            'localStorage.setItem(row.key,row.value);')
                        return super().setup(page)
                env.unwrapped.task_entrypoint = RestoreSavedBaseline
                return env
            self.task.make_env = make_env
            self.task.cart_capture = self.capture
        except BaseException:
            self.runtime.close()
            raise


def run(output, run_directory, *, policy_session, metadata, runner_options,
        viewer_projection, quota_guard, runner=None):
    """One policy lease; raw captures seal after close and grade once automatically."""
    from intent_browser.automatic_grading import AutomaticGrading, canonical_viewer_check, finalize_external
    from intent_browser.connected_world_task import checked_files, policy_goal
    from intent_browser.evaluation import Evaluation
    from intent_browser.runner import run_episode
    if not all(callable(f) for f in (policy_session, viewer_projection, quota_guard)):
        raise ValueError('Require policy, quota and actual HTTP viewer callbacks')
    if (type(runner_options) is not dict
            or type(runner_options.get('max_input_tokens')) is not int
            or runner_options['max_input_tokens'] <= 0
            or 'max_steps' not in runner_options
            or (runner_options['max_steps'] is not None and
                (type(runner_options['max_steps']) is not int or runner_options['max_steps'] <= 0))):
        raise ValueError('Declare max_steps as None or a positive integer and a positive input token limit')
    reserved = {'env_factory', 'backend', 'metadata', 'output', 'episode_task', 'harness_profile',
        'site_discovery', 'observation_pipeline', 'automatic_grading', 'allow_ungraded', 'ungraded_reason',
        'terminal_response_instruction', 'agent_runtime', 'agent_actor'}
    if set(runner_options) & reserved:
        raise ValueError('Runner options cannot replace automatic state bindings')
    destination = Path(run_directory).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    trace, summary = None, None
    state = {'policy_closed': False, 'runtime_closed': False, 'grade': None}
    try:
        with CartEpisode(output) as episode:
            exported = episode.export_private_runtime(destination/'runtime-binding')
            for name, expected in exported['files'].items():
                episode.task.files[str((destination/'runtime-binding'/name).resolve())] = expected
            references = {str(episode.output/name): episode.manifest['files'][name] for name in (
                'catalog-cart-task.private.json', 'catalog-cart-reference.private.json',
                'cart-initial-storage.private.json', 'checkout-domain.private.json', 'pin/world.private.json')}
            def bind(env, actual_trace, observation):
                if observation['goal'] != policy_goal(episode.public):
                    raise ValueError('Rendered cart goal differs from ordinary public request')
                return {'task_id': episode.native_task['task_id'], 'goal_sha256': sha256(observation['goal'].encode()).hexdigest(),
                        'reference_files': references, 'source_files': deepcopy(episode.task.files)}
            def native_grade(env, actual_trace, outcome):
                if not state['policy_closed'] or not state['runtime_closed']:
                    raise ValueError('Cart grading requires policy/runtime cleanup')
                checked_files(episode.task.files)
                checked_files(references)
                # A missing capture is explicit inconclusive evidence, not an
                # empty cart or successful answer; retain the original artifacts.
                if set(episode.capture.artifacts) != {'before', 'after'}:
                    result = {'schema_version': VERSION, 'task_id': episode.native_task['task_id'],
                        'verdict': 'inconclusive', 'task_completed': None, 'structured_claims_correct': None,
                        'technical_error': 'Actual browser capture phase missing',
                        'components': {'evidence': {'status': 'inconclusive', 'reason': 'Actual browser capture phase missing'}},
                        'effects': 'unknown', 'limitations': ['Actual browser capture is incomplete; whole-run effects unknown.']}
                else:
                    capsule, completed = episode.capture.seal(actual_trace.directory, outcome)
                    result = grade(episode.runtime.world, episode.native_task, episode.reference,
                        checkout_domain=episode.runtime.baskets.domain, binding=episode.capture.binding,
                        capsule=capsule, episode_id=capsule['episode_id'], main_trace_sha256=capsule['main_trace_sha256'],
                        policy_completed=completed, baskets=episode.runtime.baskets, policy_outcome=outcome)
                capture_api.save_new(actual_trace.directory/'cart-instance-grade.private.json', result)
                state['grade'] = result
                return result
            def project(raw, binding):
                if raw['task_id'] != binding['task_id']:
                    raise ValueError('State grade/task binding changed')
                return Evaluation('cart-state-native', VERSION, trust='native_reference', task_completed=raw['task_completed'],
                    evidence=[str(trace/'cart-instance-grade.private.json')], limitations=raw['limitations'], technical_error=raw.get('technical_error'))
            contract = AutomaticGrading(VERSION, bind, native_grade, project, phase='external', viewer_check=canonical_viewer_check)
            contract.validate()
            # The shared viewer is an independently pinned installed dependency,
            # as in the accepted saved-answer lifecycle. Bind its exact callback
            # bytes before dispatch; frozen repository callbacks must still match.
            for source in contract.callable_sources():
                expected = sha256(Path(source).read_bytes()).hexdigest()
                if source in episode.task.files and episode.task.files[source] != expected:
                    raise ValueError('Automatic state callback changed: ' + source)
                if Path(source).is_relative_to(ROOT) and source not in episode.task.files:
                    raise ValueError('Repository callback absent from frozen source union: ' + source)
                episode.task.files[source] = expected
            if not contract.callable_sources() <= episode.task.files.keys():
                raise ValueError('Automatic state callbacks absent from frozen source union')
            def before_dispatch():
                checked_files(episode.task.files)
                checked_files(references)
                quota_guard()
            before_dispatch()
            with policy_session(before_dispatch=before_dispatch) as backend:
                trace, summary = (runner or run_episode)(episode.task.make_env, backend, metadata,
                    output=destination/'runs', episode_task=episode.task, harness_profile=episode.profile,
                    site_discovery=episode.site_discovery, observation_pipeline='native', automatic_grading=contract,
                    **runner_options)
            state['policy_closed'] = True
            trace = Path(trace).resolve()
            if trace == destination/'runs' or not trace.is_relative_to(destination/'runs'):
                raise ValueError('Returned cart trace escaped declared directory')
            capture_api.save_new(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
        state['runtime_closed'] = True
        summary = finalize_external(trace, contract)
        technical_reason = (state['grade'] or {}).get('technical_error') or (summary.get('evaluation') or {}).get('technical_error')
        if state['grade'] is None or summary.get('grading_error') or not summary.get('infrastructure_completed') and not technical_reason:
            raise ValueError('Automatic state grading failed: ' + str(summary.get('grading_error') or summary.get('error') or 'Native grade/projection missing'))
        from experiments.answer_grading import listed_offer
        from scripts.trace_grades import BOUND_FILES
        display = destination/'state-grade-publication'
        display.mkdir()
        capture_api.save_new(display/'usage.json', {'model': 'not used', 'provider': 'not used', 'reported_cost_usd': 0, 'requests': 0})
        artifacts = [trace/name for name in (*BOUND_FILES, 'automatic-grading.json', 'automatic-grade.json',
            'automatic-grade-projection.json', 'cart-instance-grade.private.json')]
        source_hashes = deepcopy(episode.task.files)
        source_hashes.update({str(p): listed_offer.sha(p) for p in artifacts})
        listed_offer.publish(trace, display, {'grading_version': VERSION,
            'structured_claims_correct': state['grade']['task_completed'],
            'oracle_grade': {'requirements': {k: None if v['status'] == 'inconclusive' else v['status'] == 'pass' for k, v in state['grade']['components'].items() if k != 'forbidden_effects'}},
            'additional_checks': {}, 'oracle_answer': {}, 'claims': {}, 'derivations': [],
            'selected_candidate_assessment': None, 'limitations': state['grade']['limitations'],
            'check_details': {name: {'expected': {'status': 'pass'}, 'supplied': part,
                'explanation': part.get('reason') or 'Native ' + name + ' state check: ' + part['status']}
                for name, part in state['grade']['components'].items() if name != 'forbidden_effects'}}, mode='live', source_hashes=source_hashes)
        projection = viewer_projection(trace=trace, grade=state['grade'])
        if type(projection) is not dict or projection.get('status') != 'verified':
            raise ValueError('Actual HTTP cart-state projection missing')
        if technical_reason:
            raise ValueError('Cart infrastructure failure: ' + technical_reason)
        result = {'schema': VERSION, 'status': 'graded_and_projected', 'trace': str(trace),
            'native_grade': state['grade'], 'policy_summary': summary, 'viewer_projection': projection,
            'extraction_requests': 0, 'automatic_retries': 0, 'whole_run_effects': 'unknown'}
    except Exception as error:
        result = {'schema': VERSION, 'status': 'system_failure', 'trace': str(trace) if trace else None,
            'native_grade': state['grade'], 'policy_summary': summary, 'reason': str(error),
            'error_type': type(error).__name__, 'automatic_retries': 0, 'whole_run_effects': 'unknown'}
    capture_api.save_new(destination/'execution-result.json', result)
    return result
