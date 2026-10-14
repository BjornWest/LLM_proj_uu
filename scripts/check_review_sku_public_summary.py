"""Saved-input, zero-provider review summary/DOM/AX check on fresh output."""
import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from environments.website_world.catalog_adapter import public_products
from environments.website_world.native_review_pages import LAYOUTS, NativeReviewPage
from environments.website_world.surrounding_pages import ReviewPage, path
from environments.website_world.review_rating_scopes import sku_rating_summary, SKU_SUMMARY_LAYOUTS


def write(directory, name, value):
    (directory/name).write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


async def check(recipe, output, expected_world_sha256):
    recipe, output = recipe.resolve(), output.resolve()
    if output == recipe or output.is_relative_to(recipe) or recipe.is_relative_to(output):
        raise ValueError('Use a fresh output separate from the frozen recipe')
    world_path = recipe/'pin/world.private.json'
    payload = world_path.read_bytes()
    if sha256(payload).hexdigest() != expected_world_sha256:
        raise ValueError('Saved world bytes changed')
    task = json.loads((recipe/'catalog-review-task.private.json').read_bytes())
    reference = json.loads((recipe/'catalog-review-reference.private.json').read_bytes())
    if (task['operation'], task['subject_scope']) != ('rating_summary', 'sku'):
        raise ValueError('Require the saved SKU rating-summary fixture')
    world = json.loads(payload); pid, sid = task['subject']['product_id'], task['subject']['sku_id']
    item = next(p for p in world['products'] if p['public']['product_id'] == pid)
    public = public_products({'products': [item]})
    summary = sku_rating_summary(public[pid], sid)
    if summary != reference['summary']:
        raise ValueError('Public corpus summary differs from saved native reference')
    output.mkdir(parents=True, exist_ok=False)
    write(output, 'binding.json', {'metadata': {'tags': ['scripted']}, 'world_sha256': expected_world_sha256,
        'task_sha256': sha256((recipe/'catalog-review-task.private.json').read_bytes()).hexdigest(),
        'reference_sha256': sha256((recipe/'catalog-review-reference.private.json').read_bytes()).hexdigest(),
        'product_id': pid, 'sku_id': sid, 'summary': summary,
        'public_model_rating_count': public[pid]['rating_summary']['rating_count'],
        'browser_environment': {'LD_LIBRARY_PATH': os.environ.get('LD_LIBRARY_PATH'),
                                'PLAYWRIGHT_BROWSERS_PATH': os.environ.get('PLAYWRIGHT_BROWSERS_PATH')},
        'world_draws': 0, 'provider_requests': 0, 'automatic_task_grade': 'not_a_policy_episode',
        'source_sha256': {name: sha256((ROOT/name).read_bytes()).hexdigest() for name in (
            'scripts/check_review_sku_public_summary.py', 'environments/website_world/catalog_adapter.py',
            'environments/website_world/native_review_pages.py', 'environments/website_world/surrounding_pages.py',
            'environments/website_world/review_rating_scopes.py',
            'environments/product_world/review_population.py')}})
    views = {}
    for layout in SKU_SUMMARY_LAYOUTS:
        site = {'name': 'Saved review scope check', 'layout': layout, 'families': [public[pid]['family_id']],
                'family_labels': {public[pid]['family_id']: public[pid]['family_id']},
                'review_presentation': {'page_size': 12}}
        cls = NativeReviewPage if layout in LAYOUTS else ReviewPage
        views[layout] = cls(site, public, {}, {}, None)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            try:
                status, body, mime = self.server.review_view.page(parsed.path, dict(parse_qsl(
                    parsed.query, keep_blank_values=True, strict_parsing=True)))
            except (KeyError, ValueError):
                status, body, mime = 404, 'Unknown review route', 'text/plain'
            self.send_response(status); self.send_header('Content-Type', mime); self.end_headers()
            self.wfile.write(body.encode('utf-8'))

        def log_message(self, *_): pass

    from playwright.async_api import async_playwright
    semaphore = asyncio.Semaphore(2)

    async def one(browser, layout):
        async with semaphore:
            directory = output/layout; directory.mkdir()
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.review_view = views[layout]
            worker = Thread(target=server.serve_forever, daemon=True); worker.start()
            base = 'http://127.0.0.1:'+str(server.server_address[1])
            context = None
            page = None
            try:
                context = await browser.new_context()
                page = await context.new_page()
                start = base+path('reviews', pid)+('?part=readers' if layout == 'editorial-magazine' else '')
                response = await page.goto(start, timeout=30000)
                assert response.status == 200, response.status
                label = 'Reviewed option' if layout in LAYOUTS else 'Reviewed configuration'
                await page.get_by_label(label).select_option(sid)
                await page.get_by_role('button', name='Filter reader notes' if layout in LAYOUTS else 'Filter comments', exact=True).click()

                async def capture(name):
                    panel = page.get_by_role('region', name='Option-specific rating summary', exact=True)
                    text = await panel.inner_text()
                    counts = (f"{summary['rating_count']} ratings; {summary['written_review_count']} written reviews, "
                              f"{summary['rating_only_count']} ratings without comments")
                    mean = (summary['mean_rounded']+' / 5' if summary['mean_rounded'] is not None
                            else 'Mean rating undefined (no ratings)')
                    assert counts in text and mean in text and sid in text
                    rows = await panel.locator('tbody tr').all()
                    for stars, row in zip(range(5, 0, -1), rows, strict=True):
                        assert (await row.get_by_role('cell').inner_text()).strip() == str(summary['star_counts'][str(stars)])
                        assert (await row.get_by_role('rowheader').inner_text()).strip() == f'{stars} stars'
                    cdp = await context.new_cdp_session(page)
                    try: ax = await cdp.send('Accessibility.getFullAXTree')
                    finally: await cdp.detach()
                    names = '\n'.join(n.get('name', {}).get('value', '') for n in ax['nodes'] if not n.get('ignored'))
                    assert counts in names and mean in names and sid in names
                    (directory/(name+'.html')).write_text(await page.content())
                    write(directory, name+'-ax.json', ax)
                    write(directory, name+'-state.json', {'url': page.url, 'option_summary_text': text})

                await capture('selected-option')
                await page.get_by_role('region', name='Option-specific rating summary').get_by_role('link', name='1 stars', exact=True).click()
                await capture('filtered-comments')
                if layout in LAYOUTS:
                    await page.goto(base+path('variants', sid), timeout=30000)
                    await capture('option-page')
                write(directory, 'result.json', {'metadata': {'tags': ['scripted']}, 'status': 'public_summary_pass',
                    'silent_ratings_included': True, 'ordinary_selector_and_histogram_click': True,
                    'scope': 'Renderer HTTP/DOM/raw Chromium AX; no full Runtime or automatic task grading'})
                return layout
            except Exception as error:
                if page is not None:
                    (directory/'failure.html').write_text(await page.content())
                    write(directory, 'failure.json', {'metadata': {'tags': ['scripted']},
                        'url': page.url, 'error': repr(error)})
                raise
            finally:
                if context is not None: await context.close()
                await asyncio.to_thread(server.shutdown)
                server.server_close(); worker.join()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            results = await asyncio.gather(*(one(browser, layout) for layout in SKU_SUMMARY_LAYOUTS), return_exceptions=True)
            failures = [repr(value) for value in results if isinstance(value, BaseException)]
            write(output, 'result.json', {'metadata': {'tags': ['scripted']}, 'passed': [v for v in results if isinstance(v, str)],
                'failures': failures, 'provider_requests': 0, 'world_draws': 0})
            if failures: raise AssertionError(failures)
        finally: await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--world-sha256', required=True)
    args = parser.parse_args()
    asyncio.run(check(args.recipe.resolve(), args.output.resolve(), args.world_sha256))
