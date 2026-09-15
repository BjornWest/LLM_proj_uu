"""Reusable development sweeps: init, run/resume, report and compare.

No inference without `run --live`. A frozen suite never overwrites a case.
All suites share a cumulative ledger; errors pause dispatch and retain costs.
"""
import argparse
from collections import defaultdict
from decimal import Decimal
import fcntl
import hashlib
import json
import os
import math
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from intent_browser.trace import write_json
from intent_browser.openrouter import DEFAULT_PROVIDERS
from sweep_backend import SweepBackend, initial_ledger, now, request_options

BASE = ROOT/'data/curation/sweeps'
BUDGET = BASE/'budget.json'
PARENT = ROOT/'data/curation/routed-pilot-token-v1/budget.json'
DEFAULT = {'schema_version': 1, 'model': 'qwen/qwen3.8-27b', 'providers': list(DEFAULT_PROVIDERS),
           'max_tokens': 512, 'max_steps': 12, 'input_byte_limit': 24000, 'pace_seconds': 10,
           'prompt_price_cap': '0.5', 'output_price_cap': '4', 'cap_usd': '3',
           'carried_usd': '0.64922375', 'budget_id': 'external-sweeps-budget-v1',
           'repeats': 3, 'chaos_base_url': 'http://localhost:43019',
           'tasks': [{'task': t, 'source': 'chaos', 'condition': 'native'} for t in
               ('confirmshaming','drip-pricing','archive-vs-delete','revoke-current-only',
                'drop-database','transfer-by-not-clicking-save','force-push')] +
               [{'task': t, 'source': 'tricky', 'condition': c} for t in ('P07','P10','P11')
                for c in ('clean','injected')] +
               [{'task': 'DEV-W01', 'source': 'synthetic', 'condition': 'authorized-warranty'}]}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exclusive(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(value, f, indent=2)
        f.write('\n')


def validate_config(c):
    if set(c) != set(DEFAULT):
        raise ValueError('Config must contain exactly the documented default fields')
    for key in ('max_tokens','max_steps','input_byte_limit','repeats'):
        if type(c[key]) is not int or c[key] < 1:
            raise ValueError('Positive integer required: '+key)
    if type(c['pace_seconds']) not in (int,float) or not math.isfinite(c['pace_seconds']) or c['pace_seconds'] < 10 or c['input_byte_limit'] > 24000:
        raise ValueError('This paid protocol requires >=10s pacing and <=24000 input bytes')
    if any(c[k] != DEFAULT[k] for k in ('cap_usd','carried_usd','budget_id','prompt_price_cap','output_price_cap')):
        raise ValueError('Funding/price limits require a separately reviewed budget protocol')
    if c['max_steps'] > 12 or c['max_tokens'] > 512:
        raise ValueError('Current authorized protocol caps steps at 12 and output at 512')
    if not c['model'] or c['model'].startswith('@preset/') or not c['providers'] or not set(c['providers']) <= set(DEFAULT_PROVIDERS):
        raise ValueError('Use model slug and authorized provider subset')
    available = {(x['source'],x['task'],x['condition']) for x in DEFAULT['tasks']}
    selected = [(x['source'],x['task'],x['condition']) for x in c['tasks']]
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= available:
        raise ValueError('Choose unique supported task/condition records')
    request_options(c)


def cases(c):
    return [{**task, 'repeat': r, 'seed': r-1,
             'case_id': f"{task['task']}-{task['condition']}-r{r:02d}",
             'pair_id': f"{task['task']}-r{r:02d}" if task['source']=='tricky' else None}
            for r in range(1,c['repeats']+1) for task in c['tasks']]


def inherited():
    from prepare_fresh_pilot import inherited_evidence
    evidence = inherited_evidence()
    if Decimal(read(PARENT)['reserved_cost_usd']) != Decimal(DEFAULT['carried_usd']):
        raise ValueError('Historical funding changed')
    return evidence


def fingerprints():
    modules = ('__init__','actions','backend','chaos','chaos_verifier','evaluation','observation',
               'openrouter','pilot','runner','search','trace','tricky','tricky_authorized',
               'tricky_membership','tricky_privacy')
    paths = [ROOT/'intent_browser'/f'{m}.py' for m in modules]
    paths += [Path(__file__), Path(__file__).with_name('sweep_backend.py'),
              Path(__file__).with_name('test_sweep.py'), Path(__file__).with_name('prepare_fresh_pilot.py'),
              ROOT/'scripts/inspect_chaos.mjs', ROOT/'data/curation/pilot_manifest.json',
              ROOT/'data/curation/inventory.jsonl', ROOT/'config/authorized_warranty_contract.json']
    for name in ('chaos_verifier','policy_exposure_validation_v2','tricky_membership_validation','tricky_privacy_validation'):
        paths.append(ROOT/'config'/f'{name}.json')
    for name in ('tricky','tricky-privacy','tricky-membership'):
        base = ROOT/'.local'/name
        paths += [base/'build.json'] + list((base/'dist').rglob('*'))
        paths += [p for p in (base/'catalog.json',base/'appointments.json') if p.exists()]
    return {str(p.relative_to(ROOT)):sha(p) for p in paths if p.is_file()}


def preflight(c):
    from intent_browser.chaos_verifier import fingerprint_server, certification
    provenance = fingerprint_server(c['chaos_base_url'])
    for task in c['tasks']:
        if task['source']=='chaos' and not certification(provenance,task['task']):
            raise ValueError('Chaos task/build certificate mismatch')
    exposure = read(ROOT/'config/policy_exposure_validation_v2.json')
    for path, h in exposure['source_sha256'].items():
        if sha(ROOT/path) != h:
            raise ValueError('Exposure validation source changed: '+path)
    reports = [exposure]
    for name, key in [('chaos_verifier','validation_report'),('tricky_membership_validation','report'),('tricky_privacy_validation','report')]:
        config = read(ROOT/'config'/f'{name}.json')
        path = ROOT/config[key]
        if sha(path) != config[key+'_sha256']:
            raise ValueError('Validation report changed: '+str(path))
        reports.append(read(path))
    count = 0
    for report in reports:
        if report.get('complete') is False:
            raise ValueError('Incomplete saved validation')
        for case in report['cases']:
            directory = ROOT/case['episode']
            for path,h in case.get('artifact_sha256',case.get('artifacts_sha256',{})).items():
                if sha(directory/path) != h:
                    raise ValueError('Saved validation artifact changed')
                count += 1
    for name in ('tricky','tricky-privacy','tricky-membership'):
        base = ROOT/'.local'/name
        build = read(base/'build.json')
        for path,h in build['dist_sha256'].items():
            if sha(base/'dist'/path) != h:
                raise ValueError('Fixture asset mismatch')
        for field,file in [('catalog_sha256','catalog.json'),('appointments_sha256','appointments.json')]:
            if field in build and sha(base/file)!=build[field]:
                raise ValueError('Fixture catalog mismatch')
    # Independent curation reviews contain the explicitly reconstructed P10
    # metadata-only source change and P11 current-source closure.
    privacy = read(ROOT/'config/tricky_privacy_validation.json')
    if sha(ROOT/'intent_browser/tricky_privacy.py') != privacy['post_validation_metadata_change']['final_source_sha256']:
        raise ValueError('P10 reviewed current source changed')
    membership = read(ROOT/'config/tricky_membership_validation.json')
    for row in membership['cases']:
        ep = read(ROOT/row['episode']/'episode.json')
        if ep['runtime']['source_sha256']['tricky_membership.py'] != sha(ROOT/'intent_browser/tricky_membership.py'):
            raise ValueError('P11 current-source evidence changed')
    return {'chaos':provenance, 'saved_artifact_checks':count, 'training_eligible':False,
            'scope':'Selected development contracts; saved scripted evidence, not benchmark-wide readiness.'}


def make_task(case, c, provenance):
    if case['source']=='chaos':
        from intent_browser.chaos import ChaosClient, ChaosTask
        class CertifiedTask(ChaosTask):
            def prepare(self, trace):
                result = super().prepare(trace)
                if not self.verifier_ready or not self.policy_goal or self.provenance != provenance:
                    raise ValueError('Live Chaos task/build mismatch')
                return result
        return CertifiedTask(ChaosClient(c['chaos_base_url']),case['task'])
    from intent_browser.tricky import TrickyTask
    from intent_browser.tricky_privacy import PrivacyTask
    from intent_browser.tricky_membership import MembershipTask
    from intent_browser.tricky_authorized import AuthorizedWarrantyTask
    if case['task']=='DEV-W01':
        return AuthorizedWarrantyTask()
    cls={'P07':TrickyTask,'P10':PrivacyTask,'P11':MembershipTask}[case['task']]
    return cls(condition='no_added_injection' if case['condition']=='clean' else 'one_selected_injection')


def init_suite(suite, c):
    validate_config(c)
    if (suite/'profile.json').exists():
        raise ValueError('Existing suite; use run to resume or choose a new suite name')
    ready, parent = preflight(c), inherited()
    from intent_browser.trace import runtime_provenance
    exclusive(suite/'profile.json', {'schema_version':1, 'suite':suite.name, 'created_at':now(),
        'config':c, 'cases':cases(c), 'source_sha256':fingerprints(), 'readiness':ready,
        'inherited':parent, 'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'policy_projection':'Only task adapter goal plus ordinary runner observations; no grader input.',
        'split':'development','training_eligible':False,'curation_ready':False,
        'observation_lifecycle':'paced-fresh-v1','parallel':False,'retries':0,
        'runtime_at_freeze':runtime_provenance(),
        'settings':{'temperature':0,'video':True,'headless':True,'chaos_slow_mo_ms':250,'tricky_slow_mo_ms':100},
        'authorization':'Bjorn requested 14-condition initial sweep, inspect then up to three repeats within remaining cumulative $3.'})
    print(json.dumps({'suite':str(suite.relative_to(ROOT)), 'cases':len(cases(c)), 'preflight':ready['saved_artifact_checks']}))


def report(suite):
    profile = read(suite/'profile.json')
    rows=[]
    for case in profile['cases']:
        path=suite/'cases'/f"{case['case_id']}.json"
        result=read(path) if path.exists() else {'status':'unexecuted'}
        rows.append({**case, **result})
    groups=defaultdict(list)
    for row in rows: groups[(row['source'],row['task'],row['condition'])].append(row)
    aggregates=[]
    for (source,task,condition), values in groups.items():
        done=[v for v in values if v['status']=='completed']
        metrics={k:{'true':sum(v['evaluation'].get(k) is True for v in done),
                    'false':sum(v['evaluation'].get(k) is False for v in done),
                    'unknown':sum(v['evaluation'].get(k) is None for v in done)}
                 for k in ('task_completed','authorization_satisfied','safe_success','injection_exposed','injection_avoided')}
        aggregates.append({'source':source,'task':task,'condition':condition,'planned':len(values),
            'executed':len(done),'technical_failures':sum(bool(v['evaluation']['technical_error']) for v in done),
            'action_errors':sum(v.get('action_error_count',0) for v in done),'metrics':metrics})
    result={'suite':suite.name,'profile_sha256':sha(suite/'profile.json'),'cases':rows,'groups':aggregates,
        'budget':{k:v for k,v in read(BUDGET).items() if k not in ('requests','inherited')} if BUDGET.exists() else None,
        'limits':['Development subset, not published benchmark score.',
                  'Fresh Chaos sessions determine variants; BrowserGym seed does not control their generation.',
                  'Provider routing is best effort; compare actual providers and variant descriptors.',
                  'Unknown/error outcomes remain separate; no training eligibility.']}
    write_json(suite/'report.json',result)
    lines=[f'# {suite.name}', '', '| Task | Condition | Executed | Safe true / false / unknown | Technical errors |',
           '|---|---|---:|---|---:|']
    for g in aggregates:
        m=g['metrics']['safe_success']
        lines.append(f"| {g['task']} | {g['condition']} | {g['executed']}/{g['planned']} | {m['true']} / {m['false']} / {m['unknown']} | {g['technical_failures']} |")
    lines += ['', 'Cases and exact trace directories:', '']
    for r in rows:
        if r.get('episode'): lines.append(f"- {r['case_id']}: `{r['episode']}`; safe={r['evaluation']['safe_success']}")
    (suite/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return result


def run(suite, limit, live):
    profile=read(suite/'profile.json'); c=profile['config']; validate_config(c)
    frozen=sha(suite/'profile.json')
    def validate():
        if sha(suite/'profile.json')!=frozen or fingerprints()!=profile['source_sha256'] or inherited()!=profile['inherited']:
            raise ValueError('Frozen profile/source/funding mismatch; create a new suite for changed runtime')
    validate()
    if preflight(c)!=profile['readiness']:
        raise ValueError('Environment provenance changed; create a new suite')
    if not live:
        print('Preflight passed; no inference. Use run --live to dispatch.'); return
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env',override=False)
    key=os.environ['OPENROUTER_API_KEY']
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    from intent_browser.runner import run_episode
    from intent_browser.actions import make_action_set
    import browsergym.core
    import gymnasium as gym
    with BUDGET.with_suffix('.lock').open('a') as budget_lock:
        fcntl.flock(budget_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if not BUDGET.exists(): exclusive(BUDGET,initial_ledger(c,profile['inherited']))
        if read(BUDGET)['inherited']!=profile['inherited']:
            raise ValueError('Shared ledger ancestor changed')
    done=0
    for case in profile['cases']:
        if done>=limit: break
        path=suite/'cases'/f"{case['case_id']}.json"
        if path.exists():
            old=read(path)
            if old['status']!='completed' or not old.get('audit_passed'):
                raise ValueError('Interrupted/unaudited case requires review: '+case['case_id'])
            continue
        validate()
        backend=SweepBackend(key,BUDGET,validate,c,suite.name+'/'+case['case_id'])
        # Detect ledger errors/budget exhaustion before creating another episode.
        with BUDGET.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            data,_,_=backend._read_ledger()
            from sweep_backend import reservation
            worst_case=reservation(c['input_byte_limit'],c['max_tokens'],c)*c['max_steps']
            if Decimal(data['reserved_cost_usd'])+worst_case>Decimal(c['cap_usd']):
                backend.close()
                print('Budget stop before episode: insufficient reservation capacity for a full worst-case episode.')
                report(suite)
                break
        exclusive(path,{**case,'status':'started','started_at':now(),'profile_sha256':frozen})
        task=make_task(case,c,profile['readiness']['chaos'])
        action_set=make_action_set()
        def factory(video):
            if case['source']!='chaos':
                return task.make_env(video,action_mapping=action_set.to_python_code,headless=True)
            return gym.make('browsergym/openended',task_kwargs={'start_url':task.start_url,'goal':task.policy_goal},
                headless=True,slow_mo=250,wait_for_user_message=False,record_video_dir=video,action_mapping=action_set.to_python_code)
        try:
            directory,summary=run_episode(factory,backend,{'task':case['task'],'source':case['source'],
                'development_case':case,'driver':'llm','model':c['model'],'backend':backend.base_url,
                'protocol_id':suite.name,'profile_sha256':frozen,'profile':str((suite/'profile.json').relative_to(ROOT)),
                'training_eligible':False,'curation_ready':False,'split':'development','generation':request_options(c),
                'max_tokens':c['max_tokens'],'headless':True,'budget_ledger':str(BUDGET.relative_to(ROOT))},
                output=ROOT/'runs',max_steps=c['max_steps'],seed=case['seed'],record_video=True,
                search_backend=None,episode_task=task,before_observation=backend.wait_until_ready)
            steps=[json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
            ledger=[r for r in read(BUDGET)['requests'] if r['case_id']==suite.name+'/'+case['case_id']]
            delivered=[s for s in steps if s.get('model_request') is not None]
            audit=(len(delivered)==len(ledger) and all(s['model_request']==r['model_request'] and
                s['model_response']==r['model_response'] and r['session_id']==directory.name and
                s['model_request']['messages']==s['messages'] and s['observation']['text'].startswith('decision-')
                for s,r in zip(delivered,ledger)))
            lifecycle=[json.loads(line)['event'] for line in (directory/'events.jsonl').read_text().splitlines()]
            audit=bool(audit and 'environment_close_started' in lifecycle and lifecycle.index('evaluation_completed')<lifecycle.index('environment_close_started'))
            record={**case,'status':'completed','finished_at':now(),'episode':str(directory.relative_to(ROOT)),
                'evaluation':summary['evaluation'],'step_count':summary['step_count'],
                'action_error_count':summary['action_error_count'],'stop_reason':summary['stop_reason'],
                'requests':len(ledger),'providers':[r.get('routing',{}).get('resolved_provider') for r in ledger],
                'reported_cost_usd':str(sum((Decimal(str(r['reported_cost_usd'])) for r in ledger if r['reported_cost_usd'] is not None),Decimal(0))),
                'reserved_usd':str(sum((Decimal(r['reservation_usd']) for r in ledger),Decimal(0))),
                'audit_passed':audit,'profile_sha256':frozen,
                'variant_descriptor':read(directory/'chaos-contract.json') if case['source']=='chaos' else None,
                'artifact_sha256':{p.name:sha(p) for p in directory.iterdir() if p.is_file()}}
            write_json(path,record); report(suite); done+=1
            print(json.dumps({'case':case['case_id'],'safe':record['evaluation']['safe_success'],'audit':audit}),flush=True)
            if summary['error'] or backend.stopped or not audit:
                raise ValueError('Sweep paused for case error/audit; no automatic retry')
        finally:
            backend.close()
            if hasattr(task,'close'): task.close()
            elif hasattr(task,'client'): task.client.close()


def compare(left,right):
    a,b=report(left),report(right)
    pa,pb=read(left/'profile.json'),read(right/'profile.json')
    index={r['case_id']:r for r in a['cases']}
    rows=[]
    for r in b['cases']:
        old=index.get(r['case_id'])
        if old and old['status']==r['status']=='completed':
            rows.append({'case_id':r['case_id'],'before':old['evaluation'],'after':r['evaluation'],
                         'before_providers':old['providers'],'after_providers':r['providers']})
    return {'before':left.name,'after':right.name,'matched_cases':rows,
        'changed_config_fields':[k for k in pa['config'] if pa['config'][k]!=pb['config'][k]],
        'changed_sources':[k for k in set(pa['source_sha256'])|set(pb['source_sha256']) if pa['source_sha256'].get(k)!=pb['source_sha256'].get(k)],
        'limits':'Task-condition-repeat matching only; inspect generated Chaos descriptors and provider changes before attributing differences.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['init','run','report','compare','template'])
    p.add_argument('--suite',default='external-baseline-v1')
    p.add_argument('--config',type=Path)
    p.add_argument('--other')
    p.add_argument('--live',action='store_true')
    p.add_argument('--limit',type=int,default=1,help='Maximum new episodes; completed cases are skipped')
    args=p.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',args.suite) or (args.other and not re.fullmatch(r'[a-zA-Z0-9_-]+',args.other)) or args.limit<1:
        p.error('Use simple suite names and positive limit')
    if args.command=='template': print(json.dumps(DEFAULT,indent=2));return
    BASE.mkdir(parents=True,exist_ok=True)
    suite=BASE/args.suite
    # One dispatcher across all suites prevents budget/pacing races.
    with (BASE/'dispatch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.command=='init': init_suite(suite,read(args.config) if args.config else DEFAULT)
        elif args.command=='run': run(suite,args.limit,args.live)
        elif args.command=='report': print(json.dumps(report(suite)['groups'],indent=2))
        else:
            if not args.other:p.error('--other required')
            print(json.dumps(compare(suite,BASE/args.other),indent=2))


if __name__=='__main__': main()
