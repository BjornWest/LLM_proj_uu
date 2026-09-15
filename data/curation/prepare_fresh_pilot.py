"""Offline adoption of paced-fresh-v1 with a separate cumulative budget lineage.

The CLI only freezes/rechecks an offline profile. No live switch, credential
loading, browser launch or paid dispatch is exposed. Tests supply MockTransport.
Historical wrappers and ledgers stay immutable. A future paid cohort requires
separate environment readiness, case selection and a newly reviewed profile.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from intent_browser.backend import ChatCompletionsBackend, BackendResponseError
from intent_browser.openrouter import DEFAULT_PROVIDERS, provider_options, routing_record
from intent_browser.trace import write_json

STATE = ROOT / 'data/curation/fresh-observation-offline-v1'
MODEL = 'qwen/qwen3.8-27b'
CASE = {'case_id': 'OFFLINE-HOOK-01', 'source_task_id': None, 'seed': 0}
CAP = Decimal('3')
INPUT_BOUND, MAX_TOKENS, MAX_STEPS, PACE = 24000, 512, 12, 10
RESERVATION = (Decimal(INPUT_BOUND) * Decimal('0.5') + Decimal(MAX_TOKENS) * 4) / 1000000
INHERITED = {'data/curation/routed-pilot-token-v1/budget.json': Decimal('0.64922375')}
CARRIED = sum(INHERITED.values(), Decimal(0))


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprints():
    # Scoped project import closure; third-party versions and relevant extraction
    # implementations are recorded separately. Demo modules are not imported.
    names = ('__init__.py', 'runner.py', 'backend.py', 'actions.py', 'trace.py',
             'evaluation.py', 'openrouter.py', 'search.py', 'observation.py', 'chaos_verifier.py')
    paths = [ROOT/'intent_browser'/name for name in names] + [Path(__file__),
        ROOT/'OBSERVATION_PACING.md', ROOT/'config/observation_pacing_validation.json',
        ROOT/'config/chaos_verifier.json', ROOT/'config/policy_exposure_validation_v2.json',
        ROOT/'.local/preflight/harness-exposure-v2-readiness.json', ROOT/'data/curation/test_fresh_pilot.py']
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def inherited_evidence():
    result = {}
    for name, expected in INHERITED.items():
        ledger = json.loads((ROOT/name).read_text())
        total = Decimal(ledger['reserved_cost_usd'])
        calculated = sum((Decimal(r['reservation_usd']) for r in ledger['requests']), Decimal(0)) + Decimal(ledger.get('carried_reservations_usd', '0'))
        if total != expected or calculated != expected:
            raise ValueError('Historical reservation totals changed; reconcile before sending')
        if any(r['status'] != 'completed' or r.get('audit_issue') for r in ledger['requests']):
            raise ValueError('Parent inference error/unknown cost requires review')
        result[name] = {'sha256': sha(ROOT/name), 'reserved_cost_usd': str(total), 'request_count': len(ledger['requests'])}
    review_path = ROOT/'data/curation/routed-pilot-token-v1/audit.json'
    if not json.loads(review_path.read_text())['all_checks_passed']:
        raise ValueError('Previous T01 audit failed')
    result[str(review_path.relative_to(ROOT))] = {'sha256': sha(review_path)}
    for name in ('routed-pilot-token-v1', 'routed-pilot-account-v1', 'routed-pilot-authorized-v1', 'routed-pilot-p07-v1', 'routed-pilot-v1'):
        path = ROOT/'data/curation'/name/'profile.json'
        result[str(path.relative_to(ROOT))] = {'sha256': sha(path), 'type': 'ancestor_profile'}
        for artifact, record in json.loads(path.read_text())['inherited_ledgers'].items():
            if sha(ROOT/artifact) != record['sha256']:
                raise ValueError('Ancestor evidence changed')
    return result


def state_digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def options():
    result = provider_options(DEFAULT_PROVIDERS)
    result['provider']['max_price'] = {'prompt': 0.5, 'completion': 4, 'request': 0}
    return result


def initial_ledger(not_before_epoch=0):
    return {'protocol_id': STATE.name, 'approved_cap_usd': str(CAP),
            'carried_reservations_usd': str(CARRIED), 'new_reserved_cost_usd': '0',
            'reserved_cost_usd': str(CARRIED), 'not_before_epoch': not_before_epoch, 'requests': []}


class PilotBackend(ChatCompletionsBackend):
    def __init__(self, key, ledger, validate, *, clock=time.time, sleep=time.sleep, initial_not_before_epoch=None):
        super().__init__('https://openrouter.ai/api/v1', MODEL, key, max_tokens=MAX_TOKENS,
                         request_options=options(), session_routing=True)
        self.ledger, self.validate = Path(ledger), validate
        self.clock, self.sleep = clock, sleep
        self.initial_not_before_epoch = (max(json.loads((ROOT/name).read_text()).get('not_before_epoch', 0)
                                            for name in INHERITED)
                                         if initial_not_before_epoch is None else initial_not_before_epoch)
        self.http = None
        self.stopped = False
        self.ready = None
        self.dispatch_epoch = None
        self.client.event_hooks['request'].append(self.capture_dispatch)
        self.client.event_hooks['response'].append(self.capture_response)

    def capture_dispatch(self, request):
        # httpx request-hook entry, not socket-write confirmation. Never headers.
        self.dispatch_epoch = self.clock()

    def _read_ledger(self):
        data = json.loads(self.ledger.read_text()) if self.ledger.exists() else initial_ledger(self.initial_not_before_epoch)
        if any(Decimal(r['reservation_usd']) != RESERVATION for r in data['requests']):
            raise ValueError('Unexpected reservation amount; no refunds or credits allowed')
        new_total = sum((Decimal(r['reservation_usd']) for r in data['requests']), Decimal(0))
        if (data.get('protocol_id') != STATE.name or Decimal(data['approved_cap_usd']) != CAP or
                Decimal(data['carried_reservations_usd']) != CARRIED or
                Decimal(data['new_reserved_cost_usd']) != new_total or
                Decimal(data['reserved_cost_usd']) != CARRIED + new_total):
            raise ValueError('Budget ledger mismatch; no request sent')
        if any(r['status'] != 'completed' or r.get('audit_issue') for r in data['requests']):
            raise ValueError('Prior failed/unknown/audit attempt requires review; no request sent')
        if len(data['requests']) >= MAX_STEPS:
            raise ValueError('Single-case request limit reached; no request sent')
        deadline = data.get('not_before_epoch', 0)
        if type(deadline) not in (float, int) or not math.isfinite(deadline):
            raise ValueError('Invalid readiness deadline')
        return data, new_total, deadline

    def wait_until_ready(self):
        if self.stopped or not self.session_id:
            raise ValueError('Stopped or missing episode session; no readiness check')
        self.ready = None
        started = self.clock()
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        while True:
            with self.ledger.with_suffix('.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                data, _, deadline = self._read_ledger()
                if self.clock() >= deadline:
                    self.ready = {'state_sha256': state_digest(data), 'session_id': self.session_id,
                                  'started_epoch': started, 'ready_epoch': self.clock(),
                                  'wait_seconds': self.clock() - started, 'not_before_epoch': deadline}
                    return dict(self.ready)
            # No lock held during sleep. No source validation, reservation or HTTP.
            self.sleep(max(0, min(60, deadline - self.clock())))

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
            ready, self.ready = self.ready, None  # consume one hook result
            data, new_total, deadline = self._read_ledger()
            if (ready is None or ready['session_id'] != self.session_id or
                    ready['state_sha256'] != state_digest(data) or self.clock() < deadline):
                raise ValueError('Readiness changed or hook missing; reject stale prompt without waiting')
            # Capture and prompt construction occurred after readiness. Recheck
            # immutable sources here, then reserve once under the dispatch lock.
            self.validate()
            total = CARRIED + new_total + RESERVATION
            if total > CAP:
                raise ValueError('Cumulative $3 reservation cap reached; no request sent')
            request = {'model': self.model, 'messages': messages, 'temperature': 0,
                       'max_tokens': self.max_tokens, 'stream': False, **self.request_options,
                       'session_id': self.session_id}
            row = {'protocol_id': STATE.name, 'case_id': CASE['case_id'],
                   'session_id': self.session_id, 'status': 'reserved', 'started_at': now(),
                   'reservation_epoch': self.clock(), 'readiness': ready, 'reservation_usd': str(RESERVATION),
                   'input_byte_bound': bound, 'model_request': request, 'model_response': None,
                   'reported_cost_usd': None, 'audit_issue': None}
            data['requests'].append(row)
            data.update(reserved_cost_usd=str(total), new_reserved_cost_usd=str(new_total + RESERVATION))
            write_json(self.ledger, data)
            self.http = None
            self.dispatch_epoch = None
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
                row.update(finished_at=now(), attempt_finished_epoch=end, http=self.http,
                           http_request_hook_epoch=self.dispatch_epoch,
                           timing_scope='httpx request hook; response headers hook; backend attempt end (not socket/body timestamps)')
                # This is attempt completion, NOT a confirmed HTTP response if
                # transport failed. Interrupted processes leave status=reserved.
                cooldown = max(PACE, 60 if row['status'] != 'completed' else 0,
                               (self.http or {}).get('retry_after_seconds') or 0)
                data['not_before_epoch'] = end + cooldown
                write_json(self.ledger, data)




def readiness_evidence():
    """Read-only source/artifact and saved grader replay; no servers or browsers."""
    from intent_browser.chaos_verifier import verifier_fingerprints, evaluate_trace
    from intent_browser.tricky import verify_p07
    from scripts.verify_policy_exposure import audit as audit_exposure
    from scripts.verify_authorized_warranty import replay as replay_warranty
    reference = ROOT/'.local/preflight/harness-exposure-v2-readiness.json'
    readiness = json.loads(reference.read_text())
    if readiness['status'] != 'ready_for_new_offline_profile':
        raise ValueError('Readiness is not for an offline profile')
    def check_sources(sources):
        for name, expected in sources.items():
            if sha(ROOT/name) != expected:
                raise ValueError('Readiness source mismatch: ' + name)
    check_sources(readiness['source_sha256'])
    cases, artifact_count = [], 0
    reports = {}
    for name in ('config/observation_pacing_validation.json', 'config/policy_exposure_validation_v2.json'):
        report = json.loads((ROOT/name).read_text())
        reports[name] = sha(ROOT/name)
        check_sources(report['source_sha256'])
        for case in report['cases']:
            directory = ROOT/case['episode']
            for artifact, expected in case.get('artifacts_sha256', case.get('artifact_sha256', {})).items():
                if sha(directory/artifact) != expected:
                    raise ValueError('Saved validation artifact changed: ' + case['episode'] + '/' + artifact)
                artifact_count += 1
            steps = [json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
            if any(row.get('model_request') is not None for row in steps):
                raise ValueError('Scripted evidence unexpectedly contains model HTTP requests')
            if 'family' in case:
                if audit_exposure(directory) != case['audit']:
                    raise ValueError('Exposure acknowledgment replay mismatch')
                build = json.loads((directory/'tricky-build.json').read_text())
                catalog_path = ROOT/'.local/tricky/catalog.json'
                if sha(catalog_path) != build['catalog_sha256']:
                    raise ValueError('Catalog changed')
                catalog = {str(p['id']): p for p in json.loads(catalog_path.read_text())}
                if case['family'] == 'DEV-W01':
                    replayed = replay_warranty(directory, catalog)
                else:
                    final = json.loads((directory/'tricky-final-state.json').read_text())
                    replayed = verify_p07(final['orders'], final['browser']['cart'], catalog,
                                         exposed=final['browser']['policy_exposure_before_commit'])
                if replayed != case['receipt_replay']:
                    raise ValueError('Receipt replay mismatch')
            cases.append({'episode':case['episode'], 'source':name, 'hashes_match':True,
                          'replay': 'exposure_and_receipts' if 'family' in case else 'timing_artifact_hashes'})
    cert = json.loads((ROOT/'config/chaos_verifier.json').read_text())
    if cert['verifier_source_sha256'] != verifier_fingerprints():
        raise ValueError('Chaos certificate source mismatch')
    if sha(ROOT/cert['validation_report']) != cert['validation_report_sha256']:
        raise ValueError('Chaos validation report hash mismatch')
    reports[cert['validation_report']] = cert['validation_report_sha256']
    report = json.loads((ROOT/cert['validation_report']).read_text())
    sessions = set()
    for case in report['cases']:
        directory = ROOT/case['episode']
        read = lambda name: json.loads((directory/name).read_text())
        for name, expected in case['artifact_sha256'].items():
            if sha(directory/name) != expected:
                raise ValueError('Chaos saved evidence changed: '+name)
            artifact_count += 1
        runtime = read('episode.json')['runtime']['source_sha256']
        for name in ('runner.py','observation.py','trace.py','chaos.py','chaos_verifier.py'):
            if runtime[name] != sha(ROOT/'intent_browser'/name):
                raise ValueError('Chaos evidence was not executed by the current runtime')
        session, external = read('chaos-session.json'), read('external_evaluation.json')
        if session['session'] in sessions or session['environment_revision']['files_sha256'] != cert['files_sha256']:
            raise ValueError('Chaos session/build mismatch')
        sessions.add(session['session'])
        snapshots = [read('initial-state.json')['task_state']['browser_state']]
        snapshots += [json.loads(p.read_text()) for p in sorted(directory.glob('task-state-*.json'))]
        start_url = session['base_url'] + session['selected']['taskUrl']
        result = evaluate_trace(read('chaos-contract.json'), session, external['score'], external['events']['events'],
                                [snap for snap in snapshots if snap['url'] == start_url])
        if result != case['replayed_contract']:
            raise ValueError('Chaos contract replay mismatch')
        steps = [json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
        if any(row.get('model_request') is not None for row in steps):
            raise ValueError('Unexpected model HTTP request in scripted Chaos evidence')
        cases.append({'episode':case['episode'], 'task':case['task'], 'scenario':case['scenario'],
                      'replay':'chaos_contract', 'hashes_match':True})
    if len(cases) != 23 or len(sessions) != 16:
        raise ValueError('Incomplete 23-case readiness evidence')
    return {'reference':str(reference.relative_to(ROOT)), 'reference_sha256':sha(reference),
            'runtime_commit':readiness['git_commit'], 'source_sha256':readiness['source_sha256'],
            'validation_reports_sha256':reports, 'cases':cases, 'artifact_hash_checks':artifact_count,
            'exposure_contract':'policy-input-ack-v2', 'chaos_certificate_current':True,
            'known_unfixed':readiness['known_unfixed'],
            'scope':'Local saved-artifact validation/replay; no new browser execution or live process attestation.'}


def main():
    from importlib.metadata import version
    import browsergym.core.env as bg_env
    import browsergym.utils.obs as bg_obs
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    dependencies = {name: version(name) for name in ('browsergym-core', 'playwright', 'httpx', 'gymnasium', 'numpy')}
    if dependencies['browsergym-core'] != '0.14.3':
        raise ValueError('Unreviewed BrowserGym version')
    evidence = readiness_evidence()
    body = {'protocol_id': STATE.name, 'status': 'offline_wrapper_only', 'live_enabled': False,
            'training_eligible': False, 'curation_ready': False, 'case': None,
            'source_sha256': fingerprints(), 'inherited_ledgers': inherited_evidence(),
            'dependency_versions': dependencies, 'readiness_evidence': evidence,
            'extraction_source_sha256': {'browsergym.core.env': sha(bg_env.__file__), 'browsergym.utils.obs': sha(bg_obs.__file__)},
            'model': MODEL, 'generation': {'temperature': 0, 'max_tokens': MAX_TOKENS, **options()},
            'session_id': 'episode_id; supplied by run_episode', 'observation_lifecycle': 'paced-fresh-v1',
            'max_steps': MAX_STEPS, 'pace_seconds': PACE, 'retries': 0, 'search': None, 'cache_padding': False,
            'approved_cap_usd': str(CAP), 'carried_reservations_usd': str(CARRIED),
            'per_request_reservation_usd': str(RESERVATION),
            'readiness': {'harness_contract': 'OBSERVATION_PACING.md',
                          'chaos_certificate_current': evidence['chaos_certificate_current'],
                          'tricky_exposure': 'policy-input-ack-v2 / verifier v2; decision input plus completion acknowledgment before first checkout; failed/unmatched attempts preserve null',
                          'paid_cohort': 'not staged or enabled'},
            'scope': 'Project inference import closure plus dependency versions and extraction implementation hashes; no environment adapter selected.'}
    path = STATE/'profile.json'
    if path.exists():
        if json.loads(path.read_text()) != body:
            raise ValueError('Offline profile inputs changed; stage a new revision without overwriting')
    else:
        write_json(path, body)
    print(json.dumps({'profile': str(path.relative_to(ROOT)), 'sha256': sha(path),
                      'live_enabled': False, 'carried_reservations_usd': str(CARRIED),
                      'readiness': body['readiness']}, indent=2))


if __name__ == '__main__':
    main()
