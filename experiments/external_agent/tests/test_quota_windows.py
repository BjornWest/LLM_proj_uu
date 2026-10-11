"""Synthetic complete quota reads and real HTTP facade; no provider/account calls."""
from copy import deepcopy
import json
import threading
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from experiments.external_agent.subscription_quota import (
    snapshot, SubscriptionQuotaGuard, SubscriptionQuotaUnavailable, SubscriptionQuotaExhausted,
)
from experiments.external_agent.episode_admission import EpisodeConcurrency, EpisodeLease, SuiteEpisode
from experiments.external_agent.backend import ExternalAgentBackend
from experiments.external_agent.server import BridgeServer
from experiments.external_agent.tests.test_episode_admission import worker


def single(name='primary', *, used=1, duration=10080):
    bucket = {'limitId': 'codex', 'primary': None, 'secondary': None}
    bucket[name] = {'usedPercent': used, 'windowDurationMins': duration, 'resetsAt': 200}
    return {'rateLimitsByLimitId': {'codex': bucket}, 'rateLimits': deepcopy(bucket)}


@pytest.mark.parametrize('name', ['primary', 'secondary'])
@pytest.mark.parametrize('shape', ['both', 'legacy', 'multi'])
def test_explicit_null_window_is_known_absence(name, shape):
    raw = single(name)
    if shape == 'legacy': del raw['rateLimitsByLimitId']
    if shape == 'multi': del raw['rateLimits']
    saved = deepcopy(raw)
    checked = snapshot(raw, require_complete_windows=True)
    assert raw == saved
    assert checked['weekly']['remaining_percent'] == 99
    assert checked['windows'] == [{'name': name, 'duration_minutes': 10080,
                                  'remaining_percent': 99, 'resets_at': 200}]
    assert checked['window_states'][name] == 'applicable'
    assert checked['window_states']['secondary' if name == 'primary' else 'primary'] == 'not_applicable'


def test_only_shorter_window_remains_enforced_without_fake_weekly_allowance(tmp_path):
    guard = SubscriptionQuotaGuard(tmp_path, reader=lambda: single(duration=300))
    checked = guard(require_complete_windows=True)
    assert checked['weekly'] is None and checked['windows'][0]['remaining_percent'] == 99
    guard.reader = lambda: single(duration=300, used=99)
    with pytest.raises(SubscriptionQuotaExhausted): guard(require_complete_windows=True)


@pytest.mark.parametrize('name', ['primary', 'secondary'])
@pytest.mark.parametrize('used', [99, 100])
def test_every_applicable_window_enforces_floor(tmp_path, name, used):
    guard = SubscriptionQuotaGuard(tmp_path, reader=lambda: single(name, used=used))
    with pytest.raises(SubscriptionQuotaExhausted): guard(require_complete_windows=True)
    receipt = json.loads((tmp_path/'checks.jsonl').read_text())
    assert receipt['status'] == 'held_at_floor' and receipt['paid_fallback'] is False


def invalid_reads():
    bad = [None, [], {}, {'rateLimits': None, 'rateLimitsByLimitId': None},
           {'rateLimitsByLimitId': []}, {'rateLimitsByLimitId': {'reserve': single()['rateLimits']}},
           {'rateLimitsByLimitId': {'codex': None}},
           {'rateLimits': {'limitId': 'codex', 'primary': None, 'secondary': None}}]
    bucket = single()['rateLimits']
    for key in ('primary', 'secondary', 'limitId'):
        value = deepcopy(bucket); del value[key]; bad.append({'rateLimits': value})
    for value in ({}, [], '', False, 0):
        value_bucket = deepcopy(bucket); value_bucket['secondary'] = value
        bad.append({'rateLimits': value_bucket})
    for key, values in {'usedPercent': [True, '1', -1, 101, float('nan'), float('inf'), 10**500],
                        'windowDurationMins': [True, None, 0, -1, '10080', 10080.0],
                        'resetsAt': [True, None, -1, '200', 200.0]}.items():
        for value in values:
            value_bucket = deepcopy(bucket); value_bucket['primary'][key] = value
            bad.append({'rateLimits': value_bucket})
        value_bucket = deepcopy(bucket); del value_bucket['primary'][key]
        bad.append({'rateLimits': value_bucket})
    for key, value in [('limitId', 'reserve'), ('tertiary', bucket['primary']),
                        ('spendControlReached', True), ('spendControlReached', 0),
                        ('spendControlReached', 'false'), ('rateLimitReachedType', 'unknown')]:
        value_bucket = deepcopy(bucket); value_bucket[key] = value
        bad.append({'rateLimits': value_bucket})
    extra = deepcopy(bucket); extra['primary']['unknown'] = 0; bad.append({'rateLimits': extra})
    conflict = single(); conflict['rateLimits']['primary']['usedPercent'] = 2; bad.append(conflict)
    mismatch = single(); mismatch['rateLimits']['secondary'] = mismatch['rateLimits'].pop('primary'); bad.append(mismatch)
    invalid_legacy = single(); invalid_legacy['rateLimits'] = []; bad.append(invalid_legacy)
    for value in (False, None, 1, 'true'):
        item = single(); item['ordinaryUsageAllowed'] = value; bad.append(item)
    return bad


@pytest.mark.parametrize('raw', invalid_reads())
def test_unknown_or_malformed_snapshot_never_records_admitted(tmp_path, raw):
    guard = SubscriptionQuotaGuard(tmp_path, reader=lambda: raw)
    with pytest.raises(SubscriptionQuotaUnavailable): guard(require_complete_windows=True)
    receipt = json.loads((tmp_path/'checks.jsonl').read_text())
    assert receipt['status'] == 'held_unverifiable' and receipt['paid_fallback'] is False
    assert not receipt.get('quota')


