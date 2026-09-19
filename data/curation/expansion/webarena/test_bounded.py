import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from data.curation.expansion.webarena.run_bounded import execute_case


class ProcessBoundaryTests(unittest.TestCase):
    def test_completion_and_log_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'log.txt'
            result = execute_case([sys.executable, '-c', 'print("scripted only")'], log, 5)
            self.assertFalse(result['timed_out'])
            self.assertEqual(result['returncode'], 0)
            self.assertEqual(log.read_text().strip(), 'scripted only')
            with self.assertRaises(FileExistsError):
                execute_case([sys.executable, '-c', 'raise Exception("must not run")'], log, 5)
            self.assertEqual(log.read_text().strip(), 'scripted only')

    def test_timeout_terminates_owned_descendant(self):
        with tempfile.TemporaryDirectory() as temp:
            pidfile = Path(temp) / 'pid.json'
            child = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
            parent = (
                'import signal,subprocess,sys,time,json;from pathlib import Path;'
                'signal.signal(signal.SIGUSR1,signal.SIG_IGN);'
                f'p=subprocess.Popen([sys.executable,"-c",{child!r}]);'
                f'Path({str(pidfile)!r}).write_text(json.dumps(p.pid));time.sleep(30)')
            result = execute_case([sys.executable, '-c', parent], Path(temp) / 'log', 3,
                                  grace_seconds=0.3)
            self.assertTrue(result['timed_out'])
            self.assertLess(result['ended_at_unix'] - result['started_at_unix'], 5)
            child_pid = json.loads(pidfile.read_text())
            status = Path(f'/proc/{child_pid}/status')
            deadline = time.monotonic() + 2
            while status.exists() and time.monotonic() < deadline:
                state = next(x for x in status.read_text().splitlines() if x.startswith('State:'))
                if 'Z' in state:
                    break
                time.sleep(0.02)
            if status.exists():
                # A killed grandchild can briefly remain as an init-owned zombie.
                self.assertIn('Z', next(x for x in status.read_text().splitlines()
                                        if x.startswith('State:')))
            self.assertNotEqual(child_pid, os.getpid())

    def test_invalid_timeout_no_log_or_process(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'log'
            with self.assertRaises(ValueError):
                execute_case([sys.executable, '-c', 'raise Exception'], log, 0)
            self.assertFalse(log.exists())


if __name__ == '__main__':
    unittest.main()
