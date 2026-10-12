import datetime as dt
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from scripts.trace_suites import SuiteCatalog, episode_updated_at, timestamp, trace_id


class SuiteRecencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plans = []
        self.grades = patch.object(SuiteCatalog, 'verified_grade', return_value=None)
        self.grades.start()
        self.addCleanup(self.grades.stop)

    def suite(self, ident, *, traces=(), **fields):
        cases = [{'case_id': str(n), 'task_id': 'task', 'task_title': 'Task',
                  'model': {'model': 'fixture', 'transport': 'openrouter'}, 'repeat': 1,
                  'trace_directory': str(trace)} for n, trace in enumerate(traces)]
        if not traces:
            cases = [{'case_id': 'queued', 'task_id': 'task',
                      'model': {'model': 'fixture', 'transport': 'openrouter'}, 'repeat': 1,
                      'cohort': str(self.root / ident / 'queued')}]
        path = self.root / ident / 'suite.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'schema': 'episode-suite-plan-v1', 'id': ident,
                                    'title': ident, 'cases': cases, **fields}))
        self.plans.append(path)
        return path

    def trace(self, ident, modified=100):
        path = self.root / 'runs' / ident
        path.mkdir(parents=True)
        metadata = path / 'metadata.json'
        metadata.write_text('{}')
        os.utime(metadata, (modified, modified))
        return path

    def catalog(self):
        return SuiteCatalog(plan_paths=self.plans)

    def test_suite_timestamps_are_normalized_and_newest_first(self):
        self.suite('old', created_at='2026-10-10T12:00:00Z')
        self.suite('new', updated_at='2026-10-12T12:00:00+02:00')
        self.suite('middle', started_at='2026-10-12T09:30:00Z')
        self.suite('queued')
        rows = self.catalog().index()
        self.assertEqual([r['id'] for r in rows], ['new', 'middle', 'old', 'queued'])
        self.assertEqual(rows[0]['updated_at'], '2026-10-12T10:00:00+00:00')
        self.assertIsNone(rows[-1]['updated_at'])

    def test_latest_episode_summary_orders_and_refreshes_suite(self):
        a, b, c = (self.trace(name) for name in ('a', 'b', 'c'))
        self.suite('first', traces=[a, b])
        self.suite('second', traces=[c])
        summaries = {trace_id(a): {'updated_at': '2026-10-10T00:00:00Z'},
                     trace_id(b): {'updated_at': '2026-10-12T00:00:00Z'},
                     trace_id(c): {'updated_at': '2026-10-11T00:00:00Z'}}
        catalog = self.catalog()
        before = catalog.index(summaries)
        self.assertEqual([r['id'] for r in before], ['first', 'second'])
        summaries[trace_id(c)]['updated_at'] = '2026-10-13T00:00:00Z'
        after = catalog.index(summaries)
        self.assertEqual([r['id'] for r in after], ['second', 'first'])
        self.assertEqual({r['id']: {k: v for k, v in r.items() if k != 'updated_at'} for r in before},
                         {r['id']: {k: v for k, v in r.items() if k != 'updated_at'} for r in after})

    def test_cold_catalog_uses_file_updates_without_reading_model_payloads(self):
        old, new = self.trace('old', 100), self.trace('new', 200)
        self.suite('old-suite', traces=[old])
        self.suite('new-suite', traces=[new])
        steps = old / 'steps.jsonl'
        steps.write_text('opaque model context; deliberately not valid JSON')
        os.utime(steps, (300, 300))
        original = Path.read_text

        def checked_read(path, *args, **kwargs):
            if path.name == 'steps.jsonl':
                self.fail('Suite ordering read model payloads')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', checked_read):
            rows = self.catalog().index()
        self.assertEqual([r['id'] for r in rows], ['old-suite', 'new-suite'])
        self.assertEqual(timestamp(rows[0]['updated_at']).timestamp(), 300)
        self.assertEqual(steps.read_text(), 'opaque model context; deliberately not valid JSON')

    def test_valid_summary_does_not_stat_trace_files(self):
        trace = self.trace('summary')
        with patch.object(Path, 'stat', side_effect=AssertionError('Unnecessary stat scan')):
            result = episode_updated_at(trace, {'updated_at': '2026-10-12T01:00:00Z'})
        self.assertEqual(result.isoformat(), '2026-10-12T01:00:00+00:00')

    def test_stat_fallback_ignores_derived_grades_and_nonrecording_files(self):
        trace = self.trace('recording', 100)
        for name in ('derived-answer-grade.json', 'derived-answer-check-details.json', 'note.txt'):
            path = trace / name
            path.write_text('{}')
            os.utime(path, (10000, 10000))
        self.assertEqual(episode_updated_at(trace, {}).timestamp(), 100)

    def test_unrepresentable_file_times_do_not_hide_suites(self):
        trace = self.root / 'extreme'
        for modified in (2**40, -2**40, 253402300800):
            with patch.object(Path, 'stat', return_value=SimpleNamespace(st_mode=stat.S_IFREG,
                                                                       st_mtime=modified)):
                result = episode_updated_at(trace, {'started_at': '2026-10-12T00:00:00Z'})
            self.assertEqual(result.isoformat(), '2026-10-12T00:00:00+00:00')

    def test_invalid_suite_and_summary_timestamps_use_file_fallback(self):
        trace = self.trace('fallback', 200)
        self.suite('s', traces=[trace], updated_at='bad date', created_at=123, started_at=None)
        row = self.catalog().index({trace_id(trace): {'updated_at': 'not a date'}})[0]
        self.assertEqual(timestamp(row['updated_at']).timestamp(), 200)

    def test_explicit_suite_timestamp_has_precedence_over_episode_fallback(self):
        trace = self.trace('explicit')
        self.suite('s', traces=[trace], updated_at='2026-10-11T00:00:00Z',
                   created_at='2026-10-10T00:00:00Z')
        row = self.catalog().index({trace_id(trace): {'updated_at': '2026-10-12T00:00:00Z'}})[0]
        self.assertEqual(row['updated_at'], '2026-10-11T00:00:00+00:00')

    def test_missing_files_use_started_at_and_unavailable_times_sort_last(self):
        missing = self.root / 'missing'
        self.suite('started', traces=[missing])
        self.suite('unknown', updated_at='invalid')
        rows = self.catalog().index({trace_id(missing): {'started_at': '2026-10-12T00:00:00Z'}})
        self.assertEqual([r['id'] for r in rows], ['started', 'unknown'])
        self.assertIsNone(rows[-1]['updated_at'])

    def test_equal_times_have_stable_id_order_across_registration_orders(self):
        self.suite('z', updated_at='2026-10-12T10:00:00Z')
        self.suite('a', updated_at='2026-10-12T12:00:00+02:00')
        self.suite('unknown-z')
        self.suite('unknown-a')
        catalog = self.catalog()
        expected = ['a', 'z', 'unknown-a', 'unknown-z']
        self.assertEqual([r['id'] for r in catalog.index()], expected)
        self.plans.reverse()
        self.assertEqual([r['id'] for r in catalog.index()], expected)

    def test_timestamp_handles_naive_utc_and_rejects_invalid_values(self):
        self.assertEqual(timestamp('2026-10-12T10:00:00'),
                         dt.datetime(2026, 10, 12, 10, tzinfo=dt.timezone.utc))
        for value in (None, 42, True, {}, '', 'bad', '0001-01-01T00:00:00+12:00'):
            self.assertIsNone(timestamp(value))

    def test_http_suite_poll_refreshes_without_sessions_or_full_projections(self):
        from http.server import ThreadingHTTPServer
        from scripts.trace_hub import Hub, make_handler
        older, newer = self.trace('older'), self.trace('newer')
        for trace, date in ((older, '2026-10-10T00:00:00Z'), (newer, '2026-10-12T00:00:00Z')):
            (trace / 'metadata.json').write_text(json.dumps({'browsergym_version': '0.14.3',
                                                           'driver': 'scripted', 'tags': ['scripted']}))
            (trace / 'events.jsonl').write_text(json.dumps({'event': 'episode_started', 'timestamp': date})+'\n')
        self.suite('older-suite', traces=[older])
        self.suite('newer-suite', traces=[newer])
        registry = self.root / 'registry.json'
        registry.write_text(json.dumps({'project_root': str(self.root), 'roots': [str(older.parent)],
                                        'patterns': [], 'suites': [str(p) for p in self.plans]}))
        projections, snapshots, hubs = [], [], []

        class ObservedHub(Hub):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                hubs.append(self)

            def project(self, directory):
                projections.append(directory)
                return super().project(directory)

            def snapshot(self):
                snapshots.append(self.mode)
                return super().snapshot()

        clock = [100.0]
        with patch('scripts.trace_hub.time.monotonic', side_effect=lambda: clock[0]):
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(registry, hub_class=ObservedHub))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:'+str(server.server_port)

            def fetch(route='/api/suites'):
                with urlopen(base+route, timeout=5) as response:
                    return json.load(response)

            try:
                self.assertEqual([r['id'] for r in fetch()], ['newer-suite', 'older-suite'])
                self.assertEqual(len(snapshots), 1)
                fetch()
                fetch('/api/suites/newer-suite')
                self.assertEqual(len(snapshots), 1, 'Repeated polls should reuse recent snapshots')
                with (older / 'events.jsonl').open('a') as stream:
                    stream.write(json.dumps({'event': 'tool_call_finished',
                                             'timestamp': '2026-10-13T00:00:00Z'})+'\n')
                clock[0] += 3
                self.assertEqual([r['id'] for r in fetch()], ['older-suite', 'newer-suite'])
                self.assertEqual(len(snapshots), 2)
                # Snapshot failures in unrelated roots retain readable suites.
                clock[0] += 3
                with patch.object(Hub, 'snapshot', side_effect=ValueError('Unrelated corrupt recording')):
                    self.assertEqual(fetch()[0]['id'], 'older-suite')
                    self.assertEqual(fetch('/api/suites/older-suite')['case_count'], 1)
                self.assertEqual(projections, [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_suite_refresh_reuses_a_recent_sessions_snapshot(self):
        from scripts.trace_hub import Hub
        registry = self.root / 'registry.json'
        registry.write_text(json.dumps({'project_root': str(self.root), 'roots': [], 'patterns': [], 'suites': []}))
        hub = Hub(registry)
        with patch('scripts.trace_hub.time.monotonic', return_value=100):
            hub.snapshot()
            with patch.object(hub, 'snapshot', side_effect=AssertionError('Duplicate snapshot')):
                self.assertEqual(hub.suite_summaries(), {})


if __name__ == '__main__':
    unittest.main()
