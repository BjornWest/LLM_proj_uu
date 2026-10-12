"""CPU controls for the shared scrape, accurate rates and small observations."""
import http.server
import json
import threading
import time

import pytest

from browser_training.capacity_control import CapacitySnapshot, SharedMetricsPoller
from browser_training.serving_telemetry import ServingTelemetry, counters, status_line, wandb_values


MODEL = 'Qwen/test'


def metrics(*, model=MODEL, engine='0', generated=100, computed=1000, cached=3000, external=2000):
    labels = f'model_name="{model}",engine="{engine}"'
    return '\n'.join([
        f'vllm:generation_tokens_total{{{labels}}} {generated}',
        f'vllm:prompt_tokens_by_source_total{{{labels},source="local_compute"}} {computed}',
        f'vllm:prompt_tokens_by_source_total{{{labels},source="local_cache_hit"}} {cached}',
        f'vllm:prompt_tokens_by_source_total{{{labels},source="external_kv_transfer"}} {external}',
        f'vllm:num_requests_running{{{labels}}} 2',
        f'vllm:num_requests_waiting{{{labels}}} 1',
        f'vllm:num_requests_waiting_by_reason{{{labels},reason="capacity"}} 1',
        f'vllm:num_requests_waiting_by_reason{{{labels},reason="deferred"}} 0',
        f'vllm:kv_cache_usage_perc{{{labels}}} 0.9',
        f'vllm:num_preemptions_total{{{labels}}} 0',
    ]) + '\n'


def snap(at):
    return CapacitySnapshot(at, 1, 0, 2, .9, 0)


def observer(**kwargs):
    return ServingTelemetry(session_id='session-a', model=MODEL, model_revision='revision',
        clock=lambda: 8, wall_clock=lambda: 1000, **kwargs)


def record(t, text, snapshot, **source):
    t.observe(text, snapshot, model=source.get('model', MODEL), engine=source.get('engine', '0'))


def read(t, **kwargs):
    return t.read(observer_id=t.observer_id, **kwargs)


def test_rates_select_initial_prefill_accounting_and_aggregate_output():
    t = observer()
    record(t, metrics() + metrics(model='other', generated=999999), snap(1))
    assert read(t, )['rows'][0]['rates']['output_tokens_per_s'] is None
    record(t, metrics(generated=180, computed=1400, cached=4200, external=2400), snap(3))
    row = read(t, after=1)['rows'][0]
    assert row['rates']['output_tokens_per_s'] == 40
    assert row['rates']['initial_prefill_tokens_per_s'] == 200
    assert row['rates']['local_cached_input_tokens_per_s'] == 600
    assert row['rates']['external_cached_input_tokens_per_s'] == 200
    assert row['rates']['cpu_load_bytes_per_s'] is None
    assert row['interval_cached_input_fraction'] == .8
    assert row['running_requests'] == 2 and row['waiting_requests'] == 1
    assert row['elapsed_seconds'] == 2
    assert 'output=40.0 tokens/s' in status_line(row)
    assert 'prefill-completed=200.0 tokens/s' in status_line(row)
    assert wandb_values(row)['serving/kv_cache_percent'] == 90
    assert 'serving/cpu_load_bytes_per_s' not in wandb_values(row)
    assert wandb_values(row)['serving_available/cpu_load_bytes_per_s'] == 0
    json.dumps(row, allow_nan=False)


def test_labels_select_exact_engine_and_escaped_model_without_summing_dimensions():
    assert counters(metrics() + metrics(engine='1'), model=MODEL, engine='0')['output_tokens'] == 100
    escaped = metrics(model='escaped\\"model')
    assert counters(escaped, model='escaped"model', engine='0')['output_tokens'] == 100
    with pytest.raises(ValueError, match='Ambiguous'):
        counters(metrics() + metrics(), model=MODEL, engine='0')
    for value in ('NaN', '-1', '0.5', 'inf'):
        with pytest.raises(ValueError):
            counters(metrics().replace('} 100\n', '} ' + value + '\n'), model=MODEL, engine='0')


def test_counter_reset_and_long_gaps_cannot_appear_as_rate_spikes():
    t = observer()
    record(t, metrics(generated=100), snap(1))
    record(t, metrics(generated=20), snap(2))
    row = read(t, after=1)['rows'][0]
    assert row['counter_reset'] and row['counter_segment'] == 1
    assert all(v is None for v in row['rates'].values())
    record(t, metrics(generated=30), snap(3))
    assert read(t, after=2)['rows'][0]['rates']['output_tokens_per_s'] == 10
    record(t, metrics(generated=10000), snap(20))
    row = read(t, after=3)['rows'][0]
    assert row['sample_gap'] and row['counter_segment'] == 2
    assert row['rates']['output_tokens_per_s'] is None
    assert wandb_values(row)['serving/sample_gap'] == 1
    assert wandb_values(read(t, after=1)['rows'][0])['serving/counter_reset'] == 1


