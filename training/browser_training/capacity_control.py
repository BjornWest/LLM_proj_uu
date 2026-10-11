"""Shared vLLM telemetry and turn-boundary parking; no model/cache manipulation.

One parent owns the poller and controller. Process callers may marshal the
register/acquire/release/finish methods over their existing admission channel.
An HTTP request starts only after acquire_turn returns. Caller cleanup, browser
freshness, native grading, policy leases and rental deadlines remain external.
"""

from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import http.client
import math
import re
import socket
import threading
import time
from urllib.parse import urlsplit


_SAMPLE = re.compile(r'^([\w:]+)(?:\{(.*)\})?\s+([^\s]+)(?:\s+[^\s]+)?$')
_LABEL = re.compile(r'\s*([A-Za-z_][A-Za-z0-9_]*)="((?:\\.|[^"\\])*)"\s*(,|$)')
_NAMES = {
    "vllm:num_requests_running", "vllm:num_requests_waiting",
    "vllm:num_requests_waiting_by_reason", "vllm:kv_cache_usage_perc",
    "vllm:num_preemptions_total",
}


def _labels(text):
    labels, offset = {}, 0
    while offset < len(text):
        match = _LABEL.match(text, offset)
        if match is None or match[1] in labels:
            raise ValueError("Malformed or duplicate metric label")
        def unescape(m):
            try:
                return {"n": "\n", "\\": "\\", '"': '"'}[m[1]]
            except KeyError as exc:
                raise ValueError("Unsupported metric-label escape") from exc
        labels[match[1]] = re.sub(r'\\(.)', unescape, match[2])
        offset = match.end()
        if match[3] and offset == len(text):
            raise ValueError("Trailing metric-label comma")
    return labels


@dataclass(frozen=True)
class CapacitySnapshot:
    observed_at: float
    capacity_waiting: int
    deferred_waiting: int
    running: int
    kv_usage: float
    preemptions: int

    def validate(self):
        if not math.isfinite(self.observed_at) or self.observed_at < 0:
            raise ValueError("Invalid observation timestamp")
        for value in (self.capacity_waiting, self.deferred_waiting,
                      self.running, self.preemptions):
            if type(value) is not int or value < 0:
                raise ValueError("Counts must be nonnegative integers")
        if not math.isfinite(self.kv_usage) or not 0 <= self.kv_usage <= 1:
            raise ValueError("Invalid cache-usage fraction")


def parse_metrics(body, *, model, engine="0", observed_at=None):
    """Select exactly one model/engine; retain reason labels, never sum replicas."""
    selected = {}
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        # Unrelated exporter series need not use this subset's label grammar.
        name = re.split(r'[\s{]', line, maxsplit=1)[0]
        if name not in _NAMES:
            continue
        match = _SAMPLE.fullmatch(line)
        if match is None:
            raise ValueError("Malformed capacity metric")
        labels = _labels(match[2] or "")
        if labels.get("model_name") != model or labels.get("engine") != engine:
            continue
        reason = labels.get("reason") if name.endswith("waiting_by_reason") else None
        key = name, reason
        if key in selected:
            raise ValueError("Ambiguous model/engine capacity metric")
        selected[key] = float(match[3])

    def count(name, reason=None):
        value = selected[(name, reason)]
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            raise ValueError("Invalid metric count")
        return int(value)
    try:
        snapshot = CapacitySnapshot(
            time.monotonic() if observed_at is None else observed_at,
            count("vllm:num_requests_waiting_by_reason", "capacity"),
            count("vllm:num_requests_waiting_by_reason", "deferred"),
            count("vllm:num_requests_running"),
            selected[("vllm:kv_cache_usage_perc", None)],
            count("vllm:num_preemptions_total"),
        )
        if count("vllm:num_requests_waiting") != snapshot.capacity_waiting + snapshot.deferred_waiting:
            raise ValueError("Waiting reason counts do not match total")
    except KeyError as exc:
        raise ValueError("Missing model/engine capacity metrics; enable vLLM stats") from exc
    snapshot.validate()
    return snapshot


