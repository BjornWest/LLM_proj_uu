"""Forkserver preload for hindrance_model_run.py --worker-start forkserver.

Imported once in the multiprocessing forkserver. It imports the modules every
episode process would import itself (browser stack, harness, grader, world and
publication modules, including their import-time catalogue caches), then
freezes the garbage collector so forked episode processes share those pages
copy-on-write instead of each holding a private copy.

It never raises: a failed import is recorded and that module is simply imported
by the episode process as before. The report (path from the environment) lists
the source files loaded here with their mtime/size, so the runner can switch
back to spawned workers if any of them changes on disk during a round.
"""
import gc
import json
import os
import sys
import time

MODULES = [
    'httpx', 'numpy', 'playwright.sync_api', 'browsergym.core',
    'intent_browser.backend', 'intent_browser.runner', 'intent_browser.harness',
    'intent_browser.standard_profile', 'intent_browser.automatic_grading',
    'intent_browser.hindrance_context', 'intent_browser.input_budget',
    'intent_browser.shared_tokenizer', 'intent_browser.openrouter',
    'agent_trace.adapters.browsergym',
    'training.browser_training.native_suite_recording',
    'environments.commerce_scenarios.publication',
    'environments.commerce_scenarios.episode', 'environments.commerce_scenarios.runtime',
    'environments.commerce_scenarios.consent_extras',
    'environments.commerce_scenarios.pricing_promotions',
    'environments.commerce_scenarios.steering_recurrence',
    'environments.website_world.runtime', 'environments.website_world.product_disclosure',
    'environments.website_world.catalog_adapter',
    'environments.website_world.simulated_order_task',
    'environments.website_world.simulated_order_capture',
    'environments.website_world.simulated_order_grading',
    'experiments.commerce_dark_patterns.automatic',
    'experiments.accepted_catalog_commerce.model',
    'scripts.hindrance_suite',
    # Imported lazily during an episode (measured on an offline episode, 2026-10-20).
    'httpcore', 'h11', 'anyio', 'certifi', 'jinja2', 'tokenizers', 'playwright.async_api',
    'agent_trace.collections', 'intent_browser.browser_events', 'intent_browser.browser_feedback',
    'intent_browser.browser_shutdown', 'intent_browser.cdp_json', 'intent_browser.chat_ui',
    'intent_browser.checkpoint_browser', 'intent_browser.chromium_pool',
    'intent_browser.completion_diagnostics', 'intent_browser.episode_admission',
    'intent_browser.execution_feedback', 'intent_browser.fact_provenance',
    'intent_browser.human_browser', 'intent_browser.model_input_budget',
    'intent_browser.native_capture', 'intent_browser.observation_pipeline',
    'intent_browser.observation_writer', 'intent_browser.readiness', 'intent_browser.retry_policy',
    'intent_browser.runtime_defaults', 'intent_browser.shared_browsergym',
    'intent_browser.site_discovery', 'intent_browser.step_telemetry', 'jinja2.sandbox',
    'environments.website_drafts.variation_sampling', 'environments.website_drafts.variation_settings',
    'environments.website_world.basket_fulfilment', 'environments.website_world.delivery_options',
    'environments.website_world.local_origins', 'environments.website_world.quote_offer_task',
    'environments.website_world.simulated_order_presentation',
    'environments.website_world.simulated_order_runtime',
    'experiments.accepted_catalog_commerce.delivery_admission',
    'experiments.accepted_catalog_commerce.prepared_quote',
    'experiments.commerce_dark_patterns.request_labels',
    'experiments.commerce_dark_patterns.steering_recurrence',
]
REPORT_ENV = 'HINDRANCE_WORKER_PRELOAD_REPORT'


def _preload():
    started, errors = time.time(), {}
    for name in MODULES:
        try:
            __import__(name)
        except BaseException as error:  # noqa: BLE001 - never take the forkserver down
            errors[name] = type(error).__name__ + ': ' + str(error)[:300]
    files = {}
    for module in list(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if not path:
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        files[os.path.realpath(path)] = [stat.st_mtime_ns, stat.st_size]
    gc.collect()
    gc.freeze()
    report = os.environ.pop(REPORT_ENV, None)
    if report:
        status = {}
        for line in open('/proc/self/status'):
            if line.startswith(('VmRSS', 'RssAnon')):
                status[line.split(':')[0]] = line.split(':')[1].strip()
        value = {'pid': os.getpid(), 'seconds': round(time.time() - started, 2), 'modules': len(sys.modules),
                 'errors': errors, 'memory': status, 'files': files}
        tmp = report + '.tmp'
        with open(tmp, 'w') as stream:
            json.dump(value, stream)
        os.replace(tmp, report)


try:
    _preload()
except BaseException:  # noqa: BLE001
    pass
