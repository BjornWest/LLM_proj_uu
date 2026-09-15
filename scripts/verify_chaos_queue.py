"""Direct native blur/click checks on a versioned Chaos FIFO build; no model calls."""
import argparse
import json
import os
from pathlib import Path
import time

import browsergym.core
import gymnasium as gym
from intent_browser.actions import make_action_set
from intent_browser.chaos import ChaosClient,ChaosTask
from intent_browser.runner import run_episode
from intent_browser.trace import write_json
from scripts.verify_chaos import FixtureDriver
from scripts.setup_chaos_repair import digest

ROOT=Path(__file__).resolve().parents[1]

class QueueTask(ChaosTask):
    def capture_initial(self,env,observation,info):
        result=super().capture_initial(env,observation,info)
        def intercept(route):
            event=route.request.post_data_json.get('event',{})
            if event.get('kind')=='input':
                if self.case=='network-failure':return route.abort('failed')
                if self.case=='delayed-input':time.sleep(.3)
            route.continue_()
        if self.case in ['delayed-input','network-failure']:
            env.unwrapped.page.route('**/api/stage/*/interact',intercept)
        return result

    def after_step(self,env,trace,index):
        result=super().after_step(env,trace,index)
        queue=env.unwrapped.page.evaluate('() => window.__intentChaosQueueSnapshot?.() ?? null')
        write_json(trace.directory/f'queue-state-{index:03d}.json',queue)
        return result

class DirectDriver(FixtureDriver):
    def plan(self):
        stage=self.task.descriptor['stage']
        edits=[('fill',key,value) for key,value in stage['check']['expectedValues'].items()]
        if self.scenario=='readonly-blur':
            edits += [('press',next(iter(stage['check']['expectedValues'])),'Tab')]
        return edits+[('click',stage['check']['mustClick'][0],None)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--report',type=Path,default=ROOT/'.local/preflight/chaos-fifo-v2.json')
    args=parser.parse_args()
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    report={'scope':'Privileged scripted FIFO repair validation, no model calls','cases':[],'complete':False,
      'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),ROOT/'intent_browser/runner.py',ROOT/'environments/chaos/stage-queue.mjs',ROOT/'environments/chaos/stage-component-prefix.js.txt']}}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    for repeat in range(2):
      for case in ['direct','delayed-input','readonly-blur','network-failure']:
        client=ChaosClient(args.base_url);task=QueueTask(client,'transfer-by-not-clicking-save',preflight=True)
        task.case=case
        environment={}
        def factory(video):
            env=gym.make('browsergym/openended',task_kwargs={'start_url':task.start_url,'goal':task.policy_goal},
                action_mapping=make_action_set().to_python_code,headless=True,slow_mo=100,wait_for_user_message=False)
            environment['env']=env
            return env
        try:
            directory,summary=run_episode(factory,DirectDriver(task,case,environment),{
                'task':'chaos.transfer-fifo-development','scenario':case,'repeat':repeat+1,
                'model':None,'driver':'privileged-scripted','training_eligible':False},
                max_steps=5,output=ROOT/'runs',episode_task=task,
                before_observation=lambda:{'source':'queue-preflight','wait_seconds':0})
            assert summary['action_error_count']==0,summary
            if case=='network-failure':
                assert summary['evaluation']['safe_success'] is None
                assert summary['evaluation']['technical_error'] is not None
            else:assert summary['error'] is None,summary
            steps=[json.loads(s) for s in (directory/'steps.jsonl').read_text().splitlines()]
            assert all(s['model_request'] is None for s in steps)
            assert sum(s['action'].startswith('click(') for s in steps)==1
            queue=json.loads(sorted(directory.glob('queue-state-*.json'))[-1].read_text())
            assert queue and queue['version']=='stage-fifo-v2'
            session=json.loads((directory/'chaos-session.json').read_text())
            assert queue['context']['session']==session['session']
            assert queue['context']['challengeId']==task.task_id
            assert queue['context']['mountNonce'] and queue['unmountedAt'] is None
            events=queue['events'];dispatched=[e for e in events if e['phase']=='dispatched']
            raw=json.loads((directory/'external_evaluation.json').read_text())
            server=[e for e in raw['events']['events'] if e['event'] in ['input','click']]
            if case=='network-failure':
                assert len(dispatched)==1 and dispatched[0]['kind']=='input'
                assert queue['reason']=='request_failed' and not server
                assert any(e['phase']=='discarded' and e['kind']=='click' for e in events)
            else:
                assert summary['evaluation']['safe_success'] is True
                assert queue['reason']=='terminal:success'
                assert [e['kind'] for e in dispatched]==(['input','input','click'] if case=='readonly-blur' else ['input','click'])
                assert [e['event'] for e in server]==[e['kind'] for e in dispatched]
                assert all(e['metadata']['isTrusted'] is True for e in server)
                commit=next(e for e in server if e['event']=='click')
                assert commit['metadata']['target']==task.descriptor['stage']['check']['mustClick'][0]
                assert raw['selected_results'][0]['mountCount']==1
            lifecycle=[json.loads(s)['event'] for s in (directory/'events.jsonl').read_text().splitlines()]
            assert lifecycle.index('evaluation_completed')<lifecycle.index('environment_close_started')
            report['cases'].append({'case':case,'repeat':repeat+1,'episode':str(directory.relative_to(ROOT)),
                'evaluation':summary['evaluation'],'queue':queue,'server_interactions':server,'passed':True,
                'artifact_sha256':{p.name:digest(p) for p in directory.iterdir() if p.suffix in ['.json','.jsonl','.txt']}})
            write_json(args.report,report);print(case,repeat+1,'passed',flush=True)
        finally:client.close()
    report['complete']=True;write_json(args.report,report);print(args.report)

if __name__=='__main__':main()
