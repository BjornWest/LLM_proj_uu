"""CPU lifecycle controls; the fixture guardian does not qualify real containment."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'training/scripts'))
import qwen_container_services as C
import qwen_host_worker as W

GUARD = '''import argparse,json,os,pathlib,signal,subprocess,sys,time,hashlib
p=argparse.ArgumentParser();p.add_argument('--memory-mib');p.add_argument('--tasks');p.add_argument('--receipt');p.add_argument('--wall-seconds');p.add_argument('--grace-seconds');p.add_argument('--cleanup-seconds');p.add_argument('cmd',nargs=argparse.REMAINDER);a=p.parse_args()
d=pathlib.Path(a.receipt);d.mkdir(mode=0o700)
child=subprocess.Popen(a.cmd[1:]);birth=int(pathlib.Path('/proc/'+str(child.pid)+'/stat').read_text().rsplit(')',1)[1].split()[19])
super_birth=int(pathlib.Path('/proc/'+str(os.getpid())+'/stat').read_text().rsplit(')',1)[1].split()[19])
r={'schema':'container-job-v1','mode':'monitored_process_tree','source_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'root':{'pid':child.pid,'start_ticks':birth},'supervisor':{'pid':os.getpid(),'start_ticks':super_birth}}
(d/'entry.json').write_text(json.dumps(r))
def stop(sig,frame):
 child.terminate();child.wait(timeout=2)
 (d/'result.json').write_text(json.dumps({**r,'cleanup_verified':CLEAN,'entry_verified':True,'payload_gate_released':True,'returncode':143}))
 sys.exit(143)
signal.signal(signal.SIGTERM,stop)
while True:time.sleep(.05)
'''


class ServicesTests(unittest.TestCase):
    def fixture(self, root, *, clean=True):
        guard = root/'guard.py'; guard.write_text(GUARD.replace('CLEAN', repr(clean)))
        entry = root/'host/training/scripts'; entry.mkdir(parents=True)
        (entry/'serve_qwen_suite.py').write_text(
            'import os,time\nprint("secret_present="+str("VAST_API_KEY" in os.environ),flush=True)\ntime.sleep(60)\n')
        run = root/'runs/test'; run.mkdir(parents=True, mode=0o700)
        spec = {'execution_backend':'container-monitored-v1', 'container_launcher':
                {'path':str(guard),'sha256':sha256(guard.read_bytes()).hexdigest()},
                'server_memory_mib':57344, 'host_root':str(root/'host'), 'browser_python':sys.executable,
                'rl_python':sys.executable, 'snapshot':'/unused/snapshot', 'cache_root':'/unused/cache'}
        return spec, run

    def test_actual_guardian_and_payload_are_distinct_and_sigterm_drains(self):
        with tempfile.TemporaryDirectory() as t:
            spec, run = self.fixture(Path(t)); services = C.ContainerServices(spec)
            with patch.dict(os.environ, {'VAST_API_KEY':'DO_NOT_TRANSMIT'}):
                argv = W.unit_argv(spec, run, 60)
                self.assertNotIn('systemd-run', ' '.join(argv))
                services.call(argv)
            name='qwen-test'; state=services.state(name); row=services.rows[name]
            self.assertNotEqual(int(state['MainPID']), row['guardian']['pid'])
            self.assertEqual(state['backend'], 'container-monitored-v1')
            try:
                deadline=time.monotonic()+2
                while 'secret_present=False' not in (run/'vllm.log').read_text() and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertIn('secret_present=False', (run/'vllm.log').read_text())
            finally:
                services.stop(name, state['InvocationID'], expected_directory=run)
            self.assertEqual(services.state(name)['MainPID'], '0')
            self.assertEqual(row['child'].returncode, 143)
            receipt=json.loads((run/'qwen-test-service-terminal.json').read_text())
            self.assertTrue(receipt['cleanup_verified'])
            self.assertEqual(services.state('unknown'), {'LoadState':'not-found'})

    def test_unverified_cleanup_fails_instead_of_publishing_success(self):
        with tempfile.TemporaryDirectory() as t:
            spec, run = self.fixture(Path(t), clean=False); services=C.ContainerServices(spec)
            services.call(W.unit_argv(spec, run, 60)); state=services.state('qwen-test')
            with self.assertRaisesRegex(RuntimeError,'not verified'):
                services.stop('qwen-test',state['InvocationID'],expected_directory=run)
            self.assertFalse((run/'qwen-test-service-terminal.json').exists())
            self.assertIsNotNone(services.rows['qwen-test']['child'].poll())

    def test_verified_deadline_exit_is_not_a_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as t:
            spec,run=self.fixture(Path(t));guard=Path(spec['container_launcher']['path'])
            code=guard.read_text().replace("'returncode':143", "'returncode':124,'first_stop_reason':'wall_deadline'").replace('sys.exit(143)','sys.exit(124)')
            guard.write_text(code);spec['container_launcher']['sha256']=sha256(guard.read_bytes()).hexdigest()
            services=C.ContainerServices(spec);services.call(W.unit_argv(spec,run,60));state=services.state('qwen-test')
            services.rows['qwen-test']['child'].terminate();services.rows['qwen-test']['child'].wait(timeout=3)
            services.stop('qwen-test',state['InvocationID'],expected_directory=run)
            terminal=json.loads((run/'qwen-test-service-terminal.json').read_text())
            self.assertTrue(terminal['cleanup_verified']);self.assertEqual(terminal['guardian_exit_code'],124)
            self.assertEqual(terminal['first_stop_reason'],'wall_deadline')

    def test_changed_source_and_expired_rental_never_start_guardian(self):
        with tempfile.TemporaryDirectory() as t:
            spec,run=self.fixture(Path(t))
            with self.assertRaises(TimeoutError):W.unit_argv(spec,run,.5)
            argv=W.unit_argv(spec,run,60);Path(spec['container_launcher']['path']).write_text('changed')
            with patch.object(C.subprocess,'Popen') as launch,self.assertRaises(ValueError):
                C.ContainerServices(spec).call(argv)
            launch.assert_not_called()

    def test_stop_refuses_wrong_owner_and_does_not_signal(self):
        with tempfile.TemporaryDirectory() as t:
            spec,run=self.fixture(Path(t));services=C.ContainerServices(spec)
            services.call(W.unit_argv(spec,run,60));state=services.state('qwen-test')
            try:
                with patch.object(C,'send_pidfd') as send:
                    with self.assertRaises(ValueError):services.stop('qwen-test','other',expected_directory=run)
                    with self.assertRaises(ValueError):services.stop('qwen-test',None,expected_directory=Path('/other'))
                    send.assert_not_called()
            finally:services.stop('qwen-test',state['InvocationID'],expected_directory=run)

    def test_real_pidfds_work_when_python_wrappers_are_missing(self):
        with patch.object(C.os,'pidfd_open',None,create=True),patch.object(C.signal,'pidfd_send_signal',None,create=True):
            descriptor=C.open_pidfd(os.getpid())
            try:C.send_pidfd(descriptor,0)
            finally:os.close(descriptor)
            with tempfile.TemporaryDirectory() as t:
                spec,run=self.fixture(Path(t));services=C.ContainerServices(spec)
                services.call(W.unit_argv(spec,run,60));state=services.state('qwen-test')
                services.stop('qwen-test',state['InvocationID'],expected_directory=run)
                self.assertIsNotNone(services.rows['qwen-test']['child'].poll())

    def test_adapter_is_separate_and_uses_small_threshold(self):
        with tempfile.TemporaryDirectory() as t:
            spec,run=self.fixture(Path(t));argv=C.launch_argv(spec,run,12.5,'qwen-test-qualification',binding={'path':'/binding','sha256':'a'*64})
            self.assertEqual(argv[argv.index('--memory-mib')+1],'512')
            self.assertEqual(argv[argv.index('--tasks')+1],'0')  # memory is the only guard
            self.assertEqual(argv[argv.index('--wall-seconds')+1],'12.5')
            self.assertIn(str(run/'qwen-test-qualification'),argv)
            self.assertIn(str(run/'ready'),argv)

    def test_container_bootstrap_plan_cannot_install_and_execute_requires_deadline(self):
        path=ROOT/'training/scripts/bootstrap_qwen_container.sh'
        plan=subprocess.run(['bash',str(path)],capture_output=True,text=True,timeout=5)
        self.assertEqual(plan.returncode,0,plan.stderr)
        self.assertIn('Plan only',plan.stdout)
        self.assertNotIn('systemctl',plan.stdout)
        missing=subprocess.run(['bash',str(path),'--execute'],capture_output=True,text=True,timeout=5)
        self.assertEqual(missing.returncode,2)
        self.assertIn('original rental deadline',missing.stderr)


if __name__ == '__main__': unittest.main()