def test_identity_mismatch_or_empty_model_counters_cannot_mislabel_gauges():
    t = observer()
    for source in ({'model':'other', 'engine':'0'}, {'model':MODEL, 'engine':'1'}):
        with pytest.raises(ValueError, match='model/engine'):
            record(t, metrics(), snap(1), **source)
    with pytest.raises(ValueError, match='No serving counters'):
        record(t, metrics(model='other'), snap(1))
    assert read(t)['rows'] == []


def test_observer_recreation_requires_a_new_cursor_even_after_sequences_catch_up():
    a, b = observer(), observer()
    for i in range(1, 5):
        record(a, metrics(), snap(i)); record(b, metrics(), snap(i))
    assert a.observer_id != b.observer_id
    with pytest.raises(ValueError, match='observer changed'):
        b.read(after=2, observer_id=a.observer_id)
    with pytest.raises(ValueError, match='observer changed'):
        b.read(after=2)
    batch = b.read(after=0)
    assert len(batch['rows']) == 4 and batch['observer_id'] == b.observer_id


def test_lazy_transfer_first_total_is_visible_without_inventing_a_rate():
    t = observer()
    record(t, metrics(), snap(1))
    body = metrics() + f'vllm:kv_offload_load_bytes_total{{engine="0",model_name="{MODEL}"}} 1.0459e10\n'
    body += f'vllm:generation_tokens_created{{engine="0",model_name="{MODEL}"}} 99999\n'
    record(t, body, snap(2))
    row = read(t, after=1)['rows'][0]
    assert row['rates']['cpu_load_bytes_per_s'] is None
    assert wandb_values(row)['serving_total/cpu_load_bytes'] == 10459000000
    assert row['counters']['output_tokens'] == 100
    assert 'unavailable' in status_line(read(t)['rows'][0])


def test_gap_boundary_and_concurrent_copy_safe_reads():
    from concurrent.futures import ThreadPoolExecutor
    t = observer()
    record(t, metrics(generated=100), snap(1))
    record(t, metrics(generated=150), snap(6))
    assert read(t, after=1)['rows'][0]['rates']['output_tokens_per_s'] == 10
    def writer():
        for i in range(7, 107):
            record(t, metrics(generated=150+i), snap(i))
    def reader():
        for _ in range(100):
            batch = t.read()
            assert len(batch['rows']) <= 120
            assert batch['rows'][-1]['seq'] <= batch['latest_seq']
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(writer), pool.submit(reader), pool.submit(reader)]
        for f in futures:
            f.result(timeout=3)
    assert t.read()['latest_seq'] == 102


def test_missing_counters_need_two_actual_observations_and_do_not_fake_zero():
    t = observer()
    absent = '\n'.join(line for line in metrics().splitlines() if 'generation_tokens' not in line)
    record(t, absent, snap(1))
    record(t, metrics(generated=10000), snap(2))
    assert read(t, after=1)['rows'][0]['rates']['output_tokens_per_s'] is None
    record(t, metrics(generated=10020), snap(3))
    assert read(t, after=2)['rows'][0]['rates']['output_tokens_per_s'] == 20


def test_history_and_wire_batches_are_bounded_and_loss_is_visible():
    t = observer(history=2)
    for i in range(1, 5):
        record(t, metrics(generated=i), snap(i))
    batch = read(t, after=0, limit=1)
    assert batch['gap'] and batch['latest_seq'] == 4 and batch['oldest_seq'] == 3
    assert [r['seq'] for r in batch['rows']] == [3]
    assert batch['latest_sample_age_seconds'] == 4
    batch['rows'][0]['counters']['output_tokens'] = 999
    assert read(t, after=2)['rows'][0]['counters']['output_tokens'] == 3
    assert read(t, after=3)['gap'] is False
    for cursor, limit in ((-1, 1), (5, 1), (0, 121), (True, 1)):
        with pytest.raises(ValueError):
            read(t, after=cursor, limit=limit)


