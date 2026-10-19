#!/usr/bin/env python3
"""Bounded, scripted Playwright acceptance for the full-page backend adapter.

Start mock_backend.py --delay 4 first, then run through run_bounded_job.py.
"""
import argparse
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


async def main(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = {'metadata': {'tags': ['scripted']}, 'cases': {}}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])

        async def run_case(name):
            context = await browser.new_context(viewport={'width': 1440, 'height': 1000})
            await context.tracing.start(screenshots=True, snapshots=True)
            page = await context.new_page()
            errors, requests, cancellations = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.post_data_json) if request.method == 'POST' and request.url.endswith('/api/tasks') else None)
            page.on('response', lambda response: cancellations.append(response.status) if response.url.endswith('/cancel') else None)
            try:
                await page.goto(args.url)
                await page.wait_for_function('window.ravenChatDemo?.ready && window.RavenConversations', timeout=60000)
                await page.evaluate('''() => {
                  window.observedSites=[];window.observedStates=[];window.landed=false;
                  document.addEventListener('raven-web-activity', e=>{if(e.detail.url)observedSites.push(e.detail.url)});
                  document.getElementById('chat-scene').addEventListener('raven-chat-land',()=>window.landed=true);
                  new MutationObserver(()=>observedStates.push(document.getElementById('chat-scene').dataset.state)).observe(document.getElementById('chat-scene'),{attributes:true,attributeFilter:['data-state']});
                }''')
                if name in ('early-final', 'dropped-stream'):
                    async def fixed_stream(route):
                        events = [{'type':'status','state':'working'}] if name == 'dropped-stream' else [{'type':'final','markdown':'## Early answer','sources':[{'id':'early-1','title':'Example','url':'https://example.com/','evidence':'Captured example evidence','illustrative':True}]}]
                        await route.fulfill(status=200,content_type='text/event-stream',body=''.join('data: '+json.dumps(event)+'\n\n' for event in events))
                    await page.route('**/events', fixed_stream)
                if name == 'creation-race':
                    async def slow_create(route):
                        response = await route.fetch()
                        await asyncio.sleep(2)
                        await route.fulfill(response=response)
                    await page.route('**/api/tasks', slow_create)
                await page.locator('#message-input').fill('Please research three websites' + (' [error]' if name == 'error' else ''))
                await page.locator('#chat-form').evaluate('(form)=>form.requestSubmit()')
                await page.wait_for_function("ravenChatDemo.state==='takeoff'")
                assert requests[0]['mode'] == 'background' and requests[0]['history'] == []
                if name == 'full':
                    await page.screenshot(path=str(out / 'm1-takeoff.png'))
                    for index in range(1, 4):
                        await page.wait_for_function('(count)=>window.observedSites.length>=count', arg=index, timeout=60000)
                        await page.wait_for_function("document.getElementById('web-activity').dataset.icon==='favicon'")
                        await page.screenshot(path=str(out / f'm1-site-{index}.png'))
                    # The former ten-second timer must not complete this 12-second run.
                    assert await page.locator('.message:not(.user)').count() == 0
                    await page.wait_for_selector('.message-copy h2', timeout=60000)
                    await page.wait_for_function('window.landed', timeout=60000)
                    assert await page.locator('button.raven-citation').count() == 3
                    await page.screenshot(path=str(out / 'm1-final.png'))
                    await page.locator('button.raven-citation').first.click()
                    await page.locator('.raven-citation-evidence summary').click()
                    await page.screenshot(path=str(out / 'm1-citation.png'))
                    assert await page.locator('.message').count() == 2
                    await page.reload()
                    await page.wait_for_function('window.ravenChatDemo?.ready', timeout=60000)
                    assert await page.locator('.message').count() == 2
                    assert await page.locator('button.raven-citation').count() == 3
                    await page.locator('#message-input').fill('Follow up with those sources')
                    await page.locator('#chat-form').evaluate('(form)=>form.requestSubmit()')
                    await page.wait_for_timeout(400)
                    assert len(requests[1]['history']) == 2
                    assert requests[1]['conversation_id'] == requests[0]['conversation_id']
                    await page.locator('#stop-task').click()
                elif name in ('cancel', 'creation-race', 'switch'):
                    if name != 'creation-race':
                        await page.wait_for_function('window.observedSites.length>=1', timeout=60000)
                    if name == 'switch':
                        await page.locator('#new-conversation').click()
                    else:
                        await page.locator('#stop-task').click()
                    await page.wait_for_function("ravenChatDemo.state==='idle' && ravenChatDemo.started===null")
                    await page.wait_for_timeout(3500)
                    assert cancellations == [200], cancellations
                    assert await page.locator('.message:not(.user)').count() == 0
                    await page.screenshot(path=str(out / f'm1-{name}.png'))
                elif name in ('early-final', 'dropped-stream'):
                    await page.wait_for_function('window.landed', timeout=60000)
                    if name == 'early-final':
                        assert await page.locator('button.raven-citation').count() == 1
                        assert 'Early answer' in await page.locator('.message:not(.user)').inner_text()
                    else:
                        assert 'Connection to Raven was interrupted' in await page.locator('.message:not(.user)').inner_text()
                        assert cancellations == [200], cancellations
                else:
                    await page.get_by_text('Raven could not finish: Scripted offline error.', exact=False).wait_for(timeout=60000)
                    await page.wait_for_function('window.landed', timeout=60000)
                    assert await page.locator('.message').count() == 2
                    await page.screenshot(path=str(out / 'm1-error.png'))
                assert not errors, errors
                results['cases'][name] = {'passed': True, 'requests': requests, 'cancel_statuses': cancellations, 'browser_errors': errors}
            except Exception as error:
                await page.screenshot(path=str(out / f'failure-{name}.png'))
                results['cases'][name] = {'passed': False, 'error': str(error), 'browser_errors': errors}
            finally:
                await context.tracing.stop(path=str(out / f'm1-{name}-trace.zip'))
                await context.close()

        # Independent browser contexts, storage, and SSE sessions; bounded to two.
        semaphore = asyncio.Semaphore(2)
        async def bounded(name):
            async with semaphore:
                await run_case(name)
        await asyncio.gather(*(bounded(name) for name in ['full', 'cancel', 'error', 'creation-race', 'switch', 'early-final', 'dropped-stream']))
        await browser.close()
    (out / 'm1-results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps({name: row['passed'] for name, row in results['cases'].items()}, indent=2))
    if any(not row['passed'] for row in results['cases'].values()):
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8767/chat-fullpage-v42.html')
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
