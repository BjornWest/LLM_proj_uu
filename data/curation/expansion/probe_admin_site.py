"""Full Shopping Admin site gate and original navigation task157 rehearsal.

Privileged scripted controls, no model calls. Secondary back-office capability
probe; does not add this task to the primary consumer-assistant catalog.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from browsergym.core.env import BrowserEnv
from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.runner import run_episode
from scripts.smoke_webarena_controls import LocalSiteTask

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = 'http://localhost:17780'


class Driver:
    def __init__(self):
        self.env = None
        self.step = 0
        self.evidence = []

    def complete(self, messages):
        page = self.env.unwrapped.page
        self.evidence.append({'url': page.url, 'body': page.locator('body').inner_text()})
        if self.step == 0:
            locator = page.locator('#menu-magento-customer-customer a').first
        elif self.step == 1:
            locator = page.get_by_role('link', name='All Customers', exact=True)
        else:
            assert '/customer/index' in page.url
            assert page.get_by_role('heading', name='Customers', exact=True).is_visible()
            return Completion("send_msg_to_user('Done')", {'source': 'privileged-scripted-site-gate', 'model_calls': 0})
        bid = locator.get_attribute('bid')
        assert bid and f'[{bid}]' in messages[-1]['content'], 'Target missing from delivered AX'
        self.step += 1
        return Completion(f'click({bid!r})', {'source': 'privileged-scripted-site-gate', 'model_calls': 0})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.environ.get('LD_LIBRARY_PATH', '')
    blocked = []
    driver = Driver()
    def factory(video):
        env = BrowserEnv(task_entrypoint=LocalSiteTask,
                        task_kwargs={'start_url': ORIGIN+'/admin', 'goal': 'View the details of all customers', 'diagnostics': blocked},
                        headless=True, slow_mo=100, timeout=10000,
                        action_mapping=make_action_set().to_python_code,
                        pw_context_kwargs={'extra_http_headers': {'X-M2-Admin-Auto-Login': 'admin:admin1234'},
                                           'record_har_path': str(args.output/'network.har'), 'record_har_content': 'embed', 'service_workers': 'block'},
                        wait_for_user_message=False)
        driver.env = env
        return env
    folder, summary = run_episode(factory, driver, {'source': 'webarena-verified', 'source_task_id': 157,
                               'model': None, 'driver': 'privileged-scripted', 'scope': 'Secondary back-office site gate', 'training_eligible': False},
                               output=args.output/'traces', max_steps=5, observation_text_limit=48000)
    inspect = json.loads(subprocess.check_output(['docker', 'inspect', 'curation-webarena-admin-v1-shopping_admin-1']))[0]
    report = {'schema_version': 1, 'scope': 'ShoppingAdmin complete-site gate; task157 navigation rehearsal only',
              'trace': str(folder.resolve().relative_to(ROOT)), 'summary': summary, 'page_evidence': driver.evidence,
              'off_origin_requests_blocked': blocked, 'container_id': inspect['Id'], 'image_id': inspect['Image'],
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'model_calls': 0, 'native_grader': None, 'task_accepted': False,
              'site_gate_passed': summary['error'] is None and summary['action_error_count'] == 0 and driver.step == 2}
    with (args.output/'report.json').open('x') as out:
        json.dump(report, out, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k not in ('summary', 'page_evidence')}, indent=2))


if __name__ == '__main__':
    main()
