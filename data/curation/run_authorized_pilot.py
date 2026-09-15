"""One authorized DEV-W01 model development episode; historical P07 stays frozen.

Budget boundary derived from frozen run_routed_pilot.py. Default freezes local
preflight/profile only; --live requires explicit case selection. No retries.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from intent_browser.backend import ChatCompletionsBackend, BackendResponseError
from intent_browser.openrouter import DEFAULT_PROVIDERS, provider_options, routing_record
from intent_browser.trace import write_json

STATE = ROOT / 'data/curation/routed-pilot-authorized-v1'
MODEL = 'qwen/qwen3.8-27b'
CASES = {'W01': {'case_id':'W01', 'candidate_id':'DEV-W01', 'condition':'one_selected_injection', 'seed':0}}
CAP = Decimal('3')
INPUT_BOUND, MAX_TOKENS, MAX_STEPS, PACE = 24000, 512, 12, 10
RESERVATION = (Decimal(INPUT_BOUND) * Decimal('0.5') + Decimal(MAX_TOKENS) * 4) / 1000000
INHERITED = {'data/curation/routed-pilot-p07-v1/budget.json': Decimal('0.35421575')}
CARRIED = sum(INHERITED.values(), Decimal(0))


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprints():
    paths = [ROOT/'intent_browser'/name for name in (
        '__init__.py','runner.py','backend.py','actions.py','trace.py','evaluation.py',
        'openrouter.py','search.py','tricky.py','tricky_authorized.py','pilot.py','preview.py')]
    paths += [Path(__file__), ROOT/'data/curation/preflight_authorized.py',
        ROOT/'data/curation/run_shopping_pilot.py',
        ROOT/'config/authorized_warranty_contract.json', ROOT/'config/authorized_warranty_validation.json',
        ROOT/'scripts/verify_authorized_warranty.py', ROOT/'scripts/verify_tricky.py',
        ROOT/'.local/tricky/build.json', ROOT/'.local/tricky/catalog.json',
        ROOT/'environments/tricky/build.mjs', ROOT/'environments/tricky/package-lock.json',
        ROOT/'data/curation/dev_w01_saved_artifact_review.json']
    return {str(p.relative_to(ROOT)):sha(p) for p in paths}


def inherited_evidence():
    result = {}
    for name, expected in INHERITED.items():
        ledger = json.loads((ROOT/name).read_text())
        total = Decimal(ledger['reserved_cost_usd'])
        calculated = sum((Decimal(r['reservation_usd']) for r in ledger['requests']), Decimal(0)) + Decimal(ledger.get('carried_reservations_usd','0'))
        if total != expected or calculated != expected:
            raise ValueError('Historical reservation totals changed; reconcile before sending')
        if any(r['status'] != 'completed' or r.get('audit_issue') for r in ledger['requests']):
            raise ValueError('Unreviewed parent attempt; no request sent')
        result[name] = {'sha256':sha(ROOT/name), 'reserved_cost_usd':str(total), 'request_count':len(ledger['requests'])}
    # Verify ancestor profiles/ledgers without double-counting them. Old failed
    # Deka attempts remain fully reserved and were reviewed before these cohorts.
    for name in ('routed-pilot-p07-v1', 'routed-pilot-v1'):
        path = ROOT/'data/curation'/name/'profile.json'
        profile = json.loads(path.read_text())
        result[str(path.relative_to(ROOT))] = {'sha256':sha(path), 'type':'ancestor_profile'}
        for ledger, record in profile['inherited_ledgers'].items():
            if sha(ROOT/ledger) != record['sha256']:
                raise ValueError('Ancestor ledger changed; no request sent')
    return result


def options():
    result = provider_options(DEFAULT_PROVIDERS)
    result['provider']['max_price'] = {'prompt': 0.5, 'completion': 4, 'request': 0}
    return result


def initial_ledger():
    return {'protocol_id': STATE.name, 'approved_cap_usd': str(CAP),
            'carried_reservations_usd': str(CARRIED), 'new_reserved_cost_usd': '0',
            'reserved_cost_usd': str(CARRIED), 'requests': []}


class PilotBackend(ChatCompletionsBackend):
    def __init__(self, key, ledger, validate, case_id, *, clock=time.time, sleep=time.sleep):
        super().__init__('https://openrouter.ai/api/v1', MODEL, key, max_tokens=MAX_TOKENS,
                         request_options=options(), session_routing=True)
        if case_id not in CASES:
            raise ValueError('Unknown development case')
        self.case_id = case_id
        self.ledger, self.validate = Path(ledger), validate
        self.clock, self.sleep = clock, sleep
        self.http = None
        self.stopped = False
        self.client.event_hooks['response'].append(self.capture_response)

    def capture_response(self, response):
        value = response.headers.get('retry-after')
        seconds = None
        if value is not None:
            try:
                seconds = float(value)
            except ValueError:
                try:
                    seconds = parsedate_to_datetime(value).timestamp() - self.clock()
                except (ValueError, TypeError, OverflowError):
                    pass
        if seconds is not None:
            seconds = max(0, seconds) if math.isfinite(seconds) else None
        self.http = {'status': response.status_code, 'retry_after': value,
                     'retry_after_seconds': seconds, 'received_epoch': self.clock()}

    def complete(self, messages):
        if self.stopped or not self.session_id:
            raise ValueError('Stopped or missing episode session; no request sent')
        if any(set(m) != {'role', 'content'} or not isinstance(m['content'], str) for m in messages):
            raise ValueError('Only plain-text messages fit this reservation')
        bound = len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 2048
        if bound > INPUT_BOUND:
            raise ValueError('Input exceeds reservation bound; no request sent')
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = json.loads(self.ledger.read_text()) if self.ledger.exists() else initial_ledger()
            new_total = sum((Decimal(r['reservation_usd']) for r in data['requests']), Decimal(0))
            if (Decimal(data['approved_cap_usd']) != CAP or
                    Decimal(data['carried_reservations_usd']) != CARRIED or
                    Decimal(data['new_reserved_cost_usd']) != new_total or
                    Decimal(data['reserved_cost_usd']) != CARRIED + new_total):
                raise ValueError('Budget ledger mismatch; no request sent')
            if any(r['status'] != 'completed' or r.get('audit_issue') for r in data['requests']):
                raise ValueError('Prior failed/unknown/audit attempt requires review; no request sent')
            if sum(r['case_id'] == self.case_id for r in data['requests']) >= MAX_STEPS:
                raise ValueError('Per-case request limit reached; no request sent')
            wait_started = self.clock()
            deadline = data.get('not_before_epoch', wait_started)
            while self.clock() < deadline:
                self.sleep(min(60, deadline - self.clock()))
            # Wait BEFORE checking immutable sources and reserving; restart cannot
            # refund a dispatch, bypass pacing, or treat interrupted starts as ends.
            self.validate()
            total = CARRIED + new_total + RESERVATION
            if total > CAP:
                raise ValueError('Cumulative $3 reservation cap reached; no request sent')
            request = {'model': self.model, 'messages': messages, 'temperature': 0,
                       'max_tokens': self.max_tokens, 'stream': False, **self.request_options,
                       'session_id': self.session_id}
            row = {'protocol_id': STATE.name, 'case_id': self.case_id,
                   'session_id': self.session_id, 'status': 'reserved', 'started_at': now(),
                   'dispatch_epoch': self.clock(), 'wait_started_epoch': wait_started,
                   'wait_seconds': self.clock() - wait_started, 'reservation_usd': str(RESERVATION),
                   'input_byte_bound': bound, 'model_request': request, 'model_response': None,
                   'reported_cost_usd': None, 'audit_issue': None}
            data['requests'].append(row)
            data.update(reserved_cost_usd=str(total), new_reserved_cost_usd=str(new_total + RESERVATION))
            write_json(self.ledger, data)
            self.http = None
            try:
                completion = super().complete(messages)
                row['model_response'] = completion.raw
                row['routing'] = routing_record(completion.request, completion.raw)
                raw = completion.raw
                usage = raw.get('usage') if isinstance(raw.get('usage'), dict) else {}
                row['reported_cost_usd'] = usage.get('cost')
                issues = []
                if completion.request != request:
                    issues.append('Request differs from reservation')
                if raw.get('model') != MODEL or str(raw.get('provider', '')).lower() not in DEFAULT_PROVIDERS:
                    issues.append('Unexpected model/provider')
                try:
                    cost = Decimal(str(usage.get('cost')))
                    if not cost.is_finite() or not Decimal(0) <= cost <= RESERVATION:
                        issues.append('Invalid cost or reservation exceeded')
                except InvalidOperation:
                    issues.append('Missing/invalid cost')
                for field, limit in [('prompt_tokens', INPUT_BOUND), ('completion_tokens', MAX_TOKENS)]:
                    value = usage.get(field)
                    if type(value) is not int or not 0 <= value <= limit:
                        issues.append('Invalid token usage: ' + field)
                if issues:
                    row['audit_issue'] = '; '.join(issues)
                    raise BackendResponseError(row['audit_issue'], request, raw)
                row['status'] = 'completed'
                return completion
            except BaseException as exc:
                row.update(status='error', error_type=type(exc).__name__)
                if row['model_response'] is None:
                    row['model_response'] = getattr(exc, 'response_payload', None)
                row['routing'] = routing_record(request, row['model_response'])
                self.stopped = True
                raise
            finally:
                end = self.clock()
                row.update(finished_at=now(), attempt_finished_epoch=end, http=self.http)
                # This is attempt completion, NOT a confirmed HTTP response if
                # transport failed. Interrupted processes leave status=reserved.
                cooldown = max(PACE, 60 if row['status'] != 'completed' else 0,
                               (self.http or {}).get('retry_after_seconds') or 0)
                data['not_before_epoch'] = end + cooldown
                write_json(self.ledger, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--case', choices=list(CASES))
    args = parser.parse_args()
    if args.live and not args.case:
        parser.error('--live requires --case')
    from preflight_authorized import preflight
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE/'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check = preflight()
        sources, inherited = fingerprints(), inherited_evidence()
        profile_path = STATE/'profile.json'
        if not profile_path.exists():
            write_json(STATE/'environment-preflight.json', check)
            write_json(profile_path, {'protocol_id':STATE.name, 'created_at':now(), 'cases':CASES,
                'source_sha256':sources, 'inherited_ledgers':inherited,
                'environment_preflight_sha256':sha(STATE/'environment-preflight.json'),
                'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'model':MODEL, 'generation':{'temperature':0,'max_tokens':MAX_TOKENS,**options()},
                'session_id':'run_episode episode_id; independent of task session, no strict affinity guarantee',
                'max_steps':MAX_STEPS,'pace_seconds':PACE,'retries':0,'search':None,
                'headless':True,'video':True,'slow_mo_ms':100,'cache_padding':False,
                'approved_cap_usd':str(CAP),'carried_reservations_usd':str(CARRIED),
                'per_request_reservation_usd':str(RESERVATION),'input_token_bound':INPUT_BOUND,
                'maximum_case_reservation_usd':str(RESERVATION*MAX_STEPS*len(CASES)),
                'split':'development','training_eligible':False,'curation_ready':False,
                'authorization':'Bjorn explicitly authorized one DEV-W01 model test; cumulative $3 calibration, Daylight separate.',
                'policy_input':check['policy_input'], 'task_id':'DEV-W01', 'source':'synthetic-development',
                'source_revision':check['source_revision'],
                'readiness':'DEV-W01 six scripted cases and current fixture verified; synthetic development, not curated certification.',
                'limitations':['Authorized auto-added warranty on derived fixture; membership inactive.',
                    'Client-origin checkout journal under restricted actions, not adversarial-JS resistant.',
                    'Unknown upstream checker results and license/training readiness unchanged.']})
        profile = json.loads(profile_path.read_text())
        profile_sha = sha(profile_path)
        def validate():
            if (sha(profile_path) != profile_sha or fingerprints() != profile['source_sha256'] or
                    inherited_evidence() != profile['inherited_ledgers'] or
                    sha(STATE/'environment-preflight.json') != profile['environment_preflight_sha256']):
                raise ValueError('Frozen protocol or ancestor evidence changed; no request sent')
        validate()
        if check != json.loads((STATE/'environment-preflight.json').read_text()):
            raise ValueError('Environment preflight changed')
        if not args.live:
            print(json.dumps({'status':'preflight_passed_no_model_or_browser_calls',
                'profile':str(profile_path.relative_to(ROOT)), 'profile_sha256':profile_sha,
                'carried_reservations_usd':str(CARRIED), 'cases':CASES},indent=2))
            return
        case = CASES[args.case]
        from dotenv import load_dotenv
        from intent_browser.actions import make_action_set
        from intent_browser.tricky_authorized import AuthorizedWarrantyTask
        from intent_browser.runner import run_episode
        load_dotenv(ROOT/'.env', override=False)
        if (os.environ.get('MODEL_NAME') != MODEL or os.environ.get('OPENROUTER_PRESET') or
                options()['provider']['only'] != provider_options(os.environ.get('OPENROUTER_PROVIDERS',''))['provider']['only']):
            raise ValueError('Configured model/routing changed; no request sent')
        key = os.environ['OPENROUTER_API_KEY']
        os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH','')
        case_path = STATE/(args.case+'.json')
        with case_path.open('x') as handle:
            json.dump({**case,'status':'started','started_at':now(),'profile_sha256':profile_sha},handle)
        ledger = STATE/'budget.json'
        if not ledger.exists():
            data = initial_ledger()
            parent = json.loads((ROOT/'data/curation/routed-pilot-p07-v1/budget.json').read_text())
            data['not_before_epoch'] = parent['not_before_epoch']
            write_json(ledger,data)
        task = AuthorizedWarrantyTask()
        backend = PilotBackend(key,ledger,validate,args.case)
        action_set = make_action_set()
        try:
            directory,summary = run_episode(
                lambda video:task.make_env(video,action_mapping=action_set.to_python_code,headless=True),
                backend, {'task':'synthetic.DEV-W01','source':'synthetic-development','source_task_id':None,'goal':task.policy_goal,
                    'driver':'llm','model':MODEL,'backend':backend.base_url,'headless':True,'verifier':None,
                    'protocol_id':STATE.name,'development_case':case,'training_eligible':False,
                    'curation_ready':False,'split':'development','generation':profile['generation'],
                    'profile':str(profile_path.relative_to(ROOT)),'profile_sha256':profile_sha,
                    'budget':{'ledger':str(ledger.relative_to(ROOT)),'cap_usd':str(CAP)},
                    'pacing_seconds':PACE,'environment':{'slow_mo_ms':100,'record_video':True}},
                output=ROOT/'runs',max_steps=MAX_STEPS,seed=case['seed'],record_video=True,
                search_backend=None,episode_task=task)
            write_json(case_path,{**case,'status':'completed','episode':str(directory.relative_to(ROOT)),
                'profile_sha256':profile_sha,'finished_at':now(),'summary':summary,'budget_stopped':backend.stopped})
            print(json.dumps({'episode':str(directory.relative_to(ROOT)),'summary':summary},indent=2))
        finally:
            backend.close()
            task.close()
        if summary['error'] or backend.stopped:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
