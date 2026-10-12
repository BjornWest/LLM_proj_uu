"""Bounded serving observations from the capacity poller's existing scrape.

No file/network I/O, model calls, W&B import or extra collector here. The outer
controller drains small batches into its journal, console and existing W&B run.
Rates are aggregate counter deltas per wall-clock interval, not GPU kernel speed.
"""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import math
import re
import threading
import time
import uuid

from .capacity_control import _SAMPLE, _labels


_COUNTERS = {
    ('vllm:generation_tokens_total', None): 'output_tokens',
    ('vllm:prompt_tokens_by_source_total', 'local_compute'): 'initial_prefill_tokens',
    ('vllm:prompt_tokens_by_source_total', 'local_cache_hit'): 'local_cached_input_tokens',
    ('vllm:prompt_tokens_by_source_total', 'external_kv_transfer'): 'external_cached_input_tokens',
    ('vllm:kv_offload_load_bytes_total', None): 'cpu_load_bytes',
    ('vllm:kv_offload_store_bytes_total', None): 'cpu_store_bytes',
    ('vllm:num_preemptions_total', None): 'preemptions',
}
_NAMES = {name for name, _ in _COUNTERS}


def counters(text, *, model, engine):
    """Select one exact model/engine. Missing series stay unknown, never zero."""
    result = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        if re.split(r'[\s{]', line, maxsplit=1)[0] not in _NAMES:
            continue
        match = _SAMPLE.fullmatch(line)
        if match is None:
            raise ValueError('Malformed serving counter')
        labels = _labels(match[2] or '')
        if labels.get('model_name') != model or labels.get('engine') != engine:
            continue
        name = _COUNTERS.get((match[1], labels.get('source')))
        if name is None:
            continue
        value = float(match[3])
        if name in result or not math.isfinite(value) or value < 0 or not value.is_integer():
            raise ValueError('Ambiguous or invalid serving counter: ' + name)
        result[name] = value
    return result


class ServingTelemetry:
    def __init__(self, *, session_id, model, model_revision, engine='0',
                 history=7200, max_gap_seconds=5, synthetic=False,
                 clock=time.monotonic, wall_clock=time.time):
        if any(not isinstance(v, str) or not v for v in (session_id, model, model_revision, engine)):
            raise ValueError('Explicit serving session/model/revision/engine required')
        if type(history) is not int or not 1 <= history <= 14400:
            raise ValueError('History must be 1..14400 samples')
        if (type(max_gap_seconds) not in (int, float) or not math.isfinite(max_gap_seconds)
                or max_gap_seconds <= 0 or type(synthetic) is not bool):
            raise ValueError('Invalid observation policy')
        self.session_id, self.model, self.revision, self.engine = session_id, model, model_revision, engine
        self.observer_id = uuid.uuid4().hex
        self.max_gap_seconds, self.synthetic = max_gap_seconds, synthetic
        self.clock, self.wall_clock = clock, wall_clock
        self.lock = threading.Lock()
        self.rows = deque(maxlen=history)
        self.previous, self.origin = None, None
        self.sequence = self.segment = 0

    def observe(self, text, snapshot, *, model, engine):
        """Attach as SharedMetricsPoller.on_scrape; never performs I/O."""
        snapshot.validate()
        if model != self.model or engine != self.engine:
            raise ValueError('Scrape model/engine differs from serving observer')
        values = counters(text, model=self.model, engine=self.engine)
        if not values:
            raise ValueError('No serving counters for selected model/engine')
        wall = self.wall_clock()
        if not math.isfinite(wall) or wall < 0:
            raise ValueError('Invalid wall clock')
        with self.lock:
            previous = self.previous
            dt = None if previous is None else snapshot.observed_at - previous[0]
            if dt is not None and dt <= 0:
                raise ValueError('Serving samples must advance in monotonic time')
            reset = previous is not None and any(
                values[k] < previous[1][k] for k in values.keys() & previous[1].keys())
            gap = dt is not None and dt > self.max_gap_seconds
            if reset or gap:
                self.segment += 1
            rates = {key + '_per_s': None for key in _COUNTERS.values()}
            if previous is not None and not reset and not gap:
                for key in values.keys() & previous[1].keys():
                    value = (values[key] - previous[1][key]) / dt
                    if not math.isfinite(value):
                        raise ValueError('Nonfinite serving rate')
                    rates[key + '_per_s'] = value
            cache_rates = [rates[k + '_per_s'] for k in (
                'initial_prefill_tokens', 'local_cached_input_tokens', 'external_cached_input_tokens')]
            cache_fraction = None
            if all(v is not None for v in cache_rates) and sum(cache_rates) > 0:
                cache_fraction = (cache_rates[1] + cache_rates[2]) / sum(cache_rates)
            if self.origin is None:
                self.origin = snapshot.observed_at
            self.sequence += 1
            row = dict(schema='serving-telemetry-v1', seq=self.sequence,
                session_id=self.session_id, model=self.model, model_revision=self.revision,
                observer_id=self.observer_id,
                engine=self.engine, synthetic=self.synthetic, observed_at_utc=wall,
                observed_at_monotonic=snapshot.observed_at,
                elapsed_seconds=snapshot.observed_at-self.origin, counter_segment=self.segment,
                interval_seconds=dt, counter_reset=reset, sample_gap=gap,
                running_requests=snapshot.running,
                capacity_waiting_requests=snapshot.capacity_waiting,
                deferred_waiting_requests=snapshot.deferred_waiting,
                waiting_requests=snapshot.capacity_waiting+snapshot.deferred_waiting,
                kv_cache_fraction=snapshot.kv_usage, interval_cached_input_fraction=cache_fraction,
                counters=values, rates=rates)
            self.rows.append(row)
            self.previous = snapshot.observed_at, values

    def read(self, *, after=0, limit=120, observer_id=None):
        """Small incremental transfer. Report buffer loss rather than hide it."""
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 120:
            raise ValueError('Invalid serving cursor/batch limit')
        with self.lock:
            if ((after > 0 and observer_id != self.observer_id)
                    or (observer_id is not None and observer_id != self.observer_id)):
                raise ValueError('Serving observer changed; reset cursor explicitly')
            if after > self.sequence:
                raise ValueError('Cursor exceeds current serving history')
            oldest = self.rows[0]['seq'] if self.rows else None
            latest = self.rows[-1] if self.rows else None
            return dict(session_id=self.session_id, observer_id=self.observer_id,
                latest_seq=self.sequence, oldest_seq=oldest,
                gap=oldest is not None and after < oldest-1,
                latest_sample_age_seconds=None if latest is None else max(0, self.clock()-latest['observed_at_monotonic']),
                rows=deepcopy([r for r in self.rows if r['seq'] > after][:limit]))


