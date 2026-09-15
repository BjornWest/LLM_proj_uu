"""Independent copied-Chaos React remount checks; privileged, offline, no model."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_chaos_react_boundaries import descriptor, selector
from intent_browser.chaos import ChaosClient
from intent_browser.chaos_verifier import fingerprint_server
from playwright.async_api import async_playwright


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


async def main(args):
    if args.report.exists():
        raise ValueError('Use a new evidence path')
    bundle = args.bundle.resolve()
    origin = args.base_url.rstrip('/')
    if origin == 'http://localhost:45379':
        raise ValueError('Original environment is frozen')
    provenance = fingerprint_server(origin)
    if Path(provenance['bundle']).resolve() != bundle:
        raise ValueError('Live server does not match supplied copied build')
    repair = bundle.parent/'intent-repair.json'
    original = Path(json.loads(repair.read_text())['original_package'])/'dist/cli.mjs'
    if original.resolve() == bundle:
        raise ValueError('Require a copied candidate')
    tracked = [bundle, repair, original, bundle.parent/'web/assets/intent-stage-queue.mjs',
               bundle.parent/'web/assets/index-CiX7pK2V.js', Path(__file__),
               Path(__file__).with_name('check_chaos_react_boundaries.py')]
    hashes = {str(p): sha(p) for p in tracked}
    report = {'scope': __doc__, 'provenance': provenance, 'source_sha256': hashes,
              'model_calls': 0, 'safe_success': None, 'training_eligible': False,
              'complete': False, 'cases': [],
              'limitations': ['Privileged SPA navigation and network interception; not policy episodes or grader certification.',
                             'Already dispatched requests are not undone by unmount.']}
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH', '')
    client = ChaosClient(origin)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for scenario in ('old-input-response', 'old-terminal-response', 'old-input-failure'):
                old = client.prepare('transfer-by-not-clicking-save')
                fresh = client.prepare('transfer-by-not-clicking-save')
                old_stage = descriptor(bundle, old)['stage']
                fresh_stage = descriptor(bundle, fresh)['stage']
                context = await browser.new_context()
                page = await context.new_page()
                gate, held, released = asyncio.Event(), asyncio.Event(), asyncio.Event()
                requests, operations = [], []
                result = {'case': scenario, 'old_session': old['session'], 'new_session': fresh['session'],
                          'passed': False, 'operations': operations}
                report['cases'].append(result)

                async def intercept(route):
                    payload = route.request.post_data_json
                    requests.append(payload)
                    kind = 'click' if scenario == 'old-terminal-response' else 'input'
                    if payload['session'] == old['session'] and payload['event']['kind'] == kind and not held.is_set():
                        held.set()
                        if scenario == 'old-input-failure':
                            operations.append({'operation': 'hold_before_transport_abort', 'payload': payload})
                            await gate.wait()
                            await route.abort('failed')
                        else:
                            response = await route.fetch(max_redirects=0)
                            operations.append({'operation': 'hold_original_response', 'payload': payload,
                                               'status': response.status, 'body': await response.json(), 'fetch_count': 1})
                            await gate.wait()
                            await route.fulfill(response=response)
                        released.set()
                    else:
                        await route.continue_()

                await page.route('**/api/stage/*/interact', intercept)
                try:
                    await page.goto(origin+old['selected']['taskUrl'])
                    old_target, old_value = next(iter(old_stage['check']['expectedValues'].items()))
                    field = page.locator(selector(old_target))
                    await field.fill(old_value)
                    save = page.locator(selector(old_stage['check']['mustClick'][0]))
                    if scenario == 'old-terminal-response':
                        await field.press('Tab')
                        await page.locator(selector(old_stage['data']['fields'][-1]['id'])).press('Tab')
                        await page.wait_for_function("() => {const e=window.__intentChaosQueueSnapshot().events;return e.filter(x=>x.phase==='dispatched').length===e.filter(x=>x.phase==='completed').length}")
                        await save.dblclick()
                        operations.append({'operation': 'native_fill_tabs_doubleclick'})
                    else:
                        await save.click()
                        operations.append({'operation': 'native_fill_click'})
                    await asyncio.wait_for(held.wait(), 5)
                    await page.wait_for_function("() => {const e=window.__intentChaosQueueSnapshot().events;return e.filter(x=>x.phase==='queued'&&x.kind==='click').length>e.filter(x=>x.phase==='dispatched'&&x.kind==='click').length}")
                    result['old_before_remount'] = await page.evaluate('() => window.__intentChaosQueueSnapshot()')
                    await page.evaluate("url => {window.__independentOldQueue=window.__intentChaosQueueSnapshot;history.pushState({},'',url);window.dispatchEvent(new PopStateEvent('popstate'));}", fresh['selected']['taskUrl'])
                    operations.append({'operation': 'privileged_same_document_session_navigation', 'url': fresh['selected']['taskUrl']})
                    await page.wait_for_function("session => window.__intentChaosQueueSnapshot?.().context?.session===session && !!window.__intentChaosQueueSnapshot().context.mountNonce", arg=fresh['session'])
                    await page.wait_for_function("() => window.__independentOldQueue().reason==='unmounted'")
                    new_before = await page.evaluate('() => window.__intentChaosQueueSnapshot()')
                    text_before = await page.locator('body').inner_text()
                    assert not new_before['closed'] and not new_before['events']
                    assert new_before['context']['mountNonce'] != result['old_before_remount']['context']['mountNonce']
                    gate.set()
                    await asyncio.wait_for(released.wait(), 5)
                    await page.wait_for_function("() => window.__independentOldQueue().events.some(e=>e.phase==='discarded'&&e.kind==='click')")
                    old_after = await page.evaluate('() => window.__independentOldQueue()')
                    new_after = await page.evaluate('() => window.__intentChaosQueueSnapshot()')
                    text_after = await page.locator('body').inner_text()
                    assert new_before == new_after, 'Old completion mutated fresh queue'
                    assert text_before == text_after, 'Old completion mutated fresh page text'
                    assert old_after['context'] == result['old_before_remount']['context']
                    assert old_after['unmountedAt'] is not None and old_after['reason'] == 'unmounted'
                    target, value = next(iter(fresh_stage['check']['expectedValues'].items()))
                    await page.locator(selector(target)).fill(value)
                    await page.locator(selector(fresh_stage['check']['mustClick'][0])).click()
                    operations.append({'operation': 'native_new_session_fill_click'})
                    await page.wait_for_function("() => window.__intentChaosQueueSnapshot().reason==='terminal:success'")
                    final = await page.evaluate('() => window.__intentChaosQueueSnapshot()')
                    server = {s['session']: client.get('/api/events/'+s['session'])['events'] for s in (old, fresh)}
                    for s, expected_clicks, queue in ((old, int(scenario == 'old-terminal-response'), old_after), (fresh, 1, final)):
                        interactions = [e for e in server[s['session']] if e['event'] in ('input', 'click')]
                        assert sum(e['event'] == 'click' for e in interactions) == expected_clicks
                        assert all(e['metadata']['isTrusted'] is True for e in interactions)
                        emitted = [r for r in requests if r['session'] == s['session']]
                        assert all(r['mountNonce'] == queue['context']['mountNonce'] for r in emitted)
                    result.update(passed=True, old_after_release=old_after, new_before_release=new_before,
                                  new_after_release=new_after, final_new_queue=final,
                                  fresh_page_text_before=text_before, fresh_page_text_after=text_after,
                                  retained_requests=requests, raw_server_events=server)
                except Exception as error:
                    result.update(error=f'{type(error).__name__}: {error}', retained_requests=requests)
                finally:
                    gate.set()
                    await context.close()
                    args.report.write_text(json.dumps(report, indent=2)+'\n')
                print(scenario, result['passed'], result.get('error', ''), flush=True)
        finally:
            await browser.close()
            client.close()
    report['sources_unchanged'] = all(sha(p) == h for p, h in hashes.items())
    report['complete'] = True
    report['passed'] = report['sources_unchanged'] and all(c['passed'] for c in report['cases'])
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', required=True)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    raise SystemExit(asyncio.run(main(p.parse_args())))