def test_bad_timestamps_and_synthetic_publication_fail_closed():
    t = observer(synthetic=True)
    record(t, metrics(), snap(1))
    with pytest.raises(ValueError, match='advance'):
        record(t, metrics(), snap(1))
    assert read(t, )['latest_seq'] == 1
    row = read(t, )['rows'][0]
    with pytest.raises(ValueError, match='synthetic run'):
        wandb_values(row)
    assert wandb_values(row, allow_synthetic=True)['serving/running_requests'] == 2
    for opts in ({'history':0}, {'max_gap_seconds':float('nan')}, {'max_gap_seconds':True}, {'max_gap_seconds':'5'}, {'synthetic':'yes'}):
        with pytest.raises(ValueError):
            observer(**opts)


def eventually(check):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        if check():
            return
        time.sleep(.01)
    raise AssertionError('Condition not observed')


def test_same_scrape_serves_controller_and_observer_without_extra_HTTP_calls():
    t = ServingTelemetry(session_id='local-http-scripted', model=MODEL,
        model_revision='fixture', synthetic=True)
    state = {'gets':0, 'connections':set()}
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_GET(self):
            state['gets'] += 1
            state['connections'].add(self.client_address)
            assert self.path == '/metrics'
            body = metrics(generated=state['gets']*100).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *_):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1',0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever); thread.start()
    seen = []
    failing = [True]
    def observe(text, snapshot, **source):
        # Reading status here also detects callbacks accidentally under lock.
        assert poller.status()['snapshot']['observed_at'] == snapshot.observed_at
        if failing[0]:
            raise OSError('UI observer failure')
        assert source == {"model": MODEL, "engine": "0"}
        record(t, text, snapshot, **source)
        if read(t, )['latest_seq'] == 3:
            poller.stop.set()  # Stop at a successful callback, not mid-HTTP.
    poller = SharedMetricsPoller('http://127.0.0.1:'+str(server.server_port)+'/metrics',
        model=MODEL, interval=.03, timeout=1, on_snapshot=seen.append, on_scrape=observe)
    try:
        poller.start()
        eventually(lambda: poller.status()['observer_failures'] >= 2)
        assert poller.status()['failures'] == 0 and len(seen) >= 2
        assert 'UI observer failure' in poller.status()['observer_error']
        failing[0] = False
        eventually(lambda: read(t, )['latest_seq'] >= 3)
        assert poller.status()['observer_error'] is None
        poller.close()
        assert state['gets'] == poller.status()['requests'] == len(seen)
        assert len(state['connections']) == 1
        assert read(t, )['rows'][-1]['rates']['output_tokens_per_s'] > 0
    finally:
        poller.close(); server.shutdown(); server.server_close(); thread.join(2)
    assert not thread.is_alive()


def test_invalid_capacity_skips_observer_and_observer_exit_or_stall_is_diagnosed():
    mode = {'invalid':True, 'control_fail':True}
    seen = []
    stalled, resume = threading.Event(), threading.Event()
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = metrics()
            if mode['invalid']:
                body = body.replace('} 0.9', '} NaN')
            body = body.encode()
            self.send_response(200); self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def log_message(self,*_):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever); thread.start()
    def control(_):
        if mode['control_fail']:
            raise ValueError('Controller rejected sample')
    def view(*_,**source):
        seen.append(source)
        if len(seen) == 1:
            raise SystemExit('UI-only exit')
        if len(seen) == 2:
            stalled.set()
            assert resume.wait(3)
        if len(seen) == 3:
            poller.stop.set()
    poller = SharedMetricsPoller(f'http://127.0.0.1:{server.server_port}/metrics',
        model=MODEL, interval=.01, timeout=1, on_snapshot=control, on_scrape=view)
    try:
        poller.start()
        eventually(lambda:poller.status()['failures'] >= 1)
        assert seen == [] and poller.status()['snapshot'] is None
        mode['invalid'] = False
        eventually(lambda:'Controller rejected' in (poller.status()['last_error'] or ''))
        assert seen == []
        mode['control_fail'] = False
        assert stalled.wait(3)
        status = poller.status()
        assert status['observer_failures'] == 1
        assert 'SystemExit: UI-only exit' in status['observer_error']
        assert status['observer_active_seconds'] is not None
        assert status['snapshot'] is not None
        resume.set()
        eventually(lambda:len(seen) == 3)
        poller.close()
        assert poller.status()['observer_error'] is None
        assert poller.status()['observer_last_seconds'] is not None
        assert poller.status()['observer_max_seconds'] >= 0
    finally:
        resume.set(); poller.close()
        server.shutdown(); server.server_close(); thread.join(2)
    with pytest.raises(ValueError,match='callable'):
        SharedMetricsPoller('http://localhost/metrics',model=MODEL,on_scrape='invalid')
