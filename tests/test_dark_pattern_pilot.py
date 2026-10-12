"""Focused caller failure tests, without models, browsers or generated worlds."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('dark_pilot', Path(__file__).parents[1]/'scripts/dark_pattern_pilot.py')
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)

class PilotFailures(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)

    def test_save_is_exclusive_and_atomic(self):
        target = self.output/'result.json'
        pilot.save(target, {'valid': True})
        with self.assertRaises(FileExistsError):
            pilot.save(target, {'changed': True})
        self.assertEqual(pilot.read(target), {'valid': True})
        self.assertEqual(list(self.output.glob('*.tmp')), [])

    def test_failed_serialization_does_not_publish_partial_result(self):
        target = self.output/'result.json'
        with self.assertRaises(TypeError):
            pilot.save(target, {'bad': object()})
        self.assertFalse(target.exists())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_terminal_states_and_partial_result(self):
        model = self.output/'model'
        model.mkdir()
        (self.output/'model.log').write_text('retained')
        result = model/'result.json'
        for body in ('{', '{}', '{"trace":"x","task_verdict":"invented"}'):
            result.write_text(body)
            state, evidence = pilot.terminal_evidence(self.output, 0)
            self.assertEqual(state, 'failed')
            self.assertIn('result_parse_error', evidence)
        result.write_text('{"trace":"x","task_verdict":"fail"}')
        self.assertEqual(pilot.terminal_evidence(self.output, 0)[0], 'succeeded')
        self.assertEqual(pilot.terminal_evidence(self.output, 1)[0], 'failed')
        self.assertEqual(pilot.terminal_evidence(self.output, 0, KeyboardInterrupt())[0], 'interrupted')

    def test_failure_retains_trace_location_without_result(self):
        trace = self.output/'model/runs/actual-trace'
        trace.mkdir(parents=True)
        (trace/'metadata.json').write_text('{}')
        state, evidence = pilot.terminal_evidence(self.output, 1)
        self.assertEqual(state, 'failed')
        self.assertEqual(evidence['retained_trace_directories'], [str(trace)])

    def test_supervisor_child_launch_failure_finishes_and_notifies(self):
        self._supervisor_failure(OSError('launch failed'), 'failed')

    def test_supervisor_interruption_finishes_and_notifies(self):
        self._supervisor_failure(KeyboardInterrupt('stop'), 'interrupted')

    def _supervisor_failure(self, error, expected):
        (self.output/'readiness.json').write_text('{"status":"passed","config":{"path":"test","sha256":"test"}}')
        calls = []
        class Events:
            def __init__(self, path): pass
            def register(self, *a): pass
            def subscribe(self, *a, **k): pass
            def start(self, *a): calls.append('claimed')
            def finish(self, *a): calls.append(('finish', a[2]))
        config = {'_path':'test','output':str(self.output),'suite_id':'one',
                  'thread_id':'thread','events':{}}
        with patch.object(pilot,'guard'), patch.object(pilot,'preflight'), \
             patch.object(pilot,'require_review'), patch.object(pilot,'checked',return_value=Path('test')), \
             patch.object(pilot,'pin',return_value={'path':'test','sha256':'test'}), \
             patch.object(pilot.runpy,'run_path',return_value={'Events':Events,'flush':lambda e:calls.append('flush')}), \
             patch.object(pilot.subprocess,'Popen',side_effect=error):
            with self.assertRaises(type(error)):
                pilot.supervise(config)
        self.assertEqual(calls, ['claimed', ('finish',expected), 'flush'])
        self.assertEqual(pilot.read(self.output/'supervisor-terminal.json')['state'], expected)

    def test_preflight_failure_does_not_claim(self):
        (self.output/'readiness.json').write_text('{"status":"passed","config":{"path":"test","sha256":"test"}}')
        config = {'_path':'test','output':str(self.output)}
        with patch.object(pilot,'guard'), patch.object(pilot,'require_review'), \
             patch.object(pilot,'pin',return_value={'path':'test','sha256':'test'}), \
             patch.object(pilot,'preflight',side_effect=ValueError('quota')), \
             patch.object(pilot.runpy,'run_path') as events:
            with self.assertRaises(ValueError):
                pilot.supervise(config)
            events.assert_not_called()
        self.assertFalse((self.output/'supervisor-start.json').exists())

if __name__ == '__main__':
    unittest.main()