def test_other_bucket_and_credits_cannot_supply_subscription_allowance(tmp_path):
    raw = single(used=99)
    raw['rateLimitsByLimitId']['reserve'] = single()['rateLimits']
    for bucket in (raw['rateLimits'], raw['rateLimitsByLimitId']['codex']):
        bucket['credits'] = {'hasCredits': True, 'unlimited': True, 'balance': '999999'}
    guard = SubscriptionQuotaGuard(tmp_path, reader=lambda: raw)
    with pytest.raises(SubscriptionQuotaExhausted): guard(require_complete_windows=True)


def test_guard_refreshes_null_into_new_applicable_window_and_blocks_it(tmp_path):
    reads = [single(), single()]
    for bucket in (reads[1]['rateLimits'], reads[1]['rateLimitsByLimitId']['codex']):
        bucket['secondary'] = {'usedPercent': 99, 'windowDurationMins': 300, 'resetsAt': 100}
    guard = SubscriptionQuotaGuard(tmp_path, reader=lambda: reads.pop(0))
    assert len(guard(require_complete_windows=True)['windows']) == 1
    with pytest.raises(SubscriptionQuotaExhausted): guard(require_complete_windows=True)
    assert not reads


def test_legacy_default_parser_retains_omitted_window_behavior(tmp_path):
    raw = single('secondary'); del raw['rateLimits']; del raw['rateLimitsByLimitId']['codex']['primary']
    guard = SubscriptionQuotaGuard(tmp_path, reader=lambda: raw)
    assert guard()['weekly']['remaining_percent'] == 99
    with pytest.raises(SubscriptionQuotaUnavailable): guard(require_complete_windows=True)


def test_live_shape_fixture_accepts_nullable_window_with_credit_metadata():
    # Portable synthetic version of the retained read shape, without account data.
    raw = single()
    raw['ordinaryUsageAllowed'] = True
    for bucket in (raw['rateLimits'], raw['rateLimitsByLimitId']['codex']):
        bucket.update(limitName=None, normalModelSlug=None, individualLimit=None,
                      spendControlReached=False, planType='pro', rateLimitReachedType=None,
                      credits={'hasCredits': True, 'unlimited': False, 'balance': 'fixture-only'})
    checked = snapshot(raw, require_complete_windows=True)
    assert checked['weekly']['remaining_percent'] == 99
    assert checked['window_states'] == {'primary': 'applicable', 'secondary': 'not_applicable'}


def test_old_suite_contract_cannot_mix_or_refund_its_consumed_case(tmp_path):
    guard = SubscriptionQuotaGuard(tmp_path/'quota', reader=single)
    cfg = EpisodeConcurrency('contract', 1, 2)
    new = SuiteEpisode(cfg, tmp_path/'subscription.lock', guard, model='gpt-6-luna')
    old_binding = dict(new.binding); del old_binding['quota_contract']
    old = EpisodeLease(tmp_path/'subscription.lock', cfg, binding=old_binding)
    old.begin('old-case'); old.close()
    try:
        with pytest.raises(ValueError, match='incompatible'): new.begin_episode('new-case')
        ledger = json.loads(next(old.root.glob('*.json')).read_text())
        assert set(ledger['episodes']) == {'old-case'} and ledger['dispatches'] == 0
    finally:
        new.close()


@pytest.mark.parametrize('mode', ['nullable', 'missing', 'floor'])
def test_actual_http_case_policy_and_formatter_use_same_strict_contract(tmp_path, mode):
    raw = single()
    if mode == 'missing':
        for bucket in (raw['rateLimits'], raw['rateLimitsByLimitId']['codex']): del bucket['secondary']
    if mode == 'floor': raw = single(used=99)
    reads, sends = [], []
    def read(): reads.append(True); return deepcopy(raw)
    guard = SubscriptionQuotaGuard(tmp_path/'quota', reader=read)
    case = SuiteEpisode(EpisodeConcurrency('http-suite', 1, 1), tmp_path/'subscription.lock', guard,
                        model='gpt-6-luna', provider_output_limit=True)
    case.begin_episode('case')
    try:
        for phase, effort in [('policy', 'medium'), ('formatter', 'low')]:
            backend = ExternalAgentBackend('gpt-6-luna', tmp_path/phase, pi_cli='fixture-only',
                suite_episode=case, episode_phase=phase, reasoning_effort=effort, provider_output_limit=True)
            backend.begin_episode(phase+'-session')
            server = BridgeServer(backend, 'fixture-token'); thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                request = Request(f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                    json.dumps({'model': 'gpt-6-luna', 'messages': [{'role': 'user', 'content': 'hello'}]}).encode(),
                    headers={'Authorization': 'Bearer fixture-token', 'Content-Type': 'application/json'})
                with patch('experiments.external_agent.backend.subprocess.run',
                           side_effect=lambda *a, **k: worker(k['input'], sends)) as send:
                    if mode == 'nullable':
                        with urlopen(request, timeout=5) as response: assert response.status == 200
                        assert send.call_count == 1
                    else:
                        with pytest.raises(HTTPError) as caught: urlopen(request, timeout=5)
                        assert caught.value.code == 502
                        send.assert_not_called()
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5); backend.close()
                assert not thread.is_alive()
        ledger = next(case.lease.root.glob('*.json'))
        assert json.loads(ledger.read_text())['dispatches'] == (2 if mode == 'nullable' else 0)
        assert len(reads) == 2 and len(sends) == (2 if mode == 'nullable' else 0)
    finally:
        case.close()
