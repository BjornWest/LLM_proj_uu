"""Opt-in bounded timing evidence; no browser RPCs or hot-path disk writes."""
from contextlib import contextmanager
from functools import wraps
import os
import threading
import time
import traceback


class DebugTimings:
    def __init__(self, enabled=False, max_records=50000):
        if type(enabled) is not bool:raise ValueError('debug timings must be boolean')
        if type(max_records) is not int or not 1<=max_records<=200000:raise ValueError('invalid timing record cap')
        self.enabled=enabled;self.max_records=max_records;self.rows=[];self.dropped=0
        self.origin=time.monotonic();self.lock=threading.Lock()

    def record(self, name, started, *, ended=None, **details):
        if not self.enabled:return
        ended=time.monotonic() if ended is None else ended
        row={'name':name,'start_seconds':started-self.origin,'duration_seconds':ended-started,
             'thread_id':threading.get_ident(),**details}
        with self.lock:
            if len(self.rows)<self.max_records:self.rows.append(row)
            else:self.dropped+=1

    @contextmanager
    def span(self,name,**details):
        if not self.enabled:
            yield;return
        start=time.monotonic();error=None
        try:yield
        except BaseException as exc:
            error=type(exc).__name__;raise
        finally:self.record(name,start,error_type=error,**details)

    def exception(self,exc,**details):
        if not self.enabled:return
        frames=[{'file':f.filename,'line':f.lineno,'function':f.name}
                for f in traceback.extract_tb(exc.__traceback__)]
        self.record('exception',time.monotonic(),error_type=type(exc).__name__,frames=frames,**details)

    def report(self):
        with self.lock:rows=list(self.rows);dropped=self.dropped
        return {'version':'buffered-debug-timings-v1','enabled':self.enabled,'max_records':self.max_records,
            'dropped_records':dropped,'records':rows,
            'clock':'process monotonic seconds relative to origin; shared across threads',
            'scope':'Nested/overlapping spans, not additive. No extra browser RPCs. Buffered until trace finish; abrupt process loss can lose this diagnostic buffer. Error frames omit locals and exception text.'}


def resolve_debug_timings(value=None):
    if value is None:
        raw=os.environ.get('HARNESS_DEBUG_TIMINGS','0')
        if raw not in ('0','1'):raise ValueError('HARNESS_DEBUG_TIMINGS must be 0 or 1')
        return raw=='1'
    if type(value) is not bool:raise ValueError('debug_timings must be boolean or None')
    return value


def timed(name):
    """Trace method instrumentation; disabled path adds no clock/lock/record."""
    def decorate(fn):
        @wraps(fn)
        def wrapped(self,*args,**kwargs):
            if not self.timings.enabled:return fn(self,*args,**kwargs)
            with self.timings.span(name):return fn(self,*args,**kwargs)
        return wrapped
    return decorate
