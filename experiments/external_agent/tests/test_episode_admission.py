"""Offline admission/transport controls: no OAuth or provider requests."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from experiments.external_agent.backend import ExternalAgentBackend
from experiments.external_agent.episode_admission import EpisodeConcurrency, EpisodeLease, SuiteEpisode
from experiments.external_agent.protocol import digest
from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
from intent_browser.backend import BackendResponseError


def quota(weekly=80, short=20):
    bucket = {'limitId': 'codex', 'planType': 'pro',
        'primary': {'usedPercent': short, 'windowDurationMins': 300, 'resetsAt': 100},
        'secondary': {'usedPercent': weekly, 'windowDurationMins': 10080, 'resetsAt': 200}}
    return {'ordinaryUsageAllowed': True, 'rateLimits': deepcopy(bucket),
            'rateLimitsByLimitId': {'codex': bucket}}


def backend(root, name, config=None, *, reader=quota, **options):
    return ExternalAgentBackend('gpt-6-luna', root / name, pi_cli='fixture-only',
        lock_path=root / 'subscription.lock', episode_concurrency=config,
        quota_guard=SubscriptionQuotaGuard(root / 'quota', reader=reader) if config else None,
        **options)


def worker(envelope, responses=None):
    """In-process stand-in; same audited bridge envelope, no child/network."""
    body = json.loads(envelope)
    key = body['payload']['prompt_cache_key']
    output = [
        {'type': 'reasoning', 'id': 'rs_' + key, 'summary': [], 'encrypted_content': 'opaque_' + key},
        {'type': 'message', 'id': 'msg_' + key, 'role': 'assistant',
         'content': [{'type': 'output_text', 'text': 'answer_' + key}]}]
    response = {'model': 'gpt-6-luna', 'status': 'completed', 'output': output,
                'usage': {'input_tokens': 4, 'output_tokens': 3, 'total_tokens': 7}}
    if responses is not None:
        responses.append(deepcopy(body))
    return SimpleNamespace(returncode=0, stdout=json.dumps(
        {'version': 1, 'id': body['id'], 'ok': True, 'sends': 1, 'response': response}))


@pytest.mark.parametrize('values', [('', 2, 3), (' ', 1, 1), ('x', True, 2),
    ('x', 2, False), ('x', 0, 2), ('x', 2, 1), ('x', 35, 35), ('x', 1, 35), ('x', 1.0, 2)])
def test_config_rejects_missing_unbounded_or_noninteger_limits(values):
    with pytest.raises(ValueError):
        EpisodeConcurrency(*values)


def test_default_exclusive_and_parallel_conflict_both_directions(tmp_path):
    cfg = EpisodeConcurrency('suite', 2, 3)
    a, b, pool = backend(tmp_path, 'a'), backend(tmp_path, 'b'), backend(tmp_path, 'pool', cfg)
    try:
        assert a.begin_episode('a')['concurrency'] == 1
        with pytest.raises(ValueError, match='Another external'): b.begin_episode('b')
        with pytest.raises(ValueError, match='Another external'): pool.begin_episode('p')
        a.close()
        assert pool.begin_episode('p')['concurrency'] == 2
        with pytest.raises(ValueError, match='Another external'): b.begin_episode('b')
        pool.close()
        b.begin_episode('b')
    finally:
        for item in (a, b, pool): item.close()


def test_exact_34_concurrent_admissions_and_35th_rejected(tmp_path):
    cfg = EpisodeConcurrency('suite34', 34, 34)
    items = [backend(tmp_path, f'b{i}', cfg) for i in range(35)]
    barrier = threading.Barrier(34)
    def admit(index):
        barrier.wait(timeout=10)
        return items[index].begin_episode(f'episode{index}')
    try:
        with ThreadPoolExecutor(max_workers=34) as pool:
            results = list(pool.map(admit, range(34)))
        assert {x['suite_episodes_started'] for x in results} == set(range(1, 35))
        assert len({x['session_id'] for x in results}) == 34
        with pytest.raises(ValueError, match='Concurrent episode allowance'):
            items[34].begin_episode('episode34')
        items[0].close()
        with pytest.raises(ValueError, match='Suite episode allowance'):
            items[34].begin_episode('episode34')
    finally:
        for item in items: item.close()


def test_free_probe_locks_are_released_before_control_handoff(tmp_path):
    cfg = EpisodeConcurrency('suite', 2, 2)
    first = EpisodeLease(tmp_path / 'subscription.lock', cfg)
    second = EpisodeLease(tmp_path / 'subscription.lock', cfg)
    control = first._control
    admitted = []
    @contextmanager
    def next_admission_immediately_after_unlock():
        with control():
            yield
        # Deterministic worst-case scheduler: next process enters as soon as
        # control unlocks, before begin() runs any outside-context cleanup.
        admitted.append(second.begin('second'))
    try:
        with patch.object(first, '_control', next_admission_immediately_after_unlock):
            assert first.begin('first')['suite_episodes_started'] == 1
        assert admitted[0]['suite_episodes_started'] == 2
    finally:
        first.close(); second.close()


@pytest.mark.parametrize('replacement', [EpisodeConcurrency('other', 2, 3),
    EpisodeConcurrency('suite', 1, 3), EpisodeConcurrency('suite', 2, 4)])
def test_active_suite_cannot_change_identity_or_limits(tmp_path, replacement):
    a = backend(tmp_path, 'a', EpisodeConcurrency('suite', 2, 3))
    b = backend(tmp_path, 'b', replacement)
    try:
        a.begin_episode('a')
        with pytest.raises(ValueError, match='incompatible'): b.begin_episode('b')
    finally:
        a.close(); b.close()


def test_binding_remains_exact_after_all_leases_close_and_id_cannot_replay(tmp_path):
    cfg = EpisodeConcurrency('suite', 2, 3)
    a, b = backend(tmp_path, 'a', cfg), backend(tmp_path, 'b', cfg)
    a.begin_episode('same'); a.close()
    with pytest.raises(ValueError, match='already consumed'): b.begin_episode('same')
    c = backend(tmp_path, 'c', EpisodeConcurrency('suite', 2, 4))
    try:
        with pytest.raises(ValueError, match='ledger is incompatible'): c.begin_episode('different')
    finally:
        b.close(); c.close()


@pytest.mark.parametrize('field,value', [('model', 'other'), ('reasoning_effort', 'high'),
    ('provider_output_limit', True)])
def test_transport_binding_cannot_mix_models_effort_or_output_mode(tmp_path, field, value):
    cfg = EpisodeConcurrency('suite', 2, 3)
    a, b = backend(tmp_path, 'a', cfg), backend(tmp_path, 'b', cfg)
    setattr(b, field, value)
    try:
        a.begin_episode('a')
        with pytest.raises(ValueError, match='incompatible'): b.begin_episode('b')
    finally:
        a.close(); b.close()


def test_parallel_requires_guard_and_at_least_one_percent_floor(tmp_path):
    cfg = EpisodeConcurrency('suite', 2, 2)
    for guard in (None, lambda: quota(), SubscriptionQuotaGuard(tmp_path, remaining_floor=.1, reader=quota)):
        with pytest.raises(ValueError, match='quota guard'):
            ExternalAgentBackend('gpt-6-luna', tmp_path / 'unused',
                episode_concurrency=cfg, quota_guard=guard)
    assert not (tmp_path / 'unused').exists()


@pytest.mark.parametrize('reader', [lambda: quota(weekly=99), lambda: quota(short=99), lambda: {},
    lambda: {'rateLimitsByLimitId': {'codex': {'limitId': 'codex',
        'secondary': {'usedPercent': 80, 'windowDurationMins': 10080, 'resetsAt': 200}}}}])
def test_quota_failure_never_sends_releases_capacity_and_consumes_start(tmp_path, reader):
    cfg = EpisodeConcurrency('suite', 1, 2)
    a, b = backend(tmp_path, 'a', cfg, reader=reader), backend(tmp_path, 'b', cfg)
    try:
        a.begin_episode('a')
        with patch('experiments.external_agent.backend.subprocess.run') as send:
            with pytest.raises(BackendResponseError): a.complete([{'role': 'user', 'content': 'hello'}])
            send.assert_not_called()
        assert a.failed and a._lease is None
        assert json.loads((tmp_path / 'quota/checks.jsonl').read_text())['paid_fallback'] is False
        info = b.begin_episode('b')
        assert info['suite_episodes_started'] == 2
        assert json.loads(Path(info['admission_ledger']).read_text())['dispatches'] == 0
        with pytest.raises(ValueError): a.complete([{'role': 'user', 'content': 'retry'}])
        assert not (tmp_path / 'a/0002').exists()
    finally:
        a.close(); b.close()


def test_shared_quota_reads_serialize_but_inference_runs_concurrently(tmp_path):
    cfg = EpisodeConcurrency('suite', 8, 8)
    reading = peak = 0
    def reader():
        nonlocal reading, peak
        reading += 1; peak = max(peak, reading)
        time.sleep(.02)
        reading -= 1
        return quota()
    items = [backend(tmp_path, f'b{i}', cfg, reader=reader) for i in range(8)]
    for i, item in enumerate(items): info = item.begin_episode(str(i))
    barrier = threading.Barrier(8)
    def dispatch(*args, input, **kwargs):
        barrier.wait(timeout=10)  # Fails if inference holds the control lock.
        return worker(input)
    try:
        with patch('experiments.external_agent.backend.subprocess.run', side_effect=dispatch):
            with ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(lambda b: b.complete([{'role': 'user', 'content': 'hello'}]), items))
        assert len(responses) == 8 and peak == 1
        ledger = json.loads(Path(info['admission_ledger']).read_text())
        assert ledger['dispatches'] == 8
        assert all(item['dispatches'] == 1 for item in ledger['episodes'].values())
        assert len((tmp_path / 'quota/checks.jsonl').read_text().splitlines()) == 8
    finally:
        for item in items: item.close()


def test_34_wide_slow_healthy_quota_reader_does_not_poison_queued_cases(tmp_path):
    cfg = EpisodeConcurrency('slow-suite', 34, 34)
    def reader():
        time.sleep(.8)  # Reviewer reproduction: 34 * .8 exceeds former 20s wait.
        return quota()
    items = [backend(tmp_path, f'b{i}', cfg, reader=reader) for i in range(34)]
    start = threading.Barrier(34)
    for i, item in enumerate(items): info = item.begin_episode(str(i))
    assert info['admission_lock_wait_seconds'] == 20 + 34 * 50
    assert info['quota_read_allowance_seconds'] == 50
    assert info['admission_wait_seconds'] == 20 + 35 * 50
    def turn(item):
        start.wait(timeout=10)
        return item.complete([{'role': 'user', 'content': 'hello'}])
    try:
        with patch('experiments.external_agent.backend.subprocess.run',
                   side_effect=lambda *args, input, **kw: worker(input)) as send:
            with ThreadPoolExecutor(max_workers=34) as pool:
                responses = list(pool.map(turn, items))
        assert len(responses) == send.call_count == 34
        assert all(not item.failed for item in items)
        assert json.loads(Path(info['admission_ledger']).read_text())['dispatches'] == 34
    finally:
        for item in items: item.close()


def test_same_episode_rejects_concurrent_calls_and_close_waits_for_worker(tmp_path):
    cfg = EpisodeConcurrency('suite', 1, 2)
    a, b = backend(tmp_path, 'a', cfg), backend(tmp_path, 'b', cfg)
    a.begin_episode('a')
    entered, finish = threading.Event(), threading.Event()
    def dispatch(*args, input, **kwargs):
        entered.set()
        assert finish.wait(10)
        return worker(input)
    try:
        with patch('experiments.external_agent.backend.subprocess.run', side_effect=dispatch):
            with ThreadPoolExecutor(max_workers=2) as pool:
                call = pool.submit(a.complete, [{'role': 'user', 'content': 'hello'}])
                assert entered.wait(5)
                with pytest.raises(ValueError, match='Concurrent completion'): a.complete([])
                with pytest.raises(ValueError, match='Concurrent completion'): a.complete_request({})
                close = pool.submit(a.close)
                with pytest.raises(ValueError, match='Concurrent episode'): b.begin_episode('b')
                assert not close.done()
                finish.set(); call.result(timeout=5); close.result(timeout=5)
        b.begin_episode('b')
    finally:
        finish.set(); a.close(); b.close()


def test_session_replay_artifacts_and_cache_keys_remain_private(tmp_path):
    cfg = EpisodeConcurrency('suite', 2, 2)
    a, b = backend(tmp_path, 'a', cfg), backend(tmp_path, 'b', cfg)
    sent = []
    try:
        a.begin_episode('alpha'); b.begin_episode('beta')
        with patch('experiments.external_agent.backend.subprocess.run',
                   side_effect=lambda *args, input, **kw: worker(input, sent)):
            first = [item.complete([{'role': 'user', 'content': 'hello'}]) for item in (a, b)]
            for item, result in zip((a, b), first):
                message = result.raw['choices'][0]['message']
                item.complete([{'role': 'user', 'content': 'hello'}, message,
                               {'role': 'user', 'content': 'continue'}])
        assert [entry['payload']['prompt_cache_key'] for entry in sent] == ['alpha', 'beta', 'alpha', 'beta']
        assert 'opaque_alpha' in json.dumps(sent[2]) and 'opaque_beta' not in json.dumps(sent[2])
        assert 'opaque_beta' in json.dumps(sent[3]) and 'opaque_alpha' not in json.dumps(sent[3])
        assert digest(first[0].raw['choices'][0]['message']) not in b.replay
        assert len({entry['artifact_dir'] for entry in sent}) == 4
        with pytest.raises(ValueError, match='one declared episode'):
            a.complete_request({'model': 'gpt-6-luna', 'session_id': 'beta'})
    finally:
        a.close(); b.close()


def test_source_failure_holds_before_quota_and_worker_and_never_replays(tmp_path):
    def changed(): raise RuntimeError('source changed')
    cfg = EpisodeConcurrency('suite', 1, 2)
    a, b = backend(tmp_path, 'a', cfg, before_dispatch=changed), backend(tmp_path, 'b', cfg)
    try:
        a.begin_episode('a')
        with patch('experiments.external_agent.backend.subprocess.run') as send:
            with pytest.raises(BackendResponseError): a.complete([{'role': 'user', 'content': 'hello'}])
            send.assert_not_called()
        assert not (tmp_path / 'quota').exists()
        b.begin_episode('b')
    finally:
        a.close(); b.close()


def _process_lease(lock_path, config, episode, ready, finish):
    lease = EpisodeLease(lock_path, config)
    try:
        info = lease.begin(episode)
        ready.put(('ok', episode, info))
        if not finish.poll(15): raise TimeoutError('test parent did not release child')
        finish.recv()
    except Exception as error:
        ready.put(('error', episode, str(error)))
    finally:
        lease.close()


def test_cross_process_race_and_crash_release_without_budget_refund(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    cfg = EpisodeConcurrency('multiprocess', 4, 5)
    queue = ctx.Queue()
    pipes = [ctx.Pipe() for _ in range(4)]
    children = [ctx.Process(target=_process_lease,
        args=(tmp_path / 'subscription.lock', cfg, f'child{i}', queue, pipes[i][1])) for i in range(4)]
    try:
        for child in children: child.start()
        reports = [queue.get(timeout=10) for _ in children]
        assert all(x[0] == 'ok' for x in reports), reports
        assert {x[2]['suite_episodes_started'] for x in reports} == {1, 2, 3, 4}
        extra = EpisodeLease(tmp_path / 'subscription.lock', cfg)
        with pytest.raises(ValueError, match='Concurrent episode'): extra.begin('extra')
        children[0].kill(); children[0].join(timeout=5)
        assert children[0].exitcode == -9
        assert extra.begin('extra')['suite_episodes_started'] == 5
        extra.close()
        for parent, _ in pipes[1:]: parent.send('finish')
        for child in children[1:]:
            child.join(timeout=5); assert child.exitcode == 0
        again = EpisodeLease(tmp_path / 'subscription.lock', cfg)
        with pytest.raises(ValueError, match='already consumed'): again.begin('child0')
        with pytest.raises(ValueError, match='Suite episode'): again.begin('sixth')
        exclusive = EpisodeLease(tmp_path / 'subscription.lock')
        exclusive.begin('default-after-crash'); exclusive.close()
    finally:
        for child in children:
            if child.is_alive(): child.kill()
            child.join(timeout=5)
        queue.close(); queue.join_thread()
        for parent, child in pipes: parent.close(); child.close()


def test_case_lease_spans_policy_and_one_formatter_with_separate_sessions(tmp_path):
    cfg = EpisodeConcurrency('suite', 1, 1)
    guard = SubscriptionQuotaGuard(tmp_path / 'quota', reader=quota)
    case = SuiteEpisode(cfg, tmp_path / 'subscription.lock', guard, model='gpt-6-luna')
    info = case.begin_episode('case1')
    def phase(name, effort, path):
        return ExternalAgentBackend('gpt-6-luna', tmp_path / path, pi_cli='fixture-only',
            suite_episode=case, episode_phase=name, reasoning_effort=effort)
    policy = phase('policy', 'medium', 'policy')
    formatter = phase('formatter', 'low', 'formatter')
    second_formatter = phase('formatter', 'low', 'second-formatter')
    extra_policy = phase('policy', 'medium', 'extra-policy')
    try:
        policy.begin_episode('policy-session')
        with pytest.raises(ValueError, match='in-flight phase'): formatter.begin_episode('early')
        with pytest.raises(ValueError, match='active phase'): case.close()
        with patch('experiments.external_agent.backend.subprocess.run',
                   side_effect=lambda *args, input, **kw: worker(input)):
            result = policy.complete([{'role': 'user', 'content': 'policy'}])
            policy.close()
            with pytest.raises(ValueError, match='fresh session'): formatter.begin_episode('policy-session')
            formatter.begin_episode('formatter-session')
            assert formatter.replay == {} and policy.replay
            formatter.complete([{'role': 'user', 'content': result.text}])
            formatter.close()
        with pytest.raises(ValueError, match='already consumed'): second_formatter.begin_episode('formatter2')
        with pytest.raises(ValueError, match='already consumed'): extra_policy.begin_episode('policy2')
        ledger = json.loads(Path(info['admission_ledger']).read_text())
        assert list(ledger['episodes']) == ['case1'] and ledger['dispatches'] == 2
        assert ledger['episodes']['case1']['phases'] == {
            'policy': {'session_id': 'policy-session', 'status': 'closed', 'dispatches': 1},
            'formatter': {'session_id': 'formatter-session', 'status': 'closed', 'dispatches': 1}}
        case.close()
        with pytest.raises(ValueError, match='Suite episode allowance'):
            backend(tmp_path, 'unapproved', cfg).begin_episode('case2')
    finally:
        for item in (policy, formatter, second_formatter, extra_policy): item.close()
        case.close()


def test_formatter_cannot_start_without_policy_or_change_effort(tmp_path):
    cfg = EpisodeConcurrency('suite', 1, 1)
    case = SuiteEpisode(cfg, tmp_path / 'subscription.lock',
        SubscriptionQuotaGuard(tmp_path / 'quota', reader=quota), model='gpt-6-luna')
    case.begin_episode('case')
    try:
        with pytest.raises(ValueError, match='closed first'):
            case.claim_phase('formatter', 'formatter', model='gpt-6-luna',
                reasoning_effort='low', provider_output_limit=False)
        with pytest.raises(ValueError, match='binding'):
            case.claim_phase('policy', 'policy', model='gpt-6-luna',
                reasoning_effort='high', provider_output_limit=False)
    finally:
        case.close()


def test_formatter_gets_one_dispatch_and_no_silent_retry(tmp_path):
    cfg = EpisodeConcurrency('suite', 1, 1)
    case = SuiteEpisode(cfg, tmp_path / 'subscription.lock',
        SubscriptionQuotaGuard(tmp_path / 'quota', reader=quota), model='gpt-6-luna')
    case.begin_episode('case')
    policy = ExternalAgentBackend('gpt-6-luna', tmp_path / 'policy', pi_cli='fixture-only', suite_episode=case)
    formatter = ExternalAgentBackend('gpt-6-luna', tmp_path / 'formatter', pi_cli='fixture-only',
        suite_episode=case, episode_phase='formatter', reasoning_effort='low')
    try:
        policy.begin_episode('policy'); policy.close()
        formatter.begin_episode('formatter')
        with patch('experiments.external_agent.backend.subprocess.run',
                   side_effect=lambda *args, input, **kw: worker(input)) as send:
            formatter.complete([{'role': 'user', 'content': 'format answer'}])
            with pytest.raises(BackendResponseError):
                formatter.complete([{'role': 'user', 'content': 'unapproved retry'}])
            assert send.call_count == 1
        assert formatter.failed and formatter._lease is None
    finally:
        policy.close(); formatter.close(); case.close()


def test_cli_requires_complete_finite_configuration_before_server_start(tmp_path):
    for flags in (['--max-concurrent-episodes', '2'], ['--suite-id', 'suite'],
                  ['--suite-id', 'suite', '--max-suite-episodes', '35'],
                  ['--suite-id', 'suite', '--max-suite-episodes', '2'],
                  ['--suite-id', 'suite', '--max-suite-episodes', '2', '--subscription-lock', str(tmp_path / 'lock')]):
        call = subprocess.run([sys.executable, '-m', 'experiments.external_agent', 'serve',
            '--model', 'gpt-6-luna', '--output', str(tmp_path / 'unused'), *flags],
            capture_output=True, text=True, timeout=10)
        assert call.returncode == 2
        assert not (tmp_path / 'unused').exists()


def test_parallel_backend_requires_explicit_shared_lock(tmp_path):
    with pytest.raises(ValueError, match='explicit canonical'):
        ExternalAgentBackend('gpt-6-luna', tmp_path / 'unused', pi_cli='fixture-only',
            episode_concurrency=EpisodeConcurrency('suite', 1, 1),
            quota_guard=SubscriptionQuotaGuard(tmp_path / 'quota', reader=quota))
    assert not (tmp_path / 'unused').exists()


def test_default_error_retains_exclusive_lease_until_close(tmp_path):
    a, b = backend(tmp_path, 'a'), backend(tmp_path, 'b')
    try:
        a.begin_episode('a')
        with patch('experiments.external_agent.backend.subprocess.run', side_effect=RuntimeError('fixture')):
            with pytest.raises(BackendResponseError): a.complete([{'role': 'user', 'content': 'hello'}])
        with pytest.raises(ValueError, match='Another external'): b.begin_episode('b')
        a.close(); b.begin_episode('b')
    finally:
        a.close(); b.close()


def test_failure_record_and_backend_error_survive_phase_close_write_failure(tmp_path):
    from experiments.external_agent import episode_admission as admission
    cfg = EpisodeConcurrency('suite', 1, 2)
    item = backend(tmp_path, 'one', cfg)
    item.begin_episode('one')
    original = admission._write
    def write(path, record):
        if record['episodes']['one'].get('phases', {}).get('policy', {}).get('status') == 'closed':
            raise OSError('fixture disk full')
        return original(path, record)
    try:
        with (patch('experiments.external_agent.backend.subprocess.run', side_effect=RuntimeError('fixture worker error')),
              patch.object(admission, '_write', write)):
            with pytest.raises(BackendResponseError) as failure:
                item.complete([{'role': 'user', 'content': 'hello'}])
        assert failure.value.response_payload == {'error_type': 'RuntimeError', 'cleanup_error_type': 'OSError'}
        assert json.loads((tmp_path / 'one/0001/failure.json').read_text())['type'] == 'RuntimeError'
        assert json.loads((tmp_path / 'one/0001/lease-cleanup-failure.json').read_text())['type'] == 'OSError'
        assert item.failed and item._lease is None
        replacement = backend(tmp_path, 'two', cfg)
        replacement.begin_episode('two'); replacement.close()
    finally:
        item.close()


def test_sessions_cannot_be_reused_across_case_leases(tmp_path):
    cfg = EpisodeConcurrency('suite', 2, 2)
    cases = [SuiteEpisode(cfg, tmp_path / 'subscription.lock',
        SubscriptionQuotaGuard(tmp_path / 'quota', reader=quota), model='gpt-6-luna') for _ in range(2)]
    try:
        for i, case in enumerate(cases): case.begin_episode(str(i))
        cases[0].claim_phase('policy', 'shared', model='gpt-6-luna', reasoning_effort='medium', provider_output_limit=False)
        cases[0].finish_phase('policy', 'shared')
        with pytest.raises(ValueError, match='across all cases'):
            cases[1].claim_phase('policy', 'shared', model='gpt-6-luna', reasoning_effort='medium', provider_output_limit=False)
    finally:
        for case in cases: case.close()


def test_suite_cli_validates_complete_registration_without_starting_server(tmp_path, monkeypatch):
    from experiments.external_agent import __main__ as cli
    calls = []
    monkeypatch.setattr(cli, 'serve', calls.append)
    monkeypatch.setattr(sys, 'argv', ['bridge', 'serve', '--model', 'gpt-6-luna',
        '--output', str(tmp_path / 'out'), '--suite-id', 'suite', '--max-suite-episodes', '2',
        '--max-concurrent-episodes', '2', '--subscription-lock', str(tmp_path / 'shared.lock'), '--episode-id', 'case'])
    cli.main()
    assert len(calls) == 1 and calls[0].episode_id == 'case'
    assert calls[0].max_concurrent_episodes == 2 and not (tmp_path / 'out').exists()


def test_suite_serve_records_queue_metadata_and_checks_actual_quota_reader(tmp_path, monkeypatch):
    from experiments.external_agent import server
    from scripts import product_width_watch
    helper = tmp_path / 'quota-reader.py'
    helper.write_text('# fixture source pin\n')
    monkeypatch.setattr(product_width_watch, '__file__', str(helper))
    monkeypatch.setattr('experiments.external_agent.backend.shutil.which', lambda name: 'fixture-only')
    class FixtureServer:
        server_port = 12345
        def __init__(self, backend, token, **kwargs): self.backend = backend
        def serve_forever(self, **kwargs):
            helper.write_text('# changed source\n')
            with patch('experiments.external_agent.backend.subprocess.run') as send:
                with pytest.raises(BackendResponseError):
                    self.backend.complete([{'role': 'user', 'content': 'hello'}])
                send.assert_not_called()
            raise KeyboardInterrupt()
        def server_close(self): pass
    monkeypatch.setattr(server, 'BridgeServer', FixtureServer)
    args = SimpleNamespace(output=tmp_path / 'out', suite_id='suite', max_concurrent_episodes=2,
        max_suite_episodes=2, subscription_lock=tmp_path / 'shared.lock', episode_id='case',
        model='gpt-6-luna', timeout=180, reasoning_effort='medium', provider_output_limit=True,
        port=0, max_requests=200)
    server.serve(args)
    meta = json.loads((tmp_path / 'out/server.json').read_text())
    assert str(helper) in meta['sources']
    assert meta['episode_admission']['concurrency'] == 2
    assert meta['minimum_client_timeout_seconds'] == 180 + 10 + meta['episode_admission']['admission_wait_seconds']
    assert meta['subscription_remaining_floor_percent'] == 1
    assert not (tmp_path / 'out/quota').exists()


def test_corrupt_ledger_fails_closed_and_releases_kernel_lease(tmp_path):
    cfg = EpisodeConcurrency('suite', 1, 2)
    lease = EpisodeLease(tmp_path / 'subscription.lock', cfg)
    info = lease.begin('one'); lease.close()
    Path(info['admission_ledger']).write_text('{"binding":{},"episodes":{}}')
    with pytest.raises(ValueError, match='ledger is incompatible'):
        lease = EpisodeLease(tmp_path / 'subscription.lock', cfg); lease.begin('two')
    exclusive = EpisodeLease(tmp_path / 'subscription.lock')
    exclusive.begin('default'); exclusive.close()
