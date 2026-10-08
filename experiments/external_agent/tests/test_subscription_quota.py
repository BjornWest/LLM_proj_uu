import json
import asyncio
import threading

import pytest

from experiments.external_agent.subscription_quota import (
    SubscriptionQuotaGuard, SubscriptionQuotaUnavailable, SubscriptionQuotaExhausted, snapshot,
)
from experiments.external_agent import subscription_quota as quota


def fixture(weekly=82, short=25):
    return {'rateLimitsByLimitId': {'codex': {'limitId': 'codex',
        'primary': {'usedPercent': short, 'windowDurationMins': 300, 'resetsAt': 100},
        'secondary': {'usedPercent': weekly, 'windowDurationMins': 10080, 'resetsAt': 200}}}}


def test_read_only_admission_records_actual_subscription_windows(tmp_path):
    g = SubscriptionQuotaGuard(tmp_path, reader=fixture)
    assert g()['weekly']['remaining_percent'] == 18
    assert json.loads((tmp_path/'checks.jsonl').read_text())['status'] == 'admitted'


@pytest.mark.parametrize('values', [{'weekly': 99}, {'weekly': 100}, {'short': 99}, {'short': 100}])
def test_floor_holds_weekly_and_shorter_window_without_fallback(tmp_path, values):
    g = SubscriptionQuotaGuard(tmp_path, reader=lambda: fixture(**values))
    with pytest.raises(SubscriptionQuotaExhausted): g()
    record=json.loads((tmp_path/'checks.jsonl').read_text())
    assert record['status'] == 'held_at_floor' and record['paid_fallback'] is False


@pytest.mark.parametrize('bad', [{}, {'rateLimits': {'limitId': 'reserve'}}, fixture(weekly=True), fixture(short=float('nan'))])
def test_unverifiable_quota_holds(tmp_path, bad):
    g = SubscriptionQuotaGuard(tmp_path, reader=lambda: bad)
    with pytest.raises(SubscriptionQuotaUnavailable): g()
    assert json.loads((tmp_path/'checks.jsonl').read_text())['status'] == 'held_unverifiable'


def test_reserve_model_pool_is_not_subscription_allowance():
    x = fixture(); x['rateLimitsByLimitId']['reserve'] = fixture(weekly=0)['rateLimitsByLimitId']['codex']
    assert snapshot(x)['weekly']['remaining_percent'] == 18


def test_telemetry_failure_retained(tmp_path):
    def reader(): raise TimeoutError('Control socket timed out')
    g=SubscriptionQuotaGuard(tmp_path, reader=reader)
    with pytest.raises(SubscriptionQuotaUnavailable): g()
    assert json.loads((tmp_path/'checks.jsonl').read_text())['error_type'] == 'TimeoutError'


@pytest.mark.parametrize('running_loop', [False, True])
def test_default_reader_refreshes_in_both_loop_contexts(tmp_path, monkeypatch, running_loop):
    caller_thread = threading.get_ident()
    reads = []

    async def read():
        await asyncio.sleep(0)
        reads.append(threading.get_ident())
        return fixture(weekly=81 + len(reads))

    monkeypatch.setattr(quota, '_read', read)
    guard = SubscriptionQuotaGuard(tmp_path)

    def callback():
        assert guard()['weekly']['remaining_percent'] == 18
        assert guard()['weekly']['remaining_percent'] == 17

    async def active_callback():
        loop = asyncio.get_running_loop()
        callback()
        await asyncio.sleep(0)
        assert asyncio.get_running_loop() is loop

    if running_loop:
        asyncio.run(active_callback())
        assert all(thread != caller_thread for thread in reads)
    else:
        callback()
        assert reads == [caller_thread, caller_thread]
    records = [json.loads(line) for line in (tmp_path/'checks.jsonl').read_text().splitlines()]
    assert [record['status'] for record in records] == ['admitted', 'admitted']


@pytest.mark.parametrize('running_loop', [False, True])
@pytest.mark.parametrize('mode', ['transport_error', 'floor', 'malformed'])
def test_default_reader_fails_closed_in_both_loop_contexts(tmp_path, monkeypatch, running_loop, mode):
    async def read():
        await asyncio.sleep(0)
        if mode == 'transport_error':
            raise TimeoutError('Control socket timed out')
        return fixture(weekly=99) if mode == 'floor' else {}

    monkeypatch.setattr(quota, '_read', read)
    guard = SubscriptionQuotaGuard(tmp_path)

    def callback():
        exception = SubscriptionQuotaExhausted if mode == 'floor' else SubscriptionQuotaUnavailable
        with pytest.raises(exception) as caught:
            guard()
        if mode == 'transport_error':
            assert isinstance(caught.value.__cause__, TimeoutError)

    async def active_callback():
        callback()
        await asyncio.sleep(0)

    if running_loop:
        asyncio.run(active_callback())
    else:
        callback()
    record = json.loads((tmp_path/'checks.jsonl').read_text())
    assert record['status'] == ('held_at_floor' if mode == 'floor' else 'held_unverifiable')
    assert record['paid_fallback'] is False
