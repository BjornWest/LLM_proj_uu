"""CPU protocol/concurrency controls; no browser/GPU/provider calls."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from browser_training.capacity_control import (
    CapacitySnapshot, EpisodeCapacityController, ParkingConfig,
    SharedMetricsPoller, TurnCancelled, parse_metrics,
)


def metrics(capacity=0, deferred=0, running=0, kv=.4, preemptions=0, model='qwen', engine='0'):
    labels = f'model_name="{model}",engine="{engine}"'
    return '\n'.join([
        f'vllm:num_requests_running{{{labels}}} {running}',
        f'vllm:num_requests_waiting{{{labels}}} {capacity + deferred}',
        f'vllm:num_requests_waiting_by_reason{{{labels},reason="capacity"}} {capacity}',
        f'vllm:num_requests_waiting_by_reason{{{labels},reason="deferred"}} {deferred}',
        f'vllm:kv_cache_usage_perc{{{labels}}} {kv}',
        f'vllm:num_preemptions_total{{{labels}}} {preemptions}',
    ]) + '\n'


def eventually(predicate, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.005)
    assert predicate(), 'CPU test deadline expired'


def test_parser_selects_identity_and_retains_reason():
    assert parse_metrics(metrics(2, 3, 4, .91, 8) + metrics(9, engine='1') + metrics(7, model='other'), model='qwen', observed_at=10) == CapacitySnapshot(10, 2, 3, 4, .91, 8)
    assert parse_metrics(metrics(model=r'q\"w\\en'), model='q"w\\en').running == 0


@pytest.mark.parametrize('body', [
    metrics() + metrics(), metrics().replace('reason="capacity"', 'reason="wrong"'),
    metrics().replace('} 0\n', '} -1\n', 1), metrics(kv=float('nan')), metrics(kv=1.1),
    metrics().replace('} 0\n', '} 0.5\n', 1),
    metrics().replace('vllm:num_requests_waiting{model_name="qwen",engine="0"} 0', 'vllm:num_requests_waiting{model_name="qwen",engine="0"} 1'),
    metrics().replace('engine="0"', 'engine="0",engine="0"'),
])
def test_invalid_metrics_fail_closed(body):
    with pytest.raises(ValueError):
        parse_metrics(body, model='qwen')


class Feed:
    def __init__(self):
        self.body, self.status, self.trickle = metrics(), 200, False
        self.chunked = False
        self.hits, self.clients = 0, set()
        feed = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_GET(self):
                feed.hits += 1
                feed.clients.add(self.client_address)
                body = feed.body.encode()
                self.send_response(feed.status)
                if feed.chunked:
                    self.send_header('Transfer-Encoding', 'chunked')
                else:
                    self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    if feed.chunked:
                        for chunk in (body[:23], body[23:]):
                            self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                        self.wfile.write(b'0\r\n\r\n')
                    elif feed.trickle:
                        for byte in body:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(.01)
                    else:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *_):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/metrics'
    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


@pytest.fixture
def feed():
    fixture = Feed()
    try:
        yield fixture
    finally:
        fixture.close()


def test_poller_shared_and_keepalive(feed):
    received = []
    p = SharedMetricsPoller(feed.url, model='qwen', interval=.04, timeout=.2, on_snapshot=received.append).start()
    try:
        eventually(lambda: len(received) >= 3)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: p.status(), range(1000)))
        assert feed.hits < 15
        assert len(feed.clients) == 1
        assert p.status()['snapshot']['capacity_waiting'] == 0
        with pytest.raises(RuntimeError):
            p.start()
    finally:
        p.close()
    assert not p.thread.is_alive()


def test_poller_failure_preserves_timestamp_and_recovers(feed):
    p = SharedMetricsPoller(feed.url, model='qwen', interval=.02, timeout=.15).start()
    try:
        eventually(lambda: p.status()['snapshot'] is not None)
        feed.status = 503
        eventually(lambda: p.status()['failures'] > 0)
        old = p.status()['snapshot']['observed_at']
        time.sleep(.08)
        assert p.status()['snapshot']['observed_at'] == old
        assert '503' in p.status()['last_error']
        feed.status = 200
        eventually(lambda: p.status()['last_error'] is None)
        assert p.status()['snapshot']['observed_at'] > old
    finally:
        p.close()


@pytest.mark.parametrize('trickle', [False, True])
def test_poller_bounds_response_and_shutdown(feed, trickle):
    feed.trickle = trickle
    p = SharedMetricsPoller(feed.url, model='qwen', interval=.01, timeout=.08,
                            max_bytes=4096 if trickle else 8).start()
    try:
        eventually(lambda: p.status()['failures'] > 0)
        assert p.status()['snapshot'] is None
    finally:
        started = time.monotonic()
        p.close()
        assert time.monotonic() - started < .5
    assert not p.thread.is_alive()


class Clock:
    now = 10.
    def __call__(self):
        return self.now


def setup(n=3, cap=3):
    clock = Clock()
    c = EpisodeCapacityController(ParkingConfig(max_generation_requests=cap, max_active_episodes=n), clock=clock)
    for i in range(n):
        c.register_episode(str(i), priority=i)
    observe(c, clock)
    return c, clock


def observe(c, clock, waiting=0, deferred=0, kv=.4, preemptions=0):
    clock.now += .01
    sample = CapacitySnapshot(clock.now, waiting, deferred, 0, kv, preemptions)
    c.observe(sample)
    return sample


def establish(c, n=3):
    for i in range(n):
        c.acquire_turn(str(i), f'initial-{i}', timeout=1)
        c.release_turn(str(i), f'initial-{i}')


def parked(c):
    return {i for i, r in c.status()['episodes'].items() if r['park_requested']}


def test_sticky_victims_drain_then_resume_after_episode_terminal():
    c, clock = setup(4)
    establish(c, 4)
    c.acquire_turn('3', 'ongoing', timeout=1)
    observe(c, clock, waiting=1, kv=.95)
    observe(c, clock, waiting=1, kv=.95)
    assert parked(c) == {'3'}
    assert not c.status()['episodes']['3']['parked']
    for _ in range(5):
        observe(c, clock, waiting=1, kv=.95)
    assert parked(c) == {'3'}
    c.release_turn('3', 'ongoing')
    assert c.status()['episodes']['3']['parked']
    observe(c, clock, waiting=2, kv=.95)
    assert parked(c) == {'2', '3'}
    observe(c, clock)
    assert parked(c) == {'2', '3'}
    c.finish_episode('0')
    assert parked(c) == {'3'}
    c.finish_episode('1')
    assert not parked(c)


@pytest.mark.parametrize('waiting,deferred,kv', [(0, 5, .98), (2, 0, .3)])
def test_no_parking_from_deferred_or_cold_low_kv(waiting, deferred, kv):
    c, clock = setup()
    establish(c)
    for _ in range(5):
        observe(c, clock, waiting=waiting, deferred=deferred, kv=kv)
    assert not parked(c)


def test_replay_and_brief_pressure_do_not_debounce():
    c, clock = setup()
    establish(c)
    sample = observe(c, clock, waiting=1, kv=.95)
    c.observe(sample)
    assert not parked(c)
    observe(c, clock)
    assert not parked(c)


def test_completion_credit_is_bound_to_existing_victim():
    c, clock = setup(4)
    establish(c, 4)
    observe(c, clock, waiting=1, kv=.95)
    observe(c, clock, waiting=1, kv=.95)
    c.finish_episode('0')
    assert c.status()['resume_credits'] == 1
    c.cancel_episode('3')
    c.finish_episode('3')
    observe(c, clock, kv=.95)
    observe(c, clock, waiting=1, kv=.95)
    observe(c, clock, waiting=1, kv=.95)
    assert parked(c) == {'2'}
    observe(c, clock)
    assert parked(c) == {'2'}
    c.finish_episode('1')
    assert not parked(c)


def test_parked_next_turn_waits_for_terminal():
    c, clock = setup()
    establish(c)
    observe(c, clock, waiting=1, kv=.95)
    observe(c, clock, waiting=1, kv=.95)
    # Real time keeps failure cleanup finite even if a resume assertion fails.
    c.clock = time.monotonic
    c.observe(CapacitySnapshot(time.monotonic(), 0, 0, 0, .4, 0))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(c.acquire_turn, '2', 'next', timeout=3)
        eventually(lambda: c.status()['episodes']['2']['waiting'])
        observe(c, clock)
        assert not future.done()
        c.finish_episode('0')
        assert future.result(timeout=1) == 'next'
    c.release_turn('2', 'next')
    c.finish_episode('1')
    c.finish_episode('2')
    assert not any(r['waiting'] or r['request_id'] or r['park_requested'] for r in c.status()['episodes'].values())


def test_lifecycle_cap_counts_parked_and_cancelled_until_cleanup():
    c, clock = setup()
    establish(c)
    observe(c, clock, waiting=1, kv=.95)
    observe(c, clock, waiting=1, kv=.95)
    c.cancel_episode('2')
    with pytest.raises(ValueError, match='lifecycle cap'):
        c.register_episode('new')
    c.finish_episode('2')
    c.register_episode('new')


def test_concurrent_cap_and_finally_on_http_failure():
    c = EpisodeCapacityController(ParkingConfig(max_generation_requests=2, max_active_episodes=8))
    c.observe(CapacitySnapshot(time.monotonic(), 0, 0, 0, .4, 0))
    for i in range(8):
        c.register_episode(str(i))
    gate, lock = threading.Barrier(8), threading.Lock()
    active = peak = 0
    def run(i):
        nonlocal active, peak
        gate.wait(timeout=2)
        try:
            with c.turn(str(i), f'policy:{i}', timeout=2):
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(.02)
                with lock:
                    active -= 1
                raise OSError('simulated HTTP failure')
        except OSError:
            pass
        finally:
            c.finish_episode(str(i))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(run, range(8)))
    assert peak == 2
    assert all(r['done'] and not r['request_id'] for r in c.status()['episodes'].values())


@pytest.mark.parametrize('method', ['cancel', 'close', 'stop', 'timeout'])
def test_stale_pending_wait_bounded_cancellation(method):
    c = EpisodeCapacityController()
    c.register_episode('a')
    stop = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(c.acquire_turn, 'a', 'policy:1', timeout=.15, stop_event=stop)
        eventually(lambda: c.status()['episodes']['a']['waiting'])
        if method == 'cancel':
            c.cancel_episode('a')
        elif method == 'close':
            c.close()
        elif method == 'stop':
            stop.set()
        with pytest.raises(TimeoutError if method == 'timeout' else TurnCancelled):
            future.result(timeout=1)
    assert not c.status()['episodes']['a']['waiting']


def test_pressure_keeps_one_drainer_and_blocks_new_first_turn():
    c, clock = setup()
    establish(c, 2)
    observe(c, clock, waiting=99, kv=.99)
    observe(c, clock, waiting=99, kv=.99)
    assert parked(c) == {'1'}
    c.acquire_turn('0', 'drain', timeout=1)
    c.release_turn('0', 'drain')
    c.clock = time.monotonic
    c.observe(CapacitySnapshot(time.monotonic(), 99, 0, 0, .99, 0))
    with pytest.raises(TimeoutError):
        c.acquire_turn('2', 'new', timeout=.03)


def test_release_identity_terminal_rules_and_bounded_history():
    c = EpisodeCapacityController(ParkingConfig(terminal_history=2))
    c.observe(CapacitySnapshot(time.monotonic(), 0, 0, 0, .4, 0))
    for i in range(10):
        c.register_episode(str(i))
        c.acquire_turn(str(i), 'policy:1', timeout=1)
        with pytest.raises(ValueError):
            c.acquire_turn(str(i), 'double', timeout=1)
        with pytest.raises(ValueError):
            c.finish_episode(str(i))
        with pytest.raises(ValueError):
            c.release_turn(str(i), 'wrong')
        c.release_turn(str(i), 'policy:1')
        c.finish_episode(str(i))
    assert len(c.status()['episodes']) == 2
    with pytest.raises(ValueError):
        c.register_episode('9')


def test_preemption_is_observed_not_a_standalone_parking_trigger():
    c, clock = setup()
    establish(c)
    for counter in range(1, 5):
        observe(c, clock, kv=.2, preemptions=counter)
    assert not parked(c)
    assert len([e for e in c.status()["events"] if e["kind"] == "preemption_observed"]) == 4
    observe(c, clock, kv=.2, preemptions=0)  # Counter reset is not a preemption.
    assert not parked(c)


def test_stale_gap_resets_pressure_debounce():
    c, clock = setup()
    establish(c)
    observe(c, clock, waiting=1, kv=.95)
    clock.now += 10
    observe(c, clock, waiting=1, kv=.95)
    assert not parked(c)
    observe(c, clock, waiting=1, kv=.95)
    assert parked(c) == {'2'}


def test_future_timestamp_rejected_and_stale_observation_never_parks():
    c, clock = setup()
    establish(c)
    with pytest.raises(ValueError, match='Future'):
        c.observe(CapacitySnapshot(clock.now + 1, 1, 0, 1, .99, 0))
    old_time = clock.now
    clock.now += 10
    c.observe(CapacitySnapshot(old_time + .01, 1, 0, 1, .99, 0))
    c.observe(CapacitySnapshot(old_time + .02, 1, 0, 1, .99, 0))
    assert not parked(c)
    assert not c.status()['telemetry_fresh']


def test_inflight_victim_can_receive_completion_grant_before_release():
    c, clock = setup()
    establish(c)
    c.acquire_turn('2', 'ongoing', timeout=1)
    observe(c, clock, waiting=1, kv=.95)
    observe(c, clock, waiting=1, kv=.95)
    c.finish_episode('0')
    observe(c, clock)
    assert parked(c) == {'2'}
    c.release_turn('2', 'ongoing')
    assert not parked(c)


def test_poller_close_interrupts_active_trickling_body(feed):
    feed.trickle = True
    p = SharedMetricsPoller(feed.url, model='qwen', interval=.01, timeout=2).start()
    eventually(lambda: feed.hits > 0)
    started = time.monotonic()
    p.close()
    assert time.monotonic() - started < .5
    assert not p.thread.is_alive()


@pytest.mark.parametrize('kwargs', [
    {'max_generation_requests': 0}, {'max_active_episodes': 0}, {'terminal_history': 0},
    {'sustained_samples': 0}, {'fresh_seconds': float('nan')},
    {'high_water': float('nan')}, {'high_water': .2, 'low_water': .3},
])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        EpisodeCapacityController(ParkingConfig(**kwargs))


def test_local_acquire_deadline_does_not_dispatch_or_leak_permit():
    c = EpisodeCapacityController(ParkingConfig(max_generation_requests=1))
    c.observe(CapacitySnapshot(time.monotonic(), 0, 0, 0, .4, 0))
    c.register_episode('a')
    c.register_episode('b')
    c.acquire_turn('a', 'first', timeout=1)
    with pytest.raises(TimeoutError):
        c.acquire_turn('b', 'blocked', timeout=.03)
    assert not c.status()['episodes']['b']['waiting']
    assert c.status()['episodes']['b']['turns'] == 0
    c.release_turn('a', 'first')
    with c.turn('b', 'formatter', timeout=1):
        pass


@pytest.mark.parametrize('sequence', [
    [1, 1, 2, 1, 2, 1, 2], [1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1],
])
def test_fluctuating_backlog_does_not_accumulate_sticky_victims(sequence):
    c, clock = setup(5, 5)
    establish(c, 5)
    for count in sequence:
        observe(c, clock, waiting=count, kv=.95)
        assert len(parked(c)) <= max(sequence)
    assert len(parked(c)) == max(sequence)


def test_coincident_preemption_and_capacity_does_not_mark_unselected_victims_covered():
    c, clock = setup(5, 5)
    establish(c, 5)
    observe(c, clock, waiting=3, kv=.95, preemptions=1)
    assert not parked(c)
    observe(c, clock, waiting=3, kv=.95, preemptions=1)
    assert parked(c) == {'2', '3', '4'}


def test_terminal_history_uses_completion_order_not_registration_order():
    c = EpisodeCapacityController(ParkingConfig(terminal_history=1))
    c.register_episode('long')
    c.register_episode('short')
    c.finish_episode('short')
    c.finish_episode('long')
    assert set(c.status()['episodes']) == {'long'}
    with pytest.raises(ValueError):
        c.register_episode('long')
    with pytest.raises(ValueError):
        c.finish_episode('long')


def test_invalid_port_is_rejected_before_polling():
    with pytest.raises(ValueError):
        SharedMetricsPoller('http://127.0.0.1:99999/metrics', model='qwen')


def test_poller_accepts_vllm_chunked_framing_with_keepalive(feed):
    feed.chunked = True
    p = SharedMetricsPoller(feed.url, model='qwen', interval=.02, timeout=.2).start()
    try:
        eventually(lambda: p.status()['requests'] >= 3 and p.status()['snapshot'] is not None)
        assert p.status()['failures'] == 0
        assert len(feed.clients) == 1
    finally:
        p.close()


def test_poller_callback_failure_stays_explicit_and_recovers(feed):
    broken = threading.Event()
    broken.set()
    def callback(_):
        if broken.is_set():
            raise RuntimeError('controller callback failure')
    p = SharedMetricsPoller(feed.url, model='qwen', interval=.02, timeout=.2, on_snapshot=callback).start()
    try:
        eventually(lambda: p.status()['failures'] > 0)
        assert p.status()['snapshot'] is None
        assert 'controller callback failure' in p.status()['last_error']
        broken.clear()
        eventually(lambda: p.status()['snapshot'] is not None)
        assert p.status()['last_error'] is None
    finally:
        p.close()


def test_dispatch_retirement_is_idempotent_and_not_episode_cancellation():
    c, _ = setup()
    c.retire_dispatch('2')
    c.retire_dispatch('2')
    row = c.status()['episodes']['2']
    assert row['dispatch_retired'] and not row['done'] and not row['cancelled']
    with pytest.raises(TurnCancelled, match='dispatch retired'):
        c.acquire_turn('2', 'policy:next', timeout=1)
    with pytest.raises(ValueError, match='lifecycle cap'):
        c.register_episode('replacement')
    events = [e for e in c.status()['events'] if e['episode_id'] == '2']
    assert [e['kind'] for e in events] == ['episode_registered', 'dispatch_retired']
    assert c.status()['resume_credits'] == 0
    c.finish_episode('2')
    c.retire_dispatch('2')  # Terminal retained row: also an idempotent no-op.
    c.register_episode('replacement')
    kinds = [e['kind'] for e in c.status()['events'] if e['episode_id'] == '2']
    assert kinds == ['episode_registered', 'dispatch_retired', 'episode_finished']


def test_dispatch_retirement_wakes_waiter_without_granting_a_turn():
    c = EpisodeCapacityController()  # Missing telemetry keeps acquire pending.
    c.register_episode('case')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(c.acquire_turn, 'case', 'policy:1', timeout=2)
        eventually(lambda: c.status()['episodes']['case']['waiting'])
        c.retire_dispatch('case')
        with pytest.raises(TurnCancelled, match='dispatch retired'):
            future.result(timeout=1)
    row = c.status()['episodes']['case']
    assert not row['waiting'] and row['request_id'] is None and row['turns'] == 0
    assert not row['cancelled'] and not row['done']


def test_retired_inflight_actor_retains_both_caps_until_verified_cleanup():
    c = EpisodeCapacityController(ParkingConfig(max_generation_requests=1, max_active_episodes=2))
    c.observe(CapacitySnapshot(time.monotonic(), 0, 0, 0, .4, 0))
    c.register_episode('ended')
    c.register_episode('live')
    c.acquire_turn('ended', 'outstanding', timeout=1)
    c.retire_dispatch('ended')
    for _ in range(2):  # Failed cleanup must neither end nor forgive the permit.
        with pytest.raises(ValueError, match='HTTP work in flight'):
            c.finish_episode('ended')
        c.retire_dispatch('ended')
    with pytest.raises(ValueError, match='lifecycle cap'):
        c.register_episode('new')
    with pytest.raises(TimeoutError):
        c.acquire_turn('live', 'blocked', timeout=.03)
    with pytest.raises(TurnCancelled, match='dispatch retired'):
        c.acquire_turn('ended', 'another', timeout=1)
    row = c.status()['episodes']['ended']
    assert row['request_id'] == 'outstanding' and not row['done'] and not row['cancelled']
    c.release_turn('ended', 'outstanding')  # Caller has verified HTTP cleanup.
    with c.turn('live', 'next', timeout=1):
        pass
    with pytest.raises(ValueError, match='lifecycle cap'):
        c.register_episode('new')  # Request release alone does not end lifecycle.
    c.finish_episode('ended')
    c.register_episode('new')
    events = [e['kind'] for e in c.status()['events'] if e['episode_id'] == 'ended']
    assert events.count('dispatch_retired') == 1
    assert events.count('episode_finished') == 1
    assert 'episode_cancelled' not in events and 'episode_parked' not in events


def test_retired_parked_actor_no_longer_covers_live_backlog():
    c, clock = setup()
    establish(c)
    observe(c, clock, waiting=1, kv=.95)
    observe(c, clock, waiting=1, kv=.95)
    assert parked(c) == {'2'}
    c.retire_dispatch('2')
    assert not parked(c)
    assert c.status()['resume_credits'] == 0
    observe(c, clock, waiting=1, kv=.95)
    assert parked(c) == {'1'}  # A real live actor replaces the closed channel.
    observe(c, clock)
    assert parked(c) == {'1'}  # Retirement itself did not grant a resume.
    c.finish_episode('2')  # Only actual terminal cleanup grants the resume.
    assert not parked(c)
    assert not c.status()['episodes']['2']['cancelled']
    resumed = [e['episode_id'] for e in c.status()['events'] if e['kind'] == 'episode_resumed']
    assert resumed == ['1']


def test_retired_high_priority_actor_is_not_used_as_the_remaining_drainer():
    c, clock = setup()
    establish(c)
    c.retire_dispatch('0')
    observe(c, clock, waiting=9, kv=.99)
    observe(c, clock, waiting=9, kv=.99)
    assert parked(c) == {'2'}  # Keep live '1', not ended high-priority '0'.
    c.acquire_turn('1', 'draining', timeout=1)
    c.release_turn('1', 'draining')
    assert not c.status()['episodes']['0']['park_requested']


def test_retirement_drops_bound_grant_without_transferring_it():
    c, clock = setup(4, 4)
    establish(c, 4)
    observe(c, clock, waiting=2, kv=.95)
    observe(c, clock, waiting=2, kv=.95)
    c.finish_episode('0')
    assert c.status()['episodes']['2']['resume_granted']
    c.retire_dispatch('2')
    assert c.status()['resume_credits'] == 0
    observe(c, clock)
    assert parked(c) == {'3'}
    assert not c.status()['episodes']['3']['resume_granted']
    c.finish_episode('2')
    assert not parked(c)
    resumed = [e['episode_id'] for e in c.status()['events'] if e['kind'] == 'episode_resumed']
    assert resumed == ['3']


def test_retired_inflight_parking_request_never_becomes_a_ghost_park_on_release():
    c, clock = setup()
    establish(c)
    c.acquire_turn('2', 'ongoing', timeout=1)
    observe(c, clock, waiting=1, kv=.95)
    observe(c, clock, waiting=1, kv=.95)
    assert c.status()['episodes']['2']['park_requested']
    c.retire_dispatch('2')
    assert c.status()['episodes']['2']['request_id'] == 'ongoing'
    c.release_turn('2', 'ongoing')
    row = c.status()['episodes']['2']
    assert not row['park_requested'] and not row['parked'] and not row['resume_granted']
    assert row['request_id'] is None and not row['done']
    assert not any(e['kind'] == 'episode_parked' and e['episode_id'] == '2' for e in c.status()['events'])
    observe(c, clock, waiting=1, kv=.95)
    assert parked(c) == {'1'}
    c.finish_episode('0')
    assert c.status()['episodes']['1']['resume_granted']
    assert not c.status()['episodes']['2']['resume_granted']


def test_cancel_then_retire_preserves_existing_cancellation_and_one_retirement_event():
    c, _ = setup()
    c.cancel_episode('2')
    c.retire_dispatch('2')
    c.retire_dispatch('2')
    assert c.status()['episodes']['2']['cancelled']
    assert c.status()['episodes']['2']['dispatch_retired']
    c.finish_episode('2')
    kinds = [e['kind'] for e in c.status()['events'] if e['episode_id'] == '2']
    assert kinds.count('episode_cancelled') == 1 and kinds.count('dispatch_retired') == 1
    assert kinds.count('episode_finished') == 1


def test_retire_dispatch_concurrent_calls_emit_one_event():
    c, _ = setup()
    gate = threading.Barrier(8)
    def retire(_):
        gate.wait(timeout=2)
        c.retire_dispatch('2')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(retire, range(8)))
    assert sum(e['kind'] == 'dispatch_retired' for e in c.status()['events']) == 1
    assert not c.status()['episodes']['2']['cancelled']


def test_retire_fresh_capacity_waiter_before_holder_releases():
    c = EpisodeCapacityController(ParkingConfig(max_generation_requests=1, max_active_episodes=2))
    c.observe(CapacitySnapshot(time.monotonic(), 0, 0, 0, .4, 0))
    c.register_episode('holder')
    c.register_episode('ended')
    c.acquire_turn('holder', 'held', timeout=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(c.acquire_turn, 'ended', 'waiting', timeout=2)
        eventually(lambda: c.status()['episodes']['ended']['waiting'])
        c.retire_dispatch('ended')
        c.release_turn('holder', 'held')
        with pytest.raises(TurnCancelled, match='dispatch retired'):
            future.result(timeout=1)
    row = c.status()['episodes']['ended']
    assert row['request_id'] is None and row['turns'] == 0 and not row['waiting']
    assert not row['done'] and not row['cancelled']
    with pytest.raises(ValueError, match='lifecycle cap'):
        c.register_episode('new')
    c.finish_episode('ended')
    c.register_episode('new')