def status_line(row):
    def rate(key):
        v = row['rates'][key + '_per_s']
        return 'unavailable' if v is None else f'{v:,.1f}'
    stamp = datetime.fromtimestamp(row['observed_at_utc'], timezone.utc).isoformat(timespec='seconds')
    return (f"[vLLM serving {stamp}] running={row['running_requests']} "
        f"waiting={row['waiting_requests']} (capacity={row['capacity_waiting_requests']}, "
        f"deferred={row['deferred_waiting_requests']}) KV={100*row['kv_cache_fraction']:.1f}% "
        f"prefill-completed={rate('initial_prefill_tokens')} tokens/s output={rate('output_tokens')} tokens/s "
        f"counter_segment={row['counter_segment']} synthetic={row['synthetic']}")


def wandb_values(row, *, allow_synthetic=False):
    """Pass to the existing suite run on the local controller, outside polling."""
    if row['synthetic'] and not allow_synthetic:
        raise ValueError('Synthetic serving data requires an explicitly synthetic run')
    result = {'serving/time_seconds': row['elapsed_seconds'],
        'serving/sample_utc': row['observed_at_utc'], 'serving/sample_sequence': row['seq'],
        'serving/running_requests': row['running_requests'],
        'serving/waiting_requests': row['waiting_requests'],
        'serving/capacity_waiting_requests': row['capacity_waiting_requests'],
        'serving/deferred_waiting_requests': row['deferred_waiting_requests'],
        'serving/kv_cache_percent': 100*row['kv_cache_fraction'],
        'serving/counter_segment': row['counter_segment'],
        'serving/counter_reset': int(row['counter_reset']),
        'serving/sample_gap': int(row['sample_gap'])}
    for key, value in row['counters'].items():
        result['serving_total/' + key] = value
    for key, value in row['rates'].items():
        result['serving_available/' + key] = int(value is not None)
        if value is not None:
            result['serving/' + key] = value
    if row['interval_cached_input_fraction'] is not None:
        result['serving/cached_input_percent'] = 100*row['interval_cached_input_fraction']
    return result
