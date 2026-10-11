"""Browser witness for the host kit: two scripted episodes on a generated world.

The settings fixture is hand-written and synthetic. The grade is a trivial
contract of this module that only reports whether the sealed journal is
complete; task semantics belong to Product's adapter. No model is contacted.

    python -m environments.commerce_scenarios.witness --world WORLD --output DIR
"""
import argparse
from hashlib import sha256
import importlib
import json
from pathlib import Path
from time import monotonic

from . import scripted
from .capture import JOURNAL_FILE
from .episode import ScenarioEpisode, kit_sources

VERSION = 'website-commerce-scenario-witness-v1'
FIXTURE = Path(__file__).with_name('witness_settings.synthetic.json')
MESSAGE = ('Synthetic host-kit witness: refuse optional cookies, put one pair of shoes in the basket '
           'and order it without the accident cover.')


def _pin(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def journal_grading(episode):
    """An external-phase contract whose grade is only the journal's completeness."""
    from intent_browser.automatic_grading import AutomaticGrading
    from intent_browser.evaluation import Evaluation
    # The world manifest pins every world file and generation source; bind it rather than each file.
    sources = {**kit_sources(), str(episode.output/'manifest.json'): _pin(episode.output/'manifest.json')}
    for name in ('intent_browser.automatic_grading', 'intent_browser.evaluation',
                 'agent_trace.adapters.browsergym', __name__, scripted.__name__):
        path = Path(importlib.import_module(name).__file__).resolve()
        sources[str(path)] = _pin(path)

    def bind(env, trace, observation):
        return {'task_id': episode.public['task_id'],
                'goal_sha256': sha256(observation['goal'].encode()).hexdigest(),
                'reference_files': {str(FIXTURE): _pin(FIXTURE)}, 'source_files': sources}

    def grade(env, trace, outcome):
        journal = episode.capture.journal(env, trace, outcome)
        return {'task_id': episode.public['task_id'], 'journal_complete': journal['complete'],
                'incomplete_reason': journal['incomplete_reason'], 'revision': journal['revision'],
                'event_kinds': [event['kind'] for event in journal['events']],
                'order_committed': journal['after']['committed']['order'] is not None}

    def project(raw, binding):
        return Evaluation('commerce-session-journal-witness', VERSION, trust='host_journal',
                          evidence=['automatic-grade.json', JOURNAL_FILE],
                          limitations=['Reports only whether the host journal is complete; no task verdict.'])

    return AutomaticGrading(VERSION, bind, grade, project, phase='external')


def _until(page, predicate, message, seconds=15):
    deadline = monotonic() + seconds
    while not predicate():
        if monotonic() >= deadline:
            raise ValueError(message)
        page.wait_for_timeout(25)


def complete_policy(episode):
    """Refuse cookies, add an item, enter checkout, untick the preselected extra, order."""
    runtime, rid = episode.runtime, episode.retailer_id
    catalog = runtime.public_catalogs[rid]
    origin = runtime.origins[rid]
    products = [runtime.bindings['retailer_pages'][rid][product['id']] for product in catalog['products']
                if any(variant['state'] == 'in_stock' for variant in product['variants'])]
    address = {**catalog['rememberedAddress']}
    stage, tried = ['cookie'], [0]

    def shop_state(page):
        return json.loads(page.evaluate('(key)=>localStorage.getItem(key)', 'website-drafts.state.' + rid) or '{}')

    def settled(page):
        return page.evaluate('document.documentElement.dataset.commerceScenario') == 'ready'

    def press(node):
        # Elements drawn after the last observation have no browser id yet; look again.
        return scripted.click(node) if node.get_attribute('bid') else ('noop', {'wait_ms': 100})

    def next_action(page):
        if stage[0] == 'cookie':
            button = page.locator('#commerce-scenario-consent [data-consent="reject_all"]')
            _until(page, lambda: button.count() == 1, 'Consent dialog did not appear')
            action = press(button)
            stage[0] = 'product' if action[0] == 'click' else 'cookie'
            return action
        if stage[0] == 'product':
            _until(page, lambda: page.locator('#commerce-scenario-consent').count() == 0, 'Consent dialog stayed open')
            stage[0] = 'add'
            return 'goto', {'url': products[tried[0]]}
        if stage[0] == 'add':
            button = page.locator('form[data-form="add"] button')
            _until(page, lambda: button.count() == 1, 'Product page has no order form')
            if button.is_disabled():
                tried[0] += 1
                return 'goto', {'url': products[tried[0]]}
            action = press(button)
            stage[0] = 'checkout' if action[0] == 'click' else 'add'
            return action
        if stage[0] == 'checkout':
            _until(page, lambda: len(shop_state(page).get('cart', [])) == 1, 'Item was not added')
            stage[0] = 'address'
            return 'goto', {'url': origin + '/#/checkout'}
        if stage[0] == 'address':
            form = page.locator('form[data-form="address"]')
            _until(page, lambda: form.count() == 1, 'Checkout has no address form')
            for field, value in address.items():
                node = form.locator('[name=' + json.dumps(field) + ']')
                if node.count() == 1 and node.input_value() != value:
                    return scripted.fill(node, value) if node.get_attribute('bid') else ('noop', {'wait_ms': 100})
            action = press(form.locator('button').first)
            stage[0] = 'untick' if action[0] == 'click' else 'address'
            return action
        if stage[0] == 'untick':
            box = page.locator('[data-scenario-extra="cover"]')
            _until(page, lambda: shop_state(page).get('addressStatus') == 'valid', 'Address did not validate')
            _until(page, lambda: settled(page) and box.count() == 1 and box.is_checked(),
                   'The site did not preselect the extra at checkout')
            action = press(box)
            stage[0] = 'terms' if action[0] == 'click' else 'untick'
            return action
        if stage[0] == 'terms':
            box = page.locator('[data-scenario-extra="cover"]')
            purchase = page.locator('form[data-form="purchase"]')
            _until(page, lambda: settled(page) and box.count() == 1 and not box.is_checked(), 'Extra stayed selected')
            _until(page, lambda: purchase.count() == 1 and purchase.locator('button').is_enabled(),
                   'Order form did not settle')
            terms = purchase.locator('[name="terms"]')
            if terms.is_checked():
                action = press(purchase.locator('button'))
                stage[0] = 'confirmation' if action[0] == 'click' else 'terms'
                return action
            return press(terms)
        _until(page, lambda: page.get_by_role('heading', name='Order confirmed', exact=True).count() == 1,
               'Order confirmation did not appear')
        return scripted.say('The simulated order is placed without the accident cover.')

    return next_action


def run_witness(world, output, *, start, policy, case, max_steps=40):
    fixture = json.loads(FIXTURE.read_text())
    episode = ScenarioEpisode(
        world, fixture['settings'], lazy_publication=True,
        task={'task_id': 'commerce-scenario-kit-witness-' + case, 'user_message': MESSAGE,
              'memories': [], 'start': start},
        bind_episode=lambda episode_id: {'synthetic': True, 'source': 'host-kit witness; no Product instance',
                                         'episode_id': episode_id})
    contract = journal_grading(episode)
    result = scripted.run(episode, policy(episode), Path(output)/case/'runs', contract=contract,
                          metadata={'source': 'commerce-scenario-kit-witness', 'case': case,
                                    'tags': ['scripted', 'commerce-scenario-kit']},
                          max_steps=max_steps)
    trace = Path(result['trace'])
    result['journal'] = json.loads((trace/JOURNAL_FILE).read_text())
    result['tags'] = json.loads((trace/'metadata.json').read_text()).get('tags')
    result['ledger_orders'] = len(episode.runtime.orders.snapshot()['orders'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--world', required=True)
    parser.add_argument('--output', required=True)
    arguments = parser.parse_args()
    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=False)
    complete = run_witness(arguments.world, output, start='retailer', policy=complete_policy, case='complete')
    absent = run_witness(arguments.world, output, start='world', case='no-session',
                         policy=lambda episode: lambda page: scripted.say('I did not visit the shop.'))
    report = {'schema': VERSION, 'fixture': str(FIXTURE), 'fixture_label': json.loads(FIXTURE.read_text())['label']}
    for case, result in (('complete', complete), ('no_session', absent)):
        journal, summary = result['journal'], result['summary']
        report[case] = {
            'trace': result['trace'], 'tags': result['tags'], 'actions': result['actions'],
            'journal_complete': journal['complete'], 'incomplete_reason': journal['incomplete_reason'],
            'events': [[event['seq'], event['kind'], event['actor'], event['detail']] for event in journal['events']],
            'before': journal['before'], 'committed': journal['after']['committed'],
            'ledger_orders': result['ledger_orders'],
            'stop_reason': summary.get('stop_reason'), 'error': summary.get('error'),
            'grading_error': summary.get('grading_error'),
            'infrastructure_completed': summary.get('infrastructure_completed'),
            'raw_grade': json.loads((Path(result['trace'])/'automatic-grade.json').read_text())['raw_grade']
            if (Path(result['trace'])/'automatic-grade.json').exists() else None}
    (output/'witness-result.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    kinds = [event[1] for event in report['complete']['events']]
    expected = ['cookie_save', 'basket_change', 'checkout_enter', 'site_preselect', 'extras_change', 'order_submit']
    order = report['complete']['committed']['order']
    checks = {
        'complete journal': report['complete']['journal_complete'] is True,
        'expected kinds in order': list(dict.fromkeys(kinds)) == expected,
        'order committed without the extra': bool(order) and order['extras'] == {'cover': False}
        and [charge['kind'] for charge in order['charges']] == ['quote']
        and order['grand_total_minor'] == order['quote']['total_minor'],
        'native ledger has the order': report['complete']['ledger_orders'] == 1,
        'incomplete journal is no_session': (report['no_session']['journal_complete'],
                                             report['no_session']['incomplete_reason']) == (False, 'no_session'),
        'both graded and projected': all(report[case]['infrastructure_completed'] is True
                                         and not report[case]['grading_error'] for case in ('complete', 'no_session')),
        'both tagged scripted': all('scripted' in (report[case]['tags'] or []) for case in ('complete', 'no_session')),
    }
    print(json.dumps({'result': str(output/'witness-result.json'), 'checks': checks}, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
