"""Model-free browser checks of filtered sidebar batches and suite startup."""
import argparse
import asyncio
import datetime as dt
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent / 'common_agent_util')]
from agent_trace.sessions import make_handler
from scripts.trace_hub import make_handler as hub_handler


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n')


async def check_mode(browser, mode, output):
    output.mkdir(parents=True, exist_ok=False)
    checks, errors = [], []

    def check(name, value):
        assert value, name
        checks.append(name)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        runs = root / 'runs'
        pins = {}
        for index in range(257):
            trace = runs / f'episode-{index:03}'
            write(trace / 'metadata.json', {
                'browsergym_version': 'fixture', 'trace_title': trace.name,
                'collection': 'Filtered/child' if index < 137 else 'Other',
                'driver': 'scripted', 'tags': ['scripted', 'keep'] if index < 137 else ['scripted', 'omit'],
            })
            write(trace / 'steps.jsonl', {'step': 0, 'model_response': {'choices': [{'message': {'content': 'Fixture'}}]}})
            write(trace / 'episode.json', {'stop_reason': 'agent_finished'})
            write(trace / 'events.jsonl', {'event': 'episode_started', 'timestamp': (dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=index)).isoformat()})
            for path in trace.iterdir():
                pins[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        plans = []
        for ident, date, index in [('older', '2026-10-10T00:00:00Z', 0), ('newer', '2026-10-13T00:00:00Z', 136)]:
            plan = root / ident / 'suite.json'
            write(plan, {'schema': 'episode-suite-plan-v1', 'id': ident, 'title': ident,
                         'created_at': date, 'tags': ['scripted'], 'cases': [{
                             'case_id': ident, 'task_id': ident, 'repeat': 1,
                             'trace_directory': str(runs / f'episode-{index:03}'),
                             'model': {'model': 'scripted', 'transport': 'scripted'},
                         }]})
            plans.append(str(plan))
        registry = root / 'sources.json'
        write(registry, {'project_root': str(root), 'roots': [str(runs)], 'suites': plans})
        handler = make_handler(runs) if mode == 'shared' else hub_handler(registry)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        context = await browser.new_context(viewport={'width': 1400, 'height': 1000})
        page = await context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            await page.goto(url + '/#latest')
            await page.wait_for_function("current && document.querySelectorAll('#sessions .session').length===100")
            await page.locator('#live').uncheck()
            check('first batch contains 100 of 257 episodes', await page.locator('#sidebar-count').inner_text() == 'Showing 100 of 257 episodes')
            target = await page.evaluate('scopedSessions()[150].id')
            await page.goto(url + '/#' + target)
            await page.wait_for_function('(id)=>current?.id===id && document.querySelectorAll("#sessions .session").length===100', arg=target)
            await page.locator('#live').uncheck()
            check('deep-linked older episode stays highlighted within 100-row cap', await page.locator('#sessions .session[aria-current="true"]').get_attribute('data-session-id') == target and 'outside loaded range' in await page.locator('#sessions .session[aria-current="true"]').inner_text())
            await page.evaluate("window.keptSidebarCard=document.querySelector('#sessions .session')")
            await page.locator('#sidebar-more').click()
            check('load more appends the next 100', await page.locator('#sessions .session').count() == 200)
            check('existing card identity is retained', await page.evaluate("keptSidebarCard===document.querySelector('#sessions .session')"))
            await page.evaluate('refresh()')
            check('catalog refresh preserves loaded batches', await page.locator('#sessions .session').count() == 200)
            await page.locator('#sidebar-more').click()
            check('last partial batch has no load button', await page.locator('#sessions .session').count() == 257 and await page.locator('#sidebar-more').is_hidden())
            check('keyboard focus retained when final load button disappears', await page.evaluate("document.activeElement===document.querySelectorAll('#sessions .session')[200]"))
            await page.locator('#collection [data-collection="Filtered"]').click()
            await page.wait_for_function("document.querySelectorAll('#sessions .session').length===100")
            check('folder filtering happens before slicing and resets batch', await page.locator('#sidebar-count').inner_text() == 'Showing 100 of 137 episodes' and await page.evaluate("[...document.querySelectorAll('#sessions .session')].every(b=>sessions.find(s=>s.id===b.dataset.sessionId).viewer_collection==='Filtered/child')"))
            await page.locator('#sidebar-more').click()
            check('folder last batch contains all 137 matches', await page.locator('#sessions .session').count() == 137)
            await page.locator('#order').select_option('oldest')
            check('order changes reset to 100 in correct order', await page.locator('#sessions .session').count() == 100 and await page.evaluate("document.querySelector('#sessions .session').dataset.sessionId===[...scopedSessions()].reverse()[0].id"))
            check('order reset retains current episode highlight within cap', await page.locator('#sessions .session[aria-current="true"]').count() == 1)
            await page.locator('#organize-folders').click()
            await page.locator('#select-folder').click()
            check('bulk selection reports selected episodes outside loaded batch', await page.locator('#sidebar-selection').inner_text() == '137 selected · 37 not shown')
            await page.locator('#organize-folders').click()
            await page.locator('#collection [data-collection=""]').click()
            await page.wait_for_function("document.querySelectorAll('#sessions .session').length===100")
            await page.locator('#tag-filter summary').click()
            await page.locator('#tag-filter [data-tag="keep"]').click()
            await page.wait_for_function("document.querySelector('#sidebar-count').textContent==='Showing 100 of 137 episodes'")
            check('positive tag filtering happens before slicing', await page.evaluate("[...document.querySelectorAll('#sessions .session')].every(b=>episodeTags(sessions.find(s=>s.id===b.dataset.sessionId)).includes('keep'))"))
            await page.locator('#sidebar-more').click()
            check('positive tag last batch has 137 matches', await page.locator('#sessions .session').count() == 137)
            await page.locator('#tag-filter [data-tag="keep"]').click()
            await page.wait_for_function("document.querySelector('#sidebar-count').textContent==='Showing 100 of 120 episodes'")
            check('negative tag filters reset batches and slice their matches', await page.evaluate("[...document.querySelectorAll('#sessions .session')].every(b=>!episodeTags(sessions.find(s=>s.id===b.dataset.sessionId)).includes('keep'))"))
            await page.locator('#collection [data-collection="Filtered"]').click()
            await page.wait_for_function("document.querySelectorAll('#sessions .session').length===0")
            check('empty combined filters show zero and no load button', await page.locator('#sidebar-count').inner_text() == 'Showing 0 of 0 episodes' and await page.locator('#sidebar-more').is_hidden())
            await page.locator('#clear-tags').click()
            await page.wait_for_function("document.querySelectorAll('#sessions .session').length===100")
            if mode == 'hub':
                check('suite badges bind to filtered trace IDs with a nonempty sample', await page.locator('#sessions .suite-badge').count() > 0 and await page.evaluate("[...document.querySelectorAll('#sessions .session-row')].every(row=>{const b=row.querySelector('.session'),s=sessions.find(s=>s.id===b.dataset.sessionId),a=row.querySelector('.suite-badge');return s.suite ? a?.getAttribute('href')==='#suite/'+encodeURIComponent(s.suite.id) : !a})"))
                await page.evaluate('list();list()')
                check('badge decoration does not duplicate on refresh', await page.evaluate("[...document.querySelectorAll('#sessions .session-row')].every(row=>row.querySelectorAll('.suite-badge').length<=1)"))
                # A disabled poll cannot conceal a broken initial request.
                await page.add_init_script("document.addEventListener('DOMContentLoaded',()=>{if(new URL(location.href).searchParams.has('startup-paused'))document.getElementById('live').checked=false})")
                await page.goto(url + '/?startup-paused#suites')
                await page.wait_for_selector('.suite-card', timeout=10000)
                check('cold Suites starts with Live off, without a retry rescuing initialization', not await page.locator('#live').is_checked() and 'before initialization' not in await page.locator('#connection').inner_text())
                # Reproduce a slow catalog crossing the three-second live poll.
                delayed = False

                async def delay_catalog(route):
                    nonlocal delayed
                    if not delayed:
                        delayed = True
                        await asyncio.sleep(4)
                    await route.continue_()

                await page.route('**/api/sessions', delay_catalog)
                await page.goto(url + '/#suites')
                check('load-more stays hidden while catalog is pending', await page.locator('#sidebar-more').is_hidden())
                await page.wait_for_selector('.suite-card', timeout=15000)
                check('cold suites render through slow catalog and live polling', await page.locator('.suite-card>a').all_text_contents() == ['newer', 'older'])
                check('suite startup has no collection initialization error', 'before initialization' not in await page.locator('#connection').inner_text())
                # The suite layout hides the conversation's live checkbox.
                await page.evaluate("el('live').checked=false")
                async def delay_detail(route):
                    await asyncio.sleep(0.5)
                    await route.continue_()

                await page.route('**/api/suites/newer', delay_detail)
                for ident in ('newer', 'older'):
                    if ident == 'older':
                        await page.get_by_role('link', name='← All suites').click()
                        await page.wait_for_selector('.suite-card')
                    await page.locator('.suite-card>a', has_text=ident).click()
                    if ident == 'newer':
                        await page.wait_for_selector('#suite-view [role="status"]')
                        check('suite navigation immediately displays loading status', await page.locator('#suite-view [role="status"]').inner_text() == 'Loading suite…')
                    await page.wait_for_selector('#suite-view table')
                    check(f'{ident} suite opens a populated case table', await page.locator('#suite-view tbody tr').count() == 1 and await page.locator('#suite-view h2').inner_text() == ident)
                trace_link = page.get_by_role('link', name='Open trace')
                trace_id = (await trace_link.get_attribute('href')).split('#')[1]
                await trace_link.click()
                await page.wait_for_function('(id)=>current?.id===id && document.querySelector("#sessions .session[aria-current=true]")?.dataset.sessionId===id', arg=trace_id)
                check('suite Open trace retains older episode highlight within cap', await page.locator('#sessions .session').count() == 100)
                await page.locator('#show-suites').click()
                await page.wait_for_selector('.suite-card')
                await page.reload()
                await page.wait_for_selector('.suite-card')
                check('suite reload retains functioning index', await page.locator('.suite-card').count() == 2)
                await page.evaluate("location.hash='suite/missing'")
                await page.wait_for_selector('#suite-view [role="alert"]')
                check('unavailable suite has visible error rather than empty panel', '404' in await page.locator('#suite-view [role="alert"]').inner_text())
                await page.evaluate("window.keptSuiteError=document.querySelector('#suite-view [role=alert]');el('live').checked=false")
                await page.evaluate('refresh({background:true})')
                check('repeated suite errors retain alert identity without re-announcing', await page.evaluate("keptSuiteError===document.querySelector('#suite-view [role=alert]')") and 'existing view retained' not in await page.locator('#connection').inner_text())
                await page.locator('#show-suites').click()
                await page.wait_for_selector('.suite-card')
                check('suite index recovers after unavailable route', await page.locator('.suite-card').count() == 2)
            await page.screenshot(path=str(output / 'desktop.png'), full_page=True)
            await page.set_viewport_size({'width': 390, 'height': 844})
            check('pagination fits mobile layout', await page.locator('#sidebar-more').evaluate('(button)=>button.getBoundingClientRect().width<=button.parentElement.getBoundingClientRect().width'))
            check('no uncaught JavaScript errors', not errors)
            check('original recordings unchanged', all(hashlib.sha256(path.read_bytes()).hexdigest() == pin for path, pin in pins.items()))
        except BaseException:
            (output / 'failure.json').write_text(json.dumps({'checks': checks, 'errors': errors, 'url': page.url, 'connection': await page.locator('#connection').inner_text(), 'suite_panel': await page.locator('#suite-view').inner_text() if mode == 'hub' else None}, indent=2) + '\n')
            raise
        finally:
            await context.close()
            server.shutdown()
            server.server_close()
            thread.join()
    (output / 'report.json').write_text(json.dumps({'checks': checks, 'errors': errors, 'model_calls': 0}, indent=2) + '\n')
    return {'mode': mode, 'passed': len(checks)}


async def main(output):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            results = await asyncio.gather(*(check_mode(browser, mode, output / mode) for mode in ('shared', 'hub')), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            print(json.dumps(results))
        finally:
            await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    libraries = next((parent / '.local/system-libs/usr/lib/x86_64-linux-gnu' for parent in (ROOT, *ROOT.parents) if (parent / '.local/system-libs/usr/lib/x86_64-linux-gnu').is_dir()), None)
    if libraries:
        os.environ['LD_LIBRARY_PATH'] = str(libraries) + ':' + os.getenv('LD_LIBRARY_PATH', '')
    asyncio.run(main(args.output))
