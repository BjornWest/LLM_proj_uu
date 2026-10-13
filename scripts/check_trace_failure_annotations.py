"""Model-free checks of derived notes through the existing metadata API."""
import argparse
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent / 'common_agent_util')]
from scripts.trace_hub import make_handler
from tests.test_trace_failure_annotations import fixture, write


def main(output, native=False):
    output.mkdir(parents=True, exist_ok=False)
    checks, errors = [], []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest, cases = fixture(root)
        pins = {pin['path']: hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest() for case in cases for pin in case['evidence']}
        plan = root / 'suite.json'
        write(plan, {'schema': 'episode-suite-plan-v1', 'id': 'failures', 'title': 'Failures', 'cases': [
            {'case_id': c['case'], 'task_id': c['case'], 'repeat': 1, 'trace_directory': str(root / 'runs' / c['episode_id']), 'model': {'model': 'scripted', 'transport': 'scripted'}} for c in cases]})
        registry = root / 'sources.json'
        write(registry, {'project_root': str(root), 'roots': [str(root / 'runs')], 'suites': [str(plan)]})
        registry_bytes = registry.read_bytes()
        if native:
            from scripts.atomic_address_trace_hub import AddressStateHub, viewer_html
            handler=make_handler(registry,hub_class=AddressStateHub,html_factory=viewer_html)
        else: handler=make_handler(registry)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1400, 'height': 1000})
                page.on('pageerror', lambda error: errors.append(str(error)))
                for c in cases:
                    page.goto(base + '/#' + c['session_id'])
                    page.wait_for_selector('#failure-annotation')
                    page.locator('#live').uncheck()
                    label = 'Automatic answer grading failed' if c['case'] == 'H03' else 'Cancelled after a sibling infrastructure failure'
                    assert label in page.locator('#failure-annotation').inner_text()
                    assert c['grading_error'] in page.locator('#failure-annotation').inner_text()
                    assert 'No native task verdict' in page.locator('#failure-annotation').inner_text()
                    checks.append(c['case'] + ' distinct stage and error, with unknown verdict preserved')
                page.locator('#failure-annotation summary').first.click()
                assert page.locator('#failure-annotation summary', has_text='JSON · 5 items').count() == 1
                checks.append('bound evidence uses the existing rendered JSON display')
                page.evaluate("window.keptFailureNote=document.querySelector('#failure-annotation details')")
                page.evaluate('refresh({background:true})')
                assert page.evaluate("keptFailureNote===document.querySelector('#failure-annotation details')&&keptFailureNote.open")
                checks.append('unchanged polling retains the note and open evidence')
                page.evaluate('collectionState={...collectionState};delete collectionState.failure_annotations;list()')
                assert 'No native task verdict' in page.locator('#failure-annotation').inner_text()
                checks.append('classification response without annotations retains the last verified note')
                page.evaluate('refresh({background:true})')
                page.evaluate("window.savedFailureAnnotation=collectionState.failure_annotations.entries[current.id];collectionState.failure_annotations.entries[current.id]={...savedFailureAnnotation,trace_directory:'/different/recording'};list()")
                assert 'different recording directory' in page.locator('#failure-annotation').inner_text()
                assert 'No native task verdict' not in page.locator('#failure-annotation').inner_text()
                checks.append('recording-directory mismatch suppresses claims and verdict commentary')
                page.evaluate("collectionState.failure_annotations.entries[current.id]=savedFailureAnnotation;list()")
                page.locator('#show-suites').click()
                page.wait_for_selector('#suite-view .suite-card')
                page.locator('.suite-card>a').click()
                page.wait_for_selector('#suite-view table')
                assert page.locator('.failure-stage-note').count() == 2
                assert all('technical error' in row.inner_text() for row in page.locator('#suite-view tbody tr').all())
                checks.append('suite execution keeps original technical errors and adds distinct derived notes')
                page.locator('#suite-view tbody tr').last.get_by_role('link', name='Open trace').click()
                page.wait_for_selector('#failure-annotation')
                page.locator('#live').uncheck()
                case = next(c for c in cases if c['session_id'] == page.evaluate('current.id'))
                target = Path(case['evidence'][0]['path']); saved = target.read_bytes(); target.write_bytes(saved + b' ')
                page.evaluate('refresh({background:true})')
                assert 'annotation unavailable' in page.locator('#failure-annotation').inner_text()
                assert 'Annotation evidence changed' in page.locator('#failure-annotation').inner_text()
                checks.append('changed evidence removes claims and shows unavailable annotation')
                target.write_bytes(saved)
                page.evaluate('refresh({background:true})')
                assert 'No native task verdict' in page.locator('#failure-annotation').inner_text()
                checks.append('restored evidence restores the derived note')
                # Bad global metadata only affects previously annotated traces.
                manifest.write_text('{broken'); page.evaluate('refresh({background:true})')
                assert 'annotation unavailable' in page.locator('#failure-annotation').inner_text()
                page.evaluate("current={id:'unannotated',recording_locations:[]};renderFailureAnnotation()")
                assert page.locator('#failure-annotation').is_hidden()
                checks.append('malformed manifest does not label an unannotated trace as failed')
                write(manifest, {'schema': 'evaluation-derived-failure-stages-v1', 'cases': cases})
                page.evaluate('refresh()');page.wait_for_selector('#failure-annotation')
                page.locator('#live').uncheck()
                page.screenshot(path=str(output / 'desktop.png'), full_page=True)
                manifest.unlink(); page.evaluate('refresh({background:true})')
                assert page.locator('#failure-annotation').is_hidden()
                checks.append('removing annotation clears display independently of cached trace body')
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors, errors
                assert registry.read_bytes() == registry_bytes
                assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == pin for path, pin in pins.items())
                checks.append('mobile fits; no JavaScript errors; original evidence and registry preserved')
                browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()
    (output / 'report.json').write_text(json.dumps({'checks': checks, 'errors': errors, 'models': 0}, indent=2) + '\n')
    print(json.dumps({'passed': len(checks)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True);parser.add_argument('--native',action='store_true')
    args = parser.parse_args()
    libraries = next((parent / '.local/system-libs/usr/lib/x86_64-linux-gnu' for parent in (ROOT, *ROOT.parents) if (parent / '.local/system-libs/usr/lib/x86_64-linux-gnu').is_dir()), None)
    if libraries: os.environ['LD_LIBRARY_PATH'] = str(libraries) + ':' + os.getenv('LD_LIBRARY_PATH', '')
    main(args.output,args.native)
