"""One fresh routed Chaos development case under the cumulative $3 authorization.

Default: freeze local preflight/profile, no model/browser calls. --live executes
D01 once; inspect before any separately added case. Historical protocols stay frozen.
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

STATE = ROOT / 'data/curation/routed-pilot-v1'
MODEL = 'qwen/qwen3.8-27b'
CASE = {'case_id': 'D01', 'source_task_id': 'force-push', 'seed': 0}
CAP = Decimal('3')
INPUT_BOUND, MAX_TOKENS, MAX_STEPS, PACE = 24000, 512, 12, 10
RESERVATION = (Decimal(INPUT_BOUND) * Decimal('0.5') + Decimal(MAX_TOKENS) * 4) / 1000000
INHERITED = {'data/curation/calibration-chaos-v1/budget.json': Decimal('0.1082880'),
             'runs/openrouter-session-routing-budget.json': Decimal('0.04925575')}
CARRIED = sum(INHERITED.values(), Decimal(0))


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprints():
    paths = [*sorted((ROOT / 'intent_browser').glob('*.py')),
             ROOT / 'config/chaos_verifier.json', ROOT / 'scripts/inspect_chaos.mjs', Path(__file__)]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def inherited_evidence():
    result = {}
    for name, expected in INHERITED.items():
        ledger = json.loads((ROOT / name).read_text())
        total = Decimal(ledger['reserved_cost_usd'])
        calculated = sum((Decimal(r['reservation_usd']) for r in ledger['requests']), Decimal(0))
        if total != expected or calculated != expected:
            raise ValueError('Historical reservation totals changed; reconcile before sending')
        result[name] = {'sha256': sha(ROOT / name), 'reserved_cost_usd': str(total),
                        'request_count': len(ledger['requests'])}
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
    def __init__(self, key, ledger, validate, *, clock=time.time, sleep=time.sleep):
        super().__init__('https://openrouter.ai/api/v1', MODEL, key, max_tokens=MAX_TOKENS,
                         request_options=options(), session_routing=True)
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
            if len(data['requests']) >= MAX_STEPS:
                raise ValueError('Single-case request limit reached; no request sent')
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
            row = {'protocol_id': STATE.name, 'case_id': CASE['case_id'],
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


def environment_preflight(origin):
    from intent_browser.chaos import ChaosClient
    from intent_browser.chaos_verifier import fingerprint_server, certification
    provenance = fingerprint_server(origin)
    client = ChaosClient(origin)
    try:
        ids = {r['id'] for r in client.catalogue()}
    finally:
        client.close()
    if CASE['source_task_id'] not in ids or not certification(provenance, CASE['source_task_id']):
        raise ValueError('Selected Chaos task/build is not certified')
    cert = json.loads((ROOT / 'config/chaos_verifier.json').read_text())
    if sha(ROOT / cert['validation_report']) != cert['validation_report_sha256']:
        raise ValueError('Saved certificate evidence hash mismatch')
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--chaos-base-url', default='http://localhost:45379')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        provenance = environment_preflight(args.chaos_base_url)
        sources, inherited = fingerprints(), inherited_evidence()
        profile_path = STATE / 'profile.json'
        if not profile_path.exists():
            write_json(profile_path, {'protocol_id': STATE.name, 'created_at': now(), 'case': CASE,
                'source_sha256': sources, 'inherited_ledgers': inherited,
                'chaos_base_url': args.chaos_base_url, 'environment_provenance': provenance,
                'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'model': MODEL, 'generation': {'temperature': 0, 'max_tokens': MAX_TOKENS, **options()},
                'session_id': 'run_episode episode_id; top-level, no strict provider-affinity guarantee',
                'max_steps': MAX_STEPS, 'pace_seconds': PACE, 'retries': 0, 'search': None,
                'headless': True, 'video': True, 'slow_mo_ms': 250, 'cache_padding': False,
                'approved_cap_usd': str(CAP), 'carried_reservations_usd': str(CARRIED),
                'per_request_reservation_usd': str(RESERVATION), 'input_token_bound': INPUT_BOUND,
                'maximum_case_reservation_usd': str(RESERVATION * MAX_STEPS),
                'split': 'development', 'training_eligible': False, 'curation_ready': False,
                'authorization': 'Existing $3 cumulative calibration approval; one fresh development case then inspect.',
                'readiness': 'Harness owner reports d371db0 ready, hold lifted; current local certificate/build rechecked.',
                'limits': 'Scoped Chaos simulation, no transaction ledger or injection label claims; ordinary harness prompts.'})
        profile = json.loads(profile_path.read_text())
        profile_sha = sha(profile_path)

        def validate():
            if (sha(profile_path) != profile_sha or fingerprints() != profile['source_sha256'] or
                    inherited_evidence() != profile['inherited_ledgers'] or
                    args.chaos_base_url != profile['chaos_base_url']):
                raise ValueError('Frozen protocol or historical evidence changed; no request sent')
        validate()
        if provenance != profile['environment_provenance']:
            raise ValueError('Preflight environment changed')
        if not args.live:
            print(json.dumps({'status': 'local_preflight_passed_no_model_or_browser_calls',
                'profile': str(profile_path.relative_to(ROOT)), 'profile_sha256': profile_sha,
                'case': CASE, 'carried_reservations_usd': str(CARRIED),
                'per_request_reservation_usd': str(RESERVATION)}, indent=2))
            return

        from dotenv import load_dotenv
        import browsergym.core  # noqa: F401
        import gymnasium as gym
        from intent_browser.actions import make_action_set
        from intent_browser.chaos import ChaosClient, ChaosTask
        from intent_browser.runner import run_episode
        load_dotenv(ROOT / '.env', override=False)
        key = os.environ['OPENROUTER_API_KEY']
        os.environ['LD_LIBRARY_PATH'] = str(ROOT / '.local/system-libs/usr/lib/x86_64-linux-gnu') + ':' + os.getenv('LD_LIBRARY_PATH', '')
        case_path = STATE / 'D01.json'
        with case_path.open('x') as handle:
            json.dump({**CASE, 'status': 'started', 'started_at': now(), 'profile_sha256': profile_sha}, handle)

        class CertifiedTask(ChaosTask):
            def prepare(self, trace):
                result = super().prepare(trace)
                if not self.verifier_ready or not self.policy_goal or self.provenance != provenance:
                    raise ValueError('Live task contract/build mismatch; no model request permitted')
                return result

        task = CertifiedTask(ChaosClient(args.chaos_base_url), CASE['source_task_id'])
        backend = PilotBackend(key, STATE / 'budget.json', validate)
        action_set = make_action_set()
        def environment(video):
            return gym.make('browsergym/openended', task_kwargs={'start_url': task.start_url, 'goal': task.policy_goal},
                headless=True, slow_mo=250, wait_for_user_message=False,
                record_video_dir=video, action_mapping=action_set.to_python_code)
        try:
            directory, summary = run_episode(environment, backend, {
                'task': 'openended', 'source': 'browser-agent-chaos', 'source_task_id': CASE['source_task_id'],
                'driver': 'llm', 'model': MODEL, 'backend': backend.base_url, 'headless': True, 'verifier': None,
                'protocol_id': STATE.name, 'development_case': CASE, 'training_eligible': False,
                'curation_ready': False, 'split': 'development', 'generation': profile['generation'],
                'profile': str(profile_path.relative_to(ROOT)), 'profile_sha256': profile_sha,
                'budget': {'ledger': str((STATE / 'budget.json').relative_to(ROOT)), 'cap_usd': str(CAP)},
                'pacing_seconds': PACE, 'environment': {'slow_mo_ms': 250, 'record_video': True}},
                output=ROOT / 'runs', max_steps=MAX_STEPS, seed=CASE['seed'], record_video=True,
                search_backend=None, episode_task=task)
            write_json(case_path, {**CASE, 'status': 'completed', 'episode': str(directory.relative_to(ROOT)),
                'profile_sha256': profile_sha, 'finished_at': now(), 'summary': summary, 'budget_stopped': backend.stopped})
            print(json.dumps({'episode': str(directory.relative_to(ROOT)), 'summary': summary}, indent=2))
        finally:
            backend.close()
            task.client.close()
        if summary['error'] or backend.stopped:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
