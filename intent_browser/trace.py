"""Portable, append-only transitions plus compressed raw browser observations."""

import gzip
import json
import hashlib
import os
import platform
import time
from .debug_timings import DebugTimings, timed
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image


def json_default(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"Cannot serialize {type(value)}")


def write_json(path, value):
    path = Path(path)
    text = json.dumps(value, indent=2, default=json_default)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime_provenance():
    from importlib.metadata import version

    package = Path(__file__).resolve().parent
    return {"python": platform.python_version(),
            "packages": {name: version(name) for name in ("browsergym-core", "playwright", "httpx")},
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(package.glob("*.py"))},
            "observation_adapter": "axtree-text-v1", "action_parser": "literal-call-v2"}


class Trace:
    def __init__(self, root, metadata, *, async_recording=False, recording_max_bytes=128 * 1024 * 1024, recording_max_pending=8, debug_timings=False):
        self.timings = DebugTimings(debug_timings)
        self.episode_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        self.directory = Path(root) / self.episode_id
        self.directory.mkdir(parents=True)
        self.metadata = {**metadata, "schema_version": 3, "episode_id": self.episode_id,
                         "runtime": runtime_provenance(),
                         "debug_timings": {"enabled": debug_timings, "version": "buffered-debug-timings-v1",
                             "artifact": "debug-timings.json" if debug_timings else None,
                             "max_records": self.timings.max_records}}
        write_json(self.directory / "metadata.json", self.metadata)
        self.events = (self.directory / "steps.jsonl").open("w", encoding="utf-8")
        self.lifecycle = (self.directory / "events.jsonl").open("w", encoding="utf-8")
        from .observation_writer import ObservationWriter
        self.writer = (ObservationWriter(self.directory, max_bytes=recording_max_bytes,
                       max_pending=recording_max_pending) if async_recording else None)
        self.metadata['observation_recording'] = {'mode': 'background' if self.writer else 'synchronous',
            'immutable_handoff': 'JSON text plus copied pixels',
            'text_available_on_return': True, 'flush_before_episode_finished': True}
        write_json(self.directory / 'metadata.json', self.metadata)
        self.event("episode_started")

    @timed('trace.event_write')
    def event(self, kind, **data):
        if self.timings.enabled:
            ended=time.monotonic()
            duration=data.get('seconds')
            duration=duration if type(duration) in (int,float) and duration>=0 else 0
            # Reuse existing instrumentation; never collect more browser data.
            details={k:data[k] for k in ('step','phase','operation','frame_index','call_id')
                     if k in data and type(data[k]) in (str,int,float,bool)}
            self.timings.record('lifecycle.'+kind,ended-duration,ended=ended,**details)
        self.lifecycle.write(json.dumps({"event": kind,
            "timestamp": datetime.now(timezone.utc).isoformat(), **data}, default=json_default) + "\n")
        self.lifecycle.flush()

    @timed("trace.observation")
    def observation(self, index, obs, text, *, phase="transition"):
        if phase not in ("transition", "decision", "batch_guard", "background"):
            raise ValueError("Unknown observation phase")
        stem = f"{phase+'-' if phase != 'transition' else ''}observation-{index:03d}"
        screenshot = f"{stem}.png" if obs["screenshot"] is not None else None
        # Freeze nested browser values now; never retain mutable observations in
        # a worker thread. Gzip/PNG encoding and disk writes run in the background.
        with self.timings.span("trace.serialize_observation",step=index,phase=phase):
            payload = json.dumps({k: v for k, v in obs.items() if k != "screenshot"},
                                 default=json_default)
        # Exposure graders read this tiny policy-delivery artifact immediately.
        (self.directory / f"{stem}.txt").write_text(text, encoding="utf-8")
        if self.writer is not None:
            with self.timings.span('trace.enqueue_observation',step=index,phase=phase):
                self.writer.submit(stem, payload, obs['screenshot'])
        else:
            from .observation_writer import write_payload
            write_payload(self.directory, stem, payload, obs['screenshot'])
        return {"raw": f"{stem}.json.gz", "screenshot": screenshot, "text": f"{stem}.txt"}

    def flush_observations(self):
        """Barrier for callers that need all returned raw/image files now."""
        if self.writer is not None:
            self.writer.flush()

    @timed("trace.step_write")
    def append(self, step):
        self.events.write(json.dumps(step, default=json_default) + "\n")
        self.events.flush()

    def finish(self, summary):
        recording_error = None
        if self.writer is not None:
            try:
                self.writer.close()
            except Exception as exc:
                recording_error = exc
                summary = {**summary, 'recording_error': f'{type(exc).__name__}: {exc}',
                           'trace_complete': False}
            write_json(self.directory / 'recording.json', self.writer.report())
        summary = {'trace_complete': recording_error is None, **summary}
        self.event("episode_finished", stop_reason=summary.get("stop_reason"), error=summary.get("error"))
        self.events.close()
        self.lifecycle.close()
        write_json(self.directory / "episode.json", {
            **self.metadata, **summary, "steps_file": "steps.jsonl", "events_file": "events.jsonl",
            "videos": [str(p.relative_to(self.directory)) for p in self.directory.rglob("*.webm")],
        })
        if self.timings.enabled:
            write_json(self.directory / "debug-timings.json",self.timings.report())
        if recording_error is not None:
            raise RuntimeError('Trace incomplete: observation recording failed') from recording_error
