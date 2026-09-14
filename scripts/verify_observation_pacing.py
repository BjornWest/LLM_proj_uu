"""Scripted BrowserGym comparison of stale internal pacing and fresh capture. No API calls."""
import hashlib
import json
import os
from pathlib import Path
import re
import time

from browsergym.core.env import BrowserEnv
from browsergym.core.task import AbstractBrowserTask

from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.runner import run_episode
from intent_browser.trace import write_json

HTML = '''<!doctype html><title>Observation timing fixture</title>
<h1>Continue after the notification</h1>
<button id="show" onclick="showNotice()">Show notification</button>
<button id="continue" onclick="document.body.dataset.done='true';document.querySelector('#result').textContent='Completed'">Continue</button>
<p id="result"></p>
<script>function showNotice(){const b=document.createElement('button');b.textContent='Transient Close';b.onclick=()=>b.remove();document.body.append(b);setTimeout(()=>b.remove(),2000);}</script>'''


class TransientTask(AbstractBrowserTask):
    @classmethod
    def get_task_id(cls): return 'development.transient-observation'

    def setup(self, page):
        page.set_content(HTML)
        return 'Show the notification, then continue.', {}

    def validate(self, page, chat_messages):
        done = page.locator('body').get_attribute('data-done') == 'true'
        return float(done), done, '', {'fixture_completed': done}

    def teardown(self): pass


class ScriptedPolicy:
    def __init__(self, fresh): self.calls, self.fresh = 0, fresh

    def wait_until_ready(self):
        if self.calls: time.sleep(3)
        return {'requested_wait_seconds': 3 if self.calls else 0, 'source': 'scripted pacing test'}

    def complete(self, messages):
        if not self.fresh: self.wait_until_ready()  # Deliberate old ordering for the control case.
        text = messages[-1]['content']
        label = 'Show notification' if not self.calls else 'Transient Close' if "button 'Transient Close'" in text else 'Continue'
        bid = re.search(r"\[([^\]]+)\] button '" + re.escape(label) + "'", text)
        if not bid: raise ValueError('Scripted fixture control absent: ' + label)
        self.calls += 1
        return Completion(f"click('{bid[1]}')", {'source': 'scripted-observation-timing-fixture'})


def main():
    root = Path(__file__).resolve().parents[1]
    libraries = root/'.local/system-libs/usr/lib/x86_64-linux-gnu'
    if libraries.is_dir(): os.environ['LD_LIBRARY_PATH'] = str(libraries)+':'+os.getenv('LD_LIBRARY_PATH','')
    records=[]
    for fresh in [False, True]:
        backend=ScriptedPolicy(fresh)
        def factory(video):
            return BrowserEnv(task_entrypoint=TransientTask,headless=True,slow_mo=0,timeout=500,
                pre_observation_delay=.1,action_mapping=make_action_set().to_python_code,
                record_video_dir=video,wait_for_user_message=False)
        path,summary=run_episode(factory,backend,{
            'task':'development.transient-observation','model':'scripted-policy','verifier':'fixture-native',
            'training_eligible':False,'network_model_calls':0,'fixture_sha256':hashlib.sha256(HTML.encode()).hexdigest(),
            'condition':'fresh-after-wait' if fresh else 'legacy-wait-inside-complete'},
            output=root/'runs',max_steps=2,record_video=True,
            before_observation=backend.wait_until_ready if fresh else None)
        rows=[json.loads(line) for line in (path/'steps.jsonl').read_text().splitlines()]
        assert backend.calls==len(rows)==summary['browser_step_count']==2
        assert summary['error'] is None
        assert "button 'Transient Close'" in (path/'observation-001.txt').read_text()
        assert bool(rows[1].get('action_error')) is not fresh
        assert summary['success'] is (True if fresh else None)
        assert summary['final_info']['task_info']['fixture_completed'] is fresh
        if fresh:
            assert "button 'Transient Close'" not in rows[1]['messages'][-1]['content']
            assert rows[1]['pacing_seconds']>=3 and rows[1]['request_seconds']<1
            assert rows[1]['observation']['text']=='decision-observation-001.txt'
        else:
            assert "button 'Transient Close'" in rows[1]['messages'][-1]['content']
            assert rows[1]['request_seconds']>=3 and rows[1]['pacing_seconds']==0
        for row in rows:
            assert (path/row['observation']['text']).read_text() in row['messages'][-1]['content']
            assert row['model_request'] is None  # Scripted policy, no invented HTTP request.
        events=[json.loads(line) for line in (path/'events.jsonl').read_text().splitlines()]
        names=[e['event'] for e in events]
        assert names.index('evaluation_completed')<names.index('environment_close_started')
        files=['metadata.json','steps.jsonl','events.jsonl','episode.json','evaluation.json']
        files+=sorted(p.name for p in path.glob('*observation-*.txt'))
        records.append({'condition':'fresh-after-wait' if fresh else 'legacy-wait-inside-complete',
            'episode':str(path.relative_to(root)),'native_success':summary['success'],
            'fixture_completed':summary['final_info']['task_info']['fixture_completed'],
            'action_error_count':summary['action_error_count'],'timing_totals':summary['timing_totals'],
            'artifacts_sha256':{file:hashlib.sha256((path/file).read_bytes()).hexdigest() for file in files}})
    report={'scope':'Scripted local BrowserGym integration; no model, search or real-site calls',
            'cases':records,'source_sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
                ['intent_browser/runner.py','intent_browser/observation.py','intent_browser/trace.py','scripts/verify_observation_pacing.py']}}
    target=root/'.local/preflight/observation-pacing.json';target.parent.mkdir(parents=True,exist_ok=True)
    write_json(target,report)
    print('Both timing conditions verified:',target)


if __name__=='__main__': main()
