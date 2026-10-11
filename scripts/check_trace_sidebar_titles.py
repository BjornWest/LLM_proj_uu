"""Zero-provider browser check of lazy titles during ongoing trace updates."""
import argparse
import asyncio
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / 'common_agent_util'))
from scripts.trace_hub import Hub, make_handler


async def check(output):
    output.mkdir(parents=True, exist_ok=False)
    checks, errors, projections = [], [], []

    def expect(name, condition):
        assert condition, name
        checks.append(name)

    def ident(name):
        return hashlib.sha256(('browsergym:' + name).encode()).hexdigest()[:20]

    class ObservedHub(Hub):
        def project(self, entry):
            projections.append(entry['directory'].name)
            return super().project(entry)

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        runs = root / 'runs'
        for name, day in [('selected', '01'), ('unopened', '02'), ('legacy', '03'), ('broken', '04')]:
            run = runs / name
            run.mkdir(parents=True)
            (run / 'metadata.json').write_text(json.dumps({'browsergym_version': 'fixture',
                'driver': 'scripted', 'tags': ['scripted']}))
            (run / 'events.jsonl').write_text(json.dumps({'event': 'episode_started',
                'timestamp': '2026-01-' + day + 'T00:00:00Z'}) + '\n')
            if name != 'legacy':
                (run / 'initial-state.json').write_text(json.dumps({'resolved_goal': name + ' wet-paving task'}))
            (run / 'steps.jsonl').write_text(json.dumps({'step': 0, 'model_request': {'messages': [
                {'role': 'user', 'content': 'USER GOAL: ' + name + ' wet-paving task'}]}}) + '\n')
        (runs / 'broken' / 'initial-state.json').write_text('null')
        registry = root / 'sources.json'
        registry.write_text(json.dumps({'project_root': str(root), 'roots': [str(runs)]}))
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(registry, hub_class=ObservedHub))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://localhost:' + str(server.server_port)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    await page.goto(url + '/#' + ident('selected'))
                    await page.wait_for_function('current?.id === ' + json.dumps(ident('selected')))
                    await page.locator('#live').uncheck()
                    card = lambda name: page.locator('.session[data-session-id="' + ident(name) + '"]')
                    title = lambda name: card(name).locator('b')
                    expect('unopened run uses reset goal', (await title('unopened').inner_text()).startswith('unopened wet-paving task'))
                    expect('malformed optional reset file leaves catalog healthy', (await title('broken').inner_text()).startswith('Browser task'))
                    expect('unopened trace never projected', projections == ['selected'])
                    with (runs / 'unopened' / 'steps.jsonl').open('a') as f:
                        f.write(json.dumps({'step': 1, 'action': None}) + '\n')
                    # Exercise the actual three-second background timer.
                    await page.locator('#live').check()
                    with (runs / 'unopened' / 'events.jsonl').open('a') as f:
                        f.write(json.dumps({'event': 'tool_started', 'timestamp': '2026-01-02T01:00:00Z'}) + '\n')
                    await page.wait_for_function("sessions.find(s=>s.id===" + json.dumps(ident('unopened')) + ").updated_at === '2026-01-02T01:00:00Z'", timeout=10000)
                    await page.locator('#live').uncheck()
                    expect('timer keeps unopened title', (await title('unopened').inner_text()).startswith('unopened wet-paving task'))
                    expect('timer does not project unselected traces', projections == ['selected'])
                    await card('legacy').click()
                    await page.wait_for_function('current?.id === ' + json.dumps(ident('legacy')))
                    expect('opening legacy trace recovers goal', (await title('legacy').inner_text()).startswith('legacy wet-paving task'))
                    await card('selected').click()
                    await page.wait_for_function('current?.id === ' + json.dumps(ident('selected')))
                    for step in [1, 2]:
                        with (runs / 'legacy' / 'steps.jsonl').open('a') as f:
                            f.write(json.dumps({'step': step, 'action': None}) + '\n')
                        await page.evaluate('refresh({background:true})')
                        expect('legacy title retained after update ' + str(step), (await title('legacy').inner_text()).startswith('legacy wet-paving task'))
                        expect('previous legacy counts retained ' + str(step), '1 model turns' in await card('legacy').inner_text() and 'last loaded' in await card('legacy').inner_text())
                    expect('legacy not reprojected while unselected', projections.count('legacy') == 1)
                    (runs / 'legacy' / 'evaluation.json').write_text(json.dumps({'safe_success': True}))
                    await page.evaluate('refresh({background:true})')
                    expect('outcome suffix refreshes while name retained', await title('legacy').inner_text() == 'legacy wet-paving task · scripted · safe success')
                    await page.reload()
                    await page.wait_for_function('current?.id === ' + json.dumps(ident('selected')))
                    await page.locator('#live').uncheck()
                    expect('page reload keeps unselected name', (await title('legacy').inner_text()).startswith('legacy wet-paving task'))
                    (runs / 'legacy' / 'metadata.json').write_text(json.dumps({'browsergym_version': 'fixture',
                        'driver': 'scripted', 'tags': ['scripted'], 'trace_title': 'Explicit renamed task'}))
                    await page.evaluate('refresh({background:true})')
                    expect('new explicit title replaces retained name', await title('legacy').inner_text() == 'Explicit renamed task · scripted · safe success')
                    expect('no JavaScript errors', not errors)
                    await page.screenshot(path=str(output / 'desktop.png'))
                    result = {'passed': True, 'checks': checks, 'errors': errors,
                              'projections': projections, 'model_calls': 0, 'classification_writes': 0}
                    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
                    print(json.dumps(result))
                finally:
                    await browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(check(args.output))
