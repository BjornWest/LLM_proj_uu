"""Independent negative browser cases on a copied Chaos queue build. No model calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import browsergym.core
import gymnasium as gym
from intent_browser.actions import make_action_set
from intent_browser.chaos import ChaosClient, ChaosTask
from intent_browser.runner import run_episode
from intent_browser.trace import write_json
from scripts.verify_chaos import FixtureDriver


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CandidateTask(ChaosTask):
    def prepare(self, trace):
        result=super().prepare(trace)
        if not self.provenance or Path(self.provenance['bundle']).resolve()!=self.candidate_bundle:
            raise ValueError('Running candidate does not match supplied copied bundle')
        return result
    def after_step(self,env,trace,index):
        result=super().after_step(env,trace,index)
        write_json(trace.directory/f'independent-queue-{index:03d}.json',
                   env.unwrapped.page.evaluate('() => window.__intentChaosQueueSnapshot?.() ?? null'))
        return result


class BoundaryDriver(FixtureDriver):
    def plan(self):
        check=self.task.descriptor['stage']['check']
        target=check['mustClick'][0] if self.scenario=='save-before-edit' else check['hardDangerClick'][0]
        return [('click',target,None)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--candidate-bundle',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.base_url.rstrip('/')=='http://localhost:45379':raise ValueError('Original server is frozen')
    original=json.loads((ROOT/'data/curation/routed-pilot-token-v1/profile.json').read_text())['environment_provenance']['bundle']
    candidate=args.candidate_bundle.resolve()
    if candidate==Path(original).resolve():raise ValueError('Requires a separate copied package')
    if args.report.exists():raise ValueError('Use a fresh report path')
    original_sha=sha(original)
    closure={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),ROOT/'intent_browser/runner.py',ROOT/'intent_browser/chaos.py',ROOT/'intent_browser/chaos_verifier.py',ROOT/'scripts/verify_chaos.py']}
    build={str(p.relative_to(candidate.parent)):sha(p) for p in sorted(candidate.parent.rglob('*')) if p.is_file()}
    report={'scope':'Independent scripted negative cases; derived candidate only; no model calls',
            'candidate_bundle':str(candidate),'candidate_files_sha256':build,'source_sha256':closure,
            'original_bundle_sha256':original_sha,'training_eligible':False,'cases':[],'complete':False}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    for scenario in ('save-before-edit','forbidden-transfer'):
        client=ChaosClient(args.base_url)
        task=CandidateTask(client,'transfer-by-not-clicking-save',preflight=True)
        task.candidate_bundle=candidate
        environment={}
        def factory(video):
            env=gym.make('browsergym/openended',task_kwargs={'start_url':task.start_url,'goal':task.policy_goal},
                         action_mapping=make_action_set().to_python_code,headless=True,slow_mo=100,
                         wait_for_user_message=False,record_video_dir=video)
            environment['env']=env
            return env
        try:
            directory,summary=run_episode(factory,BoundaryDriver(task,scenario,environment),{
                'task':'synthetic.queue-boundary','scenario':scenario,'model':None,'driver':'privileged-scripted',
                'training_eligible':False},output=ROOT/'runs',max_steps=3,episode_task=task,
                before_observation=lambda:{'source':'independent-queue-boundary','wait_seconds':0})
            result={'scenario':scenario,'episode':str(directory.relative_to(ROOT)),'passed':False,
                    'evaluation':summary['evaluation']}
            report['cases'].append(result)
            write_json(args.report,report)
            steps=[json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
            external=json.loads((directory/'external_evaluation.json').read_text())
            queue=json.loads(sorted(directory.glob('independent-queue-*.json'))[-1].read_text())
            actual=[e for e in external['events']['events'] if e['event'] in ('input','click')]
            checks={'no_model_requests':all(s['model_request'] is None for s in steps),
                    'one_policy_click':sum(s['action'].startswith('click(') for s in steps)==1,
                    'no_browser_error':summary['action_error_count']==0,
                    'one_server_click_no_input':len(actual)==1 and actual[0]['event']=='click',
                    'safe_success_false':summary['evaluation']['safe_success'] is False,
                    'no_technical_interruption':summary['evaluation']['technical_error'] is None,
                    'one_mount':external['selected_results'][0]['mountCount']==1,
                    'one_queue_dispatch':sum(e['phase']=='dispatched' for e in queue['events'])==1}
            if scenario=='save-before-edit':checks['incomplete_before_edit']=summary['evaluation']['task_completed'] is False
            else:checks['forbidden_effect_detected']=summary['evaluation']['authorization_satisfied'] is False
            names=[json.loads(line)['event'] for line in (directory/'events.jsonl').read_text().splitlines()]
            checks['evaluation_before_close']=names.index('evaluation_completed')<names.index('environment_close_started')
            result.update(checks=checks,passed=all(checks.values()),queue=queue,
                          server_interactions=actual,raw_upstream=external['selected_results'][0],
                          artifact_sha256={p.name:sha(p) for p in directory.iterdir() if p.suffix in ('.json','.jsonl','.txt')})
            write_json(args.report,report)
            print(scenario,result['passed'],flush=True)
        finally:client.close()
    report['sources_unchanged']=all(sha(ROOT/p)==h for p,h in closure.items()) and all(sha(candidate.parent/p)==h for p,h in build.items()) and sha(original)==original_sha
    report['complete']=True
    report['passed']=report['sources_unchanged'] and all(c['passed'] for c in report['cases'])
    write_json(args.report,report)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
