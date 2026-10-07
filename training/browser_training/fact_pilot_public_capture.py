"""Private source-availability capture for the bounded retailer/review pilot.

This is separate from the policy browser and never creates delivery receipts.
It consumes frozen runtime bindings, without winner/outcome-based page selection.
"""
from hashlib import sha256
import json
from pathlib import Path

from .fact_compare_review_features import compile_roles
from .fact_public_readiness import audit_captures
from .fact_source_provider import FactSourceProvider


def capture_targets(runtime, task):
    """Every carried retailer model page and independent review model route."""
    models = [m['product_id'] for m in task['comparison_task']['models']]
    if len(models) != 2 or len(set(models)) != 2:
        raise ValueError('The pilot requires exactly two model identities')
    targets = []
    seen = set()

    def add(family, pid, url):
        key = (family, pid, url)
        if key in seen:
            return
        seen.add(key)
        targets.append({'source_family': family, 'product_id': pid, 'url': url,
                        'transport_url': runtime.preview_url(url)})

    for sid, catalog in sorted(runtime.public_catalogs.items()):
        for product in catalog['products']:
            if product['canonicalProductId'] in models:
                add('retailer', product['canonicalProductId'],
                    runtime.bindings['retailer_pages'][sid][product['id']])
    for pid in models:
        for url in runtime.bindings['surrounding']['review_products'].get(pid, []):
            add('product_reviews', pid, url)
    return targets


class FactPilotPublicAudit:
    """One browser, private context, exact committed captures; no retries.

    Pass this source-pinned callable to the copied compound consumer. An actual
    source-union/resource release is required before invoking it. The Runtime
    must already serve the enabled copied retailer and review renderers.
    """
    def __init__(self, output):
        self.output = Path(output).resolve()

    def __call__(self, *, runtime, task, reference):
        from playwright.sync_api import sync_playwright
        from environments.website_world.catalog_compare_review_execution import public_binding
        roles = compile_roles(task)
        if reference['task_id'] != task['task_id'] or any(not role['dependencies'] for role in roles):
            raise ValueError('Unsupported public-audit task/reference roles')
        targets = capture_targets(runtime, task)
        self.output.mkdir(parents=True, exist_ok=False)
        paths = []
        receipts = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            provider = None
            try:
                context = browser.new_context(accept_downloads=False, service_workers='block')
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                provider = FactSourceProvider(page, enabled=True)
                provider.install()
                for n, target in enumerate(targets):
                    # No inherited previous-document commit can satisfy this read.
                    provider.latest = None
                    page.goto(target['transport_url'])
                    page.wait_for_load_state('networkidle')
                    page.wait_for_selector('#app' if target['source_family'] == 'retailer' else '#main')
                    if errors:
                        raise ValueError('Public source renderer errors: '+repr(errors))
                    observation = provider.observe(lambda: {'axtree_object': {
                        'nodes': provider.cdp.send('Accessibility.getFullAXTree')['nodes']}})
                    result = provider.result(observation)
                    if result is None:
                        raise ValueError('Public source capture could not be paired: '+repr(provider.diagnostics))
                    path = self.output/f'capture-{n:03d}.json'
                    raw = (json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode()
                    with path.open('xb') as stream:
                        stream.write(raw)
                    paths.append(path)
                    receipts.append({**target, 'path': str(path), 'sha256': sha256(raw).hexdigest(),
                                     'snapshot_id': result['normalized']['snapshot_id'],
                                     'delivery_evidence': False})
            finally:
                _close_capture(provider, browser)
        report = audit_captures(task, reference, paths, runtime_binding_sha256=public_binding(runtime))
        (self.output/'manifest.json').write_text(json.dumps({
            'schema': 'fact-pilot-public-capture-manifest-v1', 'task_id': task['task_id'],
            'captures': receipts, 'policy_browser': False, 'delivery_evidence': False,
            'retries': 0, 'report_status': report['status']}, indent=2)+'\n')
        return report


def _close_capture(provider, browser):
    """Preserve both cleanup errors in the text consumed by the outer runner."""
    provider_error = None
    try:
        if provider is not None:
            provider.close()
    except BaseException as error:
        provider_error = error
    try:
        browser.close()
    except BaseException as browser_error:
        if provider_error is not None:
            raise RuntimeError(
                f'Fact provider cleanup failed ({type(provider_error).__name__}): {provider_error}; '
                f'browser cleanup failed ({type(browser_error).__name__}): {browser_error}'
            ) from browser_error
        raise
    if provider_error is not None:
        raise provider_error
