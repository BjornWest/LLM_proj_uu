"""Bounded, ordered disk recording of immutable observation payloads.

No Playwright objects cross the thread boundary. Encoding JSON before admission
freezes nested mutable browser data; a copied pixel buffer freezes the screenshot.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import gzip
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

from PIL import Image


def write_payload(directory, stem, payload, pixels):
    """Publish complete files atomically; failed writes leave no partial artifact."""
    directory = Path(directory)
    for suffix in (['.png'] if pixels is not None else []) + ['.json.gz']:
        target = directory / (stem + suffix)
        temporary = target.with_name(target.name + '.' + uuid4().hex + '.tmp')
        try:
            if suffix == '.png':
                Image.fromarray(pixels).save(temporary, format='PNG')
            else:
                with gzip.open(temporary, 'wt', encoding='utf-8') as stream:
                    stream.write(payload)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


class ObservationWriter:
    def __init__(self, directory, *, max_bytes=128 * 1024 * 1024, max_pending=8):
        if type(max_bytes) is not int or max_bytes <= 0 or type(max_pending) is not int or max_pending <= 0:
            raise ValueError('Recording queue limits must be positive integers')
        self.directory = directory
        self.max_bytes, self.max_pending = max_bytes, max_pending
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='trace-recording')
        self.pending = deque()
        self.bytes = 0
        self.closed = False
        self.failure = None
        self.metrics = []
        self.backpressure_seconds = 0.0
        self.high_water_bytes = 0
        self.high_water_jobs = 0

    def _retire(self):
        future, size = self.pending.popleft()
        self.bytes -= size
        try:
            self.metrics.append(future.result())
        except BaseException as exc:
            self.failure = self.failure or exc
            raise

    def submit(self, stem, payload, screenshot):
        if self.closed:
            raise RuntimeError('Observation writer is closed')
        if self.failure is not None:
            raise RuntimeError('Observation recording failed') from self.failure
        while self.pending and self.pending[0][0].done():
            self._retire()
        size = sys.getsizeof(payload) + (screenshot.nbytes if screenshot is not None else 0)
        started = time.perf_counter()
        while self.pending and (len(self.pending) >= self.max_pending or self.bytes + size > self.max_bytes):
            self._retire()
        self.backpressure_seconds += time.perf_counter() - started
        # Copy only the pixel buffer. Nested JSON is already immutable text.
        pixels = screenshot.copy() if screenshot is not None else None
        queued = time.perf_counter()
        def write():
            begin = time.perf_counter()
            write_payload(self.directory, stem, payload, pixels)
            return {'stem': stem, 'queued_at': queued, 'started_at': begin,
                    'finished_at': time.perf_counter(), 'thread_id': threading.get_ident(),
                    'payload_bytes': size}
        if size > self.max_bytes:
            # A single oversized capture cannot fit: drain then write synchronously.
            # Never silently discard evidence or retain an unbounded backlog.
            try:
                self.metrics.append(write())
            except BaseException as exc:
                self.failure = exc
                raise
            self.backpressure_seconds += time.perf_counter() - queued
            return
        self.pending.append((self.pool.submit(write), size))
        self.bytes += size
        self.high_water_bytes = max(self.high_water_bytes, self.bytes)
        self.high_water_jobs = max(self.high_water_jobs, len(self.pending))

    def flush(self):
        first_error = self.failure
        while self.pending:
            try:
                self._retire()
            except BaseException as exc:
                first_error = first_error or exc
        if first_error is not None:
            raise RuntimeError('Observation recording failed') from first_error

    def close(self):
        try:
            self.flush()
        finally:
            self.closed = True
            self.pool.shutdown(wait=True)

    def report(self):
        return {'max_bytes': self.max_bytes, 'max_pending': self.max_pending,
                'high_water_bytes': self.high_water_bytes, 'high_water_jobs': self.high_water_jobs,
                'backpressure_seconds': self.backpressure_seconds, 'writes': self.metrics,
                'clock': 'process perf_counter; timestamps comparable within this process only'}
