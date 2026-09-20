#!/usr/bin/env python3
"""Bounded browser smoke for the generated Prislyktan design preview."""
from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from export_preview import export


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='prislyktan-preview-') as temp:
        root = Path(temp)
        output = root / 'design-preview'
        export(output, '/design-preview')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}/design-preview/'
        checks: dict[str, bool] = {}
        requests: list[str] = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.on('request', lambda request: requests.append(request.url))
                page.goto(base, wait_until='domcontentloaded')
                page.wait_for_timeout(250)
                checks['preview_banner'] = page.get_by_text('Design preview — local simulated state', exact=False).count() == 1
                checks['six_pinned_cards'] = page.locator('.promo-shelf .card').count() == 6
                checks['homepage_only_pinned'] = page.locator('#products > .card').count() == 0
                page.get_by_role('searchbox', name='Sök produkter').fill('Aurora 512')
                page.get_by_role('button', name='Sök', exact=True).click()
                page.wait_for_timeout(150)
                checks['tokenized_search_url'] = '/design-preview/?q=Aurora%20512' in page.url
                product_link = page.locator('a[href$="/design-preview/products/aurora-air-14-16-512"]').first
                checks['search_result_link'] = product_link.count() == 1
                product_link.click()
                page.wait_for_timeout(150)
                checks['product_heading_after_redirect'] = page.get_by_role('heading', name='Aurora Air 14').count() == 1
                checks['product_offers_after_redirect'] = page.locator('.offer').count() == 3
                page.reload(wait_until='domcontentloaded')
                page.get_by_role('heading', name='Aurora Air 14').wait_for()
                checks['product_reload'] = page.locator('.offer').count() == 3
                page.go_back(); page.wait_for_timeout(150)
                checks['back_restores_search'] = '/design-preview/?q=Aurora%20512' in page.url and page.locator('.card').count() == 1
                for retailer in ('nordbyte', 'hemteknik', 'signalboden'):
                    page.goto(base + f'retailers/{retailer}/?product_id=aurora-air-14-16-512', wait_until='domcontentloaded')
                    page.wait_for_timeout(180)
                    checks[f'{retailer}_route'] = '/design-preview/retailers/' + retailer + '/' in page.url
                    checks[f'{retailer}_content'] = page.get_by_text('Aurora Air 14', exact=True).count() >= 1
                browser.close()
        finally:
            server.shutdown()
        checks['requests_stay_under_preview'] = all(urlsplit(url).netloc == urlsplit(base).netloc and urlsplit(url).path.startswith('/design-preview/') for url in requests)
        result = {'base': '/design-preview/', 'checks': checks, 'request_count': len(requests), 'passed': all(checks.values())}
        args.results.parent.mkdir(parents=True, exist_ok=True)
        args.results.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
