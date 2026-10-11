"""Threaded fake lifecycles: no browser, policy or provider execution."""
import importlib.util
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch
import unittest

path = Path(__file__).resolve().parents[1] / 'scripts/episode_queue.py'
spec = importlib.util.spec_from_file_location('_episode_queue_under_test', path)
q = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = q
spec.loader.exec_module(q)


class QueueTests(unittest.TestCase):
    def test_invalid_settings_create_nothing(self):
        called = []
        for config in [dict(max_concurrent_episodes=x) for x in [0, -1, True, 1.5]] + [
                dict(max_concurrent_episodes=1, prewarm_count=x) for x in [-1, True, 1.5]] + [
                dict(max_concurrent_episodes=1, start_order=x) for x in ['AB', ['A'], ['A', 'A'], ['A', 'Z']]]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                q.run_ordered_suite({'A': 'A', 'B': 'B'}, lambda *a: called.append(a), **config)
        self.assertEqual(called, [])

    def launch(self, run_case, **kwargs):
        result, errors = [], []
        def run():
            try:
                result.append(q.run_ordered_suite(dict(A='A', B='B', C='C', D='D'), run_case, **kwargs))
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        return thread, result, errors

    def finish(self, thread, errors):
        thread.join(5)
        self.assertFalse(thread.is_alive(), 'Fake suite did not clean up')
        self.assertEqual(errors, [])

    def test_rolling_order_warm_limit_and_cleanup_lease(self):
        created = {i: threading.Event() for i in 'ABCD'}
        active = {i: threading.Event() for i in 'ABCD'}
        release = {i: threading.Event() for i in 'ABCD'}
        cleanup = {i: threading.Event() for i in 'ABCD'}
        identities, closed = {}, []
        def run(case, admission):
            # One fake environment per case, retained across the ready gate.
            env = object()
            identities[case] = env
            created[case].set()
            try:
                admission.environment_ready()
                admission.check_active()
                self.assertIs(identities[case], env)
                active[case].set()
                self.assertTrue(release[case].wait(5))
                # Native grading/publication done, but cleanup is still active.
                self.assertTrue(cleanup[case].wait(5))
                return {'native_grade': case}
            finally:
                closed.append(case)
        thread, result, errors = self.launch(run, max_concurrent_episodes=2,
            prewarm_count=1, start_order=['C', 'A', 'D', 'B'])
        try:
            self.assertTrue(active['C'].wait(5)); self.assertTrue(active['A'].wait(5))
            self.assertTrue(created['D'].wait(5))
            self.assertFalse(active['D'].is_set()); self.assertFalse(created['B'].is_set())
            release['A'].set()
            self.assertFalse(active['D'].is_set())  # Cleanup still holds the lease.
            cleanup['A'].set()
            self.assertTrue(active['D'].wait(5))  # Does not wait for the entire wave.
            self.assertTrue(created['B'].wait(5)); self.assertFalse(active['B'].is_set())
        finally:
            for item in [*release.values(), *cleanup.values()]: item.set()
            self.finish(thread, errors)
        value = result[0]
        self.assertEqual([e['case'] for e in value['events'] if e['event'] == 'admitted'], ['C', 'A', 'D', 'B'])
        self.assertTrue(all(e['active'] <= 2 and e['warming_or_ready'] <= 1 for e in value['events']))
        self.assertEqual(sorted(closed), list('ABCD'))
        self.assertTrue(all(r['status'] == 'completed' for r in value['cases'].values()))

    def test_zero_warm_depth_keeps_later_cases_cold(self):
        first = threading.Event(); release = threading.Event(); started = []
        def run(case, admission):
            started.append(case)
            admission.environment_ready(); admission.check_active()
            if case == 'A':
                first.set(); self.assertTrue(release.wait(5))
            return case
        thread, result, errors = self.launch(run, max_concurrent_episodes=1, prewarm_count=0)
        try:
            self.assertTrue(first.wait(5)); self.assertEqual(started, ['A'])
        finally:
            release.set(); self.finish(thread, errors)
        self.assertEqual(started, list('ABCD'))
        self.assertFalse(any(e['event'] == 'warmup_started' for e in result[0]['events']))

    def test_two_warm_cases_and_cancellation_close_each_once(self):
        stop = threading.Event(); first = threading.Event()
        created = {i: threading.Event() for i in 'ABCD'}; closed = []; requests = []
        def run(case, admission):
            created[case].set()
            try:
                # Admission rejects even an active case before environment readiness.
                with self.assertRaises(q.AdmissionError): admission.check_active()
                admission.environment_ready()
                if case == 'A':
                    first.set(); stop.wait(5)
                admission.check_active(); requests.append(case)
            finally:
                closed.append(case)
        thread, result, errors = self.launch(run, max_concurrent_episodes=1,
            prewarm_count=2, stop_event=stop)
        try:
            self.assertTrue(first.wait(5)); self.assertTrue(created['B'].wait(5)); self.assertTrue(created['C'].wait(5))
            self.assertFalse(created['D'].is_set())
        finally:
            stop.set(); self.finish(thread, errors)
        self.assertEqual(requests, [])
        self.assertEqual(sorted(closed), list('ABC'))
        self.assertEqual(result[0]['cases']['D']['status'], 'not_started')
        self.assertTrue(result[0]['cancelled'])

    def test_failed_setup_is_not_retried_or_a_task_verdict(self):
        starts = []
        def run(case, admission):
            starts.append(case)
            if case == 'A': raise OSError('Fake setup failure')
            admission.environment_ready(); admission.check_active()
            return case
        value = q.run_ordered_suite(dict(A='A', B='B'), run,
            max_concurrent_episodes=1, prewarm_count=1)
        self.assertEqual(starts.count('A'), 1)
        self.assertEqual(value['cases']['A']['status'], 'failed')
        self.assertEqual(value['cases']['A']['error']['type'], 'OSError')
        self.assertIsNone(value['cases']['A']['result'])
        self.assertEqual(value['cases']['B']['status'], 'completed')

    def test_missing_and_duplicate_ready_hooks_are_protocol_failures(self):
        def run(case, admission):
            if case == 'A': return 'no ready hook'
            admission.environment_ready(); admission.environment_ready()
        value = q.run_ordered_suite(dict(A='A', B='B'), run,
            max_concurrent_episodes=1, prewarm_count=0)
        self.assertTrue(all(r['status'] == 'failed' and r['error']['type'] == 'AdmissionError'
                            for r in value['cases'].values()))

    def test_stop_before_start_constructs_nothing(self):
        stop = threading.Event(); stop.set(); created = []
        value = q.run_ordered_suite(dict(A='A'), lambda *a: created.append(a),
            max_concurrent_episodes=1, stop_event=stop)
        self.assertEqual(created, [])
        self.assertEqual(value['cases']['A']['status'], 'not_started')

    def test_native_hook_context_and_cancellation_type(self):
        stop = threading.Event(); first = threading.Event(); warmed = threading.Event()
        class NativeCancelled(RuntimeError): pass
        def run(case, admission):
            callback = admission.runner_callback(NativeCancelled)
            if case == 'B': warmed.set()
            callback(SimpleNamespace(episode_id='trace-'+case,
                directory=Path('/private/runs')/case, ready_monotonic=10.5))
            admission.check_active()
            if case == 'A': first.set(); stop.wait(5)
            admission.check_active()
        thread, result, errors = self.launch(run, max_concurrent_episodes=1,
            prewarm_count=1, stop_event=stop)
        try:
            self.assertTrue(first.wait(5)); self.assertTrue(warmed.wait(5))
        finally:
            stop.set(); self.finish(thread, errors)
        self.assertEqual(result[0]['cases']['B']['status'], 'cancelled')
        self.assertEqual(result[0]['cases']['B']['error']['type'], 'NativeCancelled')
        self.assertEqual(result[0]['cases']['A']['ready_context']['episode_id'], 'trace-A')

    def test_replacement_thread_start_failure_is_terminal(self):
        real_start = q.Thread.start; ran = []
        def start(thread):
            if thread.name == 'episode-B':
                raise RuntimeError('Fake thread capacity ceiling')
            return real_start(thread)
        def run(case, admission):
            ran.append(case); admission.environment_ready(); admission.check_active()
            return case
        with patch.object(q.Thread, 'start', start):
            value = q.run_ordered_suite(dict(A='A', B='B', C='C'), run,
                max_concurrent_episodes=1, prewarm_count=0)
        self.assertEqual(ran, ['A'])
        self.assertEqual(value['cases']['A']['status'], 'completed')
        self.assertEqual(value['cases']['B']['status'], 'failed')
        self.assertEqual(value['cases']['B']['error']['type'], 'RuntimeError')
        self.assertEqual(value['cases']['C']['status'], 'not_started')
        self.assertTrue(value['cancelled'])
        self.assertEqual([e['case'] for e in value['events'] if e['event'] == 'worker_start_failed'], ['B'])

    def test_initial_thread_start_failure_creates_nothing(self):
        ran = []
        with patch.object(q.Thread, 'start', side_effect=RuntimeError('Fake initial thread failure')):
            value = q.run_ordered_suite(dict(A='A', B='B'), lambda *a: ran.append(a),
                max_concurrent_episodes=2, prewarm_count=1)
        self.assertEqual(ran, [])
        self.assertEqual(value['cases']['A']['status'], 'failed')
        self.assertEqual(value['cases']['B']['status'], 'not_started')


if __name__ == '__main__':
    unittest.main(verbosity=2)
