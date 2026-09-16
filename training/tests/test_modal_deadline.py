"""Check budget enforcement and diagnostics locally; never hydrate Modal objects."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest

pytest.importorskip('modal')
spec = importlib.util.spec_from_file_location('modal_training_test', Path(__file__).parents[1] / 'scripts/modal_training.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_expired_authorization_starts_nothing():
    with pytest.raises(RuntimeError, match='deadline expired'):
        launcher.gpu_probe.get_raw_f()('expired', '/unused', 0)


def test_streaming_preserves_failure_output(tmp_path, capsys):
    path = tmp_path / 'child.log'
    code = launcher.run_logged([sys.executable, '-c', "print('diagnostic'); raise SystemExit(3)"],
        path, cwd=tmp_path, env=os.environ.copy(), timeout=5)
    assert code == 3
    assert path.read_text() == 'diagnostic\n'
    assert capsys.readouterr().out == 'diagnostic\n'


def test_deadline_terminates_running_child(tmp_path):
    path = tmp_path / 'child.log'
    command = [sys.executable, '-u', '-c', 'import os,time; print(os.getpid(),flush=True); time.sleep(60)']
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        launcher.run_logged(command, path, cwd=tmp_path, env=os.environ.copy(), timeout=0.3)
    assert time.monotonic() - started < 5
    pid = int(path.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
