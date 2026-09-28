"""Local Chromium target-guard stall checks; no model or external website calls."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path
import time
from types import MethodType, SimpleNamespace

from playwright.sync_api import sync_playwright

from intent_browser.human_browser import HumanBrowser, GUARD_SECONDS
from intent_browser.native_capture import CaptureDeadlineExceeded
from intent_browser.targeted_guard import check


def case(mode):
    events = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('<button bid="1" onclick="window.commits++">Commit</button>'
                             '<script>window.commits=0</script>')
            cdp = page.context.new_cdp_session(page)
            tree = cdp.send('Accessibility.getFullAXTree')
            target = next(n for n in tree['nodes'] if n.get('role', {}).get('value') == 'button')
            target['browsergym_id'] = '1'
            frame = cdp.send('Page.getFrameTree')['frameTree']['frame']['id']
            cdp.detach()
            trace = SimpleNamespace(event=lambda name, **data: events.append({'event': name, **data}))
            human = SimpleNamespace(env=SimpleNamespace(page=page), trace=trace,
                                    capture_timeout_mode=mode, association={})
            human._guard_operation = MethodType(HumanBrowser._guard_operation, human)
            connection = page._impl_obj._connection
            prior_wrapper = connection.wrap_api_call
            page.evaluate('setTimeout(() => {const end=performance.now()+3200; '
                          'while(performance.now()<end){}}, 10)')
            time.sleep(.04)
            started = time.monotonic()
            result = error = None
            try:
                result = check(human,
                    {'frame_capture': {'bid_frames': {'1': frame}}, 'document': {'frame_id': frame}},
                    {'axtree_object': tree}, SimpleNamespace(name='click', arguments={'bid': '1'}))
            except CaptureDeadlineExceeded as exc:
                error = exc.document_scan_detail
            elapsed = time.monotonic() - started
            assert connection.wrap_api_call == prior_wrapper
            # This read waits for the finite fixture stall to finish, outside the timed guard.
            assert page.evaluate('window.commits') == 0
            if mode == 'bounded':
                assert error and error['scope'] == 'browser_guard', (result, error)
                assert error['phase'] == 'targeted_action'
                assert GUARD_SECONDS - .1 <= elapsed < GUARD_SECONDS + .75, elapsed
            else:
                assert error is None and result['reason'] is None, (result, error)
                assert elapsed >= 2.8, elapsed
                assert any(e['event'] == 'browser_guard_budget_overrun' for e in events)
            return {'mode': mode, 'passed': True, 'seconds': elapsed, 'error': error,
                    'events': events, 'browser_actions': 0}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Prevent an accidental overwrite before starting browser work.
    with args.output.open('x') as stream:
        with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn')) as pool:
            cases = list(pool.map(case, ('bounded', 'diagnostic')))
        root = Path(__file__).resolve().parents[1]
        hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in
                  ('intent_browser/targeted_guard.py', 'intent_browser/human_browser.py',
                   'intent_browser/native_capture.py')}
        json.dump({'passed': True, 'cases': cases, 'source_sha256': hashes,
                   'paid_model_calls': 0}, stream, indent=2)
    print(json.dumps({'passed': True, 'cases': len(cases)}))


if __name__ == '__main__':
    main()