class SharedMetricsPoller:
    """One persistent HTTP connection, bounded reads/timeouts, shared snapshots.

    on_snapshot must be a short local callback, e.g. controller.observe.
    Other consumers read status(); they never make their own HTTP requests.
    HTTP failures retain the old timestamp so consumers detect stale telemetry.
    """
    def __init__(self, url, *, model, engine="0", interval=1.0, timeout=2.0,
                 max_bytes=1024 * 1024, on_snapshot=None):
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path.rstrip("/") != "/metrics"):
            raise ValueError("Use an HTTP(S) /metrics URL without embedded credentials")
        if not all(math.isfinite(v) and v > 0 for v in (interval, timeout)):
            raise ValueError("Poll interval and timeout must be positive finite seconds")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("Invalid response limit")
        parsed.port  # Reject out-of-range/non-numeric ports at construction.
        self.address, self.model, self.engine = parsed, model, engine
        self.interval, self.timeout, self.max_bytes = interval, timeout, max_bytes
        self.on_snapshot = on_snapshot
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.snapshot = None
        self.requests = self.failures = 0
        self.last_error = None
        self.thread = None
        self.active_socket = None

    def start(self):
        with self.lock:
            if self.thread is not None or self.stop.is_set():
                raise RuntimeError("Poller already started or closed")
            self.thread = threading.Thread(target=self._run, name="vllm-metrics", daemon=True)
            self.thread.start()
        return self

    def _run(self):
        connection, failures = None, 0
        try:
            while not self.stop.is_set():
                try:
                    if connection is None:
                        factory = http.client.HTTPSConnection if self.address.scheme == "https" else http.client.HTTPConnection
                        connection = factory(self.address.hostname, self.address.port, timeout=self.timeout)
                    with self.lock:
                        self.requests += 1
                    if connection.sock is None:
                        connection.connect()
                    active_socket = connection.sock
                    with self.lock:
                        self.active_socket = active_socket
                    def interrupt_socket():
                        try:
                            active_socket.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    # Socket inactivity timeouts alone do not bound trickling bodies.
                    watchdog = threading.Timer(self.timeout, interrupt_socket)
                    watchdog.daemon = True
                    watchdog.start()
                    try:
                        if self.stop.is_set():
                            break
                        connection.request("GET", self.address.path, headers={"Accept": "text/plain"})
                        response = connection.getresponse()
                        if response.status != 200:
                            raise OSError(f"Metrics HTTP status {response.status}")
                        body = response.read(self.max_bytes + 1)
                        if len(body) > self.max_bytes:
                            raise ValueError("Metrics response exceeds byte limit")
                        if not response.isclosed() or response.length not in (None, 0):
                            raise OSError("Incomplete metrics response")
                    finally:
                        watchdog.cancel()
                        # Ensure a fired watchdog cannot hit the next keepalive request.
                        watchdog.join()
                        with self.lock:
                            self.active_socket = None
                    snapshot = parse_metrics(body.decode("utf-8"), model=self.model, engine=self.engine)
                    # Callbacks never run under the poller's lock.
                    if self.on_snapshot is not None:
                        self.on_snapshot(snapshot)
                    with self.lock:
                        self.snapshot, self.last_error = snapshot, None
                    failures = 0
                except Exception as exc:
                    with self.lock:
                        self.failures += 1
                        self.last_error = f"{type(exc).__name__}: {exc}"
                    failures += 1
                    if connection is not None:
                        connection.close()
                        connection = None
                self.stop.wait(min(30.0, self.interval * 2 ** min(failures, 5)))
        finally:
            if connection is not None:
                connection.close()

    def status(self):
        with self.lock:
            return dict(snapshot=None if self.snapshot is None else asdict(self.snapshot),
                        requests=self.requests, failures=self.failures, last_error=self.last_error)

    def close(self):
        self.stop.set()
        with self.lock:
            if self.active_socket is not None:
                try:
                    self.active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.thread is not None:
            self.thread.join(2 * self.timeout + 1)
            if self.thread.is_alive():
                raise TimeoutError("Metrics collector did not stop")


@dataclass(frozen=True)
class ParkingConfig:
    max_generation_requests: int = 4
    max_active_episodes: int = 4
    terminal_history: int = 128
    high_water: float = .85
    low_water: float = .70
    sustained_samples: int = 2
    fresh_seconds: float = 3.0

    def validate(self):
        if type(self.max_generation_requests) is not int or self.max_generation_requests < 1:
            raise ValueError("Invalid generation cap")
        if type(self.max_active_episodes) is not int or self.max_active_episodes < 1:
            raise ValueError("Invalid active lifecycle cap")
        if type(self.terminal_history) is not int or self.terminal_history < 1:
            raise ValueError("Invalid terminal history limit")
        if type(self.sustained_samples) is not int or self.sustained_samples < 1:
            raise ValueError("Invalid debounce count")
        if not 0 <= self.low_water < self.high_water <= 1:
            raise ValueError("Require 0 <= low water < high water <= 1")
        if not math.isfinite(self.fresh_seconds) or self.fresh_seconds <= 0:
            raise ValueError("Invalid telemetry freshness")


