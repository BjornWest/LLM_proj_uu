"""Scripted package acceptance: real browsers and original graders, no inference.

Run the copied script with the copied runtime. Existing certificate suites and
live worker state remain untouched. All outputs go to a new writable directory.
"""
import argparse
import json
from pathlib import Path
import re

from intent_browser.environment_package import verify, digest
from intent_browser.environment_runtime import EnvironmentRuntime
from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.runner import run_episode


class SmallDriver:
    def __init__(self, session, positive):
        self.session,self.positive,self.index = session,positive,0
    def complete(self, messages):
        page = self.session.environment['env'].unwrapped.page
        if self.session.kind == 'ikea':
            locator = page.locator('#plan-none' if self.positive else 'input[name="protection-plan"]').first
            action = f"click({locator.get_attribute('bid')!r})"
        elif self.session.task_id == 'miniwob.click-test':
            action = f"click({page.locator('#subbtn').get_attribute('bid')!r})"
        else:
            if self.index == 0:
                # BrowserGym removes MiniWoB's query node after extracting the
                # goal. Use the actual delivered goal, not a removed DOM node.
                match = re.search(r'Enter "([^"]+)"', messages[-1]['content'])
                if self.positive and not match: raise ValueError('MiniWoB goal missing expected text')
                text = match[1] if self.positive else 'wrong answer'
                action = f"fill({page.locator('#tt').get_attribute('bid')!r}, {text!r})"
            else: action = f"click({page.locator('#subbtn').get_attribute('bid')!r})"
        if self.index >= (2 if self.session.task_id=='miniwob.enter-text' else 1):
            action = "send_msg_to_user('Scripted package check complete')"
        self.index += 1
        return Completion(action, {'source':'privileged-package-validation'})


def backend(session, positive):
    if session.kind == 'campus':
        from intent_browser.demo import RehearsalBackend
        return RehearsalBackend(session.site.area)
    if session.kind in ('miniwob','ikea'): return SmallDriver(session,positive)
    from scripts.verify_hosted_worker import driver
    return driver(session.task,session.environment,session.kind,positive)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--task',action='append')
    p.add_argument('--negative',action='store_true')
    p.add_argument('--miniwob-load-all',action='store_true',help='Reset each registered MiniWoB task; not full task completion certification')
    args = p.parse_args()
    with EnvironmentRuntime(args.package,args.output) as runtime:
        expected_sources = runtime.manifest['files']
        if args.miniwob_load_all:
            selected = next(d['tasks'] for d in runtime.manifest['datasets'] if d['id']=='miniwob')
        else:
            selected = args.task or [t for d in runtime.manifest['datasets'] if d['id']!='miniwob' for t in d['tasks']] + ['miniwob.click-test','miniwob.enter-text']
        rows = []
        for task_id in selected:
            with runtime.session(task_id) as session:
                if args.miniwob_load_all:
                    # A completed no-action diagnostic captures initial load and
                    # network evidence without claiming native task success.
                    class LoadDriver:
                        def complete(self,messages):
                            return Completion("send_msg_to_user('Load-only diagnostic')",{'source':'scripted-load-only'})
                    agent = LoadDriver()
                else: agent = backend(session,not args.negative)
                directory, result = session.run(agent,
                    metadata={'model':'none','driver':'privileged-package-validation','training_eligible':False},
                    max_steps=16,seed=42)
                events = [json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
                names = [e['event'] for e in events]
                steps = [json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()] if (directory/'steps.jsonl').exists() else []
                evaluation = result['evaluation']
                checks = {'no_technical_error':result['error'] is None,'no_action_errors':result['action_error_count']==0,
                    'no_external_browser_requests':not session.blocked,
                    'no_model_requests':all(s.get('model_request') is None for s in steps),
                    'evaluation_before_close':('environment_close_started' in names and names.index('evaluation_completed')<names.index('environment_close_started')),
                    'package_provenance':json.loads((directory/'task.json').read_text()).get('environment_package',{}).get('manifest_sha256')==runtime.manifest_hash}
                if not args.miniwob_load_all:
                    if session.kind == 'ikea': checks['diagnostic_unknown']=all(evaluation[k] is None for k in ('task_completed','authorization_satisfied','safe_success','injection_avoided'))
                    elif session.kind == 'miniwob': checks['native_success']=evaluation['task_completed'] is (not args.negative)
                    else: checks['expected_safe_success']=evaluation['safe_success'] is (not args.negative)
                row = {'task':task_id,'episode':directory.name,'checks':checks,'passed':all(checks.values()),'evaluation':evaluation,
                       'artifact_sha256':{p.name:digest(p) for p in directory.iterdir() if p.is_file()}}
                rows.append(row)
                report = {'package_sha256':runtime.manifest_hash,'passed':all(r['passed'] for r in rows),'cases':rows,
                          'model_calls':0,'downloads':0,'load_only':args.miniwob_load_all,
                          'network_isolation':'Use docker --network none to establish OS-level isolation; this script records browser requests.'}
                (runtime.state/'report.json').write_text(json.dumps(report,indent=2))
                print(json.dumps({'task':task_id,'passed':row['passed'],'checks':checks}),flush=True)
        assert verify(args.package)['files'] == expected_sources
        if not all(r['passed'] for r in rows): raise SystemExit('Some package cases failed; inspect report.json')


if __name__=='__main__': main()
