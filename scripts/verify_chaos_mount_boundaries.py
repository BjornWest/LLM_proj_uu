"""Privileged offline Chaos v2 React mount/context diagnostics; no policy calls.

Delayed old mount success/rejection and same-session challenge change are tested
with native Playwright edits/clicks and explicitly recorded history/popstate SPA
controls. Diagnostic boundary passes never become benchmark safe-success labels.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright
from intent_browser.chaos import ChaosClient
from intent_browser.chaos_verifier import fingerprint_server, inspect_task
from intent_browser.evaluation import Evaluation
from intent_browser.trace import Trace, write_json

ROOT = Path(__file__).resolve().parents[1]
CASES = ('delayed-mount-success', 'delayed-mount-rejection', 'same-session-challenge-change')
SNAPSHOT = '''() => ({url:location.href,text:document.body.innerText,
 goal:document.querySelector('[data-testid="goal-banner"]')?.innerText??null,
 fields:[...document.querySelectorAll('input,select,textarea')].map(e=>({target:e.getAttribute('data-bac'),type:e.type,value:e.value,checked:e.checked,readonly:e.readOnly})),
 queue:window.__intentChaosQueueSnapshot?.()??null})'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def selector(target):
    return '[data-bac='+json.dumps(target)+']'


def same_session_target(client, session, task_id):
    for row in session['challenges']:
        routing = client.get('/api/resolve/'+quote(row['id'], safe=''))
        if routing['sessionId'] != session['session']:
            raise ValueError('Cross-session route resolution')
        if routing['challengeId'] == task_id:
            return {'session': session['session'], 'selected': row,
                    'source_task_id': task_id, 'routing': routing}
    raise ValueError('Second stage absent from same session')


async def snapshot(page, trace, label):
    state = await page.evaluate(SNAPSHOT)
    write_json(trace.directory/f'{label}.json', state)
    (trace.directory/f'{label}.txt').write_text(state['text'])
    await page.screenshot(path=str(trace.directory/f'{label}.png'), full_page=True)
    trace.event('diagnostic_observation', label=label, artifacts=[f'{label}.json', f'{label}.txt', f'{label}.png'])
    return state


async def wait_mounted(page, target):
    await page.wait_for_function('''expected => {
      const q=window.__intentChaosQueueSnapshot?.();
      return q?.context?.session===expected.session && q?.context?.challengeId===expected.challenge && !!q.context.mountNonce;
    }''', arg={'session': target['session'], 'challenge': target['source_task_id']})
    await page.locator('[data-testid="goal-banner"]').wait_for(state='visible')


async def complete_native(page, descriptor, record):
    stage = descriptor['stage']
    for target, value in stage['check'].get('expectedValues', {}).items():
        record('playwright.locator.fill', target=target, value=value)
        await page.locator(selector(target)).fill(value)
    for target, value in stage['check'].get('expectedChecked', {}).items():
        record('playwright.locator.set_checked', target=target, checked=value)
        await page.locator(selector(target)).set_checked(value)
    target = stage['check']['mustClick'][0]
    record('playwright.locator.click', target=target)
    await page.locator(selector(target)).click()
    await page.wait_for_function("window.__intentChaosQueueSnapshot().reason === 'terminal:success'")


async def case_run(browser, client, provenance, scenario):
    old = client.prepare('transfer-by-not-clicking-save')
    fresh = (same_session_target(client, old, 'force-push') if scenario == 'same-session-challenge-change'
             else client.prepare('transfer-by-not-clicking-save'))
    old_descriptor = inspect_task(provenance, old['source_task_id'], old['session'])
    fresh_descriptor = inspect_task(provenance, fresh['source_task_id'], fresh['session'])
    trace = Trace(ROOT/'runs', {'task': 'chaos.react-mount-boundaries', 'scenario': scenario,
                  'driver': 'privileged-native-playwright-diagnostic', 'model': None,
                  'model_calls': 0, 'training_eligible': False, 'headless': True,
                  'safe_success': None, 'environment_revision': provenance})
    for name, data in [('old-session.json', old), ('new-session.json', fresh),
                       ('old-descriptor.json', old_descriptor), ('new-descriptor.json', fresh_descriptor)]:
        write_json(trace.directory/name, data)
    operations, requests, responses, page_errors = [], [], [], []
    def record(operation, **details):
        item = {'operation': operation, **details}
        operations.append(item)
        with (trace.directory/'privileged-operations.jsonl').open('a') as file:
            file.write(json.dumps(item)+'\n')
        trace.event('privileged_browser_operation', artifact='privileged-operations.jsonl', **item)
    result = {'case': scenario, 'episode': str(trace.directory.relative_to(ROOT)), 'safe_success': None,
              'old_session': old['session'], 'new_session': fresh['session'],
              'old_challenge': old['source_task_id'], 'new_challenge': fresh['source_task_id'],
              'passed': False}
    context = await browser.new_context()
    page = await context.new_page()
    page.on('pageerror', lambda error: page_errors.append(str(error)))
    gate, held, released = asyncio.Event(), asyncio.Event(), asyncio.Event()
    claimed = False
    error = None
    async def intercept(route):
        nonlocal claimed
        request = route.request
        payload = request.post_data_json
        requests.append({'url': request.url, 'method': request.method, 'payload': payload})
        is_mount = request.url.endswith('/mount')
        wants_mount = scenario != 'same-session-challenge-change'
        matches = (payload.get('session') == old['session'] and
                   '/api/stage/'+old['source_task_id']+'/' in request.url and
                   (is_mount if wants_mount else not is_mount and payload.get('event', {}).get('kind') == 'input'))
        if claimed or not matches:
            await route.continue_()
            return
        claimed = True
        response = await route.fetch(max_redirects=0)
        body = await response.body()
        response_record = {'url': request.url, 'payload': payload, 'original_status': response.status,
                           'original_headers': response.headers, 'original_body_utf8': body.decode(),
                           'original_body_sha256': hashlib.sha256(body).hexdigest(), 'fetch_count': 1}
        responses.append(response_record)
        record('hold_original_mount_response' if is_mount else 'hold_original_input_response', **response_record)
        held.set()
        await gate.wait()
        if scenario == 'delayed-mount-rejection':
            rejected_body = json.dumps({'error': 'Controlled stale mount rejection'})
            record('deliver_controlled_old_mount_rejection', original_status=response.status,
                   delivered_status=503, delivered_body=rejected_body,
                   delivered_body_sha256=hashlib.sha256(rejected_body.encode()).hexdigest(),
                   scope='Explicit response fault; original request was fetched once')
            await route.fulfill(status=503, content_type='application/json', body=rejected_body)
        else:
            record('release_original_response_unchanged', url=request.url, status=response.status,
                   body_sha256=hashlib.sha256(body).hexdigest(), replay=False)
            await route.fulfill(response=response)
        released.set()
    await page.route('**/api/stage/*/*', intercept)
    try:
        record('page.goto', url=client.base_url+old['selected']['taskUrl'])
        await page.goto(client.base_url+old['selected']['taskUrl'])
        if scenario == 'same-session-challenge-change':
            await wait_mounted(page, old)
            target, value = next(iter(old_descriptor['stage']['check']['expectedValues'].items()))
            record('playwright.locator.fill', target=target, value=value)
            await page.locator(selector(target)).fill(value)
            save = old_descriptor['stage']['check']['mustClick'][0]
            record('playwright.locator.click', target=save)
            await page.locator(selector(save)).click()
        await asyncio.wait_for(held.wait(), 10)
        old_before = await snapshot(page, trace, 'old-before-navigation')
        queue = old_before['queue']
        assert queue['version'] == 'stage-fifo-v2'
        assert queue['context']['session'] == old['session'] and queue['context']['challengeId'] == old['source_task_id']
        if scenario != 'same-session-challenge-change':
            assert queue['context']['mountNonce'] is None and not queue['events']
        else:
            assert queue['context']['mountNonce']
            assert any(e['phase'] == 'queued' and e['kind'] == 'click' for e in queue['events'])
            assert not any(e['phase'] == 'dispatched' and e['kind'] == 'click' for e in queue['events'])
        record('privileged_same_document_navigation', url=fresh['selected']['taskUrl'],
               mechanism='Retain read-only old getter, history.pushState and dispatch PopStateEvent; no click synthesized')
        await page.evaluate('''url => {
          window.__intentOldMountQueue = window.__intentChaosQueueSnapshot;
          history.pushState({}, '', url); window.dispatchEvent(new PopStateEvent('popstate'));
        }''', fresh['selected']['taskUrl'])
        await wait_mounted(page, fresh)
        # Ensure stage controls and source goal have both reached the new page.
        await page.locator(selector(fresh_descriptor['stage']['check']['mustClick'][0])).wait_for(state='visible')
        before = await snapshot(page, trace, 'new-before-old-response')
        assert before['queue']['context']['mountNonce'] and not before['queue']['closed'] and not before['queue']['events']
        if scenario == 'same-session-challenge-change':
            assert before['queue']['context']['mountNonce'] != queue['context']['mountNonce']
            assert old['session'] == fresh['session'] and old['source_task_id'] != fresh['source_task_id']
        else:
            assert old['session'] != fresh['session']
        gate.set()
        await asyncio.wait_for(released.wait(), 10)
        # Give the stale fetch's promise/React continuation time to settle while
        # the new stage is still idle. This is a bounded diagnostic observation.
        record('settle_stale_response', milliseconds=250)
        await page.wait_for_timeout(250)
        after = await snapshot(page, trace, 'new-after-old-response')
        old_after = await page.evaluate('() => window.__intentOldMountQueue()')
        write_json(trace.directory/'old-after-response.json', old_after)
        assert before == after, 'Stale old response changed new nonce, goal, fields, queue or visible text'
        assert old_after['context'] == queue['context'] and old_after['unmountedAt'] is not None
        if scenario == 'same-session-challenge-change':
            assert old_after['reason'] == 'unmounted' and old_after['closed']
            assert any(e['phase'] == 'discarded' and e['kind'] == 'click' for e in old_after['events'])
        else:
            # A mount that never reached its effect has no active queue; null
            # nonce and unmountedAt, not placeholder closed:false, identify it.
            assert old_after['context']['mountNonce'] is None and not old_after['events']
        await complete_native(page, fresh_descriptor, record)
        final = await snapshot(page, trace, 'new-completed')
        assert final['queue']['context'] == before['queue']['context']
        server = {s: client.get('/api/events/'+quote(s, safe=''))['events'] for s in {old['session'], fresh['session']}}
        scores = {s: client.get('/api/score/'+quote(s, safe='')) for s in server}
        write_json(trace.directory/'server-events.json', server)
        write_json(trace.directory/'server-scores.json', scores)
        for task, count in ((old, 0), (fresh, 1)):
            interaction = [e for e in server[task['session']] if e.get('challengeId') == task['source_task_id'] and e['event'] in ('input', 'click')]
            assert sum(e['event'] == 'click' for e in interaction) == count
            assert all(e['metadata']['isTrusted'] is True for e in interaction)
        for request in requests:
            payload = request['payload']
            if request['url'].endswith('/interact'):
                target_queue = final['queue'] if '/api/stage/'+fresh['source_task_id']+'/' in request['url'] and payload['session'] == fresh['session'] else old_after
                assert payload['mountNonce'] == target_queue['context']['mountNonce']
        assert not page_errors, page_errors
        result.update(passed=True, old_context=queue['context'], new_context=final['queue']['context'],
                      old_after_response=old_after, unchanged_new_stage=True,
                      new_native_terminal='success', raw_upstream_only=True)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        result['error'] = error
        try:
            await snapshot(page, trace, 'failure-observation')
        except Exception as capture_error:
            result['capture_error'] = str(capture_error)
    finally:
        gate.set()
        if claimed and held.is_set() and not released.is_set():
            try:
                await asyncio.wait_for(released.wait(), 5)
            except Exception as release_error:
                result['release_error'] = str(release_error)
        write_json(trace.directory/'retained-requests.json', requests)
        write_json(trace.directory/'retained-responses.json', responses)
        write_json(trace.directory/'page-errors.json', page_errors)
        trace.event('evaluation_started')
        evaluation = Evaluation('chaos-react-mount-boundary-diagnostic', '1', trust='privileged_lifecycle_diagnostic',
            technical_error=error, evidence=[p.name for p in trace.directory.iterdir() if p.suffix in ('.json', '.jsonl', '.png', '.txt')],
            limitations=['No policy run or benchmark/authorization success labels.',
                         'Controlled original-response holds and explicit privileged history/popstate navigation.',
                         'HTTP 503 case is a recorded response fault; its original mount request reached the server once.',
                         'Null mount nonce means no active queue even if the diagnostic placeholder says closed:false.',
                         'Post-release comparison is a bounded observation after 250 ms; dispatched effects are not undone.']).to_dict()
        write_json(trace.directory/'evaluation.json', evaluation)
        trace.event('evaluation_completed', artifact='evaluation.json', diagnostic_boundary_passed=result['passed'])
        trace.event('environment_close_started')
        await context.close()
        trace.event('environment_close_completed')
        trace.finish({'stop_reason': 'diagnostic_complete' if result['passed'] else 'diagnostic_failure', 'error': error,
                      'evaluation': evaluation, 'boundary_passed': result['passed'], 'safe_success': None})
        result['artifact_sha256'] = {p.name: sha(p) for p in trace.directory.iterdir() if p.is_file()}
        result['evaluation_before_close'] = True
    return result


async def main(args):
    if args.report.exists():
        raise ValueError('Choose a fresh report path; historical failures are preserved')
    provenance = fingerprint_server(args.base_url)
    if provenance.get('package_version') != '0.1.0-intent.fifo2.xor32':
        raise ValueError('This diagnostic requires the immutable FIFO v2 xor32 build')
    report = {'schema_version': 1, 'scope': __doc__, 'provenance': provenance,
              'model_calls': 0, 'safe_success': None, 'training_eligible': False,
              'source_sha256': {str(Path(__file__).relative_to(ROOT)): sha(__file__)}, 'cases': [], 'complete': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH', '')
    client = ChaosClient(args.base_url)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for scenario in args.case or CASES:
                result = await case_run(browser, client, provenance, scenario)
                report['cases'].append(result)
                write_json(args.report, report)
                print(json.dumps({'case': scenario, 'passed': result['passed'], 'episode': result['episode'], 'error': result.get('error')}), flush=True)
        finally:
            await browser.close()
            client.close()
    report['server_build_unchanged'] = fingerprint_server(args.base_url) == provenance
    report['complete'] = True
    report['all_passed'] = report['server_build_unchanged'] and all(x['passed'] for x in report['cases'])
    write_json(args.report, report)
    print(args.report, flush=True)
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://localhost:46053')
    parser.add_argument('--report', type=Path, default=ROOT/'.local/preflight/chaos-mount-boundaries-v2.json')
    parser.add_argument('--case', choices=CASES, action='append')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