class TurnCancelled(RuntimeError):
    pass


class EpisodeCapacityController:
    """Sticky parking at request boundaries, with unchanged CPU/GPU LRU.

    Lower numeric priority means higher importance. Ties favour earlier episode
    admission. Aggregate telemetry cannot identify a specific server-waiting
    request: victims are selected from our registered live episodes instead.
    This is reactive flow control, not a prediction/reservation of prefix bytes.
    """
    def __init__(self, config=ParkingConfig(), *, clock=time.monotonic):
        config.validate()
        self.config, self.clock = config, clock
        self.condition = threading.Condition()
        self.rows = {}
        self.telemetry = None
        self.closed = False
        self.streak = self.admissions = 0
        self.completed = deque()
        self.sequence = 0
        self.events = deque(maxlen=2048)

    def _emit(self, kind, episode=None, **details):
        self.sequence += 1
        self.events.append(dict(sequence=self.sequence, time=self.clock(), kind=kind,
                                episode_id=episode, **details))

    def register_episode(self, episode_id, *, priority=0):
        if not isinstance(episode_id, str) or not episode_id or type(priority) is not int:
            raise ValueError("Expected nonempty episode ID and integer priority")
        with self.condition:
            if self.closed:
                raise TurnCancelled("Controller closed")
            if episode_id in self.rows:
                raise ValueError("Episode ID already registered")
            if sum(not r["done"] for r in self.rows.values()) >= self.config.max_active_episodes:
                raise ValueError("Active episode lifecycle cap reached (parked episodes count)")
            self.admissions += 1
            self.rows[episode_id] = dict(priority=priority, order=self.admissions,
                request_id=None, waiting=False, turns=0, park_requested=False,
                parked=False, resume_granted=False, done=False, cancelled=False)
            self._emit("episode_registered", episode_id, priority=priority)

    def _rank(self, item):
        _, row = item
        return row["priority"], row["order"]

    def _fresh(self):
        return (self.telemetry is not None
                and 0 <= self.clock() - self.telemetry.observed_at <= self.config.fresh_seconds)

    def _resume(self):
        if (not self._fresh() or self.telemetry.capacity_waiting
                or self.telemetry.kv_usage > self.config.low_water):
            return
        candidates = sorted(((i, r) for i, r in self.rows.items()
            if r["parked"] and r["resume_granted"] and not r["done"]
            and not r["cancelled"]), key=self._rank)
        for episode, row in candidates:
            row.update(parked=False, park_requested=False, resume_granted=False)
            self._emit("episode_resumed", episode)

    def observe(self, snapshot):
        snapshot.validate()
        with self.condition:
            if self.closed:
                return
            if snapshot.observed_at > self.clock():
                raise ValueError("Future telemetry timestamp")
            if self.telemetry is not None and snapshot.observed_at <= self.telemetry.observed_at:
                return  # Replayed samples must not satisfy debounce.
            previous = self.telemetry
            self.telemetry = snapshot
            pressure = snapshot.capacity_waiting > 0 and snapshot.kv_usage >= self.config.high_water
            continuous = previous is not None and snapshot.observed_at - previous.observed_at <= self.config.fresh_seconds
            self.streak = (self.streak + 1 if continuous else 1) if pressure else 0
            if previous is not None and snapshot.preemptions > previous.preemptions:
                self._emit("preemption_observed", count=snapshot.preemptions - previous.preemptions)
            victims = sum(r["park_requested"] and not r["done"] and not r["cancelled"]
                          for r in self.rows.values())
            needed = max(0, snapshot.capacity_waiting - victims) if self.streak >= self.config.sustained_samples else 0
            if needed and self._fresh():
                candidates = sorted(((i, r) for i, r in self.rows.items()
                    if not r["done"] and not r["cancelled"] and not r["park_requested"]
                    and r["turns"] > 0), key=self._rank, reverse=True)
                # Leave one established episode able to drain toward completion.
                for episode, row in candidates[:min(needed, max(0, len(candidates) - 1))]:
                    row.update(park_requested=True, parked=row["request_id"] is None,
                               resume_granted=False)
                    self._emit("parking_requested", episode, in_flight=row["request_id"] is not None,
                        capacity_waiting=snapshot.capacity_waiting, kv_usage=snapshot.kv_usage,
                        preemption_delta=max(0, snapshot.preemptions - previous.preemptions) if previous else 0)
                    if row["parked"]:
                        self._emit("episode_parked", episode)
            self._resume()
            self.condition.notify_all()

    def _candidate(self):
        if not self._fresh():
            return None
        inflight = sum(r["request_id"] is not None for r in self.rows.values())
        if inflight >= self.config.max_generation_requests:
            return None
        pending = [(i, r) for i, r in self.rows.items() if r["waiting"]
                   and not r["park_requested"] and not r["done"] and not r["cancelled"]]
        pressure = self.telemetry.capacity_waiting > 0 or self.telemetry.kv_usage >= self.config.high_water
        if pressure:
            # With no requests in flight, permit one existing episode to progress.
            # Without this escape, rising contexts can deadlock every actor.
            if inflight:
                return None
            pending = [(i, r) for i, r in pending if r["turns"] > 0]
        return min(pending, key=self._rank)[0] if pending else None

    def acquire_turn(self, episode_id, request_id, *, timeout, stop_event=None):
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("Expected request ID")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("A finite positive acquisition timeout is required")
        deadline = self.clock() + timeout
        with self.condition:
            row = self.rows[episode_id]
            if row["request_id"] is not None or row["waiting"]:
                raise ValueError("Only one generation request per episode may be pending")
            row["waiting"] = True
            self._emit("turn_waiting", episode_id, request_id=request_id)
            try:
                while True:
                    if self.closed or row["done"] or row["cancelled"] or (stop_event is not None and stop_event.is_set()):
                        raise TurnCancelled("Episode/controller cancelled")
                    if self.clock() >= deadline:
                        raise TimeoutError("Capacity wait timed out")
                    if self._candidate() == episode_id:
                        row.update(request_id=request_id, waiting=False, turns=row["turns"] + 1)
                        self._emit("turn_started", episode_id, request_id=request_id)
                        return request_id
                    self.condition.wait(min(.1, deadline - self.clock()))
            finally:
                row["waiting"] = False
                self.condition.notify_all()

    def release_turn(self, episode_id, request_id):
        """Call after the response stream/client cleanup, including on errors."""
        with self.condition:
            row = self.rows[episode_id]
            if row["request_id"] != request_id:
                raise ValueError("Turn release identity mismatch")
            row["request_id"] = None
            self._emit("turn_finished", episode_id, request_id=request_id)
            if row["park_requested"]:
                row["parked"] = True
                self._emit("episode_parked", episode_id)
            self._resume()
            self.condition.notify_all()

    @contextmanager
    def turn(self, episode_id, request_id, *, timeout, stop_event=None):
        self.acquire_turn(episode_id, request_id, timeout=timeout, stop_event=stop_event)
        try:
            yield
        finally:
            self.release_turn(episode_id, request_id)

    def cancel_episode(self, episode_id):
        """Wake pending local calls; caller still owns abort/cleanup of HTTP work."""
        with self.condition:
            self.rows[episode_id]["cancelled"] = True
            self._emit("episode_cancelled", episode_id)
            self.condition.notify_all()

    def finish_episode(self, episode_id):
        """After native terminal cleanup, never merely after a tool/model turn."""
        with self.condition:
            row = self.rows[episode_id]
            if row["done"] or row["request_id"] is not None:
                raise ValueError("Episode must be nonterminal with no HTTP work in flight")
            row.update(done=True, park_requested=False, parked=False, resume_granted=False)
            # Bind one completion to one currently parked/pending victim. A credit
            # must never leak to an episode parked after that completion.
            candidates = [(i, r) for i, r in self.rows.items()
                if r["park_requested"] and not r["done"] and not r["cancelled"]
                and not r["resume_granted"]]
            if candidates:
                granted, recipient = min(candidates, key=self._rank)
                recipient["resume_granted"] = True
                self._emit("resume_granted", granted, completed_episode=episode_id)
            self.completed.append(episode_id)
            while len(self.completed) > self.config.terminal_history:
                del self.rows[self.completed.popleft()]
            self._emit("episode_finished", episode_id)
            self._resume()
            self.condition.notify_all()

    def status(self):
        with self.condition:
            return dict(episodes={i: dict(r) for i, r in self.rows.items()},
                        telemetry=None if self.telemetry is None else asdict(self.telemetry),
                        telemetry_fresh=self._fresh(), resume_credits=sum(r["resume_granted"] and not r["done"] and not r["cancelled"] for r in self.rows.values()),
                        closed=self.closed, events=list(self.events))

    def close(self):
        with self.condition:
            self.closed = True
            self._emit("controller_closed")
            self.condition.notify_all()
