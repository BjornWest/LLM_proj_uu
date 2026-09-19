"""NEW native-profile browser cases; historical legacy records remain unchanged."""
import argparse
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from browsergym.core.env import BrowserEnv
from intent_browser.actions import make_action_set
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from scripts.harness_suite_tasks import scripted_backend
from data.curation.expansion.webarena.browser_batch import Driver, ReadOnlyTask, HEADERS
from data.curation.expansion.webarena.inventory import BATCH, SOURCE


class BrowserNegative(Driver):
    """Actually reads/visits the correct target, then emits a wrong outcome."""
    def steps(self):
        for action in super().steps():
            if not action.startswith('send_msg_to_user('):
                yield action
                continue
            self.record('correct_before_negative', {'url': self.page.url, 'response': self.response})
            if self.task_id in (158, 260, 324):
                yield self.act(self.page.locator('a.logo'))
                self.record('wrong_final_destination', {'url': self.page.url})
                assert urlsplit(self.page.url).path == '/'
                yield self.finish()
            else:
                self.record('deliberately_wrong_response', {'retrieved_data': []})
                yield self.finish([])


def source_hashes():
    paths = list((ROOT / 'intent_browser').glob('*.py'))
    paths += [Path(__file__), ROOT/'data/curation/expansion/webarena/browser_batch.py',
              ROOT/'scripts/harness_suite_tasks.py', SOURCE]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    task = next(t for t in json.loads(SOURCE.read_text()) if t['task_id'] == args.task)
    site = task['sites'][0]
    origin = args.reddit_origin if site == 'reddit' else args.shopping_origin
    if urlsplit(origin).hostname != 'localhost':
        raise ValueError('Local rehearsal origins only')
    start = task['start_urls'][0].replace('__' + site.upper() + '__', origin)
    before = source_hashes()
    (args.output/'source-before.json').write_text(json.dumps(before, indent=2))
    profile = native_tools_profile(parallel_tool_calls=None, compact_feedback=True,
                                   reasoning_replay='preserve')
    (args.output/'profile.json').write_text(json.dumps({
        'id': 'webarena-expansion-native-v1', 'harness': profile.describe(),
        'observation_chars': 48000, 'observation_units': 'flattened AX characters',
        'max_steps': 50, 'model_calls': 0, 'scripted_variant': args.variant,
        'driver_assistance': 'Privileged DOM extraction and selectors',
        'source_sha256': before}, indent=2))
    blocked = []
    driver = (BrowserNegative if args.variant == 'negative' else Driver)(args.task)
    backend = scripted_backend(driver)
    with tempfile.TemporaryDirectory(prefix='wav-native-expansion-') as temporary:
        har = Path(temporary)/'network.har'
        def factory(video):
            env = BrowserEnv(task_entrypoint=ReadOnlyTask,
                task_kwargs={'start_url': start, 'goal': task['intent'], 'blocked': blocked},
                headless=True, slow_mo=100, timeout=10000, pre_observation_delay=1,
                action_mapping=make_action_set().to_python_code, wait_for_user_message=False,
                pw_context_kwargs={'extra_http_headers': HEADERS[site],
                    'record_har_path': str(har), 'record_har_content': 'embed', 'service_workers': 'block'})
            driver.env = env
            return env
        try:
            trace, summary = run_episode(factory, backend, {
                'task': 'webarena-verified.expansion-native', 'source_task_id': args.task,
                'goal': task['intent'], 'driver': 'privileged-scripted-native',
                'model': None, 'network_model_calls': 0, 'training_eligible': False,
                'variant': args.variant, 'profile_reference': str(args.output/'profile.json')},
                output=args.output/'traces', max_steps=50, observation_text_limit=48000,
                harness_profile=profile, before_observation=lambda: {'scripted_wait_seconds': 0})
            if har.exists():
                (trace/'network.har').write_bytes(har.read_bytes())
        finally:
            backend.close()
    after = source_hashes()
    (args.output/'source-after.json').write_text(json.dumps(after, indent=2))
    steps = [json.loads(line) for line in (trace/'steps.jsonl').read_text().splitlines()]
    final_text = (trace/summary['final_observation']['text']).read_text()
    final_url = final_text.splitlines()[0].removeprefix('URL: ')
    row = {'task_id': args.task, 'trace': str(trace), 'variant': args.variant,
           'summary': summary, 'derived_response': driver.response,
           'final_url': final_url, 'blocked_requests': blocked,
           'source_unchanged': before == after,
           'browser_positive': args.variant == 'positive' and summary['error'] is None
               and summary['action_error_count'] == 0 and driver.response is not None,
           'scripted_path_completed': summary['error'] is None and driver.response is not None,
           'intended_outcome': args.variant == 'positive',
           'delivery_aligned': all(item['aligned'] and item['confirmed'] for step in steps
               for item in step.get('policy_delivery', {}).get('items', [])),
           'offline_transport_requests': len(steps), 'network_model_calls': 0,
           'training_ready': False, 'authorization_preserved': None,
           'evidence': driver.evidence}
    (trace/'native-case-validation.json').write_text(json.dumps(row, indent=2))
    (args.output/'report.json').write_text(json.dumps({'schema': 'webarena-native-case-v1',
        'tasks': [{k: v for k, v in row.items() if k != 'evidence'}],
        'scope': 'New native profile; scripted browser paths, original goal; no model capability claim'}, indent=2))
    print(json.dumps({k: row[k] for k in ('task_id','variant','scripted_path_completed','source_unchanged','final_url')}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=int, choices=BATCH, required=True)
    parser.add_argument('--variant', choices=['positive', 'negative'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--shopping-origin', default='http://localhost:7770')
    parser.add_argument('--reddit-origin', default='http://localhost:18999')
    args = parser.parse_args()
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH','')
    run(args)


if __name__ == '__main__':
    main()
