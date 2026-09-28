import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from intent_browser.debug_timings import DebugTimings, resolve_debug_timings
from intent_browser.trace import Trace
from intent_browser.browser_events import BrowserEvents


class TimingsTests(unittest.TestCase):
    def test_disabled_has_no_records_or_clock_calls(self):
        t=DebugTimings()
        with patch('intent_browser.debug_timings.time.monotonic',side_effect=AssertionError):
            t.record('ignored',0)
            with t.span('ignored'):pass
            t.exception(ValueError('PRIVATE'))
        self.assertEqual(t.report()['records'],[])

    def test_bound_thread_safety_and_exception_redaction(self):
        t=DebugTimings(True,max_records=11)
        def emit(i):t.record('item',t.origin,ended=t.origin+1,ordinal=i)
        with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(emit,range(50)))
        report=t.report();self.assertEqual(len(report['records']),11)
        self.assertEqual(report['dropped_records'],39)
        t=DebugTimings(True)
        try:raise ValueError('PRIVATE secret')
        except ValueError as exc:t.exception(exc,phase='test')
        text=json.dumps(t.report());self.assertNotIn('PRIVATE',text)
        self.assertIn('test_bound_thread_safety',text)
        self.assertEqual(t.report()['records'][0]['error_type'],'ValueError')

    def test_environment_explicit_override_and_validation(self):
        with patch.dict('os.environ',{'HARNESS_DEBUG_TIMINGS':'1'}):
            self.assertTrue(resolve_debug_timings())
            self.assertFalse(resolve_debug_timings(False))
        with patch.dict('os.environ',{'HARNESS_DEBUG_TIMINGS':'true'}):
            with self.assertRaises(ValueError):resolve_debug_timings()
        with self.assertRaises(ValueError):resolve_debug_timings(1)

    def test_trace_flush_once_after_finish_not_policy_data(self):
        for enabled in (False,True):
            with self.subTest(enabled=enabled),tempfile.TemporaryDirectory() as root:
                trace=Trace(root,{},debug_timings=enabled,async_recording=True)
                trace.event('observation_capture_phase',seconds=.01,phase='AX',private='SECRET')
                trace.observation(0,{'screenshot':None,'data':[1,2,3]},'Public AX')
                trace.append({'messages':[{'role':'user','content':'Public AX'}]})
                path=trace.directory/'debug-timings.json'
                self.assertFalse(path.exists())
                trace.finish({'stop_reason':'test'})
                self.assertEqual(path.exists(),enabled)
                if enabled:
                    data=path.read_text();self.assertNotIn('SECRET',data)
                    names={r['name'] for r in json.loads(data)['records']}
                    self.assertTrue({'trace.serialize_observation','trace.enqueue_observation',
                        'lifecycle.episode_finished','lifecycle.observation_capture_phase'}<=names)
                self.assertNotIn('debug_timings',(trace.directory/'steps.jsonl').read_text())


class PushDrainTests(unittest.TestCase):
    def test_drain_never_reads_context_or_evaluates_a_frame(self):
        class Forbidden:
            def __getattr__(self,key):raise AssertionError('Browser access '+key)
        c=BrowserEvents();c.context=Forbidden();page=object();frame=Forbidden()
        c._append(page,frame,{'kind':'page_announcement','text':'first'})
        self.assertEqual(c.drain()['events'][0]['text'],'first')
        self.assertEqual(c.drain()['events'],[])
        c.phase='action_window'
        c._append(page,frame,{'kind':'page_announcement','text':'late','page_time_ms':100})
        result=c.drain();self.assertEqual(result['events'][0]['text'],'late')
        self.assertEqual(result['events'][0]['page_time_ms'],100)
        self.assertIn('not occurrence',result['delivery_scope'])

    def test_custody_and_close_filter_including_buffered_events(self):
        c=BrowserEvents();p1=object();p2=object();active=[p1]
        c.page_filter=lambda p:p is active[0]
        c._append(p1,None,{'kind':'input','value':'old'})
        c._append(p2,None,{'kind':'input','value':'human'})
        active[0]=p2
        self.assertEqual(c.drain()['events'],[])
        c._append(p2,None,{'kind':'input','value':'new'})
        self.assertEqual(c.drain()['events'][0]['value'],'new')
        c.close(context_closing=True)
        c._append(p2,None,{'kind':'input','value':'closed'})
        self.assertEqual(c.drain()['events'],[])

    def test_overflow_is_explicit_and_resets(self):
        c=BrowserEvents(max_events=2);p=object()
        for i in range(5):c._append(p,None,{'kind':'page_announcement','text':str(i)})
        r=c.drain();self.assertEqual(len(r['events']),2);self.assertEqual(r['omitted'],3)
        self.assertEqual(c.drain()['omitted'],0)


if __name__=='__main__':unittest.main()
