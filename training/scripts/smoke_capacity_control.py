#!/usr/bin/env python3
"""Finite CPU-only integration: shared HTTP poller + simulated episode turns."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_training.capacity_control import EpisodeCapacityController, ParkingConfig, SharedMetricsPoller


def wait_for(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise TimeoutError('CPU smoke condition deadline exceeded')


def run():
    state = {'capacity': 0, 'kv': .4, 'requests': 0}
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_GET(self):
            state['requests'] += 1
            labels = 'model_name="mock-qwen",engine="0"'
            lines = {
                'vllm:num_requests_running': 0,
                'vllm:num_requests_waiting': state['capacity'],
                'vllm:kv_cache_usage_perc': state['kv'],
                'vllm:num_preemptions_total': 0,
            }
            body = '\n'.join(f'{name}{{{labels}}} {value}' for name, value in lines.items())
            body += f'\nvllm:num_requests_waiting_by_reason{{{labels},reason="capacity"}} {state["capacity"]}'
            body += f'\nvllm:num_requests_waiting_by_reason{{{labels},reason="deferred"}} 0\n'
            encoded = body.encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    controller = EpisodeCapacityController(ParkingConfig(max_generation_requests=3, max_active_episodes=3))
    poller = SharedMetricsPoller(f'http://127.0.0.1:{server.server_port}/metrics',
        model='mock-qwen', interval=.02, timeout=.5, on_snapshot=controller.observe).start()
    release = threading.Event()
    in_flight = threading.Event()
    pool = ThreadPoolExecutor(max_workers=2)
    snapshots = {}
    try:
        wait_for(lambda: controller.status()['telemetry_fresh'])
        for priority, episode in enumerate(('high', 'middle', 'low')):
            controller.register_episode(episode, priority=priority)
            with controller.turn(episode, f'{episode}:policy:1', timeout=3):
                pass
        def low_actor():
            with controller.turn('low', 'low:policy:2', timeout=3):
                in_flight.set()
                if not release.wait(3):
                    raise TimeoutError('Simulated in-flight turn was not released')
            with controller.turn('low', 'low:formatter:3', timeout=5):
                pass
            controller.finish_episode('low')
        low = pool.submit(low_actor)
        assert in_flight.wait(3)
        state.update(capacity=1, kv=.95)
        wait_for(lambda: controller.status()['episodes']['low']['park_requested'])
        assert not controller.status()['episodes']['low']['parked']
        release.set()
        wait_for(lambda: controller.status()['episodes']['low']['parked'])
        # Tool return does not rotate the victim or release its next generation.
        for _ in range(100):
            controller.status()
        assert not low.done()
        snapshots['first_park'] = controller.status()
        state['capacity'] = 2
        wait_for(lambda: controller.status()['episodes']['middle']['parked'])
        def middle_actor():
            with controller.turn('middle', 'middle:policy:2', timeout=5):
                pass
            controller.finish_episode('middle')
        middle = pool.submit(middle_actor)
        wait_for(lambda: controller.status()['episodes']['middle']['waiting'])
        snapshots['two_parked'] = controller.status()
        controller.finish_episode('high')
        assert not middle.done() and not low.done()
        state.update(capacity=0, kv=.4)
        middle.result(timeout=3)
        low.result(timeout=3)
        snapshots['terminal'] = controller.status()
        rows = snapshots['terminal']['episodes'].values()
        assert all(r['done'] and not r['request_id'] and not r['waiting'] and not r['parked'] for r in rows)
        resumed = [e['episode_id'] for e in snapshots['terminal']['events'] if e['kind'] == 'episode_resumed']
        assert resumed == ['middle', 'low']
        return {'metadata': {'tags': ['scripted', 'capacity-controller-smoke']},
                'qualification': 'CPU simulated HTTP/episode turns only; no vLLM/browser/GPU',
                'passed': True, 'resumed_order': resumed, 'metrics_requests': state['requests'],
                'snapshots': snapshots, 'poller': poller.status()}
    finally:
        release.set()
        controller.close()
        poller.close()
        pool.shutdown(wait=True, cancel_futures=True)
        server.shutdown()
        server.server_close()
        serving.join(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('passed', 'resumed_order', 'metrics_requests', 'qualification')}))


if __name__ == '__main__':
    main()
