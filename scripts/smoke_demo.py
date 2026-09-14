"""Exercise all three Daylight rehearsals through the UI; never request inference."""
import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', default='http://localhost:8879')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/review/demo-smoke')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    libraries = ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu'
    if libraries.is_dir():
        os.environ['LD_LIBRARY_PATH'] = str(libraries) + ':' + os.getenv('LD_LIBRARY_PATH', '')
    results, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.origin)
        page.wait_for_function('!document.querySelector("#run").disabled')
        page.click('#tasks-tab')
        page.select_option('#mode', 'rehearsal')
        initial_world=page.evaluate('world')
        for area in ('shop', 'booking', 'preferences'):
            page.click(f'[data-area={area}]')
            page.wait_for_function('!document.querySelector("#run").disabled')
            assert page.evaluate('world') == initial_world
            with page.expect_response('**/api/run') as response:
                page.click('#run')
            job = response.value.json()['job']
            page.wait_for_function('!document.querySelector("#run").disabled', timeout=60000)
            result = page.request.get(args.origin + '/api/jobs/' + job).json()
            results.append({'area': area, **result})
            assert result['mode'] == 'rehearsal' and not result['error'], result
            assert result['result']['title'] == 'Taken care of.', result
            assert page.locator('#outcome').is_visible()
            page.screenshot(path=str(args.output / f'{area}.png'), full_page=True)
            page.click('#resume-page')
            assert page.locator('#site').is_visible()
            assert page.evaluate('world') == initial_world
            print(area, result['episode'], 'passed', flush=True)
        page.click('[data-area=shop]')
        page.wait_for_function('!document.querySelector("#run").disabled')
        page.frame_locator('#site').get_by_role('heading', name='Ready for your next idea.').wait_for()
        page.screenshot(path=str(args.output / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(args.output / 'mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert not errors, errors
        browser.close()
    (args.output / 'results.json').write_text(json.dumps(results, indent=2))
    print('Three rehearsals and responsive UI passed. No model calls.')


if __name__ == '__main__':
    main()
