"""Local inherited-socket controls, including two real Python child processes."""
import importlib.util
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
q = load('_queue_channel_test_queue', ROOT/'scripts/episode_queue.py')
c = load('_queue_channel_test_channel', ROOT/'scripts/episode_queue_channel.py')


class ChannelTests(unittest.TestCase):
    def test_child_dispatch_before_ready_is_rejected_locally(self):
        left, right = socket.socketpair()
        try:
            child = c.ChildAdmission(right, 'A', RuntimeError)
            with self.assertRaises(c.ChannelError): child.before_dispatch()
            left.settimeout(.01)
            with self.assertRaises(socket.timeout): left.recv(1)
        finally: left.close(); right.close()

    def test_foreign_malformed_and_oversized_frames_are_rejected(self):
        frames = [c._encode({'case':'foreign','type':'dispatch'}), struct.pack('!I', 16385),
                  struct.pack('!I', 26)+b'{"case":"A","case":"A"}    ']
        for frame in frames:
            left, right = socket.socketpair()
            try:
                right.sendall(frame); right.shutdown(socket.SHUT_WR)
                with self.assertRaises(c.ChannelError):
                    c.serve_admission(left, SimpleNamespace(case_id='A'), expected_run_root='/private/runs')
            finally: left.close(); right.close()

    def test_two_separate_processes_are_admitted_once_in_order(self):
        # The subprocess is a tiny synthetic lifecycle, not a browser/model.
        script = '''import importlib.util,json,socket,sys,time
from pathlib import Path
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('child_channel',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
conn=socket.socket(fileno=int(sys.argv[2]));ident=sys.argv[3];out=Path(sys.argv[4]);marker=Path(sys.argv[5])
gate=m.ChildAdmission(conn,ident,RuntimeError)
(out/(ident+'-created')).write_text('one environment')
gate.environment_admission(SimpleNamespace(episode_id='trace-'+ident,directory=out/'runs'/ident,ready_monotonic=time.monotonic()))
gate.before_dispatch();(out/(ident+'-dispatch')).write_text('one fake request')
if ident=='A':
 deadline=time.monotonic()+5
 while not marker.exists():
  if time.monotonic()>deadline:raise TimeoutError('fixture release absent')
  time.sleep(.01)
conn.close();print(json.dumps({'case':ident,'fake_requests':1,'resets':1}))
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); errors = []; outputs = []
            def run(ident, admission):
                left, right = socket.socketpair()
                process = None
                try:
                    process = subprocess.Popen([sys.executable, '-I', '-B', '-c', script,
                        str(ROOT/'scripts/episode_queue_channel.py'), str(right.fileno()), ident,
                        str(root), str(root/'release')], pass_fds=(right.fileno(),),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    right.close()
                    proof = c.serve_admission(left, admission, expected_run_root=root/'runs')
                    stdout, stderr = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, stderr)
                    result = json.loads(stdout); self.assertEqual(proof['guarded_dispatches'], 1)
                    return result
                finally:
                    left.close(); right.close()
                    if process is not None and process.poll() is None:
                        process.terminate(); process.wait(timeout=5)
            def suite():
                try: outputs.append(q.run_ordered_suite(dict(A='A', B='B'), run,
                    max_concurrent_episodes=1, prewarm_count=1))
                except BaseException as exc: errors.append(exc)
            thread = threading.Thread(target=suite); thread.start()
            try:
                deadline = time.monotonic()+5
                while not ((root/'A-dispatch').exists() and (root/'B-created').exists()):
                    if time.monotonic() > deadline: self.fail('Subprocess fixture did not become ready')
                    time.sleep(.01)
                self.assertFalse((root/'B-dispatch').exists())
            finally:
                (root/'release').write_text('release'); thread.join(10)
            self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
            value = outputs[0]
            self.assertEqual([e['case']for e in value['events']if e['event']=='admitted'], ['A','B'])
            self.assertTrue(all(r['result']['fake_requests']==1 and r['result']['resets']==1
                                for r in value['cases'].values()))

    def test_cancel_wakes_parked_child_and_vetoes_active_dispatch(self):
        stop = threading.Event(); active = threading.Event(); warm = threading.Event()
        requests = []; children = []; errors = []; results = []
        class NativeCancelled(RuntimeError): pass
        def run(ident, admission):
            left, right = socket.socketpair()
            def child():
                try:
                    gate = c.ChildAdmission(right, ident, NativeCancelled)
                    if ident == 'B': warm.set()
                    gate.environment_admission(SimpleNamespace(episode_id='trace-'+ident,
                        directory=Path('/private/runs')/ident, ready_monotonic=time.monotonic()))
                    if ident == 'A': active.set(); stop.wait(5)
                    gate.before_dispatch(); requests.append(ident)
                except NativeCancelled:
                    pass
                except BaseException as exc:
                    errors.append(exc)
                finally: right.close()
            thread = threading.Thread(target=child); children.append(thread); thread.start()
            try:
                return c.serve_admission(left, admission, expected_run_root='/private/runs')
            finally:
                left.close(); thread.join(5)
                self.assertFalse(thread.is_alive())
        def suite():
            try: results.append(q.run_ordered_suite(dict(A='A', B='B'), run,
                max_concurrent_episodes=1, prewarm_count=1, stop_event=stop))
            except BaseException as exc: errors.append(exc)
        outer = threading.Thread(target=suite); outer.start()
        try:
            self.assertTrue(active.wait(5)); self.assertTrue(warm.wait(5))
        finally:
            stop.set(); outer.join(10)
        self.assertFalse(outer.is_alive()); self.assertEqual(errors, [])
        self.assertEqual(requests, [])
        self.assertTrue(all(r['status'] == 'cancelled' for r in results[0]['cases'].values()))


if __name__ == '__main__': unittest.main(verbosity=2)
