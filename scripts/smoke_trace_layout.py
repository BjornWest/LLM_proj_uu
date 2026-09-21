"""Offline replay layout regressions; three isolated browser contexts at a time.

Uses the existing local library fixture, with an explicitly modified projection
whose final observation is consolidated. No saved traces or model APIs change.
Pass --origin to check an already running library fixture (e.g. a baseline build).
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


async def settle(page):
    await page.evaluate("""() => new Promise(resolve => {
      let frames=0; function tick(){if(++frames===5)resolve();else requestAnimationFrame(tick)}
      requestAnimationFrame(tick);
    })""")


async def check_width(browser, origin, session_id, width, output, gate):
    async with gate:
        context = await browser.new_context(viewport={'width': width, 'height': 1000})
        page = await context.new_page()
        errors, checks = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def check(name, passed, detail=None):
            checks.append({'check': name, 'passed': bool(passed), 'detail': detail})

        async def projection(route):
            response = await route.fetch()
            data = await response.json()
            # Preserve real fixture assets, but vary the select's intrinsic width
            # at the end: a short decision option, then a consolidated update.
            chosen = {}
            for message in data['messages']:
                if message.get('observation_role'):
                    turn = message['turn']
                    if turn not in chosen or message['observation_role'] == 'selected':
                        chosen[turn] = message
            last_turn = max(chosen)
            for turn, message in chosen.items():
                message['observation_role'] = 'consolidated' if turn == last_turn else 'selected'
            data['messages'] = [m for m in data['messages']
                                if not m.get('observation_role') or chosen[m['turn']] is m]
            await route.fulfill(response=response, json=data)

        await page.route('**/api/library/sessions/' + session_id, projection)
        try:
            await page.goto(origin + '/workspace/replays?run=l:' + session_id)
            viewer = page.frame_locator('#shared-trace-viewer')
            await viewer.get_by_role('button', name='Replay', exact=True).click()
            await expect(viewer.locator('.browser-replay-stage img')).to_have_js_property('complete', True)
            await settle(page)
            dimensions = await viewer.locator('html').evaluate(
                'e=>({scroll:e.scrollHeight,viewport:innerHeight,width:e.scrollWidth,viewportWidth:innerWidth})')
            check('Embedded trace has no inner page scrollbar',
                  dimensions['scroll'] <= dimensions['viewport'], dimensions)
            check('Viewer fits horizontally', dimensions['width'] <= dimensions['viewportWidth'])

            slider = viewer.get_by_role('slider', name='Replay step position')
            step = viewer.get_by_label('Recorded browser step', exact=True)
            maximum = await slider.get_attribute('max')
            geometry = 'e=>({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width})'
            start = await slider.evaluate(geometry)
            await step.select_option(maximum)
            await settle(page)
            end = await slider.evaluate(geometry)
            check('Final observation cannot move or resize the scrubber', start == end, {'first': start, 'last': end})
            phase = viewer.get_by_label('Recorded observation type', exact=True)
            bounds = await phase.evaluate('e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,viewport:innerWidth})')
            check('Final observation selector stays inside the viewer', bounds['left'] >= 0 and bounds['right'] <= bounds['viewport'], bounds)

            # Real pointer dragging catches the feedback loop: width changes can
            # move the thumb back under a stationary pointer while it is held.
            await step.select_option('0')
            await slider.scroll_into_view_if_needed()
            box = await slider.bounding_box()
            await page.mouse.move(box['x'] + 4, box['y'] + box['height'] / 2)
            await page.mouse.down()
            try:
                await page.mouse.move(box['x'] + box['width'] - 4, box['y'] + box['height'] / 2, steps=24)
                values = []
                for _ in range(5):
                    await page.mouse.move(box['x'] + box['width'] - 4, box['y'] + box['height'] / 2)
                    await settle(page)
                    values.append(await slider.input_value())
            finally:
                await page.mouse.up()
            check('Dragging to the right stays on the final step', all(value == maximum for value in values), values)
            await slider.focus()
            await page.keyboard.press('Home')
            check('Keyboard Home selects the first step', await slider.input_value() == '0')
            await page.keyboard.press('End')
            check('Keyboard End selects the final step', await slider.input_value() == maximum)

            if width in (1100, 390):
                await page.screenshot(path=str(output / f'replay-{width}.png'), full_page=True)

            # Expanded records can exceed the former 14,000px frame-height cap.
            # A local DOM spacer makes that boundary deterministic at every width.
            await viewer.locator('#main').evaluate("e=>{const p=document.createElement('div');p.id='layout-test-spacer';p.style.height='15000px';e.append(p)}")
            await settle(page)
            tall = await viewer.locator('html').evaluate('e=>({scroll:e.scrollHeight,viewport:innerHeight})')
            check('Long traces use the outer page instead of a capped iframe', tall['scroll'] <= tall['viewport'], tall)
            await viewer.locator('#layout-test-spacer').evaluate('e=>e.remove()')
            await settle(page)
            height = await page.locator('#shared-trace-viewer').evaluate('e=>e.clientHeight')
            check('Viewer shrinks again when content collapses', height < 4000, height)
            await viewer.locator('#recording-notes>summary').click()
            await settle(page)
            notes = await viewer.locator('html').evaluate('e=>e.scrollHeight<=innerHeight')
            check('Expanded recording notes still use outer scrolling', notes)
            check('No browser JavaScript errors', not errors, errors)
            return {'width': width, 'checks': checks, 'passed': all(c['passed'] for c in checks)}
        finally:
            await context.close()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin')
    args = parser.parse_args()
    os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.environ.get('LD_LIBRARY_PATH', '')
    output = ROOT / '.local/vercel-demo' / ('trace-layout-' + uuid4().hex[:8])
    output.mkdir(parents=True)
    process = None
    try:
        if args.origin:
            origin = args.origin.rstrip('/')
        else:
            process = await asyncio.create_subprocess_exec(
                'node', 'tests/library-server.mjs', cwd=ROOT / 'deploy/daylight',
                env={**os.environ, 'LIBRARY_PREVIEW_AUTOLOGIN': '1'}, stdout=asyncio.subprocess.PIPE)
            info = json.loads(await process.stdout.readline())
            origin = 'http://127.0.0.1:' + str(info['port'])
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            client = await p.request.new_context()
            response = await client.get(origin + '/api/library/sessions')
            session_id = (await response.json())['sessions'][0]['id']
            gate = asyncio.Semaphore(3)
            results = await asyncio.gather(*(check_width(browser, origin, session_id, width, output, gate)
                                             for width in (1512, 1280, 1100, 900, 700, 390)))
            stats = await (await client.get(origin + '/__fixture/stats')).json()
            await client.dispose()
            await browser.close()
        passed = all(row['passed'] for row in results) and stats['writes'] == 0
        report = {'passed': passed, 'cases': results, 'fixture_writes': stats['writes'], 'model_calls': 0}
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': passed, 'report': str(output / 'report.json'),
                          'failures': [{'width': row['width'], **check} for row in results for check in row['checks'] if not check['passed']]}, indent=2))
        if not passed:
            raise SystemExit(1)
    finally:
        if process:
            process.terminate()
            await process.wait()


if __name__ == '__main__':
    asyncio.run(main())
